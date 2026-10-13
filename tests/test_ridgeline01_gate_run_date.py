"""RIDGELINE-01 round 4, item 3: the gate judges THIS run's manifest, whatever the clock says.

``RUN_FINAL.bat`` calls ``--gate`` with no ``--run-date``, and the gate used to locate the manifest
by its own read of today's date. A run that started before midnight wrote its manifest under the
old date; the gate, after midnight, looked under the new one and exited 2 INCOMPLETE on a run that
had completed. The run stamps the entry point's token into its manifest, so the gate finds the
manifest by that token. It still fails closed when no manifest carries it.
"""
from __future__ import annotations

import datetime
import json

import pytest

from src.final import deliverable

PROJECT = "probe_key"
TOKEN = "11111111-2222-3333-4444-555555555555"


class _AfterMidnight(datetime.date):
    @classmethod
    def today(cls):
        return datetime.date(2026, 9, 30)


def _manifest(root, run_date, token, passed=True):
    folder = root / "runs" / f"{run_date}_{PROJECT}"
    folder.mkdir(parents=True)
    (folder / deliverable.MANIFEST_NAME).write_text(
        json.dumps({"run_token": token, "cross_validation_all_pass": passed}), encoding="utf-8")


@pytest.fixture
def after_midnight(monkeypatch):
    monkeypatch.setattr(datetime, "date", _AfterMidnight)
    monkeypatch.setenv("QRA_PROJECT", PROJECT)
    monkeypatch.setenv(deliverable.RUN_TOKEN_ENV, TOKEN)


def test_a_run_that_crossed_midnight_is_judged_on_its_own_manifest(after_midnight, tmp_path):
    _manifest(tmp_path, "2026-09-29", TOKEN)
    assert deliverable._cli(["--gate", "--output-dir", str(tmp_path)]) == 0


def test_its_failure_is_still_reported_as_a_failure(after_midnight, tmp_path):
    _manifest(tmp_path, "2026-09-29", TOKEN, passed=False)
    assert deliverable._cli(["--gate", "--output-dir", str(tmp_path)]) == 1


def test_no_manifest_carrying_this_token_fails_closed(after_midnight, tmp_path):
    _manifest(tmp_path, "2026-09-29", "an-earlier-run")
    _manifest(tmp_path, "2026-09-30", "another-earlier-run")
    assert deliverable._cli(["--gate", "--output-dir", str(tmp_path)]) == 2


def test_no_manifest_at_all_fails_closed(after_midnight, tmp_path):
    assert deliverable._cli(["--gate", "--output-dir", str(tmp_path)]) == 2


def test_another_project_s_manifest_is_never_taken(after_midnight, tmp_path):
    folder = tmp_path / "runs" / f"2026-09-29_other_{PROJECT}"
    folder.mkdir(parents=True)
    (folder / deliverable.MANIFEST_NAME).write_text(
        json.dumps({"run_token": TOKEN, "cross_validation_all_pass": True}), encoding="utf-8")
    assert deliverable._cli(["--gate", "--output-dir", str(tmp_path)]) == 2


def test_two_manifests_carrying_the_token_fail_closed_and_are_named(after_midnight, tmp_path, capsys):
    """Round 5 (gate 3 round 4, breaker WARN): a reused token. Day A passed; day B, under the same
    token, failed. The gate took the oldest match and reported day A's PASS, exit 0."""
    _manifest(tmp_path, "2026-09-28", TOKEN, passed=True)
    _manifest(tmp_path, "2026-09-29", TOKEN, passed=False)
    assert deliverable._cli(["--gate", "--output-dir", str(tmp_path)]) == 2
    out = capsys.readouterr().out
    assert f"2026-09-28_{PROJECT}" in out and f"2026-09-29_{PROJECT}" in out, out
