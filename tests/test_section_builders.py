"""Unit tests for the SR14a section-builder modules.

Per the SR14a brief §6 (Acceptance criteria):
- AC4: each section-builder has a unit test asserting its returned
  dict-shape contract against the documented schema in the builder's
  docstring.
- AC5: each section-builder's docstring contains a "Returns" section.
- AC7: section-builder unit tests pass without invoking the full
  composer (each builder is independently testable from its inputs).

This file covers the three sections extracted in this sprint:
``audit_trail``, ``risk_matrix``, and ``walkthrough``. The other six
section modules are scaffolding stubs whose extraction is queued for a
follow-up brief — their stubs raise ``NotImplementedError`` and are not
exercised here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.final.sections import (
    build_action_implications_section,
    build_audit_trail_section,
    build_cost_drivers_section,
    build_criticality_section,
    build_page1_table_section,
    build_risk_matrix_section,
    build_s_curves_section,
    build_schedule_drivers_section,
    build_walkthrough_section,
)
from src.final.sections.audit_trail import (
    _build_counterfactual_narrative,
    _hash_file,
    build_cross_validation_sentence,
)
from src.final.sections.risk_matrix import _build_risk_matrix_data
from src.final.sections.walkthrough import _build_single_iteration_walkthrough


# ---------------------------------------------------------------------------
# audit_trail
# ---------------------------------------------------------------------------


def test_hash_file_missing_returns_sentinel(tmp_path: Path) -> None:
    """Missing files return the documented sentinel string."""
    assert _hash_file(tmp_path / "does_not_exist.bin") == "(file not found)"


def test_hash_file_matches_sha256(tmp_path: Path) -> None:
    """Output matches the stdlib SHA-256 of the file bytes."""
    p = tmp_path / "payload.bin"
    payload = b"the quick brown fox jumps over the lazy dog\n"
    p.write_bytes(payload)
    assert _hash_file(p) == hashlib.sha256(payload).hexdigest()


def test_build_cross_validation_sentence_all_pass() -> None:
    """All-gates-pass path names the per-gate consistency."""
    cv = {
        "all_pass": True,
        "cost_absolute_gap_dollars": 25_000.0,
        "cost_relative_gap_pct": 0.05,
        "schedule_absolute_gap_days": 0.5,
        "top_3_cost_contributors_integrated": ["R028", "R051", "R013"],
        "top_3_schedule_contributors_integrated": ["R090", "R017.1", "R067"],
        "top_3_cost_contributors_consistent": True,
        "top_3_schedule_contributors_consistent": True,
    }
    out = build_cross_validation_sentence(cv, n_iter=100_000)
    assert "all four gates passed" in out
    assert "100,000-iteration" in out
    assert "consistent (R028, R051, R013)" in out
    assert "consistent (R090, R017.1, R067)" in out


def test_build_cross_validation_sentence_failed_inverts() -> None:
    """Failed-gate path produces FAIL banner copy and names failed gates."""
    cv = {
        "all_pass": False,
        "cost_passes_calibration": False,
        "schedule_passes_calibration": True,
        "top_3_cost_contributors_consistent": True,
        "top_3_schedule_contributors_consistent": True,
        "cost_absolute_gap_dollars": 100_000.0,
        "cost_relative_gap_pct": 1.2,
        "schedule_absolute_gap_days": 0.1,
        "top_3_cost_contributors_integrated": ["R028"],
        "top_3_schedule_contributors_integrated": ["R090"],
    }
    out = build_cross_validation_sentence(cv, n_iter=100_000)
    assert "FAILED" in out
    assert "cost marginal calibration" in out
    assert "deliverable is suppressed" in out


def test_build_cross_validation_sentence_empty_dict_returns_empty_string() -> None:
    assert build_cross_validation_sentence({}, n_iter=100_000) == ""


def test_build_counterfactual_narrative_no_duplicates_returns_none() -> None:
    df = pd.DataFrame({"is_duplicate_of_baseline": [False, False, False]})
    assert _build_counterfactual_narrative(df, "All Series") is None


def test_build_counterfactual_narrative_with_duplicates() -> None:
    df = pd.DataFrame({
        "is_duplicate_of_baseline": [True, True, False, True],
    })
    out = _build_counterfactual_narrative(df, "All Series")
    assert out is not None
    assert "3 of 4" in out
    assert "All Series" in out


def test_build_counterfactual_narrative_empty_or_none() -> None:
    assert _build_counterfactual_narrative(None, "X") is None
    assert _build_counterfactual_narrative(pd.DataFrame(), "X") is None


def test_build_audit_trail_section_contract(tmp_path: Path) -> None:
    """Returns dict honouring every documented key including injected
    reproducibility paragraph and computed input hashes."""
    register = tmp_path / "register.xlsx"
    register.write_bytes(b"register-bytes")
    strawman = tmp_path / "strawman.xlsx"
    strawman.write_bytes(b"strawman-bytes")
    p6 = tmp_path / "p6.xlsx"
    p6.write_bytes(b"p6-bytes")

    appendix = {
        "register_path": str(register),
        "iterations": 100_000,
        "random_seed": 42,
    }
    cv = {
        "all_pass": True,
        "cost_absolute_gap_dollars": 0.0,
        "cost_relative_gap_pct": 0.0,
        "schedule_absolute_gap_days": 0.0,
        "top_3_cost_contributors_integrated": ["R028"],
        "top_3_schedule_contributors_integrated": ["R090"],
        "top_3_cost_contributors_consistent": True,
        "top_3_schedule_contributors_consistent": True,
    }
    out = build_audit_trail_section(
        appendix_audit_trail=appendix,
        cross_validation=cv,
        register_path=register,
        strawman_path=strawman,
        p6_path=p6,
        n_iter=100_000,
        reproducibility_paragraph="REPRO PARAGRAPH",
    )

    # Pass-through of appendix keys.
    assert out["register_path"] == str(register)
    assert out["iterations"] == 100_000
    # Injected reproducibility paragraph (Stage 2.5-specific narrative).
    assert out["reproducibility_paragraph"] == "REPRO PARAGRAPH"
    # Input hashes are SHA-256 hex digests.
    assert out["input_hashes"]["register_sha256"] == hashlib.sha256(
        b"register-bytes",
    ).hexdigest()
    assert out["input_hashes"]["strawman_sha256"] == hashlib.sha256(
        b"strawman-bytes",
    ).hexdigest()
    assert out["input_hashes"]["p6_sha256"] == hashlib.sha256(
        b"p6-bytes",
    ).hexdigest()
    # Cross-validation sentence string.
    assert isinstance(out["cross_validation_sentence"], str)
    assert "all four gates passed" in out["cross_validation_sentence"]


def test_build_audit_trail_section_omits_p6_hash_when_none(tmp_path: Path) -> None:
    register = tmp_path / "register.xlsx"
    register.write_bytes(b"x")
    strawman = tmp_path / "strawman.xlsx"
    strawman.write_bytes(b"y")
    out = build_audit_trail_section(
        appendix_audit_trail={},
        cross_validation={},
        register_path=register,
        strawman_path=strawman,
        p6_path=None,
        n_iter=1_000,
        reproducibility_paragraph="r",
    )
    assert "p6_sha256" not in out["input_hashes"]
    assert set(out["input_hashes"]) == {"register_sha256", "strawman_sha256"}


# ---------------------------------------------------------------------------
# risk_matrix
# ---------------------------------------------------------------------------


def _make_risk(rid: str, prob: float, opt: float, ml: float, pess: float) -> SimpleNamespace:
    return SimpleNamespace(
        risk_id=rid,
        probability=prob,
        opt_schedule_days=opt,
        ml_days=ml,
        pess_schedule_days=pess,
    )


def test_build_risk_matrix_section_contract() -> None:
    """Dict has the documented ``data`` key; entries carry the documented
    four fields per included risk."""
    risks = [
        _make_risk("R001", 0.20, 5.0, 10.0, 30.0),
        _make_risk("R002", 0.10, 1.0, 2.0, 3.0),
    ]
    # Synthetic integrated_results with two dual-coded risks and a
    # per-risk schedule array whose column means feed pw_lookup.
    integrated = {
        "per_risk_schedule_array": np.array([[2.0, 1.0], [4.0, 3.0]]),
        "risk_ids_dual": ["R001", "R002"],
    }
    out = build_risk_matrix_section(risks=risks, integrated_results=integrated)
    assert set(out) == {"data"}
    assert len(out["data"]) == 2
    for entry in out["data"]:
        assert set(entry) == {
            "risk_id",
            "probability",
            "mean_impact",
            "prob_weighted_impact",
        }


def test_build_risk_matrix_excludes_inert_risks() -> None:
    """Risks with prob=0 AND ml=0 AND no engine entry drop out."""
    risks = [
        _make_risk("R-skip", 0.0, 0.0, 0.0, 0.0),
        _make_risk("R-keep", 0.50, 1.0, 2.0, 3.0),
    ]
    integrated = {
        "per_risk_schedule_array": np.array([[0.0, 1.0]]),
        "risk_ids_dual": ["R-skip-engine", "R-keep"],
    }
    out = build_risk_matrix_section(risks=risks, integrated_results=integrated)
    ids = {entry["risk_id"] for entry in out["data"]}
    assert "R-keep" in ids
    assert "R-skip" not in ids


def test_build_risk_matrix_left_panel_is_raw_ev_pert() -> None:
    """LEFT panel ``mean_impact`` is ``(opt + 4*ml + pess) / 6``."""
    risks = [_make_risk("R001", 0.20, 5.0, 10.0, 30.0)]
    integrated = {
        "per_risk_schedule_array": np.array([[2.0]]),
        "risk_ids_dual": ["R001"],
    }
    out = build_risk_matrix_section(risks=risks, integrated_results=integrated)
    entry = out["data"][0]
    expected = (5.0 + 4.0 * 10.0 + 30.0) / 6.0
    assert entry["mean_impact"] == pytest.approx(expected)
    # RIGHT panel is the engine column mean (Mode-multiplied).
    assert entry["prob_weighted_impact"] == pytest.approx(2.0)


def test_build_risk_matrix_data_legacy_helper_still_exported() -> None:
    """The private legacy helper is preserved for backward-compatible
    consumers; section-builder simply wraps it."""
    risks = [_make_risk("R001", 0.20, 0.0, 5.0, 10.0)]
    integrated = {
        "per_risk_schedule_array": np.array([[1.0]]),
        "risk_ids_dual": ["R001"],
    }
    direct = _build_risk_matrix_data(risks=risks, integrated_results=integrated)
    wrapped = build_risk_matrix_section(
        risks=risks, integrated_results=integrated,
    )["data"]
    assert direct == wrapped


# ---------------------------------------------------------------------------
# walkthrough
# ---------------------------------------------------------------------------


def test_build_walkthrough_section_contract() -> None:
    """Dict has the documented ``walkthrough`` key with a non-empty prose
    body when input arrays are non-empty."""
    rng = np.random.default_rng(0)
    n_iter = 200
    cost_arr = rng.uniform(0, 5_000_000, size=n_iter)
    sched_arr = rng.uniform(0, 40, size=n_iter)
    per_risk_cost = rng.uniform(0, 1_000_000, size=(n_iter, 2))
    per_risk_sched = rng.uniform(0, 10, size=(n_iter, 2))
    integrated = {
        "cost_dollars_array": cost_arr,
        "schedule_days_array": sched_arr,
        "per_risk_cost_array": per_risk_cost,
        "per_risk_schedule_array": per_risk_sched,
        "risk_ids_all": ["R001", "R002"],
        "risk_ids_dual": ["R001", "R002"],
    }
    out = build_walkthrough_section(integrated_results=integrated, risks=None)
    assert set(out) == {"walkthrough"}
    text = out["walkthrough"]
    assert isinstance(text, str)
    assert "Monte Carlo iteration #" in text
    assert "percentile" in text


def test_build_walkthrough_section_empty_arrays_returns_empty_string() -> None:
    """Empty cost/schedule arrays yield an empty walkthrough string."""
    integrated = {
        "cost_dollars_array": np.array([]),
        "schedule_days_array": np.array([]),
        "per_risk_cost_array": np.array([]),
        "per_risk_schedule_array": np.array([]),
        "risk_ids_all": [],
        "risk_ids_dual": [],
    }
    out = build_walkthrough_section(integrated_results=integrated, risks=None)
    assert out["walkthrough"] == ""


def test_build_walkthrough_section_target_percentile_respected() -> None:
    """``target_percentile`` parameter controls which iteration the
    walkthrough picks."""
    n_iter = 100
    cost_arr = np.linspace(1.0, 100.0, n_iter) * 1e6
    sched_arr = np.linspace(1.0, 100.0, n_iter)
    per_risk_cost = np.zeros((n_iter, 1))
    per_risk_sched = np.zeros((n_iter, 1))
    integrated = {
        "cost_dollars_array": cost_arr,
        "schedule_days_array": sched_arr,
        "per_risk_cost_array": per_risk_cost,
        "per_risk_schedule_array": per_risk_sched,
        "risk_ids_all": ["R001"],
        "risk_ids_dual": ["R001"],
    }
    # P50 should pick the median iteration.
    out_p50 = build_walkthrough_section(
        integrated_results=integrated, risks=None, target_percentile=50,
    )
    # P95 should pick a high-iteration scenario.
    out_p95 = build_walkthrough_section(
        integrated_results=integrated, risks=None, target_percentile=95,
    )
    assert out_p50["walkthrough"] != out_p95["walkthrough"]


def test_build_single_iteration_walkthrough_legacy_helper_parity() -> None:
    """The private legacy helper is preserved; section-builder wraps it
    without altering its return."""
    n_iter = 50
    rng = np.random.default_rng(1)
    integrated = {
        "cost_dollars_array": rng.uniform(0, 1e6, size=n_iter),
        "schedule_days_array": rng.uniform(0, 20, size=n_iter),
        "per_risk_cost_array": rng.uniform(0, 1e5, size=(n_iter, 1)),
        "per_risk_schedule_array": rng.uniform(0, 5, size=(n_iter, 1)),
        "risk_ids_all": ["R001"],
        "risk_ids_dual": ["R001"],
    }
    direct = _build_single_iteration_walkthrough(
        integrated_results=integrated, risks=None,
    )
    wrapped = build_walkthrough_section(
        integrated_results=integrated, risks=None,
    )["walkthrough"]
    assert direct == wrapped


# ---------------------------------------------------------------------------
# Scaffolding stubs (six remaining sections)
# ---------------------------------------------------------------------------


# SR14a.2 session B lifted the final two SR14a scaffolding stubs
# (s_curves, criticality), so all nine section-builder modules now
# implement real functions. The original
# ``test_scaffolding_stubs_raise_not_implemented`` parametrised over the
# stub list — with the list empty the test would collect zero cases
# and pytest would mark it as an error. The test is therefore removed
# at SR14a.2 close; the per-section-builder unit tests in this file
# (and ``tests/test_section_builders_session_a.py`` /
# ``tests/test_section_builders_session_b.py``) carry the contract
# coverage forward.


def test_composer_reexports_moved_helpers() -> None:
    """``src.final.composer`` still exposes the moved helpers at module
    level so legacy test imports (~50+ test sites) keep working."""
    from src.final import composer

    assert composer._hash_file is _hash_file
    assert (
        composer.build_cross_validation_sentence is build_cross_validation_sentence
    )
    assert (
        composer._build_counterfactual_narrative is _build_counterfactual_narrative
    )
    assert composer._build_risk_matrix_data is _build_risk_matrix_data
    assert (
        composer._build_single_iteration_walkthrough
        is _build_single_iteration_walkthrough
    )
