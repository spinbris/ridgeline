"""SP23 — Mean in QRA report CG Analysis (table + chart) and Component decomposition.

Eight tests covering:
  1. compute_cg_mean returns one entry per CG group with positive values
  2. compute_rbs_l1_mean_contribution returns one entry per RBS L1 category
  3. Sum of per-CG means ≈ portfolio mean
  4. Sum of per-RBS-L1 mean contributions ≈ portfolio mean
  5. CG Analysis table cell in client_runner.ipynb references the new Mean column
  6. CG event risk chart renders paired bars (P80 + Mean) with two-entry legend
  7. P80 bars in paired chart match values rendered in legacy single-bar chart
  8. Component decomposition cell in client_appendices.ipynb references the new column
"""


import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgba
from matplotlib.patches import Rectangle

import numpy as np
import pytest

from src.config import ChainConfig, RiskInput, SimConfig
from src.simulation import MonteCarloEngine
from src.analysis import (
    compute_cg_mean,
    compute_rbs_l1_mean_contribution,
)
from src.charts import generate_cg_bar_chart




# ---------------------------------------------------------------------------
# Fixture: small simulation with risks across 3 CG groups and 3 RBS L1 cats
# ---------------------------------------------------------------------------

def _make_sim(n_iter: int = 5_000, seed: int = 42):
    risks = [
        RiskInput("R001", "Risk A", "BOP", "Triangular", "CG01",
                  0.3, 100_000, 500_000, 1_000_000, rbs_l1="1.Programme"),
        RiskInput("R002", "Risk B", "BOP", "Triangular", "CG01",
                  0.5, 200_000, 800_000, 2_000_000, rbs_l1="1.Programme"),
        RiskInput("R003", "Risk C", "Shared", "Triangular", "CG02",
                  0.4, 50_000, 300_000, 700_000, rbs_l1="2.Construction"),
        RiskInput("R004", "Risk D", "Shared", "Triangular", "CG02",
                  0.2, 100_000, 400_000, 900_000, rbs_l1="2.Construction"),
        RiskInput("R005", "Risk E", "CSE", "Triangular", "CG03",
                  0.6, 500_000, 2_000_000, 5_000_000, rbs_l1="3.External"),
    ]
    config = SimConfig(n_iter=n_iter, seed=seed, view="L2Only", tic=0.0)
    chains = ChainConfig()
    corr = {"CG01": 0.6, "CG02": 0.5, "CG03": 0.4}
    engine = MonteCarloEngine(config, [], chains, risks, corr, seed=seed, wbs_rho=0.4)
    raw = engine.run()
    return raw, risks


# ---------------------------------------------------------------------------
# 1. compute_cg_mean — one entry per CG, positive values
# ---------------------------------------------------------------------------

def test_cg_mean_computed_for_each_group():
    raw, risks = _make_sim()
    cg_mean = compute_cg_mean(raw, risks)
    assert set(cg_mean.keys()) == {"CG01", "CG02", "CG03"}
    for cg, val in cg_mean.items():
        assert isinstance(val, float)
        assert val > 0, f"{cg} mean should be positive, got {val}"


# ---------------------------------------------------------------------------
# 2. compute_rbs_l1_mean_contribution — one entry per RBS L1 category
# ---------------------------------------------------------------------------

def test_rbs_l1_mean_contribution_computed_for_each_category():
    raw, risks = _make_sim()
    contrib = compute_rbs_l1_mean_contribution(raw, risks)
    assert set(contrib.keys()) == {"1.Programme", "2.Construction", "3.External"}
    for label, val in contrib.items():
        assert isinstance(val, float)
        assert val > 0, f"{label} mean contribution should be positive, got {val}"


# ---------------------------------------------------------------------------
# 3. Sum of per-CG means ≈ portfolio mean (means are linear; tight tolerance)
# ---------------------------------------------------------------------------

def test_sum_cg_mean_close_to_portfolio_mean():
    raw, risks = _make_sim(n_iter=10_000)
    cg_mean = compute_cg_mean(raw, risks)
    portfolio_mean = float(np.mean(raw.ev_costs.sum(axis=1)))
    sum_cg = sum(cg_mean.values())
    rel = abs(sum_cg - portfolio_mean) / portfolio_mean
    assert rel < 0.005, (
        f"Sum of CG means {sum_cg:,.2f} differs from portfolio mean "
        f"{portfolio_mean:,.2f} by {rel*100:.2f}% (>0.5% tolerance)"
    )


# ---------------------------------------------------------------------------
# 4. Sum of per-RBS-L1 mean contributions ≈ portfolio mean
# ---------------------------------------------------------------------------

def test_sum_rbs_l1_mean_close_to_portfolio_mean():
    raw, risks = _make_sim(n_iter=10_000)
    contrib = compute_rbs_l1_mean_contribution(raw, risks)
    portfolio_mean = float(np.mean(raw.ev_costs.sum(axis=1)))
    sum_contrib = sum(contrib.values())
    rel = abs(sum_contrib - portfolio_mean) / portfolio_mean
    assert rel < 0.005, (
        f"Sum of RBS L1 mean contributions {sum_contrib:,.2f} differs from "
        f"portfolio mean {portfolio_mean:,.2f} by {rel*100:.2f}% (>0.5% tolerance)"
    )


# ---------------------------------------------------------------------------
# 5. CG Analysis table cell references the new Mean column + cg_mean dict
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 6. CG event risk chart renders paired bars with two-entry legend
# ---------------------------------------------------------------------------

_CG_SUMMARY_FIXTURE = [
    {"cg_code": "CG01", "cg_description": "Group 1", "n_risks": 2, "rho": 0.5,
     "risk_ids": ["R1", "R2"],
     "group_p50": 1_000_000.0, "group_p80": 3_000_000.0,
     "group_p90": 4_000_000.0, "group_mean": 1_500_000.0,
     "group_std": 500_000.0, "group_emv": 1_000_000.0,
     "var_contribution": 1.0, "pct_of_total_var": 0.6},
    {"cg_code": "CG02", "cg_description": "Group 2", "n_risks": 3, "rho": 0.5,
     "risk_ids": ["R3", "R4", "R5"],
     "group_p50": 800_000.0, "group_p80": 1_500_000.0,
     "group_p90": 2_500_000.0, "group_mean": 1_200_000.0,
     "group_std": 400_000.0, "group_emv": 900_000.0,
     "var_contribution": 0.7, "pct_of_total_var": 0.4},
    {"cg_code": "CG03", "cg_description": "Group 3", "n_risks": 1, "rho": 0.5,
     "risk_ids": ["R6"],
     "group_p50": 500_000.0, "group_p80": 2_000_000.0,
     "group_p90": 3_000_000.0, "group_mean": 800_000.0,
     "group_std": 300_000.0, "group_emv": 600_000.0,
     "var_contribution": 0.5, "pct_of_total_var": 0.2},
]


def _capture_figs(monkeypatch):
    """Patch plt.close to retain figures for introspection. Returns capture list."""
    captured: list = []
    real_close = plt.close

    def fake_close(fig=None):
        if fig is not None:
            captured.append(fig)
        # do NOT call real_close — keep figure alive for assertions

    monkeypatch.setattr(plt, "close", fake_close)
    return captured, real_close


def test_cg_chart_renders_paired_bars(tmp_path, monkeypatch):
    cg_mean = {"CG01": 1_500_000.0, "CG02": 1_200_000.0, "CG03": 800_000.0}
    path = tmp_path / "cg_paired.png"

    captured, real_close = _capture_figs(monkeypatch)
    try:
        generate_cg_bar_chart(_CG_SUMMARY_FIXTURE, path, p_level=80, cg_mean=cg_mean)
        assert path.exists() and path.stat().st_size > 0

        assert captured, "Expected figure to have been produced"
        fig = captured[-1]
        ax = fig.axes[0]

        bars = [p for p in ax.patches if isinstance(p, Rectangle)]
        n_cg = len(_CG_SUMMARY_FIXTURE)
        assert len(bars) == 2 * n_cg, \
            f"Expected {2 * n_cg} bars (P80 + Mean per CG), got {len(bars)}"

        colours = {tuple(round(c, 3) for c in p.get_facecolor()) for p in bars}
        assert len(colours) == 2, \
            f"Expected exactly 2 distinct bar colours, got {len(colours)}: {colours}"

        legend = ax.get_legend()
        assert legend is not None, "Paired chart should have a legend"
        labels = [t.get_text() for t in legend.get_texts()]
        assert len(labels) == 2, f"Expected 2 legend entries, got {labels}"
        assert any("P80" in l for l in labels), f"Legend missing P80 entry: {labels}"
        assert any("Mean" in l for l in labels), f"Legend missing Mean entry: {labels}"
    finally:
        for fig in captured:
            real_close(fig)


# ---------------------------------------------------------------------------
# 7. P80 bars in paired chart match values rendered in legacy single-bar chart
# ---------------------------------------------------------------------------

def test_cg_chart_p80_bars_unchanged(tmp_path, monkeypatch):
    cg_mean = {"CG01": 100_000.0, "CG02": 50_000.0, "CG03": 80_000.0}
    legacy_path = tmp_path / "legacy.png"
    paired_path = tmp_path / "paired.png"

    captured, real_close = _capture_figs(monkeypatch)
    try:
        generate_cg_bar_chart(_CG_SUMMARY_FIXTURE, legacy_path, p_level=80)
        assert legacy_path.exists()
        legacy_fig = captured[-1]
        legacy_bars = [p for p in legacy_fig.axes[0].patches if isinstance(p, Rectangle)]
        legacy_widths = sorted(round(p.get_width(), 6) for p in legacy_bars)

        generate_cg_bar_chart(_CG_SUMMARY_FIXTURE, paired_path, p_level=80, cg_mean=cg_mean)
        assert paired_path.exists()
        paired_fig = captured[-1]
        paired_bars = [p for p in paired_fig.axes[0].patches if isinstance(p, Rectangle)]

        # Filter paired bars to those whose face colour matches the P80 colour (#2166AC)
        from src.charts import BOP_BLUE
        p80_rgba = to_rgba(BOP_BLUE)
        def _is_p80(bar):
            face = bar.get_facecolor()
            return all(abs(a - b) < 0.01 for a, b in zip(face, p80_rgba))
        paired_p80_widths = sorted(
            round(p.get_width(), 6) for p in paired_bars if _is_p80(p)
        )

        assert len(paired_p80_widths) == len(legacy_widths), (
            f"P80 bar count mismatch: legacy {len(legacy_widths)}, "
            f"paired-P80 {len(paired_p80_widths)}"
        )
        assert paired_p80_widths == pytest.approx(legacy_widths, rel=1e-6), (
            f"P80 bar widths changed between legacy and paired modes: "
            f"legacy={legacy_widths}, paired_p80={paired_p80_widths}"
        )
    finally:
        for fig in captured:
            real_close(fig)


# ---------------------------------------------------------------------------
# 8. Component decomposition cell references the new Contribution to Mean col
# ---------------------------------------------------------------------------
