"""Build a register end-to-end: scaffold -> populate -> polish.

polish() MUST be last. The Charts tab is formula-driven off Simulation and
EMV & Mode Analysis, and step 47's autofit sizes columns from the values that are
actually present - run it before the data lands and every helper column is sized for an
empty sheet.

    python tools/build_register.py                     # scaffold + polish, no data
    python tools/build_register.py --out dist/wind_register.xlsx
    python tools/build_register.py --from <populated.xlsx>   # polish an existing build

There is deliberately no data-fill step wired in here. Populating Simulation is
project-specific (the MC engine, or scripts/build_synthetic_wind_fixture.py for the CI
fixture) and does not belong in a shared builder. Use --from to hand in a populated
workbook, or accept an unpopulated one and re-run polish after the model has run.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.register_polish import DEFAULT_WORKBOOK, polish  # noqa: E402
from tools.register_scaffold import main as scaffold_main  # noqa: E402


def build(out: Path, source: Path | None = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    if source is None:
        rc = scaffold_main([str(out)])
        if rc:
            raise SystemExit(rc)
        print("NOTE: Simulation is empty - the charts will be built over blank ranges. "
              "Populate it and re-run tools/register_polish.py.")
    else:
        shutil.copyfile(source, out)
        print(f"copied {source} -> {out}")
    polish(str(out))                       # LAST, always
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_WORKBOOK)
    ap.add_argument("--from", dest="source", type=Path, default=None,
                    help="populated workbook to polish instead of scaffolding a new one")
    args = ap.parse_args(argv)
    print(f"built {build(args.out, args.source)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
