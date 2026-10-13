"""AM09: ws4a_repro_gate meta-allowlist boundary.

The gate neutralises the additive AM09 provenance meta fields + the top-level
schema_version string, but must keep EVERY number bit-locked. These tests pin
that boundary: a run that differs ONLY in those allowlisted fields PASSES, and a
run where a single headline number moves FAILS. The gate is run in-process via the
script's main(argv); the exit code is what is asserted (RS-A2).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_GATE = _ROOT / "scripts" / "ws4a_repro_gate.py"


def _baseline() -> dict:
    """A pre-AM09 (schema 1.0, no provenance stamp) frozen baseline shape."""
    return {
        "schema_version": "1.0",
        "meta": {
            "engine_run_hash": "00000000-0000-4000-8000-000000000000",
            "engine_run_date": "2026-05-28T14:00:00Z",
            "period_end_date": "2026-05-28",
            "iterations": 1000,
            "seed": 42,
        },
        "headline": {"p80_days_behind_plan": 12.5},
        "risks": [
            {
                "risk_id": "R001",
                "days_at_risk_p80": 3.0,
                "tornado_sample_sigma_days": 1.1,
            }
        ],
    }


def _stamped_candidate() -> dict:
    """The same run, AM09-stamped: schema 1.2 + provenance meta, a fresh nonce,
    and the interim popped risk field moved - but every NUMBER identical."""
    doc = _baseline()
    doc["schema_version"] = "1.2"
    doc["meta"]["engine_run_hash"] = "11111111-1111-4111-8111-111111111111"
    doc["meta"].update(
        engine_sha="5972da0d28907f7f8e86963dfb3df9029daacb02",
        engine_sha_pinned="5972da0d28907f7f8e86963dfb3df9029daacb02",
        engine_sha_matches_pin=True,
        engine_tree_dirty=False,
        input_sha256={"register": "a" * 64, "xer": "b" * 64, "workbook": "c" * 64},
    )
    # neutralised (popped) interim field may legitimately move
    doc["risks"][0]["tornado_sample_sigma_days"] = 9.9
    return doc


def _run_gate(tmp_path: Path, baseline: dict, candidate: dict) -> int:
    (tmp_path / "base.json").write_text(json.dumps(baseline), encoding="utf-8")
    (tmp_path / "cand.json").write_text(json.dumps(candidate), encoding="utf-8")
    # In-process (RS-A2): the script exposes main(argv) -> int; a subprocess here would
    # trip the shell-out guard for no property gained - the exit code is what is asserted.
    import importlib.util
    spec = importlib.util.spec_from_file_location("ws4a_repro_gate", _GATE)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod.main(["ws4a_repro_gate.py", str(tmp_path / "base.json"), str(tmp_path / "cand.json")])


def test_gate_passes_when_only_allowlisted_fields_differ(tmp_path: Path) -> None:
    assert _run_gate(tmp_path, _baseline(), _stamped_candidate()) == 0


def test_gate_fails_when_a_headline_number_moves(tmp_path: Path) -> None:
    cand = _stamped_candidate()
    cand["headline"]["p80_days_behind_plan"] = 12.6  # one number moved
    assert _run_gate(tmp_path, _baseline(), cand) == 1


def test_gate_fails_when_a_risk_number_moves(tmp_path: Path) -> None:
    cand = _stamped_candidate()
    cand["risks"][0]["days_at_risk_p80"] = 3.1  # a locked number moved
    assert _run_gate(tmp_path, _baseline(), cand) == 1
