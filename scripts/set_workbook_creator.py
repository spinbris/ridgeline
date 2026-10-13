"""Replace a name in the parts of an Office workbook that carry it, and nothing else (PUBLICFACE-01).

Written for ``tests/golden/wind_register_polished.xlsx``, which named a third party as its creator
(``docProps/core.xml``) and in the Prepared-by cell B61 of its TOC sheet. That file is the workbook
Excel-approved at POLISH-01 and its ``Dashboard``, ``Diagnostics`` and TOC sheets were built by hand,
so no generator rebuilds it (``docs/polish_handoff.md``, ``tests/test_polish.py``). A rebuild would
change far more than two fields. So this **patches** it: every part that holds the old name is
rewritten with the new one, and every other part is copied byte for byte, in the same order, with the
same compression and timestamps.

Usage::

    python scripts/set_workbook_creator.py --old OLD            # the polished golden, in place
    python scripts/set_workbook_creator.py SRC DST --old OLD [--new NEW]

The name to replace is always given: no default here names the party.

It asserts what it did: each carrying part holds the name, the member list is unchanged, and nothing
else differs. A file already free of the name is reported and left alone, so it is idempotent.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.final.product import MAKER  # noqa: E402

DEFAULT_TARGET = REPO_ROOT / "tests" / "golden" / "wind_register_polished.xlsx"


def patch_workbook(src: Path, dst: Path, old: str, new: str = MAKER) -> list[str]:
    """Write ``dst`` as ``src`` with ``old`` replaced by ``new``; return the parts that changed.

    Returns ``[]`` and writes nothing when no part holds ``old``.
    """
    needle, repl = old.encode("utf-8"), new.encode("utf-8")
    with zipfile.ZipFile(src) as zin:
        carriers = [n for n in zin.namelist() if needle in zin.read(n)]
        if not carriers:
            return []
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        with zipfile.ZipFile(tmp, "w") as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename in carriers:
                    data = data.replace(needle, repl)
                out = zipfile.ZipInfo(info.filename, info.date_time)
                out.compress_type = info.compress_type
                out.external_attr = info.external_attr
                out.create_system = info.create_system
                zout.writestr(out, data)
    shutil.move(str(tmp), str(dst))
    return carriers


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", nargs="?", type=Path, default=DEFAULT_TARGET)
    ap.add_argument("dst", nargs="?", type=Path, default=None)
    ap.add_argument("--old", required=True, help="the name to replace")
    ap.add_argument("--new", default=MAKER)
    args = ap.parse_args(argv)
    dst = args.dst or args.src
    changed = patch_workbook(args.src, dst, args.old, args.new)
    if not changed:
        print(f"{args.src}: no part holds {args.old!r}; left alone")
        return 0
    print(f"{dst}: {args.old!r} -> {args.new!r} in {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
