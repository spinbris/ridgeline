"""SR-S3-Beta-19 §5 — Decision 5 regression tests.

Decision 5 closes the Beta-16 ranking-metric work for the Mean docx
variant. Mean variant must:

1. Rank cost drivers by Mean contribution (not P80).
2. Label the action-implications "Current contribution" column with
   "(Mean)" suffix instead of "(P80)".

Beta-16 Item 1 implemented the data-layer ranking; Beta-16 Item 3
(sweep) propagated the label through the action-implications table.
Decision 5 in Beta-19 codifies both as explicit regression tests so
the Mean docx variant cannot silently revert to P80-ranking.

These tests are unit tests against the composer / build helpers; the
slow E2E coverage continues to live in test_run_refproject_beta19_smoke.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.final.composer import (
    _build_cost_tornado_data,
    _build_treatment_roi_table,
)


def _synthetic_integrated_results() -> dict:
    """Per-risk cost array crafted so the Mean ranking differs from P80.

    Construction (algebra):
      - R001 fires 30% of iterations at $10M, else $0.
        P80 = $10M (fires 30% > 20% percentile tail).
        Mean = 0.30 × $10M = $3M.
      - R002 is constant at $5M.
        P80 = $5M. Mean = $5M.

    P80 ranking → R001 (10M) > R002 (5M).
    Mean ranking → R002 (5M) > R001 (3M).
    Top-driver flips between the two metrics — the canonical Decision 5
    fingerprint.
    """
    rng = np.random.default_rng(42)
    n = 10_000
    r001_per_iter = np.zeros(n)
    fires = rng.random(n) < 0.30
    r001_per_iter[fires] = 10_000_000.0
    r002_per_iter = np.full(n, 5_000_000.0)
    r003_per_iter = rng.uniform(1_000_000, 4_000_000, size=n)
    per_risk = np.column_stack([r001_per_iter, r002_per_iter, r003_per_iter])
    return {
        "per_risk_cost_array": per_risk,
        "risk_ids_all": ["R001", "R002", "R003"],
    }


def test_decision_5_cost_tornado_ranks_by_mean_in_mean_variant() -> None:
    """Mean-variant cost tornado must rank by Mean contribution.

    The synthetic R001 has the highest P80 (heavy tail) but R002 has
    the highest Mean (constant load). In the Mean variant the top
    driver must be R002.
    """
    results = _synthetic_integrated_results()
    drivers_p80 = _build_cost_tornado_data(
        results, risk_titles=None, n=3, headline_metric="P80",
    )
    drivers_mean = _build_cost_tornado_data(
        results, risk_titles=None, n=3, headline_metric="Mean",
    )

    assert drivers_p80, "P80 variant produced no drivers"
    assert drivers_mean, "Mean variant produced no drivers"

    # Verify metric label propagation.
    assert all(d["metric_name"] == "P80" for d in drivers_p80)
    assert all(d["metric_name"] == "Mean" for d in drivers_mean)

    # Decision 5 invariant: top driver differs by metric.
    assert drivers_p80[0]["risk_id"] == "R001", (
        f"P80 variant top driver should be R001 (heavy tail); "
        f"got {drivers_p80[0]['risk_id']}"
    )
    assert drivers_mean[0]["risk_id"] == "R002", (
        f"Mean variant top driver should be R002 (constant load); "
        f"got {drivers_mean[0]['risk_id']}"
    )


def test_decision_5_action_implications_label_follows_variant() -> None:
    """Mean variant action-implications "Current contribution" cells
    must carry "(Mean)" suffix; P80 variant carries "(P80)" suffix.
    """
    cost_drivers_p80 = [
        {"risk_id": "R001", "value": 1.64, "metric_name": "P80"},
    ]
    cost_drivers_mean = [
        {"risk_id": "R001", "value": 0.93, "metric_name": "Mean"},
    ]
    schedule_drivers: list[dict] = []

    df_p80 = _build_treatment_roi_table(
        cost_drivers_p80, schedule_drivers, headline_metric="P80",
    )
    df_mean = _build_treatment_roi_table(
        cost_drivers_mean, schedule_drivers, headline_metric="Mean",
    )

    assert "(P80)" in df_p80.loc[0, "Current contribution"]
    assert "(Mean)" not in df_p80.loc[0, "Current contribution"]
    assert "(Mean)" in df_mean.loc[0, "Current contribution"]
    assert "(P80)" not in df_mean.loc[0, "Current contribution"]


def test_decision_5_treatment_roi_with_workshop_input_preserves_variant_label() -> None:
    """When a workshop-populated Treatments row joins on a cost driver,
    the populated row's "Current contribution" cell still carries the
    variant metric label (Beta-19 §4 wires the populated reduction; the
    label is Beta-19 §5 / Beta-16 Item 3).
    """
    cost_drivers_mean = [
        {"risk_id": "R067", "value": 1.0, "metric_name": "Mean"},
    ]
    schedule_drivers: list[dict] = []
    treatments = pd.DataFrame([
        {
            "risk_id": "R067",
            "treatment_description": "Pre-build inverters",
            "effectiveness_pct": 40.0,
            "effectiveness_confidence": "Medium",
        }
    ])
    df = _build_treatment_roi_table(
        cost_drivers_mean,
        schedule_drivers,
        headline_metric="Mean",
        treatments=treatments,
    )
    assert "(Mean)" in df.loc[0, "Current contribution"]
    assert "Pre-build inverters" in df.loc[0, "Illustrative treatment"]
    assert "$0.40M (40% effective)" in df.loc[0, "Estimated reduction"]
