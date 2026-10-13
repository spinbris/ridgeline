"""PROCDIET-01 A1 and A4: run the audit lane's pytest half, retrying a failure exactly once.

Runs the node IDs in ``tests/audit_lane.txt``. When tests fail (a failure or an error), the failed
ones are rerun once, by node ID and with the first run's worker count:
- a golden failed: red at once, never retried (GATEHOLD-01 P1). A golden is seeded and exact, so
  a pass on a second try would hide a moved number, not a flake;
- failed twice, or not run by the retry: red (P2);
- passed on the retry: green, and each such test is printed as a FLAKE. It leaves the audit
  lane and gets a register row (A4); this script never edits the list itself.

A collection error or a missing node ID is never retried. Exit 0 is green.

Usage:
    python scripts/audit_lane.py [-n 4] [--report flakes.txt]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIST = REPO / "tests" / "audit_lane.txt"


def node_ids() -> list[str]:
    lines = LIST.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def is_golden(node: str) -> bool:
    """A golden by where it lives: under ``tests/golden/``, or a file named for one (the period
    golden, ``tests/test_7a_period_json_golden.py``)."""
    path = node.split("::", 1)[0].replace("\\", "/")
    return path.startswith("tests/golden/") or "golden" in path.rsplit("/", 1)[-1]


def pytest(args: list[str], report: str) -> tuple[int, dict[str, set[str]]]:
    """Runs pytest; returns its exit code and each reported node's outcomes from the short
    summary (``report`` is the ``-r`` characters). A node can carry two: PASSED, then ERROR in
    teardown."""
    cmd = [sys.executable, "-m", "pytest", *args, "-q", f"-r{report}"]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    outcomes: dict[str, set[str]] = {}
    for ln in proc.stdout.splitlines():
        word, _, rest = ln.partition(" ")
        if word in ("FAILED", "ERROR", "PASSED") and rest:
            outcomes.setdefault(rest.split(" - ", 1)[0], set()).add(word)
    return proc.returncode, outcomes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-n", default="4", help="pytest-xdist workers")
    ap.add_argument("--report", type=Path, help="write the flakes, one per line, here")
    args = ap.parse_args(argv)

    rc, first = pytest([*node_ids(), "-n", args.n, "--durations=10"], "fE")
    failed = [node for node, seen in first.items() if seen & {"FAILED", "ERROR"}]
    flakes: list[str] = []
    goldens = [f for f in failed if is_golden(f)]
    if rc == 1 and goldens:
        for g in goldens:
            print(f"GOLDEN FAILED (never retried, GATEHOLD-01 P1): {g}")
    elif rc == 1 and failed:
        print(f"\nA4: {len(failed)} failed; retrying them once.\n")
        rc_again, again = pytest([*failed, "-n", args.n], "fEp")
        flakes = [f for f in failed if again.get(f) == {"PASSED"}]
        for f in failed:
            if f not in flakes:
                print(f"FAILED AGAIN, or not run by the retry: {f}")
        rc = 0 if rc_again == 0 and len(flakes) == len(failed) else 1
        if rc:  # a retry that failed certifies nothing, so it names no flake
            flakes = []
    for f in flakes:
        print(f"FLAKE (passed on the retry; quarantine it and raise a register row): {f}")
    if args.report:
        args.report.write_text("".join(f"{f}\n" for f in flakes), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
