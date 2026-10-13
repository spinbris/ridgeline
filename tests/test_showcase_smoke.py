"""The showcase entry point runs to completion and writes what it promises.

SHOWCASE-RENDER-01. `scripts/run_wind_showcase.py` is this repository's own
end-to-end demonstration: it runs all three engine layers against the committed
synthetic fixtures and writes the deliverable substrate. It crashed partway
through `render()` on an undefined name, and **no test exercised it**, so it
stopped working at an unknown date in two repositories and neither noticed.

WHY THIS ASSERTS THE OUTPUTS AND NOT THE EXIT CODE
    The crash happened *after* four of the promised files had been written. A
    test that only checked the process exited cleanly would have caught it, but a
    test that checked "some output appeared" would not — and that is the tempting
    shape. Every file the module docstring promises is asserted by name, so a
    future partial render fails here rather than being noticed by a person
    opening the folder.

WHY IT IS `slow`, and it is not because it is slow
    Measured at ~23s, which would sit in the per-stage gate comfortably. It
    carries the marker because it WRITES TO `outputs/`, and this suite groups
    every outputs-writer onto one xdist worker (`conftest._OUTPUTS_GROUP`) to
    keep them from colliding — the same shared state CACHEFIDELITY-01 is about.
    Adding an outputs-writer to the fast lane widens that surface for no gain,
    because the fast counterpart already covers this defect class.

    That counterpart is `test_no_undefined_names.py`, which catches the class
    statically across the whole tree in under a second. So the cheap check runs
    every stage and this one runs at the merge — and if you are tempted to
    de-mark this for speed, the 23s is not the reason it is here.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_wind_showcase.py"
OUT_DIR = REPO_ROOT / "outputs" / "wind_showcase"

#: Every artefact the script's own docstring promises.
PROMISED = (
    "wind_cost_qra.md",
    "wind_sra_schedule.md",
    "wind_stage3_cpm.md",
    "wind_integrated_headline.md",
)


@pytest.mark.slow
def test_showcase_runs_and_writes_every_promised_output(tmp_path):
    """Run the entry point for real; assert each promised file exists.

    Run in a subprocess deliberately: the script is invoked as a script by
    anyone using it, and importing it instead would exercise a path the user
    never takes and skip its ``__main__`` guard and argument handling.
    """
    # Deliberately NOT a skip. The entry point is a tracked file, so its absence
    # is a defect and not an environmental condition - and a skip here would be
    # exactly the "coverage traded for a green lane" shape the guard rules forbid.
    # (The first draft skipped, with an interpolated reason, and
    # test_no_skip_reason_interpolates_a_value caught it.)
    assert SCRIPT.is_file(), "scripts/run_wind_showcase.py is missing from the repository."

    before = {p.name: p.stat().st_mtime_ns for p in OUT_DIR.glob("*") if p.is_file()}

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--allow-dirty"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=1800,
    )

    assert proc.returncode == 0, (
        f"the showcase exited {proc.returncode}. It is this repository's own "
        f"demonstration path, so a non-zero exit means the demonstration does not "
        f"run.\n--- stderr tail ---\n{proc.stderr[-2000:]}"
    )

    missing = [name for name in PROMISED if not (OUT_DIR / name).is_file()]
    assert not missing, (
        f"the showcase exited cleanly but did not write: {missing}. Every file "
        "named here is promised by the script's own docstring; a partial render "
        "is the defect this test exists for."
    )

    # A pre-existing file left by an earlier run must not be mistaken for output
    # this run produced - that is how a broken renderer keeps looking fine.
    stale = [
        name for name in PROMISED
        if name in before and (OUT_DIR / name).stat().st_mtime_ns == before[name]
    ]
    assert not stale, (
        f"these files were not rewritten by this run and are stale from an "
        f"earlier one: {stale}. The run did not actually produce them."
    )
