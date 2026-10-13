"""
Chart generation for Monte Carlo simulation outputs.

Three charts, all matplotlib → PNG for xlwings insertion:
  1. S-curve: cost probability distribution (grey L1, green total, blue gap)
  2. Tornado: top 10 variance drivers (horizontal bars, color-coded by owner)
  3. Convergence: P90 at increasing iteration subsets

Style: clean, professional, suitable for director/lender presentation.
All monetary values displayed in $M.
"""

import textwrap
from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")  # non-interactive backend for file output
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from src.config import SimConfig, TornadoEntry, SimRawResults, GainPainConfig
from src.final.chart_theme import apply_theme as _apply_chart_theme

# SR17 Workstream D — chart theme applied at module import so cost-side
# chart helpers pick up the brand palette without per-callsite changes.
_apply_chart_theme()


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

GREY = "#8C8C8C"
GREEN = "#2E8B57"
BLUE_FILL = "#B0D4F1"
ORANGE = "#E07020"
BOP_BLUE = "#2166AC"
CSE_ORANGE = "#D6604D"
SHARED_PURPLE = "#8073AC"
L1_GREY = "#999999"
OPP_GREEN = "#66BD63"

OWNER_COLOURS = {
    "bop": BOP_BLUE,
    "cs ": CSE_ORANGE,
    "cs_": CSE_ORANGE,
    "share": SHARED_PURPLE,
    "layer 1": L1_GREY,
    "": L1_GREY,
}


def _owner_colour(owner: str, layer: str = "") -> str:
    if layer == "Layer 1":
        return L1_GREY
    o = owner.lower()
    for prefix, colour in OWNER_COLOURS.items():
        if o.startswith(prefix):
            return colour
    return L1_GREY


def _m(val: float) -> str:
    """Format dollars as $XM."""
    return f"${val / 1e6:,.0f}M"


# ---------------------------------------------------------------------------
# Common style
# ---------------------------------------------------------------------------


def _apply_style(fig, ax):
    """Apply clean professional style."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")


# ---------------------------------------------------------------------------
# 1. S-Curve — Cost probability distribution
# ---------------------------------------------------------------------------


def generate_s_curve(
    sc_data: dict,
    config: SimConfig,
    output_path: str | Path,
    view: str = "All",
    pool_budget: float | None = None,
) -> None:
    """Generate the S-curve overlay chart.

    Parameters
    ----------
    sc_data : dict with sc_total_1..99, sc_l1_1..99, and optionally sc_pool_1..99
    config : SimConfig (for TIC, contingency, budget line)
    output_path : path to save PNG
    view : stakeholder view label for title
    pool_budget : Risk Pool budget ($) — used as budget line when view=Shared
    """
    percentiles = list(range(1, 100))

    fig, ax = plt.subplots(figsize=(10, 6))
    _apply_style(fig, ax)

    if view == "L2Only":
        # L2Only view: pure event risk costs from $0, no TIC/budget
        total_vals = np.array([sc_data[f"sc_total_{p}"] for p in percentiles]) / 1e6

        ax.plot(
            total_vals,
            percentiles,
            color=GREEN,
            linewidth=2.5,
            label="Total event risk cost",
            zorder=4,
        )

        # P-level reference lines (P50/P80/P90)
        x_range = (
            max(total_vals) - min(total_vals)
            if max(total_vals) > min(total_vals)
            else 1.0
        )
        offset = x_range * 0.03
        for p in [50, 80, 90]:
            idx = p - 1
            ax.axhline(p, color="#CCCCCC", linestyle=":", linewidth=0.8, zorder=1)
            ax.annotate(
                f"P{p}",
                xy=(total_vals[idx], p),
                xytext=(total_vals[idx] + offset, p + 2),
                fontsize=8,
                color=GREEN,
                arrowprops=dict(arrowstyle="-", color="#AAAAAA", lw=0.5),
            )

        ax.set_xlabel("Total Event Risk Cost ($M)", fontsize=11)
        ax.set_title(
            "Event Risk (L2) \u2014 Cost Probability Distribution",
            fontsize=13,
            fontweight="bold",
        )
    elif view == "Shared" and f"sc_pool_1" in sc_data:
        # Shared view: plot pool distribution (pure L2 costs, no TIC)
        pool_vals = np.array([sc_data[f"sc_pool_{p}"] for p in percentiles]) / 1e6

        ax.plot(
            pool_vals,
            percentiles,
            color=SHARED_PURPLE,
            linewidth=2.5,
            label="Shared risk pool cost",
            zorder=4,
        )

        # Budget line = pool_budget
        if pool_budget is not None:
            budget = pool_budget / 1e6
            budget_label = f"Risk Pool {_m(pool_budget)}"
        else:
            budget = (config.tic + config.contingency) / 1e6
            budget_label = f"Budget {_m(config.tic + config.contingency)}"
        ax.axvline(
            budget,
            color=ORANGE,
            linestyle="--",
            linewidth=2,
            label=budget_label,
            zorder=5,
        )

        # P-level reference lines
        x_range = (
            max(pool_vals) - min(pool_vals) if max(pool_vals) > min(pool_vals) else 1.0
        )
        offset = x_range * 0.03
        for p in [50, 80, 90]:
            idx = p - 1
            ax.axhline(p, color="#CCCCCC", linestyle=":", linewidth=0.8, zorder=1)
            ax.annotate(
                f"P{p}",
                xy=(pool_vals[idx], p),
                xytext=(pool_vals[idx] + offset, p + 2),
                fontsize=8,
                color=SHARED_PURPLE,
                arrowprops=dict(arrowstyle="-", color="#AAAAAA", lw=0.5),
            )

        ax.set_xlabel("Shared Risk Pool Cost ($M)", fontsize=11)
        ax.set_title(
            "Shared Risk Pool \u2014 Cost Probability Distribution",
            fontsize=13,
            fontweight="bold",
        )
    else:
        # Standard view: dual-curve (L1 + total)
        total_vals = np.array([sc_data[f"sc_total_{p}"] for p in percentiles]) / 1e6
        l1_vals = np.array([sc_data[f"sc_l1_{p}"] for p in percentiles]) / 1e6
        budget = (config.tic + config.contingency) / 1e6

        ax.plot(
            l1_vals,
            percentiles,
            color=GREY,
            linewidth=2,
            label="Layer 1 only (estimate uncertainty)",
            zorder=3,
        )
        ax.plot(
            total_vals,
            percentiles,
            color=GREEN,
            linewidth=2.5,
            label="Total integrated (L1 + L2 events)",
            zorder=4,
        )
        ax.fill_betweenx(
            percentiles,
            l1_vals,
            total_vals,
            color=BLUE_FILL,
            alpha=0.5,
            label="Event risk contribution",
            zorder=2,
        )
        ax.axvline(
            budget,
            color=ORANGE,
            linestyle="--",
            linewidth=2,
            label=f"Budget {_m(config.tic + config.contingency)}",
            zorder=5,
        )

        x_range = (
            max(total_vals) - min(total_vals)
            if max(total_vals) > min(total_vals)
            else 1.0
        )
        offset = x_range * 0.03
        for p in [50, 80, 90]:
            idx = p - 1
            ax.axhline(p, color="#CCCCCC", linestyle=":", linewidth=0.8, zorder=1)
            ax.annotate(
                f"P{p}",
                xy=(total_vals[idx], p),
                xytext=(total_vals[idx] + offset, p + 2),
                fontsize=8,
                color=GREEN,
                arrowprops=dict(arrowstyle="-", color="#AAAAAA", lw=0.5),
            )

        tic_m = config.tic / 1e6
        ax.axvline(tic_m, color="#AAAAAA", linestyle=":", linewidth=1, zorder=1)
        ax.annotate(f"TIC {_m(config.tic)}", xy=(tic_m, 5), fontsize=8, color="#666666")

        ax.set_xlabel("Total Outturn Cost ($M)", fontsize=11)
        ax.set_title(
            f"Cost Probability Distribution \u2014 {view} View",
            fontsize=13,
            fontweight="bold",
        )

    ax.set_ylabel("Cumulative Probability (%)", fontsize=11)
    ax.set_ylim(0, 100)
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("$%.0fM"))
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9)
    ax.grid(axis="x", alpha=0.3)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 2. Tornado chart — variance drivers
# ---------------------------------------------------------------------------


def generate_tornado(
    tornado_entries: list[TornadoEntry],
    output_path: str | Path,
    view: str = "All",
) -> None:
    """Generate horizontal tornado bar chart.

    Parameters
    ----------
    tornado_entries : list of TornadoEntry, pre-sorted descending by variance
    output_path : path to save PNG
    view : stakeholder view label for title
    """
    if not tornado_entries:
        # Create empty chart
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.text(
            0.5,
            0.5,
            "No risk data available",
            ha="center",
            va="center",
            fontsize=14,
            color="#999999",
            transform=ax.transAxes,
        )
        fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
        plt.close(fig)
        return

    # Take top 10 (should already be limited, but safety cap)
    entries = tornado_entries[:10]
    n = len(entries)

    # Reverse for bottom-to-top display (largest at top)
    entries = entries[::-1]

    raw_labels = [f"{e.risk_id} {e.description}" for e in entries]
    # Label budget at figsize=(12,...) + left=0.38 + 9pt font: ~42 chars per
    # line, 3-line cap => ~126 chars total. Longer labels are truncated with
    # an ellipsis placeholder via textwrap's max_lines.
    WRAP_WIDTH = 42
    labels = [
        textwrap.fill(lbl, width=WRAP_WIDTH, max_lines=3, placeholder=" ...")
        for lbl in raw_labels
    ]
    values = [e.std_contribution / 1e6 for e in entries]
    colours = [_owner_colour(e.owner, e.layer) for e in entries]

    fig, ax = plt.subplots(figsize=(12, max(4, n * 0.75 + 1)))
    _apply_style(fig, ax)

    y_pos = np.arange(n)
    bars = ax.barh(y_pos, values, color=colours, edgecolor="white", height=0.65)

    # Value labels on bars
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_width() + 0.05,
            bar.get_y() + bar.get_height() / 2,
            f"${val:,.1f}M",
            va="center",
            fontsize=9,
            color="#333333",
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.tick_params(axis="y", labelsize=9)
    # Rank 1 already at top via entries[::-1] above; no invert_yaxis needed.
    ax.set_xlabel("Standard Deviation Contribution ($M)", fontsize=11)
    if view == "L2Only":
        title = "Risk Drivers \u2014 Tornado Chart \u2014 Event Risks (L2)"
    else:
        title = f"Risk Drivers \u2014 Tornado Chart \u2014 {view} View"
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_xlim(0, max(values) * 1.25 if values else 1)

    # Legend — only show owners that actually appear in the chart
    from matplotlib.patches import Patch

    present_owners = set()
    for e in entries:
        if e.layer == "Layer 1":
            present_owners.add("layer 1")
        else:
            o = e.owner.lower()
            for prefix in OWNER_COLOURS:
                if o.startswith(prefix):
                    present_owners.add(prefix)
                    break

    legend_items = []
    if "layer 1" in present_owners:
        legend_items.append(Patch(facecolor=L1_GREY, label="Layer 1 (WBS variation)"))
    if "bop" in present_owners:
        legend_items.append(Patch(facecolor=BOP_BLUE, label="BOP Contractor"))
    if "cs " in present_owners or "cs_" in present_owners:
        legend_items.append(Patch(facecolor=CSE_ORANGE, label="Owner"))
    if "share" in present_owners:
        legend_items.append(Patch(facecolor=SHARED_PURPLE, label="Shared"))

    if legend_items:
        ax.legend(handles=legend_items, loc="lower right", fontsize=8, framealpha=0.9)

    fig.subplots_adjust(left=0.38, right=0.97, top=0.92, bottom=0.08)
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 3. Convergence chart
# ---------------------------------------------------------------------------


def generate_convergence(
    conv_data: dict,
    output_path: str | Path = None,
    view: str = "All",
    fig=None,
    ax=None,
) -> "plt.Figure | None":
    """Generate convergence check chart (P90 vs iteration count) with 95% CI band.

    Parameters
    ----------
    conv_data : dict
        Either a flat dict with conv_1000, conv_5000, ... keys (legacy path),
        and/or a "bootstrap" sub-dict carrying the iter_grid / point / p025 /
        p975 arrays from :func:`src.bootstrap.bootstrap_convergence`.
    output_path : path to save PNG. If None, the figure is returned for
        in-memory inspection (used by the chart-caption test).
    view : stakeholder view label for axis labels
    fig, ax : optional pre-built matplotlib objects (for tests)
    """
    points = [1000, 5000, 10000, 20000, 30000, 50000, 100000]
    boot = conv_data.get("bootstrap")

    values = []
    for n in points:
        key = f"conv_{n}"
        if key in conv_data:
            values.append(conv_data[key] / 1e6)
        else:
            break

    if boot is None and len(values) < 2:
        return None  # not enough data

    if fig is None or ax is None:
        fig, ax = plt.subplots(figsize=(8, 4.5))
    _apply_style(fig, ax)

    x_vals = points[: len(values)]
    if not x_vals and boot is not None:
        # Pure-bootstrap path — use the engine's iter_grid directly.
        x_vals = list(boot["iter_grid"])
        values = [float(p) / 1e6 for p in boot["point"]]

    if boot is not None:
        boot_x = list(boot["iter_grid"])
        p025 = [float(v) / 1e6 for v in boot["p025"]]
        p975 = [float(v) / 1e6 for v in boot["p975"]]
        ax.fill_between(
            boot_x, p025, p975,
            color=GREEN, alpha=0.20, zorder=2,
            label="95% bootstrap CI (Monte-Carlo error)",
        )

    ax.plot(
        x_vals, values, marker="o", color=GREEN, linewidth=2, markersize=8, zorder=4,
        label="P90 point estimate",
    )
    ax.xaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f"{int(x / 1000)}k")
    )
    ax.set_xticks(x_vals)

    # Convergence band: scaled tolerance
    final_val = values[-1]
    tol = max(final_val * 0.0015, 0.05) if values else 0.5
    ax.axhspan(
        final_val - tol,
        final_val + tol,
        color=GREEN,
        alpha=0.1,
        label=f"\u00b1${tol:,.1f}M tolerance",
        zorder=1,
    )
    ax.axhline(final_val, color=GREEN, linestyle=":", linewidth=1, zorder=2)

    # Check if converged
    if len(values) >= 2:
        delta = abs(values[-1] - values[-2])
        status = "Converged" if delta < tol else f"Delta: ${delta:,.1f}M"
        colour = GREEN if delta < tol else ORANGE
        ax.annotate(
            status,
            xy=(x_vals[-1], values[-1]),
            xytext=(x_vals[-1], values[-1] + tol * 1.5),
            fontsize=10,
            color=colour,
            fontweight="bold",
            ha="center",
        )

    # Data labels
    for i, (xv, val) in enumerate(zip(x_vals, values)):
        ax.annotate(
            f"${val:,.1f}M",
            xy=(xv, val),
            xytext=(0, -18),
            textcoords="offset points",
            fontsize=8,
            color="#666666",
            ha="center",
        )

    ax.set_xlim(0, x_vals[-1] * 1.05)
    ax.set_xlabel("Iterations", fontsize=11)
    if view == "L2Only":
        ax.set_ylabel("P90 Event Risk Cost ($M)", fontsize=11)
        ax.set_title(
            "Convergence Check \u2014 L2 P90 Stability", fontsize=13, fontweight="bold"
        )
    elif view == "Shared":
        ax.set_ylabel("P90 Shared Pool Cost ($M)", fontsize=11)
        ax.set_title(
            "Convergence Check \u2014 Pool P90 Stability",
            fontsize=13,
            fontweight="bold",
        )
    else:
        ax.set_ylabel("P90 Total Outturn Cost ($M)", fontsize=11)
        ax.set_title(
            "Convergence Check \u2014 P90 Stability", fontsize=13, fontweight="bold"
        )
    ax.legend(loc="upper right", fontsize=9)

    # SP18a — mandatory caption distinguishing simulation precision from
    # project-cost uncertainty. The exact wording is fixed by the brief and
    # tested for in tests/test_bootstrap.py::TestChartCaption.
    ax.text(
        0.99, -0.18,
        "CI band reflects simulation precision (Monte-Carlo error), "
        "not project-cost uncertainty.",
        transform=ax.transAxes, ha="right", va="top",
        fontsize=8, style="italic", color="#555555",
    )

    fig.tight_layout()
    if output_path is not None:
        fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
        plt.close(fig)
        return None
    return fig


# ---------------------------------------------------------------------------
# 4. Output histogram — frequency distribution of total outturn
# ---------------------------------------------------------------------------


def generate_output_histogram(
    total_costs: np.ndarray,
    config: SimConfig,
    output_path: str | Path,
    view: str = "All",
    pool_budget: float | None = None,
    shared_l2: np.ndarray | None = None,
) -> None:
    """Frequency histogram of total outturn cost distribution."""
    fig, ax = plt.subplots(figsize=(10, 6))
    _apply_style(fig, ax)

    if view == "L2Only" and shared_l2 is not None:
        # L2Only view: pure event risk costs from $0, no TIC/budget
        vals = shared_l2 / 1e6
        hist_colour = "#A8D5A2"  # light green
        edge_colour = GREEN
        title = "Event Risk (L2) Cost Distribution"
        xlabel = "Total Event Risk Cost ($M)"

        ax.hist(
            vals,
            bins=50,
            color=hist_colour,
            edgecolor=edge_colour,
            linewidth=0.5,
            alpha=0.85,
            zorder=3,
        )
    elif view == "Shared" and shared_l2 is not None:
        # Shared view: plot pure L2 costs (pool sizing)
        vals = shared_l2 / 1e6
        hist_colour = SHARED_PURPLE
        edge_colour = "#5E548E"
        title = f"Shared Risk Pool Distribution \u2014 {view} View"
        xlabel = "Shared Risk Pool Cost ($M)"

        ax.hist(
            vals,
            bins=50,
            color=hist_colour,
            edgecolor=edge_colour,
            linewidth=0.5,
            alpha=0.85,
            zorder=3,
        )

        if pool_budget is not None:
            budget = pool_budget / 1e6
            ax.axvline(
                budget,
                color=ORANGE,
                linestyle="--",
                linewidth=2,
                label=f"Risk Pool {_m(pool_budget)}",
                zorder=5,
            )
    else:
        # Standard view
        vals = total_costs / 1e6
        hist_colour = BLUE_FILL
        edge_colour = BOP_BLUE
        title = f"Outturn Cost Distribution \u2014 {view} View"
        xlabel = "Total Outturn Cost ($M)"

        ax.hist(
            vals,
            bins=50,
            color=hist_colour,
            edgecolor=edge_colour,
            linewidth=0.5,
            zorder=3,
        )

        budget = (config.tic + config.contingency) / 1e6
        ax.axvline(
            budget,
            color=ORANGE,
            linestyle="--",
            linewidth=2,
            label=f"Budget {_m(config.tic + config.contingency)}",
            zorder=5,
        )

        tic_m = config.tic / 1e6
        ax.axvline(
            tic_m,
            color="#AAAAAA",
            linestyle=":",
            linewidth=1.5,
            label=f"TIC {_m(config.tic)}",
            zorder=4,
        )

    # Clip x-axis to P99 to prevent lognormal outliers compressing the chart
    if len(vals) > 0:
        p1 = float(np.percentile(vals, 1))
        p99 = float(np.percentile(vals, 99))
        if p99 > p1:
            x_margin = (p99 - p1) * 0.1
            ax.set_xlim(p1 - x_margin, p99 + x_margin)

    # P50 / P80 / P90 lines (works for both views)
    pline_colour = SHARED_PURPLE if view == "Shared" else GREEN  # L2Only uses GREEN
    for p, ls in [(50, "-"), (80, "--"), (90, "-.")]:
        pval = float(np.percentile(vals, p))
        ax.axvline(pval, color=pline_colour, linestyle=ls, linewidth=1.5, zorder=5)
        ax.annotate(
            f"P{p} {_m(pval * 1e6)}",
            xy=(pval, ax.get_ylim()[1] * 0.92),
            fontsize=8,
            color=pline_colour,
            rotation=90,
            va="top",
            ha="right" if p == 90 else "left",
        )

    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel("Count", fontsize=11)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("$%.0fM"))
    if ax.get_legend_handles_labels()[1]:  # only show legend if there are labels
        ax.legend(loc="upper right", fontsize=9, framealpha=0.9)
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 5. Input distribution panel — top-N tornado risks
# ---------------------------------------------------------------------------


def generate_input_distribution_panel(
    raw: SimRawResults,
    risks: list,
    tornado_entries: list,
    output_path: str | Path,
    top_n: int = 5,
) -> None:
    """Panel of sampled cost distributions for top-N tornado risks (Layer 2)."""
    # Filter to Layer 2 entries only
    l2_entries = [e for e in tornado_entries if e.layer != "Layer 1"][:top_n]
    n_panels = len(l2_entries)

    if n_panels == 0:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(
            0.5,
            0.5,
            "No Layer 2 risks to display",
            ha="center",
            va="center",
            fontsize=14,
            color="#999999",
            transform=ax.transAxes,
        )
        fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
        plt.close(fig)
        return

    # Build risk_id → index map
    risk_idx_map = {r.risk_id: i for i, r in enumerate(risks)}

    ncols = 2 if n_panels > 3 else 1
    nrows = (n_panels + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 3 * nrows))
    if n_panels == 1:
        axes = np.array([axes])
    axes = axes.flatten()

    for k, entry in enumerate(l2_entries):
        ax = axes[k]
        _apply_style(fig, ax)
        idx = risk_idx_map.get(entry.risk_id)
        if idx is None or idx >= raw.ev_costs.shape[1]:
            ax.text(
                0.5,
                0.5,
                "N/A",
                ha="center",
                va="center",
                transform=ax.transAxes,
                color="#999999",
            )
            continue

        costs_all = raw.ev_costs[:, idx] / 1e6
        fired_mask = costs_all != 0
        costs_fired = costs_all[fired_mask]
        fire_rate = float(np.mean(fired_mask)) * 100
        n_fired = int(np.sum(fired_mask))

        colour = _owner_colour(entry.owner, entry.layer)

        if n_fired > 10:
            ax.hist(
                costs_fired,
                bins=30,
                color=colour,
                edgecolor="white",
                linewidth=0.3,
                alpha=0.85,
            )

            p50_f = float(np.percentile(costs_fired, 50))
            p90_f = float(np.percentile(costs_fired, 90))
            ax.axvline(
                p50_f, color=colour, linestyle="-", linewidth=1.2, alpha=0.7, zorder=5
            )
            ax.axvline(
                p90_f, color=colour, linestyle="--", linewidth=1.2, alpha=0.7, zorder=5
            )

            ax.set_title(
                f"{entry.risk_id}: {textwrap.shorten(entry.description, width=60, placeholder=' ...')}",
                fontsize=9,
            )
            ax.annotate(
                f"Fires: {fire_rate:.0f}% | If fired \u2192 P50: {_m(p50_f * 1e6)}, P90: {_m(p90_f * 1e6)}",
                xy=(0.98, 0.92),
                xycoords="axes fraction",
                fontsize=7,
                ha="right",
                color="#444444",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    facecolor="white",
                    edgecolor="#CCCCCC",
                    alpha=0.8,
                ),
            )
        else:
            ax.text(
                0.5,
                0.5,
                f"{entry.risk_id}\nFires: {fire_rate:.0f}%\nToo few to plot distribution",
                ha="center",
                va="center",
                transform=ax.transAxes,
                fontsize=9,
                color="#999999",
            )

        ax.set_xlabel("Cost if fired ($M)", fontsize=8)
        ax.tick_params(labelsize=7)

    # Hide unused axes
    for plot_idx in range(n_panels, len(axes)):
        axes[plot_idx].set_visible(False)

    fig.suptitle(
        "Top Risk Input Distributions (cost if fired)", fontsize=13, fontweight="bold"
    )
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 6. Gain/pain share distribution
# ---------------------------------------------------------------------------


def generate_gain_pain_chart(
    gp_results: dict,
    gp_config: GainPainConfig,
    output_path: str | Path,
) -> None:
    """Probability distribution of BOP net position after gain/pain share."""
    fig, ax = plt.subplots(figsize=(10, 6))
    _apply_style(fig, ax)

    if not gp_config.enabled:
        ax.text(
            0.5,
            0.5,
            "Gain/Pain share not yet enabled\n— awaiting client agreement",
            ha="center",
            va="center",
            fontsize=16,
            color="#999999",
            transform=ax.transAxes,
        )
        ax.set_xlim(-1, 1)
        ax.set_ylim(-1, 1)
        ax.axis("off")
        fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
        plt.close(fig)
        return

    bop_net = gp_results["bop_net"] / 1e6
    max_gain = gp_config.max_reward_pct * gp_config.toc / 1e6
    max_pain = gp_config.max_risk_pct * gp_config.toc / 1e6

    # Single uniform bin set across full range — avoids discontinuity at zero
    n_bins = 50
    bins = np.linspace(bop_net.min(), bop_net.max(), n_bins + 1)
    counts, edges = np.histogram(bop_net, bins=bins)

    gain_plotted = False
    pain_plotted = False
    for i, count in enumerate(counts):
        bin_centre = (edges[i] + edges[i + 1]) / 2
        if bin_centre >= 0:
            colour = "#66BD63"
            label = "Gainshare" if not gain_plotted else None
            gain_plotted = True
        else:
            colour = "#D6604D"
            label = "Painshare" if not pain_plotted else None
            pain_plotted = True
        ax.bar(
            edges[i],
            count,
            width=edges[i + 1] - edges[i],
            color=colour,
            edgecolor="white",
            linewidth=0.3,
            alpha=0.85,
            align="edge",
            label=label,
            zorder=3,
        )

    # Cap lines
    ax.axvline(
        max_gain,
        color=ORANGE,
        linestyle="--",
        linewidth=1.5,
        label=f"Max gain cap {_m(max_gain * 1e6)}",
        zorder=5,
    )
    ax.axvline(
        -max_pain,
        color=ORANGE,
        linestyle="--",
        linewidth=1.5,
        label=f"Max pain cap -{_m(max_pain * 1e6)}",
        zorder=5,
    )

    # Breakeven line
    ax.axvline(0, color="#AAAAAA", linestyle=":", linewidth=1.5, zorder=4)

    # P10/P50/P90
    for p, ls in [(10, "-."), (50, "-"), (90, "-.")]:
        pval = float(np.percentile(bop_net, p))
        ax.axvline(pval, color=BOP_BLUE, linestyle=ls, linewidth=1.2, zorder=5)
        ax.annotate(
            f"P{p} {_m(pval * 1e6)}",
            xy=(pval, ax.get_ylim()[1] * 0.85),
            fontsize=8,
            color=BOP_BLUE,
            rotation=90,
            va="top",
        )

    ax.set_xlabel("BOP Net Position ($M)", fontsize=11)
    ax.set_ylabel("Count", fontsize=11)
    ax.set_title("BOP Gain/Pain Share Distribution", fontsize=13, fontweight="bold")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 7. WBS distribution panel — Layer 1 bucket distributions
# ---------------------------------------------------------------------------


def generate_wbs_distribution_panel(
    raw: SimRawResults,
    buckets: list,
    output_path: str | Path,
) -> None:
    """Panel of Layer 1 WBS bucket variation distributions (dynamic grid)."""
    # When view=Shared, l1_buckets is all zeros — no L1 variation to plot
    n_buckets = min(len(buckets), raw.l1_buckets.shape[1])
    active = [
        k
        for k in range(n_buckets)
        if buckets[k].base_cost > 0 and np.any(raw.l1_buckets[:, k] != 0)
    ]
    if not active:
        # Nothing to plot — save a blank placeholder and return
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.text(
            0.5,
            0.5,
            "Layer 1 not simulated for this view",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=11,
        )
        ax.axis("off")
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return

    ncols = 4
    nrows = max(1, (len(active) + ncols - 1) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 3 * nrows))
    axes = axes.flatten()

    for plot_idx, k in enumerate(active):
        ax = axes[plot_idx]
        _apply_style(fig, ax)
        bucket = buckets[k]
        pct_var = raw.l1_buckets[:, k] / bucket.base_cost * 100
        pct_var = pct_var[np.isfinite(pct_var)]  # guard against any remaining NaN
        if len(pct_var) == 0:
            ax.set_visible(False)
            continue
        ax.hist(
            pct_var,
            bins=40,
            color="#D0D0D0",
            edgecolor="#666666",
            linewidth=0.3,
            alpha=0.85,
        )
        ax.axvline(0, color="#999999", linestyle=":", linewidth=1)
        ax.set_title(f"{bucket.name} (base ${bucket.base_cost / 1e6:.0f}M)", fontsize=9)
        ax.set_xlabel("% variation", fontsize=8)
        ax.tick_params(labelsize=7)

    for plot_idx in range(len(active), len(axes)):
        axes[plot_idx].set_visible(False)

    fig.suptitle("Layer 1 WBS Bucket Distributions", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 8. CG bar chart — correlation group P-level contributions
# ---------------------------------------------------------------------------

_CG_COLOURS = [
    "#2166AC",
    "#D6604D",
    "#8073AC",
    "#4DAF4A",
    "#FF7F00",
    "#E7298A",
    "#66C2A5",
    "#A6761D",
    "#999999",
    "#377EB8",
]


def generate_cg_bar_chart(
    cg_summary: list[dict],
    output_path: str | Path,
    p_level: int = 80,
    cg_mean: dict[str, float] | None = None,
) -> None:
    """Horizontal bar chart showing each CG group's P-level contribution.

    SP23: when ``cg_mean`` is supplied (mapping cg_code -> mean cost in $),
    render paired bars per CG group \u2014 P-level (existing) plus Mean (new) \u2014
    with a two-entry legend distinguishing the series. Sort order by P-level
    is preserved. When ``cg_mean`` is None, falls back to the legacy
    single-bar layout with per-CG colour rotation.
    """
    if not cg_summary:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(
            0.5,
            0.5,
            "No CG data available",
            ha="center",
            va="center",
            fontsize=14,
            color="#999999",
            transform=ax.transAxes,
        )
        fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
        plt.close(fig)
        return

    p_key = f"group_p{p_level}"

    # Sort ascending for bottom-to-top display (largest at top)
    entries = sorted(cg_summary, key=lambda d: d.get(p_key, 0))
    n = len(entries)

    labels = [f"{d['cg_code']} {d['cg_description']} ({d['n_risks']})" for d in entries]
    values = [d.get(p_key, 0) / 1e6 for d in entries]

    if cg_mean is None:
        colours = [_CG_COLOURS[i % len(_CG_COLOURS)] for i in range(n)]

        fig, ax = plt.subplots(figsize=(10, max(4, n * 0.5 + 1)))
        _apply_style(fig, ax)

        y_pos = np.arange(n)
        bars = ax.barh(y_pos, values, color=colours, edgecolor="white", height=0.65)

        for bar, val in zip(bars, values):
            ax.text(
                bar.get_width() + 0.05,
                bar.get_y() + bar.get_height() / 2,
                f"${val:,.1f}M",
                va="center",
                fontsize=9,
                color="#333333",
            )

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=9)
        ax.set_xlabel("Event Risk Cost ($M)", fontsize=11)
        ax.set_title(
            f"Correlation Group \u2014 Event Risk Exposure (P{p_level})",
            fontsize=13,
            fontweight="bold",
        )
        ax.set_xlim(0, max(values) * 1.25 if values and max(values) > 0 else 1)

        fig.tight_layout()
        fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
        plt.close(fig)
        return

    mean_values = [cg_mean.get(d["cg_code"], 0.0) / 1e6 for d in entries]

    fig, ax = plt.subplots(figsize=(10, max(4, n * 0.7 + 1)))
    _apply_style(fig, ax)

    y_pos = np.arange(n)
    bar_height = 0.4
    p80_colour = BOP_BLUE
    mean_colour = ORANGE

    p_bars = ax.barh(
        y_pos - bar_height / 2, values,
        color=p80_colour, edgecolor="white",
        height=bar_height, label=f"P{p_level} ($M)",
    )
    m_bars = ax.barh(
        y_pos + bar_height / 2, mean_values,
        color=mean_colour, edgecolor="white",
        height=bar_height, label="Mean ($M)",
    )

    for bar, val in zip(p_bars, values):
        ax.text(
            bar.get_width() + 0.05,
            bar.get_y() + bar.get_height() / 2,
            f"${val:,.1f}M",
            va="center", fontsize=8, color="#333333",
        )
    for bar, val in zip(m_bars, mean_values):
        ax.text(
            bar.get_width() + 0.05,
            bar.get_y() + bar.get_height() / 2,
            f"${val:,.1f}M",
            va="center", fontsize=8, color="#333333",
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Event Risk Cost ($M)", fontsize=11)
    ax.set_title(
        f"Correlation Group \u2014 Event Risk Exposure (P{p_level} and Mean)",
        fontsize=13,
        fontweight="bold",
    )
    max_v = max(values + mean_values + [0.0])
    ax.set_xlim(0, max_v * 1.25 if max_v > 0 else 1)
    ax.legend(loc="lower right", fontsize=10)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 9. Removal impact — grouped bar chart
# ---------------------------------------------------------------------------


def generate_removal_chart(
    removal_impact: list[dict],
    output_path: str | Path,
    p_level: int = 80,
) -> None:
    """Grouped bar chart showing P-level with each top risk removed."""
    if not removal_impact:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.text(
            0.5,
            0.5,
            "No removal data available",
            ha="center",
            va="center",
            fontsize=14,
            color="#999999",
            transform=ax.transAxes,
        )
        fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
        plt.close(fig)
        return

    original_p = removal_impact[0]["original_p"] / 1e6

    labels = ["Original"] + [f"Without {d['risk_id']}" for d in removal_impact]
    values = [original_p] + [d["removed_p"] / 1e6 for d in removal_impact]
    colours = ["#999999"] + [
        f"#{max(0x40, 0x21 + i * 0x30):02x}{max(0x60, 0x66 + i * 0x20):02x}AC"
        for i in range(len(removal_impact))
    ]
    # Simpler: use a blue gradient
    colours = ["#999999"] + ["#6BAED6", "#4292C6", "#2171B5"][: len(removal_impact)]

    fig, ax = plt.subplots(figsize=(8, 5))
    _apply_style(fig, ax)

    x_pos = np.arange(len(labels))
    bars = ax.bar(x_pos, values, color=colours, edgecolor="white", width=0.6)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.1,
            f"${val:,.1f}M",
            ha="center",
            fontsize=9,
            color="#333333",
        )

    ax.set_xticks(x_pos)
    ax.set_xticklabels(labels, fontsize=9, rotation=15, ha="right")
    ax.set_ylabel("Event Risk Cost ($M)", fontsize=11)
    ax.set_title(
        f"Impact of Removing Top Risk Drivers (P{p_level})",
        fontsize=13,
        fontweight="bold",
    )
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("$%.0fM"))
    ax.set_ylim(0, max(values) * 1.15 if values else 1)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 10. Exposure curve — cost at each confidence level
# ---------------------------------------------------------------------------


def generate_exposure_curve(
    p_levels: list[int],
    costs: list[float],
    output_path: str | Path,
    highlight_levels: list[int] | None = None,
) -> None:
    """Line chart: confidence level vs event risk cost.

    Data comes from existing S-curve lookup (sc_total_1..99), not a new
    analysis function. This is a rotated S-curve presentation.
    """
    if highlight_levels is None:
        highlight_levels = [50, 80, 90]

    costs_m = [c / 1e6 for c in costs]

    fig, ax = plt.subplots(figsize=(10, 6))
    _apply_style(fig, ax)

    ax.plot(p_levels, costs_m, color=GREEN, linewidth=2.5, zorder=4)
    ax.fill_between(p_levels, 0, costs_m, color=GREEN, alpha=0.1, zorder=2)

    for p in highlight_levels:
        if p in p_levels:
            idx = p_levels.index(p)
            val = costs_m[idx]
            ax.plot(p, val, "o", color=GREEN, markersize=8, zorder=5)
            ax.annotate(
                f"P{p}: ${val:,.1f}M",
                xy=(p, val),
                xytext=(p + 3, val + (max(costs_m) * 0.04)),
                fontsize=9,
                color="#333333",
                fontweight="bold",
                arrowprops=dict(arrowstyle="-", color="#AAAAAA", lw=0.5),
            )
            ax.axvline(p, color="#CCCCCC", linestyle=":", linewidth=0.8, zorder=1)

    ax.set_xlabel("Confidence Level (%)", fontsize=11)
    ax.set_ylabel("Event Risk Cost ($M)", fontsize=11)
    ax.set_title(
        "Event Risk Exposure by Confidence Level", fontsize=13, fontweight="bold"
    )
    ax.set_xlim(0, 100)
    ax.set_ylim(0)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("$%.0fM"))
    ax.grid(axis="both", alpha=0.3)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# SP17 B2: Bridge waterfall chart (EMV Simple -> EMV PERT -> MC Mean -> P80 -> P90)
# ---------------------------------------------------------------------------

BRIDGE_ANCHOR = "#2C3E50"     # neutral dark blue for first and last bars
BRIDGE_POS = "#E67E22"        # orange for positive deltas (uplift)
BRIDGE_NEG = "#27AE60"        # green for negative deltas (rare)


def generate_bridge_waterfall(
    waterfall_df,
    output_path: str | Path,
    title: str = "EMV to P90 Bridge Waterfall",
    figsize: tuple[float, float] = (11, 6.5),
    currency_div: float = 1_000_000.0,
    currency_suffix: str = "M",
) -> None:
    """Render and save a bridge waterfall to output_path as PNG.

    waterfall_df : DataFrame with columns [stage, value, delta, annotation],
        produced by src.reporting.compute_bridge_waterfall_data. Must have
        at least 2 rows; row 0's delta is ignored (anchor).

    First and last bars are anchor bars from zero to their value. Intermediate
    bars are floating bars that visualise the delta from the previous stage.
    Positive deltas use BRIDGE_POS (orange); negative deltas use BRIDGE_NEG
    (green); anchor bars use BRIDGE_ANCHOR (dark blue).

    Caller displays via IPython.display.Image(filename=output_path).
    """
    n = len(waterfall_df)
    if n < 2:
        raise ValueError(f"waterfall_df must have at least 2 rows; got {n}")

    stages = list(waterfall_df["stage"])
    values = [float(v) for v in waterfall_df["value"]]
    deltas = [waterfall_df["delta"].iloc[i] for i in range(n)]
    annotations = list(waterfall_df["annotation"])

    def fmt_money(v: float) -> str:
        return f"${v / currency_div:,.2f}{currency_suffix}"

    def fmt_delta(v: float) -> str:
        sign = "+" if v >= 0 else "-"
        return f"{sign}${abs(v) / currency_div:,.2f}{currency_suffix}"

    fig, ax = plt.subplots(figsize=figsize)
    _apply_style(fig, ax)

    x_positions = list(range(n))
    bar_width = 0.55

    # First bar: anchor from 0 to value
    ax.bar(
        0, values[0], bottom=0.0, width=bar_width,
        color=BRIDGE_ANCHOR, edgecolor="white", linewidth=0.6, zorder=3,
    )

    # Intermediate bars (1..n-2): floating from prev value to current value
    for i in range(1, n - 1):
        delta = values[i] - values[i - 1]
        bottom = min(values[i - 1], values[i])
        height = abs(delta)
        colour = BRIDGE_POS if delta >= 0 else BRIDGE_NEG
        ax.bar(
            i, height, bottom=bottom, width=bar_width,
            color=colour, edgecolor="white", linewidth=0.6, zorder=3,
        )

    # Last bar: anchor from 0 to value
    ax.bar(
        n - 1, values[-1], bottom=0.0, width=bar_width,
        color=BRIDGE_ANCHOR, edgecolor="white", linewidth=0.6, zorder=3,
    )

    # Connecting step lines between bar tops
    for i in range(n - 1):
        ax.plot(
            [i + bar_width / 2, i + 1 - bar_width / 2],
            [values[i], values[i]],
            color="#7F8C8D", linestyle="--", linewidth=0.8, zorder=2,
        )

    # Value label at top of each bar
    y_max_so_far = max(values)
    for i, v in enumerate(values):
        ax.text(
            i, v + y_max_so_far * 0.02,
            fmt_money(v),
            ha="center", va="bottom",
            fontsize=10, fontweight="bold", color="#2C3E50",
        )

    # Delta label centred on intermediate bars
    for i in range(1, n):
        delta = deltas[i]
        if delta is None or (isinstance(delta, float) and np.isnan(delta)):
            continue
        if i == n - 1 and n > 2:
            # Final bar is an anchor, not a floating delta bar; show delta
            # as a mid-bar subscript below the value label
            y_pos = values[i] * 0.5
            label_colour = "white"
        else:
            y_pos = (values[i - 1] + values[i]) / 2.0
            label_colour = "white"
        ax.text(
            i, y_pos,
            fmt_delta(delta),
            ha="center", va="center",
            fontsize=9, fontweight="bold", color=label_colour,
        )

    # Axes
    ax.set_xticks(x_positions)
    ax.set_xticklabels(stages, fontsize=10)
    ax.set_ylabel(f"Cost (${currency_suffix})", fontsize=11)
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _pos: f"${v / currency_div:,.0f}{currency_suffix}")
    )
    ax.set_ylim(0, max(values) * 1.18)
    ax.grid(axis="y", alpha=0.3, zorder=1)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=14)

    # Annotation footnote block below the chart
    footnote_lines = [f"{i + 1}. {stages[i]}: {annotations[i]}" for i in range(n)]
    footnote_text = "\n".join(footnote_lines)
    fig.text(
        0.02, 0.02,
        footnote_text,
        ha="left", va="bottom",
        fontsize=8, color="#34495E",
        family="sans-serif",
    )

    fig.tight_layout(rect=(0, 0.18, 1, 1))
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# SP18b: Per-day P-curve chart
#
# IMPORTANT: this is NOT a phased S-curve. It shows the distribution of
# CUMULATIVE risk-driven cost crystallising by project day, not contractual
# cash-flow timing. The caption text below is mandatory under SP18b.
# ---------------------------------------------------------------------------

PER_DAY_CAPTION = (
    "Per-day P-curve shows the distribution of CUMULATIVE risk-driven cost "
    "crystallising by project day. This is NOT a phased S-curve and does "
    "not represent contractual cash-flow timing."
)


def generate_per_day_pcurve(
    curve: dict,
    output_path: str | Path = None,
    *,
    fig=None,
    ax=None,
    thumbnail: bool = False,
) -> "plt.Figure | None":
    """Render the per-day P-curve (P50 / P80 / P90 cumulative cost vs day).

    Parameters
    ----------
    curve : dict from :func:`src.per_day_curve.compute_per_day_curve` (or the
        analysis-layer wrapper). Required keys: ``day_axis``, ``p050``,
        ``p080``, ``p090``. If ``curve.get("enabled") is False`` the function
        returns ``None`` without rendering.
    output_path : path to save PNG; if ``None``, return the figure instead
        (used by tests).
    thumbnail : if True, render a small (160×90 px-equivalent) sparkline-style
        version suitable for the dashboard thumbnail slot.
    """
    if not curve or not curve.get("enabled", True):
        return None
    day_axis = np.asarray(curve["day_axis"])
    p50 = np.asarray(curve["p050"]) / 1e6
    p80 = np.asarray(curve["p080"]) / 1e6
    p90 = np.asarray(curve["p090"]) / 1e6

    if thumbnail:
        figsize = (3.2, 1.8)
        title_fs = 9
        label_fs = 7
        line_w = 1.2
    else:
        figsize = (8.5, 4.8)
        title_fs = 13
        label_fs = 11
        line_w = 2.0

    if fig is None or ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    _apply_style(fig, ax)

    ax.fill_between(day_axis, p50, p90, color=GREEN, alpha=0.12, zorder=1,
                    label="P50 to P90 envelope")
    ax.plot(day_axis, p50, color=GREEN, linewidth=line_w, linestyle="-",
            label="P50", zorder=4)
    ax.plot(day_axis, p80, color=ORANGE, linewidth=line_w, linestyle="--",
            label="P80", zorder=4)
    ax.plot(day_axis, p90, color=BOP_BLUE, linewidth=line_w, linestyle=":",
            label="P90", zorder=4)

    ax.set_xlabel("Project day", fontsize=label_fs)
    ax.set_ylabel("Cumulative risk cost ($M)", fontsize=label_fs)
    if not thumbnail:
        ax.set_title(
            "Per-day P-curve: cumulative risk cost by project day",
            fontsize=title_fs, fontweight="bold",
        )
        ax.legend(loc="upper left", fontsize=9, framealpha=0.9)
        # MANDATORY caption: see PER_DAY_CAPTION constant. Tested for in
        # tests/test_per_day_curve.py::TestChartCaption.
        ax.text(
            0.99, -0.18,
            PER_DAY_CAPTION,
            transform=ax.transAxes, ha="right", va="top",
            fontsize=8, style="italic", color="#555555", wrap=True,
        )
    else:
        ax.set_xticks([])
        ax.tick_params(axis="y", labelsize=7)

    ax.set_xlim(day_axis[0], day_axis[-1])
    ax.set_ylim(bottom=0)

    fig.tight_layout()
    if output_path is not None:
        fig.savefig(str(output_path), dpi=200, bbox_inches="tight")
        plt.close(fig)
        return None
    return fig
