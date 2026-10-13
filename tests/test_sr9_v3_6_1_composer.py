"""SR9 v3.6.1 - composer credibility patch regression tests.

Asserts the four credibility patches stay in place across future sprints:

- A5: zero-expansion notice keys are emitted when the audit trail has zeros.
- B1a: Stage 3 Beta P80 is suppressed when ≥1 top-3 driver is unmapped.
- B2a: scenario dedup collapses identical-signature scenarios; the helper
  is generic across the two B2a surfaces (page1_range_table and
  div["scenarios"]).
- B3: counterfactual narrative emitted when ≥1 row is_duplicate_of_baseline=True.

Audit-trail fixtures use the AutoMapAuditRow schema confirmed in
the SR9 v3.6.1-02 credibility brief,
section 5.0.3: zero expansion is one row per affected risk with
activity_id == "" (no activity_count column).
"""
from __future__ import annotations

import pandas as pd

from src.final.composer import (
    _build_auto_mapper_zero_expansion_notice,
    _build_counterfactual_narrative,
    _build_dedup_footnote,
    _dedupe_scenarios_by_signature,
    _stage3_beta_unmapped_top_drivers,
)


# ---------------------------------------------------------------------------
# Fixture helper - mirrors src/sra/cpm/auto_mapper.py::_audit_rows_for_driver:
#  - one row per (risk_id, activity_id) for mapped risks
#  - one row with activity_id == '' for zero-expansion risks
# Columns match AutoMapAuditRow exactly.
# ---------------------------------------------------------------------------

def _make_audit_df(zero_ids: list[str], mapped_ids: list[str]) -> pd.DataFrame:
    rows = []
    for rid in zero_ids:
        rows.append({
            "risk_id": rid,
            "activity_id": "",
            "pattern_id": "P00",
            "injection_method": "additive_pert_days",
            "opt_pert": 0.0, "ml_pert": 0.0, "pess_pert": 0.0,
            "probability": 0.1,
            "derived_at_run_time": True, "workshop_validated": False,
        })
    for rid in mapped_ids:
        for aid in ("ACT_1", "ACT_2"):
            rows.append({
                "risk_id": rid,
                "activity_id": aid,
                "pattern_id": "P05",
                "injection_method": "additive_pert_days",
                "opt_pert": 0.0, "ml_pert": 5.0, "pess_pert": 10.0,
                "probability": 0.1,
                "derived_at_run_time": True, "workshop_validated": False,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# A5 - zero-expansion notice
# ---------------------------------------------------------------------------

def test_a5_zero_expansion_notice_present_when_audit_has_zeros(tmp_path):
    audit = _make_audit_df(zero_ids=["R013", "R026.1"], mapped_ids=["R017.1"])
    audit_path = tmp_path / "audit.parquet"
    audit.to_parquet(audit_path)
    stage3 = {"auto_mapper_audit_path": str(audit_path)}

    notice = _build_auto_mapper_zero_expansion_notice(stage3)
    assert notice is not None
    assert notice["n_zero"] == 2
    assert notice["n_total"] == 3
    assert notice["zero_risk_ids"] == ["R013", "R026.1"]
    assert "R013" in notice["paragraph"]
    assert "R026.1" in notice["paragraph"]


def test_a5_zero_expansion_notice_absent_when_no_zeros(tmp_path):
    audit = _make_audit_df(zero_ids=[], mapped_ids=["R017.1", "R067"])
    audit_path = tmp_path / "audit.parquet"
    audit.to_parquet(audit_path)
    stage3 = {"auto_mapper_audit_path": str(audit_path)}

    assert _build_auto_mapper_zero_expansion_notice(stage3) is None


def test_a5_handles_missing_stage3():
    assert _build_auto_mapper_zero_expansion_notice(None) is None
    assert _build_auto_mapper_zero_expansion_notice({}) is None


# ---------------------------------------------------------------------------
# B1a - Stage 3 Beta P80 suppression
# ---------------------------------------------------------------------------

def test_b1a_unmapped_top_drivers_intersection(tmp_path):
    audit = _make_audit_df(
        zero_ids=["R026.1", "R090", "R013"],
        mapped_ids=["R017.1", "R067"],
    )
    audit_path = tmp_path / "audit.parquet"
    audit.to_parquet(audit_path)
    stage3 = {"auto_mapper_audit_path": str(audit_path)}

    # Top-3 from production headline includes R026.1 and R090 (zero-mapped)
    # plus R017.1 (mapped). Intersection should return {R026.1, R090}.
    top3 = ["R017.1", "R026.1", "R090"]
    unmapped = _stage3_beta_unmapped_top_drivers(stage3, top3)
    assert unmapped == {"R026.1", "R090"}


def test_b1a_suppression_returns_empty_when_all_top3_mapped(tmp_path):
    audit = _make_audit_df(
        zero_ids=["R013"],  # not in top-3
        mapped_ids=["R017.1", "R026.1", "R090"],
    )
    audit_path = tmp_path / "audit.parquet"
    audit.to_parquet(audit_path)
    stage3 = {"auto_mapper_audit_path": str(audit_path)}

    top3 = ["R017.1", "R026.1", "R090"]
    assert _stage3_beta_unmapped_top_drivers(stage3, top3) == set()


# ---------------------------------------------------------------------------
# B2a - scenario dedup (generic helper used by both surfaces)
# ---------------------------------------------------------------------------

def test_b2a_dedupe_collapses_identical_signature():
    """Surface-2 signature: integrated and naive-sum P80 dollars rounded
    to whole dollars. DP_Review and All_Series collapse under 8S strawman."""
    scenarios = [
        ("DP_Review", {
            "integrated_p80_dollars": 29_270_000.0,
            "naive_sum_p80_dollars": 29_710_000.0,
        }),
        ("All_Series", {
            "integrated_p80_dollars": 29_270_000.0,
            "naive_sum_p80_dollars": 29_710_000.0,
        }),
        ("Dummy_Realistic", {
            "integrated_p80_dollars": 26_840_000.0,
            "naive_sum_p80_dollars": 25_580_000.0,
        }),
    ]
    sig = lambda name, d: (
        round(float(d["integrated_p80_dollars"]), 0),
        round(float(d["naive_sum_p80_dollars"]), 0),
    )
    keep, deduped = _dedupe_scenarios_by_signature(scenarios, sig)
    kept_names = [name for name, _ in keep]
    assert kept_names == ["DP_Review", "Dummy_Realistic"]
    assert deduped == [("DP_Review", "All_Series")]
    # Footnote contains the scenario names and the mode-mix label.
    footnote = _build_dedup_footnote(deduped, mode_mix_summary="8S")
    assert "All_Series" in footnote
    assert "DP_Review" in footnote
    assert "8S" in footnote


def test_b2a_dedupe_keeps_distinct_scenarios():
    """All three scenarios distinct - no dedup. Empty footnote returned."""
    scenarios = [
        ("DP_Review", {
            "integrated_p80_dollars": 27_500_000.0,
            "naive_sum_p80_dollars": 28_100_000.0,
        }),
        ("All_Series", {
            "integrated_p80_dollars": 31_050_000.0,
            "naive_sum_p80_dollars": 31_600_000.0,
        }),
        ("Dummy_Realistic", {
            "integrated_p80_dollars": 26_840_000.0,
            "naive_sum_p80_dollars": 25_580_000.0,
        }),
    ]
    sig = lambda name, d: (
        round(float(d["integrated_p80_dollars"]), 0),
        round(float(d["naive_sum_p80_dollars"]), 0),
    )
    keep, deduped = _dedupe_scenarios_by_signature(scenarios, sig)
    assert len(keep) == 3
    assert deduped == []
    assert _build_dedup_footnote(deduped, mode_mix_summary="5S/2H/1P") == ""


# ---------------------------------------------------------------------------
# B3 - counterfactual narrative
# ---------------------------------------------------------------------------

def test_b3_narrative_emitted_when_duplicates_exist():
    df = pd.DataFrame([
        {"is_duplicate_of_baseline": False},
        {"is_duplicate_of_baseline": True},
        {"is_duplicate_of_baseline": True},
    ])
    narrative = _build_counterfactual_narrative(df, baseline_mode_mix="8S")
    assert narrative is not None
    assert "8S" in narrative
    assert "2 of 3" in narrative


def test_b3_narrative_absent_when_no_duplicates():
    df = pd.DataFrame([{"is_duplicate_of_baseline": False}] * 3)
    assert _build_counterfactual_narrative(df, baseline_mode_mix="8S") is None
