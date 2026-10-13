"""Reporting helpers for client notebooks.

Stage A: EMV credibility bridge - per-risk expected monetary values and
waterfall bridge segments explaining the gap between simple EMV and MC Mean.

Stage B: Risk deep-dive cards - top-N risk cards ranked by tornado
sensitivity with input distribution and fired-only histogram charts.

This module imports from existing modules but does NOT modify them.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

# SR17 Workstream D: chart theme applied at module import so the lazy
# matplotlib imports inside per-function bodies pick up the brand
# palette via the shared rcParams.
from src.final.chart_theme import apply_theme as _apply_chart_theme
_apply_chart_theme()

if TYPE_CHECKING:
    from src.config import RiskInput, TornadoEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Function 1: Per-risk EMV table
# ---------------------------------------------------------------------------

def compute_emv_table(
    risks: list[RiskInput],
    ev_costs: np.ndarray,
    risk_ids: list[str],
) -> pd.DataFrame:
    """Compute per-risk EMV under three methods for the credibility bridge.

    Parameters
    ----------
    risks : list[RiskInput]
        Active risks as returned by reader / register_loader.
    ev_costs : np.ndarray
        2-D array (n_iter, n_risks) from SimRawResults.ev_costs.
        Column *i* corresponds to ``risk_ids[i]``.
    risk_ids : list[str]
        Risk IDs matching the column order of *ev_costs*.

    Returns
    -------
    pd.DataFrame
        Columns: RiskID, Title, Owner, CG_Group, Prob_Pct, EMV_Simple,
        EMV_PERT, MC_Mean, Delta_PERT_to_MC, Delta_Pct.
        Sorted by EMV_Simple descending.
    """
    # Build a lookup from risk_id -> RiskInput for fast access
    risk_lookup: dict[str, RiskInput] = {r.risk_id: r for r in risks}

    # Map risk_ids to column indices
    id_to_col: dict[str, int] = {rid: i for i, rid in enumerate(risk_ids)}

    rows: list[dict] = []
    for r in risks:
        rid = r.risk_id

        # MC Mean from simulation arrays
        if rid in id_to_col:
            mc_mean = float(np.mean(ev_costs[:, id_to_col[rid]]))
        else:
            logger.warning("RiskID %s not found in risk_ids - setting MC_Mean=0", rid)
            mc_mean = 0.0

        prob = r.probability
        opt = r.opt_cost
        ml = r.ml_cost
        pess = r.pess_cost

        emv_simple = prob * ml
        pert_mean = (opt + 4.0 * ml + pess) / 6.0
        emv_pert = prob * pert_mean

        delta = mc_mean - emv_pert
        delta_pct = round(delta / emv_pert * 100.0, 1) if emv_pert != 0 else 0.0

        rows.append({
            "RiskID": rid,
            "Title": r.description,
            "Owner": r.owner,
            "CG_Group": r.correlation_group,
            "Prob_Pct": prob,
            "EMV_Simple": emv_simple,
            "EMV_PERT": emv_pert,
            "MC_Mean": mc_mean,
            "Delta_PERT_to_MC": delta,
            "Delta_Pct": delta_pct,
        })

    # Warn about risk_ids entries not found in risks list
    risk_set = {r.risk_id for r in risks}
    for rid in risk_ids:
        if rid not in risk_set:
            logger.warning("risk_ids entry %s not found in risks list - skipped", rid)

    df = pd.DataFrame(rows)
    df.sort_values("EMV_Simple", ascending=False, inplace=True, ignore_index=True)
    return df


# ---------------------------------------------------------------------------
# Function 2: Waterfall bridge segments
# ---------------------------------------------------------------------------

def compute_emv_bridge(
    emv_df: pd.DataFrame,
    mc_mean: float,
    mean_nil_corr: float | None = None,
) -> dict:
    """Aggregate per-risk EMV table into waterfall bridge segments.

    The bridge explains the gap between simple EMV (P * ML) and the MC Mean.
    EMV is a mean (average) measure, so the correct MC comparator is the
    MC Mean, not the P50 (median). For right-skewed distributions the mean
    exceeds the median.

    Parameters
    ----------
    emv_df : pd.DataFrame
        Output of :func:`compute_emv_table`.
    mc_mean : float
        MC Mean for the base-case run.
    mean_nil_corr : float or None
        If supplied (Stage C), the combined uplift is split into correlation
        premium and chaining/other.  None in Stage A.

    Returns
    -------
    dict
        Keys: emv_simple_total, emv_pert_total, mc_mean_total,
        segment_distribution_shape, segment_modelling_uplift,
        segment_correlation_premium, segment_chaining_other,
        mc_mean, combined_uplift_label.
    """
    emv_simple_total = float(emv_df["EMV_Simple"].sum())
    emv_pert_total = float(emv_df["EMV_PERT"].sum())
    mc_mean_total = float(emv_df["MC_Mean"].sum())

    segment_distribution_shape = emv_pert_total - emv_simple_total
    segment_modelling_uplift = mc_mean - emv_pert_total

    if mean_nil_corr is not None:
        segment_correlation_premium = mean_nil_corr - emv_pert_total
        segment_chaining_other = mc_mean - mean_nil_corr
        combined_uplift_label = None
    else:
        segment_correlation_premium = None
        segment_chaining_other = None
        combined_uplift_label = "Correlation and chaining"

    # Reconciliation assertion
    expected_mean = emv_simple_total + segment_distribution_shape + segment_modelling_uplift
    assert abs(expected_mean - mc_mean) < 1.0, (
        f"Bridge reconciliation failed: computed {expected_mean:.0f} vs mc_mean {mc_mean:.0f}"
    )

    return {
        "emv_simple_total": emv_simple_total,
        "emv_pert_total": emv_pert_total,
        "mc_mean_total": mc_mean_total,
        "segment_distribution_shape": segment_distribution_shape,
        "segment_modelling_uplift": segment_modelling_uplift,
        "segment_correlation_premium": segment_correlation_premium,
        "segment_chaining_other": segment_chaining_other,
        "mc_mean": mc_mean,
        "combined_uplift_label": combined_uplift_label,
    }


# ---------------------------------------------------------------------------
# Stage B: Dollar formatting helper
# ---------------------------------------------------------------------------

def _fmt_dollars(val: float) -> str:
    """Format dollar value as $X.XM or $XK depending on magnitude."""
    if abs(val) >= 1_000_000:
        return f"${val / 1_000_000:,.1f}M"
    elif abs(val) >= 1_000:
        return f"${val / 1_000:,.0f}K"
    else:
        return f"${val:,.0f}"


# ---------------------------------------------------------------------------
# Stage B: Risk deep-dive cards
# ---------------------------------------------------------------------------

def _make_input_distribution_chart(risk: RiskInput):
    """Create input distribution PDF chart for a single risk.

    Returns a matplotlib Figure object.
    """
    import matplotlib.pyplot as plt

    opt, ml, pess = risk.opt_cost, risk.ml_cost, risk.pess_cost
    dist = risk.distribution.strip()
    prob = risk.probability

    fig, ax = plt.subplots(figsize=(4, 2.5))

    if dist.upper() == "BINARY":
        # Two-bar chart: $0 (1-p) and ML cost (p)
        bar_width = max(abs(ml) * 0.15, 1000)
        ax.bar([0, ml], [1 - prob, prob], width=bar_width, color="#2E8B8B")
        ax.text(0, 1 - prob + 0.02, f"{(1 - prob) * 100:.0f}%", ha="center", fontsize=8)
        ax.text(ml, prob + 0.02, f"{prob * 100:.0f}%", ha="center", fontsize=8)
        ax.set_ylabel("Probability", fontsize=8)
        ax.set_title("Binary", fontsize=9, fontweight="bold")
    else:
        # Continuous distributions
        x = None
        y = None
        title = dist

        if dist.upper() == "PERT" and (pess - opt) > 0:
            from scipy.stats import beta as beta_dist
            alpha_param = 1 + 4 * (ml - opt) / (pess - opt)
            beta_param = 1 + 4 * (pess - ml) / (pess - opt)
            rv = beta_dist(a=alpha_param, b=beta_param, loc=opt, scale=pess - opt)
            x = np.linspace(opt, pess, 200)
            y = rv.pdf(x)
            title = "PERT"

        elif dist.upper() == "TRIANGULAR" and (pess - opt) > 0:
            from scipy.stats import triang
            if ml <= opt:
                c = 0.001  # degenerate: mode at left edge
            else:
                c = (ml - opt) / (pess - opt)
            rv = triang(c=c, loc=opt, scale=pess - opt)
            x_lo = opt - (pess - opt) * 0.02
            x_hi = pess + (pess - opt) * 0.02
            x = np.linspace(x_lo, x_hi, 200)
            y = rv.pdf(x)
            title = "Triangular"

        elif dist.upper() == "LOGNORMAL" and ml > 0 and pess > 0:
            from scipy.stats import lognorm
            mu = np.log(ml)
            sigma = (np.log(pess) - mu) / 1.2816
            if sigma > 0:
                rv = lognorm(s=sigma, scale=np.exp(mu))
                stat_lo = rv.ppf(0.01)
                stat_hi = rv.ppf(0.99)
                if opt > 0:
                    x_lo = min(stat_lo, opt * 0.8)
                else:
                    x_lo = stat_lo * 0.7
                x_hi = max(stat_hi, pess * 1.2)
                x = np.linspace(x_lo, x_hi, 300)
                y = rv.pdf(x)
                title = "Lognormal"
            else:
                # Degenerate case - fallback to bar
                ax.bar([ml], [1.0], width=max(abs(ml) * 0.1, 1000), color="#2E8B8B")
                ax.set_title("Lognormal (degenerate)", fontsize=9, fontweight="bold")
                x = None

        if x is not None and y is not None:
            ax.plot(x, y, color="#2E8B8B", linewidth=1.5)
            ax.fill_between(x, y, alpha=0.15, color="#2E8B8B")
            # Annotate Opt, ML, Pess
            for val, label in [(opt, "Opt"), (ml, "ML"), (pess, "Pess")]:
                ax.axvline(val, color="#888888", linewidth=0.5, linestyle=":")
                ax.text(val, ax.get_ylim()[1] * 0.95, label, ha="center",
                        fontsize=7, color="#555555")
            ax.set_ylabel("Probability density", fontsize=8)
            ax.set_title(title, fontsize=9, fontweight="bold")

    # Format x-axis with dollar labels
    import matplotlib.ticker as mticker
    def _tick_fmt(v, pos):
        return _fmt_dollars(v)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(_tick_fmt))
    ax.tick_params(axis="both", labelsize=7)
    ax.yaxis.set_ticklabels([])

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.patch.set_facecolor("white")
    fig.tight_layout()
    return fig


def _make_fired_histogram(risk_col: np.ndarray, risk: RiskInput):
    """Create fired-only histogram for a single risk.

    Returns a matplotlib Figure object, or None if the risk never fired.
    """
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    fired_mask = risk_col != 0 if risk.opt_cost < 0 else risk_col > 0
    fired_costs = risk_col[fired_mask]
    n_fired = int(fired_mask.sum())
    n_iter = len(risk_col)

    if n_fired == 0:
        return None, 0, n_iter, 0.0, 0.0, 0.0, 0.0

    fire_pct = round(n_fired / n_iter * 100, 1)
    fired_mean = float(np.mean(fired_costs))
    fired_p50 = float(np.percentile(fired_costs, 50))
    fired_p80 = float(np.percentile(fired_costs, 80))

    fig, ax = plt.subplots(figsize=(4, 2.5))
    ax.hist(fired_costs, bins=min(40, max(20, n_fired // 300)), color="#2E8B8B", edgecolor="white")

    # P50 and P80 dashed lines
    ax.axvline(fired_p50, color="#1B3A5C", linestyle="--", linewidth=1.2, label=f"P50 {_fmt_dollars(fired_p50)}")
    ax.axvline(fired_p80, color="#993C1D", linestyle="--", linewidth=1.2, label=f"P80 {_fmt_dollars(fired_p80)}")
    ax.legend(fontsize=7, loc="upper right")

    # Subtitle
    ax.text(0.5, 0.97, f"Risk fired in {n_fired:,} of {n_iter:,} iterations ({fire_pct}%)",
            transform=ax.transAxes, ha="center", va="top", fontsize=8, color="#666666")

    def _tick_fmt(v, pos):
        return _fmt_dollars(v)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(_tick_fmt))
    ax.set_ylabel("Iterations", fontsize=8)
    ax.tick_params(axis="both", labelsize=7)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.patch.set_facecolor("white")
    fig.tight_layout()

    return fig, n_fired, n_iter, fire_pct, fired_mean, fired_p50, fired_p80


def compute_risk_cards(
    risks: list[RiskInput],
    ev_costs: np.ndarray,
    risk_ids: list[str],
    tornado_entries: list[TornadoEntry],
    top_n: int = 5,
) -> list[dict]:
    """Build top-N risk deep-dive cards ranked by tornado sensitivity.

    Parameters
    ----------
    risks : list[RiskInput]
        Active risks as returned by reader / register_loader.
    ev_costs : np.ndarray
        2-D array (n_iter, n_risks) from SimRawResults.ev_costs.
    risk_ids : list[str]
        Risk IDs matching the column order of *ev_costs*.
    tornado_entries : list[TornadoEntry]
        Output of compute_tornado(), used for ranking and swing values.
    top_n : int
        Number of cards to return (default 5).

    Returns
    -------
    list[dict]
        Card dicts ordered by tornado rank (rank 1 first), each containing
        metadata, MC inputs, computed stats, and matplotlib Figure objects.
    """
    # Build lookups
    risk_lookup = {r.risk_id: r for r in risks}
    id_to_col = {rid: i for i, rid in enumerate(risk_ids)}

    # Filter to Layer 2 entries only, rank by std_contribution descending
    l2_entries = [e for e in tornado_entries if e.layer != "Layer 1"]
    l2_entries.sort(key=lambda e: e.std_contribution, reverse=True)
    top_entries = l2_entries[:top_n]

    cards = []
    for rank, entry in enumerate(top_entries, start=1):
        risk = risk_lookup.get(entry.risk_id)
        if risk is None:
            logger.warning("Tornado entry %s not found in risks - skipping", entry.risk_id)
            continue

        col_idx = id_to_col.get(entry.risk_id)
        if col_idx is None:
            logger.warning("Risk %s not found in ev_costs columns - skipping", entry.risk_id)
            continue

        risk_col = ev_costs[:, col_idx]

        # Input distribution chart
        fig_input = _make_input_distribution_chart(risk)

        # Fired-only histogram
        result = _make_fired_histogram(risk_col, risk)
        fig_hist, n_fired, n_iter, fire_pct, fired_mean, fired_p50, fired_p80 = result

        card = {
            # Metadata from register
            "risk_id": risk.risk_id,
            "description": risk.description,
            "cause": risk.cause or "",
            "consequence": risk.consequence or "",
            "existing_controls": risk.existing_controls or "",
            "risk_status": risk.risk_status or "Open",
            "direction": risk.direction or "Threat",
            "owner": risk.owner,
            "correlation_group": risk.correlation_group,
            "distribution": risk.distribution,
            "recurrence_type": risk.recurrence_type,

            # MC inputs
            "probability": risk.probability,
            "opt_cost": risk.opt_cost,
            "ml_cost": risk.ml_cost,
            "pess_cost": risk.pess_cost,

            # Computed stats
            "emv_simple": risk.probability * risk.ml_cost,
            "mc_mean": float(np.mean(risk_col)),
            "tornado_swing": entry.std_contribution,
            "tornado_rank": rank,

            # Fired-only stats
            "n_fired": n_fired,
            "n_iter": n_iter,
            "fire_pct": fire_pct,
            "fired_mean": fired_mean,
            "fired_p50": fired_p50,
            "fired_p80": fired_p80,

            # Chart figure objects
            "fig_input": fig_input,
            "fig_histogram": fig_hist,
        }
        cards.append(card)

    return cards


# ---------------------------------------------------------------------------
# SP17 B2: Bridge waterfall data (EMV Simple -> EMV PERT -> MC Mean -> P80 -> P90)
# ---------------------------------------------------------------------------

def compute_bridge_waterfall_data(
    risks: list["RiskInput"],
    mc_results: dict,
) -> pd.DataFrame:
    """Build the 5-row waterfall data for the bridge chart.

    Columns: stage, value, delta, annotation. Row 0's delta is None (anchor).
    EMV scalars computed via the canonical analysis.py functions
    (p*(O+ML+P)/3 and p*(O+4ML+P)/6). MC Mean/P80/P90 pulled from mc_results.

    Raises KeyError if mc_results is missing any of mean / p80 / p90.
    """
    from src.analysis import compute_emv_simple, compute_emv_pert

    for required in ("mean", "p80", "p90"):
        if required not in mc_results:
            raise KeyError(
                f"mc_results is missing required key {required!r}; "
                f"expected keys: mean, p80, p90"
            )

    emv_simple = compute_emv_simple(risks)
    emv_pert = compute_emv_pert(risks)
    mc_mean = float(mc_results["mean"])
    mc_p80 = float(mc_results["p80"])
    mc_p90 = float(mc_results["p90"])

    rows = [
        {
            "stage": "EMV Simple",
            "value": emv_simple,
            "delta": None,
            "annotation": "Point estimate, simple mean weighting: p x (O+ML+P)/3",
        },
        {
            "stage": "EMV PERT",
            "value": emv_pert,
            "delta": emv_pert - emv_simple,
            "annotation": "Point estimate, PERT weighting: p x (O+4ML+P)/6",
        },
        {
            "stage": "MC Mean",
            "value": mc_mean,
            "delta": mc_mean - emv_pert,
            "annotation": "Simulated mean: adds correlation, chains, and distribution shape effects to EMV PERT",
        },
        {
            "stage": "P80",
            "value": mc_p80,
            "delta": mc_p80 - mc_mean,
            "annotation": "Contractor contingency: tail risk beyond the mean",
        },
        {
            "stage": "P90",
            "value": mc_p90,
            "delta": mc_p90 - mc_p80,
            "annotation": "Lender contingency: further tail extension",
        },
    ]

    return pd.DataFrame(rows, columns=["stage", "value", "delta", "annotation"])
