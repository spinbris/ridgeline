"""SR-S3-Beta-16 Item 1 — cost driver ranking is metric-aware.

The cost-driver section ranks by the docx-variant's headline metric
(Mean in the Mean docx, P80 in the P80 docx). The orienting paragraph,
table column header, chart title, and chart x-axis label all track the
metric. The Item 3 (sweep) coverage for the treatment ROI table and the
prod-mode specific-recommendations sentence lives in
``test_sr_s3_beta_16_sweep.py``. The end-to-end docx assertions live
alongside the slow E2E test (Item 4).
"""
from __future__ import annotations

import numpy as np
import pytest

from src.final import commentary_text, composer


# ---------------------------------------------------------------------------
# Synthetic integrated payload — two cost-only risks, no schedule arm.
# R001 has the higher P80 contribution; R002 has the higher Mean
# contribution. The orderings therefore differ between metrics, exercising
# the metric-aware ranking refactor.
# ---------------------------------------------------------------------------


def _make_per_risk_cost_array(rng, n=4000):
    # R001: bimodal — 60% small (near-zero contribution from non-firing
    # iterations), 40% large spike. Heavy upper tail, modest mean.
    r001 = np.where(
        rng.random(n) < 0.40,
        rng.uniform(1.5e6, 2.0e6, size=n),  # spike band
        rng.uniform(0.0, 1.0e5, size=n),    # baseline band
    )

    # R002: tighter unimodal — higher Mean than R001 (no zero band) but
    # lower P80 (no spike band).
    r002 = rng.uniform(8.0e5, 9.0e5, size=n)
    return np.column_stack([r001, r002])


def _integrated_payload(seed=11):
    rng = np.random.default_rng(seed)
    per_risk = _make_per_risk_cost_array(rng)
    return {
        "per_risk_cost_array": per_risk,
        "risk_ids_all": ["R001", "R002"],
    }


# ---------------------------------------------------------------------------
# Item 1: _build_cost_tornado_data ranks by the headline metric.
# ---------------------------------------------------------------------------


def test_cost_tornado_default_ranks_by_p80():
    """Default (no headline_metric) preserves pre-Beta-16 behaviour."""
    payload = _integrated_payload()
    out = composer._build_cost_tornado_data(
        integrated_results=payload,
        risk_titles={"R001": "Risk one", "R002": "Risk two"},
    )
    assert out, "Expected drivers returned"
    # P80 should pick the spiked distribution (R001) first.
    arr = np.asarray(payload["per_risk_cost_array"])
    p80 = np.percentile(arr, 80, axis=0)
    assert np.argmax(p80) == payload["risk_ids_all"].index(out[0]["risk_id"])
    for d in out:
        assert d.get("metric_name") == "P80"


def test_cost_tornado_mean_ranks_by_mean():
    """headline_metric='Mean' ranks by per-risk mean contribution."""
    payload = _integrated_payload()
    out = composer._build_cost_tornado_data(
        integrated_results=payload,
        risk_titles={"R001": "Risk one", "R002": "Risk two"},
        headline_metric="Mean",
    )
    assert out, "Expected drivers returned"
    arr = np.asarray(payload["per_risk_cost_array"])
    means = arr.mean(axis=0)
    assert np.argmax(means) == payload["risk_ids_all"].index(out[0]["risk_id"])
    for d in out:
        assert d.get("metric_name") == "Mean"


def test_cost_tornado_metric_swap_can_reorder_top():
    """Synthetic payload designed so P80 and Mean give different #1 driver."""
    payload = _integrated_payload()
    p80 = composer._build_cost_tornado_data(
        integrated_results=payload, risk_titles=None,
    )
    mean = composer._build_cost_tornado_data(
        integrated_results=payload, risk_titles=None, headline_metric="Mean",
    )
    assert p80 and mean
    # The two metrics rank the synthetic risks differently — verifies the
    # refactor is doing more than just relabelling.
    assert p80[0]["risk_id"] != mean[0]["risk_id"]


def test_cost_tornado_pct_of_total_tracks_metric():
    """pct_of_total is computed against the metric's own total, not P80's."""
    payload = _integrated_payload()
    mean_out = composer._build_cost_tornado_data(
        integrated_results=payload, risk_titles=None, headline_metric="Mean",
    )
    total_pct = sum(d["pct_of_total"] for d in mean_out)
    assert total_pct == pytest.approx(1.0, abs=1e-9)
    # Each driver's value_dollars / sum(value_dollars) recovers pct_of_total.
    dollars = [d["value_dollars"] for d in mean_out]
    total_dollars = sum(dollars)
    for d in mean_out:
        assert d["pct_of_total"] == pytest.approx(
            d["value_dollars"] / total_dollars, abs=1e-9,
        )


def test_cost_tornado_empty_payload_returns_empty_list():
    out = composer._build_cost_tornado_data(
        integrated_results={"per_risk_cost_array": np.zeros((0, 0)), "risk_ids_all": []},
        risk_titles=None,
        headline_metric="Mean",
    )
    assert out == []


# ---------------------------------------------------------------------------
# Item 1 prose: commentary_text.format_cost_tornado_orienting substitutes
# the metric name into the orienting paragraph.
# ---------------------------------------------------------------------------


def test_cost_tornado_orienting_p80_text():
    text = commentary_text.format_cost_tornado_orienting("P80")
    assert "P80 contribution" in text
    assert "P80 percentile" in text
    assert "share of total P80 cost contingency" in text
    assert "{" not in text and "}" not in text


def test_cost_tornado_orienting_mean_text():
    text = commentary_text.format_cost_tornado_orienting("Mean")
    assert "Mean contribution" in text
    # "mean" used as the noun phrase reads naturally without the
    # "percentile" qualifier.
    assert "the mean of that risk's per-iteration cost" in text
    assert "share of total Mean cost contingency" in text
    assert "{" not in text and "}" not in text


def test_legacy_cost_tornado_orienting_constant_unchanged():
    """Existing constant is preserved so notebook display path stays working."""
    assert "P80 contribution" in commentary_text.COST_TORNADO_ORIENTING
    assert isinstance(commentary_text.COST_TORNADO_ORIENTING, str)
    assert len(commentary_text.COST_TORNADO_ORIENTING) > 50
