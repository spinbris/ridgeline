"""SR-S3-Beta-16 Item 3 (sweep) — cost-side metric-label consistency.

Beyond the Item 1 cost-tornado refactor, the cost-side prose carries two
other hard-coded "P80" references whose label should follow the docx
variant's headline metric:

  * Page 6 *Action implications* treatment ROI table — the cost-typed
    rows' "Current contribution" column ("$X.XX M (P80)" or "(Mean)")
  * Page 6 prod-mode specific-recommendations sentence — "Treatment
    effort focused on R001 ($X.XX M P80 contribution)..."

This file covers both. The Item 1 ranking-and-orienting tests live in
``test_sr_s3_beta_16_cost_metric_aware.py``.
"""
from __future__ import annotations

import pandas as pd

from src.final import composer


def _roi_cost_rows(table: pd.DataFrame) -> pd.DataFrame:
    """Return only the Cost-typed rows of the treatment ROI table."""
    type_col = next(c for c in table.columns if c == "Type")
    return table.loc[table[type_col].astype(str).str.startswith("Cost")]


def test_roi_table_p80_label_in_p80_docx():
    cost_drivers = [
        {"risk_id": "R001", "value": 1.23, "metric_name": "P80"},
        {"risk_id": "R002", "value": 0.45, "metric_name": "P80"},
    ]
    table = composer._build_treatment_roi_table(
        cost_drivers=cost_drivers,
        schedule_drivers=[],
        headline_metric="P80",
    )
    cost_rows = _roi_cost_rows(table)
    assert (cost_rows["Current contribution"].astype(str).str.contains(r"\(P80\)")).all()
    assert not (
        cost_rows["Current contribution"].astype(str).str.contains("Mean", regex=False)
    ).any()


def test_roi_table_mean_label_in_mean_docx():
    cost_drivers = [
        {"risk_id": "R001", "value": 0.42, "metric_name": "Mean"},
        {"risk_id": "R002", "value": 0.51, "metric_name": "Mean"},
    ]
    table = composer._build_treatment_roi_table(
        cost_drivers=cost_drivers,
        schedule_drivers=[],
        headline_metric="Mean",
    )
    cost_rows = _roi_cost_rows(table)
    assert (cost_rows["Current contribution"].astype(str).str.contains(r"\(Mean\)")).all()
    assert not (
        cost_rows["Current contribution"].astype(str).str.contains("P80", regex=False)
    ).any()


def test_roi_table_default_label_falls_back_to_p80():
    """Legacy callers without headline_metric still produce P80 labels."""
    cost_drivers = [
        {"risk_id": "R001", "value": 1.23},
    ]
    table = composer._build_treatment_roi_table(
        cost_drivers=cost_drivers,
        schedule_drivers=[],
    )
    cost_rows = _roi_cost_rows(table)
    assert (cost_rows["Current contribution"].astype(str).str.contains(r"\(P80\)")).all()


def test_recommendations_cost_label_p80():
    recs = composer._build_specific_recommendations(
        cost_drivers=[
            {"risk_id": "R001", "value": 2.31, "metric_name": "P80"},
        ],
        schedule_drivers=[{"risk_id": "R067"}, {"risk_id": "R013"}],
    )
    joined = " ".join(recs)
    assert "P80 contribution" in joined
    assert "$2.31M P80" in joined


def test_recommendations_cost_label_mean():
    recs = composer._build_specific_recommendations(
        cost_drivers=[
            {"risk_id": "R001", "value": 1.17, "metric_name": "Mean"},
        ],
        schedule_drivers=[{"risk_id": "R067"}, {"risk_id": "R013"}],
    )
    joined = " ".join(recs)
    assert "Mean contribution" in joined
    assert "$1.17M Mean" in joined
    cost_sentence = next(r for r in recs if "R001" in r)
    assert "P80" not in cost_sentence
