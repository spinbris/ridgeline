"""Measure which ``outputs/`` files a test actually writes.

**Why this is in the repo.** Answering "which ``outputs/`` subtree does each
notebook test write?" costs roughly 40 minutes of box time, because the only
honest way to find out is to run the notebooks and look. TESTLANE-01 A paid that
once, to decide whether the ``outputs/`` co-tenants partition into disjoint
groups (they do not - every ``final_runner`` test writes ``outputs/runs``). The
measured table is committed in the test notes so the question is
answered from the record rather than re-run. This tool is here so that a *new*
test can be measured on its own, in its own duration, instead of re-deriving the
method and re-running the whole set.

**The method, and its one trap.** Snapshot ``outputs/`` (path -> mtime_ns, size),
run the test, snapshot again, diff. The trap is that the snapshot has to survive
a JSON round-trip: storing ``(mtime, size)`` as a tuple and reloading it as a
list makes every single entry compare unequal, and the diff then reports the
entire tree as written. That is not a hypothetical - it is what the first run of
this produced, and the tell was that the "changed" count was exactly the total
file count. Hence lists, and hence ``--control``.

**Preconditions matter as much as for a lane.** Move ``outputs/runs/`` aside
first (never delete), keep ``outputs/charts`` (it is an input, CHARTSDEP-01), and
run nothing else concurrently - a second process writing under ``outputs/`` is
indistinguishable from the test under measurement.

Usage::

    python tests/tools/outputs_writeset.py --control          # prove it reads 0 on an untouched tree
    python tests/tools/outputs_writeset.py snap  base.json
    python -m pytest tests/test_whatever.py -q
    python tests/tools/outputs_writeset.py diff  base.json    # what the test wrote
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

ROOT = "outputs"


def snapshot(root: str = ROOT) -> dict[str, list[int]]:
    """path -> [mtime_ns, size]. Lists, not tuples: see the module docstring."""
    out: dict[str, list[int]] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            p = pathlib.Path(dirpath, name)
            try:
                st = p.stat()
            except OSError:
                continue
            out[str(p).replace("\\", "/")] = [st.st_mtime_ns, st.st_size]
    return out


def changed_since(base_path: str) -> list[str]:
    base = json.load(open(base_path, encoding="utf-8"))
    now = snapshot()
    return sorted(k for k in now if k not in base or now[k] != base[k])


def subtrees(paths: list[str]) -> list[str]:
    return sorted({
        "/".join(p.split("/")[:2]) if len(p.split("/")) > 2 else f"{ROOT}/<root file>"
        for p in paths
    })


def report(base_path: str) -> int:
    changed = changed_since(base_path)
    print(f"  files written/changed: {len(changed)}")
    for s in subtrees(changed):
        print(f"    {s}")
    return 0


def control() -> int:
    """An untouched tree must diff to zero. Run this before trusting any number.

    Without it, a diff that reports "everything changed" and a diff that reports
    the truth look equally plausible on a tree nobody has memorised.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        base = pathlib.Path(d, "control.json")
        json.dump(snapshot(), open(base, "w", encoding="utf-8"))
        changed = changed_since(str(base))
    if changed:
        print(f"CONTROL FAILED: {len(changed)} files reported changed on an untouched tree")
        for c in changed[:10]:
            print(f"    {c}")
        return 1
    print("CONTROL PASSED: untouched tree diffs to 0")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--control":
        sys.exit(control())
    if len(sys.argv) == 3 and sys.argv[1] == "snap":
        s = snapshot()
        json.dump(s, open(sys.argv[2], "w", encoding="utf-8"))
        print(f"baseline: {len(s)} files")
        sys.exit(0)
    if len(sys.argv) == 3 and sys.argv[1] == "diff":
        sys.exit(report(sys.argv[2]))
    print(__doc__)
    sys.exit(2)
