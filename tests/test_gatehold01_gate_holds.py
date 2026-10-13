"""GATEHOLD-01: the gate holds.

P1  a golden that fails on the first run fails the audit lane; it is never retried.
P2  a retry is honest: a test is a flake only if the retry ran it and it passed there, and the
    retry keeps the first run's worker count.
P3  a diff touching the gate's own files (the audit list, the scripts the audit lane and `ci.yml`
    run, `.github/workflows/`) classifies Track N, naming the path.

`scripts/audit_lane.py` is driven through a stand-in for the `subprocess` module that answers
with pytest's own summary lines, honouring the `-r` characters it was asked for, so the script
parses exactly what it would parse in CI. `scripts/track.py` is fed `git diff --name-status`
text. Nothing here shells out.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

GOLDEN = "tests/golden/test_golden.py::test_golden_headline[synthetic_wind-p80]"
PERIOD_GOLDEN = "tests/test_7a_period_json_golden.py::test_period_json_matches_golden"
REFUSAL = "tests/test_rsd2_calibration_tolerance.py::test_reader_raises_for_a_workbook_without_tolerances"
OTHER = "tests/test_configtruth01_seed.py::test_a_negative_or_non_numeric_seed_is_refused_by_name"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"gatehold01_{name}", REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakePytest:
    """Answers each pytest call in turn: ``runs`` is a list of (returncode, {node: outcome}). An
    outcome may be a tuple, one summary line each: ("PASSED", "ERROR") is a teardown error."""

    _FLAG = {"FAILED": "f", "ERROR": "E", "PASSED": "p"}

    def __init__(self, runs):
        self.runs = list(runs)
        self.calls: list[list[str]] = []

    def run(self, cmd, **_):
        self.calls.append(list(cmd))
        rc, outcomes = self.runs.pop(0)
        chars = "".join(a[2:] for a in cmd if a.startswith("-r"))
        lines = ["=========================== short test summary info ============================"]
        for node, seen in outcomes.items():
            for outcome in (seen,) if isinstance(seen, str) else seen:
                if self._FLAG[outcome] in chars or ("A" in chars):
                    lines.append(f"{outcome} {node}" + ("" if outcome == "PASSED" else " - AssertionError"))
        return subprocess.CompletedProcess(cmd, rc, "\n".join(lines) + "\n", "")


@pytest.fixture
def lane(monkeypatch):
    module = _load("audit_lane")

    def drive(runs, argv=()):
        fake = FakePytest(runs)
        monkeypatch.setattr(module, "subprocess", fake)
        return module.main(list(argv)), fake

    return drive


# --- P1: a golden is never retried ---------------------------------------------------------------

@pytest.mark.parametrize("golden", [GOLDEN, PERIOD_GOLDEN])
def test_p1_a_golden_that_fails_once_then_passes_fails_the_lane(lane, golden, capsys):
    rc, fake = lane([(1, {golden: "FAILED", REFUSAL: "PASSED"}), (0, {golden: "PASSED"})])
    assert rc == 1
    assert len(fake.calls) == 1, "a golden failure must not be retried"
    assert golden in capsys.readouterr().out


def test_p1_a_golden_failing_beside_a_flaky_refusal_still_fails_the_lane(lane):
    rc, fake = lane([(1, {GOLDEN: "FAILED", REFUSAL: "FAILED"}),
                     (0, {GOLDEN: "PASSED", REFUSAL: "PASSED"})])
    assert rc == 1
    assert len(fake.calls) == 1


# --- P2: any retry is honest ---------------------------------------------------------------------

def test_p2_a_failure_the_retry_did_not_run_stays_a_failure(lane, capsys):
    rc, _ = lane([(1, {REFUSAL: "FAILED", OTHER: "FAILED"}), (0, {REFUSAL: "PASSED"})])
    assert rc == 1
    assert f"FAILED AGAIN, or not run by the retry: {OTHER}" in capsys.readouterr().out


def test_p2_the_retry_keeps_the_worker_count_and_runs_exactly_the_failures(lane):
    rc, fake = lane([(1, {REFUSAL: "FAILED", OTHER: "PASSED"}), (0, {REFUSAL: "PASSED"})], ["-n", "4"])
    retry = fake.calls[1]
    assert retry[retry.index("-n") + 1] == "4"
    assert REFUSAL in retry and OTHER not in retry
    assert "--lf" not in retry  # the cache is not what decides what reruns
    assert rc == 0


def test_p2_an_error_counts_as_a_failure_and_is_retried(lane):
    rc, fake = lane([(1, {REFUSAL: "ERROR"}), (1, {REFUSAL: "ERROR"})])
    assert rc == 1
    assert REFUSAL in fake.calls[1]


def test_p2_a_retry_that_exits_non_zero_is_never_green_and_names_no_flake(lane, tmp_path, capsys):
    report = tmp_path / "flakes.txt"
    rc, _ = lane([(1, {REFUSAL: "FAILED"}), (1, {REFUSAL: "PASSED"})], ["--report", str(report)])
    assert rc == 1
    assert "FLAKE" not in capsys.readouterr().out
    assert report.read_text(encoding="utf-8") == ""


def test_p2_a_pass_with_a_teardown_error_on_the_retry_is_not_a_flake(lane, tmp_path):
    # Exit code 0 is staged on purpose, so only the per-node outcomes can keep this red.
    report = tmp_path / "flakes.txt"
    rc, _ = lane([(1, {REFUSAL: "FAILED"}), (0, {REFUSAL: ("PASSED", "ERROR")})],
                 ["--report", str(report)])
    assert rc == 1
    assert report.read_text(encoding="utf-8") == ""


def test_p2_a_genuine_flake_is_green_and_named(lane, tmp_path, capsys):
    report = tmp_path / "flakes.txt"
    rc, _ = lane([(1, {REFUSAL: "FAILED"}), (0, {REFUSAL: "PASSED"})], ["--report", str(report)])
    assert rc == 0
    assert f"FLAKE (passed on the retry; quarantine it and raise a register row): {REFUSAL}" \
        in capsys.readouterr().out
    assert report.read_text(encoding="utf-8") == f"{REFUSAL}\n"


@pytest.mark.parametrize("rc_first", [2, 4])
def test_p2_a_collection_error_or_missing_node_is_never_retried(lane, rc_first):
    rc, fake = lane([(rc_first, {})])
    assert rc == rc_first
    assert len(fake.calls) == 1


# --- P3: the gate's own files are Track N --------------------------------------------------------

GATE_FILES = [
    "tests/audit_lane.txt",
    "scripts/track.py",
    "scripts/audit_lane.py",
    "scripts/output_pack.py",
    "scripts/ws4a_repro_gate.py",
    ".github/workflows/ci.yml",
    ".github/workflows/nightly.yml",
]


@pytest.fixture
def classify(monkeypatch):
    module = _load("track")

    def run(name_status):
        monkeypatch.setattr(module, "_git", lambda *args: name_status if args[0] == "diff" else "")
        return module.classify("base", "head")

    return run


@pytest.mark.parametrize("path", GATE_FILES)
def test_p3_an_edit_to_a_gate_file_is_track_n_naming_the_path(classify, path):
    track, reasons = classify(f"M\t{path}\n")
    assert track == "N"
    assert any(r.startswith(f"{path}:") for r in reasons), reasons


def test_p3_a_docs_edit_stays_track_l(classify):
    readme = "README.md"
    assert classify(f"M\t{readme}\n") == ("L", [])
