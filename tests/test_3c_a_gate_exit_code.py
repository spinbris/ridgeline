"""3c Part A: the entry point's exit code, and the stale manifest it must not trust.

Raised as a BLOCKER by the Part A numerics review, and it was right twice over: the gate could
report PASS for a run that never completed, and **nothing tested it at all** - the D-11
exit-code evidence was two manual runs in the record, which cannot catch a regression.

The defect: ``RUN_FINAL.bat`` runs nbconvert with ``--allow-errors`` (D-11 - without it the
raising last cell aborts the conversion and no HTML is written at all), so nbconvert exits 0
whatever happened and the verdict has to come from the manifest. But the manifest path is keyed
by date and project only. A run that crashes today, after a run that passed today, finds the
earlier run's manifest and inherits its PASS - a gate passing against the wrong artefact.

The fix is a per-invocation token: the entry point generates one, the run stamps it into the
manifest, and the gate refuses any manifest that does not carry it. These tests hold that from
both sides, because only one side proves anything.
"""
from __future__ import annotations

import json

import pytest

from src.final.deliverable import RUN_TOKEN_ENV, gate_exit_code, manifest_path


def _write(path, *, all_pass: bool, token: str | None):
    payload = {"cross_validation_all_pass": all_pass, "artefacts": []}
    if token is not None:
        payload["run_token"] = token
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_passing_manifest_for_this_run_exits_zero(tmp_path):
    m = _write(manifest_path(tmp_path, "p", "2026-09-04"), all_pass=True, token="tok-1")
    assert gate_exit_code(m, expected_token="tok-1") == 0


def test_a_failing_manifest_for_this_run_exits_one(tmp_path):
    m = _write(manifest_path(tmp_path, "p", "2026-09-04"), all_pass=False, token="tok-1")
    assert gate_exit_code(m, expected_token="tok-1") == 1


def test_an_earlier_passing_run_today_cannot_supply_this_runs_verdict(tmp_path):
    """The BLOCKER, as a test. This is the case that used to exit 0.

    The scenario in full: a run passes at 09:00 and writes its manifest. A second run at 11:00
    crashes in cell 1 - before writing anything - so the 09:00 manifest is still sitting at the
    date-and-project path, saying all_pass true. Without the token the gate reads it and
    reports PASS for a run that produced nothing.
    """
    earlier = _write(manifest_path(tmp_path, "p", "2026-09-04"),
                     all_pass=True, token="token-from-the-0900-run")

    # the 11:00 run's token never reached a manifest, because it crashed first
    assert gate_exit_code(earlier, expected_token="token-from-the-1100-run") == 2, (
        "the gate accepted an earlier run's manifest as this run's verdict"
    )
    # and the control: with no token expectation at all, the stale manifest DOES pass -
    # which is precisely why the entry point must always pass one.
    assert gate_exit_code(earlier) == 0


def test_a_manifest_with_no_token_is_not_accepted_when_one_is_expected(tmp_path):
    """A manifest written by an older engine predates the token; it is not this run's."""
    m = _write(manifest_path(tmp_path, "p", "2026-09-04"), all_pass=True, token=None)
    assert gate_exit_code(m, expected_token="tok-1") == 2


def test_a_missing_manifest_is_incomplete_not_a_failure(tmp_path):
    """Exit 2, matching the runner's documented contract: the run did not complete.

    Distinct from 1, which means the run completed and its gate failed - a state with
    bannered artefacts on disk to investigate. Conflating them would tell a specialist to
    look for evidence that was never written.
    """
    assert gate_exit_code(manifest_path(tmp_path, "p", "2026-09-04"), "tok-1") == 2


def test_an_unreadable_manifest_is_incomplete_rather_than_a_pass(tmp_path):
    m = manifest_path(tmp_path, "p", "2026-09-04")
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text("{not json", encoding="utf-8")
    assert gate_exit_code(m, expected_token="tok-1") == 2


def test_the_run_stamps_the_entry_points_token_into_its_manifest(monkeypatch):
    """The other half of the mechanism: the token has to actually reach the manifest."""
    from src.final import deliverable

    monkeypatch.setenv(RUN_TOKEN_ENV, "tok-xyz")
    assert deliverable._run_token() == "tok-xyz"
    monkeypatch.setenv(RUN_TOKEN_ENV, "   ")
    assert deliverable._run_token() is None
    monkeypatch.delenv(RUN_TOKEN_ENV, raising=False)
    assert deliverable._run_token() is None


def test_the_runner_generates_a_token_and_passes_it_to_the_gate():
    """Read off the entry point: a mechanism only one side implements is not a mechanism."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "RUN_FINAL.bat").read_text(encoding="utf-8")
    assert "QRA_RUN_TOKEN" in text, "the runner does not generate a per-invocation token"
    assert "NewGuid" in text, "the token is not unique per invocation"
    assert "--gate" in text


@pytest.mark.parametrize("code", [0, 1, 2])
def test_every_documented_exit_code_is_reachable(code, tmp_path):
    """The runner's header documents 0, 1 and 2; each must be produced by something."""
    reachable = {
        0: lambda: gate_exit_code(
            _write(manifest_path(tmp_path, "p", "d"), all_pass=True, token="t"), "t"),
        1: lambda: gate_exit_code(
            _write(manifest_path(tmp_path, "p", "d"), all_pass=False, token="t"), "t"),
        2: lambda: gate_exit_code(manifest_path(tmp_path, "absent", "d"), "t"),
    }
    assert reachable[code]() == code
