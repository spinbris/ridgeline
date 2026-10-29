# SR9 v3 amendment - 2026-04-26 - presentation-layer reframe.
"""SR9 v3 chart helpers.

Static PNG chart generation for the executive summary and notebook.
matplotlib (already a project dependency).

Charts produced:
  - make_tornado_chart : horizontal-bar ranked driver tornado
  - make_s_curve       : multi-scenario cumulative-probability overlay
  - make_density_histogram : single-scenario density with mean / percentiles
  - make_risk_matrix   : two side-by-side scatter plots (traditional vs
                         probability-weighted)
  - make_confidence_waterfall : how integrated P80 is constructed

Module path src/final/charts.py is intentionally distinct from the
existing src/charts.py used by the cost engine; import the v3 module
via package-relative imports or `from src.final.charts import ...` to
avoid collision.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless rendering for notebook + tests

import matplotlib.pyplot as plt
import numpy as np

from src.final.chart_theme import apply_theme as _apply_chart_theme

# SR17 Workstream D — apply the chart theme at module import so every
# chart helper below picks up the categorical prop_cycle, the sequential
# cmap (replacing viridis), and the neutral grey axis defaults without
# each helper having to opt in. Idempotent.
_apply_chart_theme()
import pandas as pd


# ----------------------------------------------------------------------------
# Default colour palette
# ----------------------------------------------------------------------------

MODE_COLORS = {
    "Series": "#C0392B",     # red
    "Hybrid": "#E67E22",     # amber
    "Parallel": "#27AE60",   # green
    "n/a": "#95A5A6",        # neutral grey - Stage 3 has no Mode classification
}

SCENARIO_COLORS = {
    "DP_Review": "#7F8C8D",          # grey - conservative starting point
    "Dummy_Realistic": "#2980B9",    # mid blue - interim
    "All_Series": "#922B21",         # dark red - upper bound
    "Stage3": "#1A5276",             # deep blue - Stage 3 CPM replay headline
}


# ----------------------------------------------------------------------------
# Five-band CI palette (shared by Beta-12 banded distribution chart and the
# SR10.B chart suite). Mirrors :data:`src.final.composer.CI_BAND_DEFINITIONS`.
# Visual coding: greys for "never" / "rarely" (low criticality), amber for
# "near" (the actionable cut), reds for "often" / "always" (high criticality
# and stable critical path). The "near" band is colour-coded amber to draw
# the eye to the most useful cut for float management.
# ----------------------------------------------------------------------------

_CI_BAND_DISPLAY_ORDER = (
    "never (<10%)",
    "rarely (10-30%)",
    "near (30-70%)",
    "often (70-90%)",
    "always (90%+)",
)
_CI_BAND_COLORS = {
    "never (<10%)": "#9E9E9E",        # mid-grey
    "rarely (10-30%)": "#BDBDBD",     # light-grey
    "near (30-70%)": "#FFA726",       # amber — the actionable cut
    "often (70-90%)": "#E57373",      # light-red
    "always (90%+)": "#C62828",       # dark-red
}


# ----------------------------------------------------------------------------
# Tornado chart
# ----------------------------------------------------------------------------

def make_tornado_chart(
    ranked_risks: list[dict],
    title: str,
    x_axis_label: str,
    output_path: Path | str,
    color_map: dict | None = None,
    value_format: str = "{:.2f}",
    show_pct_of_total: bool = True,
) -> Path:
    """Generate horizontal-bar tornado chart, ranked descending by value.

    Parameters
    ----------
    ranked_risks : list of dict
        Each dict must contain keys: risk_id (str), title (str),
        value (float). Optional keys: color_category (str, used with
        color_map), pct_of_total (float, 0-1; if absent and
        show_pct_of_total, computed from values).
    title : str
        Chart title.
    x_axis_label : str
        e.g. "P80 cost contribution ($M)" or "Probability-weighted mean
        contribution (days)".
    output_path : Path or str
        Where to write the PNG.
    color_map : dict or None
        category -> hex color. If None and color_category is in entries,
        bars are uniform default colour.
    value_format : str
        Format string for value labels on bars.
    show_pct_of_total : bool
        Whether to append "(X.X% of total)" to bar labels.

    Returns
    -------
    Path
        Resolved output path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not ranked_risks:
        # Empty chart with placeholder text.
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(
            0.5, 0.5, "(no drivers to rank)",
            ha="center", va="center", fontsize=12, color="#7F8C8D",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path.resolve()

    # Sort descending by value so top driver appears at top.
    ranked = sorted(ranked_risks, key=lambda d: float(d.get("value", 0.0)), reverse=True)
    values = [float(d.get("value", 0.0)) for d in ranked]
    risk_ids = [str(d.get("risk_id", "")) for d in ranked]
    total = sum(values) if sum(values) > 0 else 1.0

    if color_map is not None:
        colors = [color_map.get(d.get("color_category", ""), "#34495E") for d in ranked]
    else:
        colors = ["#34495E"] * len(ranked)

    height = max(3.0, 0.5 * len(ranked) + 1.5)
    fig, ax = plt.subplots(figsize=(10, height))
    y_pos = np.arange(len(ranked))[::-1]
    bars = ax.barh(y_pos, values, color=colors, edgecolor="black", linewidth=0.4)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(risk_ids, fontsize=10)
    ax.set_xlabel(x_axis_label, fontsize=11)
    ax.set_title(title, fontsize=13, pad=12)
    ax.grid(axis="x", linestyle=":", color="#BDC3C7", zorder=0)
    ax.set_axisbelow(True)

    # Bar labels.
    max_val = max(values) if values else 1.0
    label_offset = 0.01 * max_val
    for bar, val, d in zip(bars, values, ranked):
        if show_pct_of_total:
            pct = d.get("pct_of_total")
            if pct is None:
                pct = val / total
            label = f"{value_format.format(val)} ({pct*100:.1f}%)"
        else:
            label = value_format.format(val)
        ax.text(
            bar.get_width() + label_offset,
            bar.get_y() + bar.get_height() / 2,
            label,
            va="center", ha="left", fontsize=9,
        )

    # Legend if colors meaningful.
    if color_map is not None:
        legend_handles = [
            plt.Rectangle((0, 0), 1, 1, color=c, label=name)
            for name, c in color_map.items()
        ]
        ax.legend(handles=legend_handles, loc="lower right", fontsize=9, framealpha=0.9)

    ax.set_xlim(left=min(0.0, min(values) * 1.1), right=max_val * 1.18)
    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()


def make_leave_one_out_tornado(
    rows: list[dict],
    title: str,
    output_path: Path | str,
    top_n: int = 10,
    method_note: str = "",
) -> Path:
    """INTSCURVE-01 P3: integrated leave-one-out bars, each split into cost and delay cost.

    ``rows`` are :func:`src.integrated.leave_one_out.integrated_leave_one_out` rows (dollars),
    already ranked. Bars are drawn in $M as two stacked segments; the label is the total saved.
    A negative segment (rare: a removal that lifts the P-level through a reshuffled tail) is
    drawn left of zero rather than hidden.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ranked = list(rows)[:top_n]
    if not ranked:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(0.5, 0.5, "(no risks to rank)", ha="center", va="center", fontsize=12,
                color="#7F8C8D", transform=ax.transAxes)
        ax.set_axis_off()
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path.resolve()

    cost = np.array([float(r["cost_part_dollars"]) for r in ranked]) / 1e6
    delay = np.array([float(r["delay_part_dollars"]) for r in ranked]) / 1e6
    saved = np.array([float(r["saved_dollars"]) for r in ranked]) / 1e6
    height = max(3.0, 0.5 * len(ranked) + 2.0)
    fig, ax = plt.subplots(figsize=(10, height))
    y_pos = np.arange(len(ranked))[::-1]
    ax.barh(y_pos, cost, color="#1F4E79", edgecolor="black", linewidth=0.4,
            label="Event-risk cost part")
    ax.barh(y_pos, delay, left=np.where(delay >= 0, np.maximum(cost, 0.0), np.minimum(cost, 0.0)),
            color="#E67E22", edgecolor="black", linewidth=0.4,
            label="Delay cost part (float-aware days x day rate)")
    span = float(max(np.max(np.abs(saved)), 1e-9))
    for y, total, c, d in zip(y_pos, saved, cost, delay):
        right = max(c, 0.0) + max(d, 0.0)
        ax.text(right + 0.01 * span, y, f"${total:.2f}M", va="center", ha="left", fontsize=9)
    ax.set_yticks(y_pos)
    ax.set_yticklabels([str(r["risk_id"]) for r in ranked], fontsize=10)
    ax.set_xlabel("Integrated P80 saved if the risk is removed ($M)", fontsize=11)
    ax.set_title(title, fontsize=13, pad=12)
    ax.grid(axis="x", linestyle=":", color="#BDC3C7", zorder=0)
    ax.set_axisbelow(True)
    ax.axvline(0.0, color="#7F8C8D", linewidth=0.8)
    ax.legend(loc="lower right", fontsize=9, framealpha=0.9)
    left = min(0.0, float(np.min(np.minimum(cost, 0.0) + np.minimum(delay, 0.0))) * 1.1)
    ax.set_xlim(left=left, right=span * 1.2)
    if method_note:
        fig.text(0.01, -0.02, method_note, fontsize=8, color="#566573", wrap=True, ha="left",
                 va="top")
    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()


def make_jcl_scatter(
    jcl: dict,
    title: str,
    output_path: Path | str,
    *,
    finish_label: str = "Project finish (working days from start)",
    max_points: int = 6000,
) -> Path:
    """INTSCURVE-01 P11: cost against finish per iteration, the target crosshair and the JCL.

    ``jcl`` is :func:`src.integrated.jcl.jcl_data`'s dict (cost in dollars, drawn in $M).
    Iterations that meet both targets are coloured; the rest are grey. At most ``max_points``
    are drawn, an evenly spaced subset of the run, so the chart is the same at every iteration
    count; the printed JCL is always the whole run's.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cost = np.asarray(jcl["cost_axis"], dtype=float) / 1e6
    finish = np.asarray(jcl["finish_axis"], dtype=float)
    meets = np.asarray(jcl["meets_both"], dtype=bool)
    step = max(1, int(np.ceil(cost.size / max_points)))
    idx = np.arange(0, cost.size, step)
    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.scatter(finish[idx][~meets[idx]], cost[idx][~meets[idx]], s=6, color="#BDC3C7",
               alpha=0.6, linewidths=0, label="Misses cost or finish target")
    ax.scatter(finish[idx][meets[idx]], cost[idx][meets[idx]], s=6, color="#1F4E79",
               alpha=0.6, linewidths=0, label="Meets both targets")
    c_t, f_t = jcl["cost_target"] / 1e6, jcl["finish_target"]
    ax.axhline(c_t, color="#C0392B", linewidth=1.2, linestyle="--")
    ax.axvline(f_t, color="#C0392B", linewidth=1.2, linestyle="--")
    frontier = jcl.get("frontier") or []
    if frontier:
        ax.plot([f for f, _ in frontier], [c / 1e6 for _, c in frontier], color="#E67E22",
                linewidth=1.8, label=f"{jcl['level']:.0%} joint-confidence frontier")
    ax.annotate(f"JCL {jcl['jcl']:.0%}\n(cost {jcl['cost_confidence']:.0%}, "
                f"finish {jcl['finish_confidence']:.0%} on their own)",
                xy=(f_t, c_t), xytext=(8, 8), textcoords="offset points", fontsize=10,
                color="#C0392B", fontweight="bold")
    ax.set_xlabel(finish_label, fontsize=11)
    ax.set_ylabel("Cost excluding delay cost ($M)", fontsize=11)
    ax.set_title(title, fontsize=13, pad=12)
    ax.grid(linestyle=":", color="#BDC3C7", zorder=0)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", fontsize=9, framealpha=0.9, markerscale=3)
    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()


# ----------------------------------------------------------------------------
# S-curve chart
# ----------------------------------------------------------------------------

#: Comparator line styles on a headline S-curve, so overlapping comparators stay distinguishable.
_COMPARATOR_DASHES = ("--", "-.", ":")


def make_s_curve(
    distributions: dict[str, np.ndarray],
    percentile_markers: list[int],
    title: str,
    output_path: Path | str,
    color_map: dict | None = None,
    x_axis_label: str = "Schedule slip (days)",
    headline_label: str | None = None,
    value_label_fmt: str | None = None,
    marker_values: dict[int, float] | None = None,
) -> Path:
    """Generate multi-scenario cumulative-probability S-curve.

    Parameters
    ----------
    distributions : dict
        scenario_label (display string) -> 1D array of sample values.
    percentile_markers : list[int]
        Percentiles to mark with vertical reference lines (e.g. [50, 80, 90, 95]).
    title : str
        Chart title.
    output_path : Path or str
        Where to write PNG.
    color_map : dict or None
        scenario_label -> hex color. Defaults applied when keys match
        SCENARIO_COLORS, otherwise matplotlib cycles.
    x_axis_label : str
        Default "Schedule slip (days)".
    headline_label : str or None
        Beta-14 §2: when set, this label's curve is rendered as the
        headline scenario — solid, full-opacity, linewidth 2.5, drawn
        last so it visually sits on top of the comparators and the
        percentile reference lines. Comparator curves are rendered at
        alpha 0.60 with linewidth 1.5. Legend ordering places the
        headline first.
    value_label_fmt : str or None
        SR-S3-Beta-18 §4: when set (e.g., ``"${value:.2f}M"`` or
        ``"{value:.1f}d"``), the chart drops a thin dotted line from
        each percentile point on the headline curve (or the first
        curve when no headline is supplied) down to the x-axis, and
        annotates that point with the formatted value. The format
        string must contain ``{value}`` as the substitution token.
        When ``None`` (default), neither drop-lines nor annotations
        are drawn — existing call sites and tests retain their prior
        behaviour. The reference horizontal P-level line + "P80"
        text label is preserved regardless.
    marker_values : dict or None
        INTSCURVE-01 P1: ``{percentile: x}`` in the plotted unit. When supplied, the drop-lines
        and labels sit at these values instead of percentiles recomputed from the plotted array,
        so a chart drawn in $M marks the headline's own figures (computed in dollars) rather than
        a rescaled array's, which can differ in the last bit.

    Returns
    -------
    Path
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 6))

    color_map = dict(color_map or {})

    # Beta-14 §2: when a headline_label is supplied, draw comparators first
    # (faded) and headline last (solid, heavy, on top of percentile lines).
    # Without a headline_label, behave as pre-Beta-14: every curve gets
    # uniform alpha 1.0 / linewidth 2.0 and legend order matches insertion.
    items = list(distributions.items())
    headline_first_handle = None
    headline_first_label = None
    comparator_handles: list = []
    comparator_labels: list[str] = []

    if headline_label is not None and headline_label in distributions:
        # DELIVFIX-01 (FW-28): comparators were drawn faded UNDER the headline, so one that
        # coincides with it - or with another comparator - vanished (wind's DP Review line).
        # Each now has its own dash pattern and is drawn ABOVE the headline, so a near-
        # coincident curve still shows; exactly identical curves share one legend entry.
        comparators: list[tuple[str, np.ndarray]] = []
        for label, samples in items:
            arr = np.sort(np.asarray(samples, dtype=float))
            if label == headline_label or arr.size == 0:
                continue
            twin = next((i for i, (_, other) in enumerate(comparators)
                         if other.shape == arr.shape and np.array_equal(other, arr)), None)
            if twin is None:
                comparators.append((label, arr))
            else:
                comparators[twin] = (f"{comparators[twin][0]} = {label}", arr)
        for n, (label, sorted_arr) in enumerate(comparators):
            cdf = np.linspace(0.0, 1.0, len(sorted_arr), endpoint=True)
            base = label.split(" = ")[0]
            color = color_map.get(base) or SCENARIO_COLORS.get(base) or None
            (line,) = ax.plot(
                sorted_arr, cdf * 100.0,
                label=label, color=color,
                linewidth=1.6, alpha=0.95, zorder=12,
                linestyle=_COMPARATOR_DASHES[n % len(_COMPARATOR_DASHES)],
            )
            comparator_handles.append(line)
            comparator_labels.append(label)

        arr = np.asarray(distributions[headline_label], dtype=float)
        if arr.size > 0:
            sorted_arr = np.sort(arr)
            cdf = np.linspace(0.0, 1.0, len(sorted_arr), endpoint=True)
            color = (
                color_map.get(headline_label)
                or SCENARIO_COLORS.get(headline_label)
                or None
            )
            (line,) = ax.plot(
                sorted_arr, cdf * 100.0,
                label=headline_label, color=color,
                linewidth=2.5, alpha=1.0, zorder=10,
            )
            headline_first_handle = line
            headline_first_label = headline_label
    else:
        for label, samples in items:
            arr = np.asarray(samples, dtype=float)
            if arr.size == 0:
                continue
            sorted_arr = np.sort(arr)
            cdf = np.linspace(0.0, 1.0, len(sorted_arr), endpoint=True)
            color = color_map.get(label) or SCENARIO_COLORS.get(label) or None
            (line,) = ax.plot(
                sorted_arr, cdf * 100.0,
                label=label, color=color, linewidth=2,
            )
            comparator_handles.append(line)
            comparator_labels.append(label)

    # Reference percentile lines on the highest-curve scenario for readability.
    if distributions and percentile_markers:
        all_max = max(
            np.percentile(np.asarray(v, dtype=float), 99)
            for v in distributions.values() if len(v) > 0
        )
        for pct in percentile_markers:
            ax.axhline(pct, color="#95A5A6", linestyle=":", linewidth=0.8, alpha=0.6)
            ax.text(all_max * 0.98, pct + 1, f"P{pct}", fontsize=8, color="#7F8C8D", ha="right")

    # SR-S3-Beta-18 §4: per-percentile drop-lines + value annotations on
    # the headline curve. Pick the headline_label's distribution if
    # supplied; otherwise the first non-empty curve in insertion order.
    # The drop runs from the curve point (x_value, pct) down to
    # (x_value, 0); the annotation sits offset above the curve point so
    # it doesn't overlap the horizontal P-level reference line.
    if value_label_fmt and distributions and percentile_markers:
        if headline_label is not None and headline_label in distributions:
            anchor_label = headline_label
        else:
            anchor_label = next(
                (lbl for lbl, arr in distributions.items()
                 if np.asarray(arr).size > 0),
                None,
            )
        if anchor_label is not None:
            anchor_arr = np.asarray(distributions[anchor_label], dtype=float)
            for pct in percentile_markers:
                x_value = (float(marker_values[pct]) if marker_values and pct in marker_values
                           else float(np.percentile(anchor_arr, pct)))
                # Vertical drop from curve down to x-axis.
                ax.plot(
                    [x_value, x_value], [0.0, float(pct)],
                    color="#34495E", linestyle=":", linewidth=0.9, alpha=0.85,
                    zorder=3,
                )
                # Annotation up-LEFT of the curve point (DELIVFIX-01, FW-28). Up-right sat on
                # the curve, which rises to the right; above a cumulative curve is to its left,
                # so that space is empty. A white backing keeps it legible over grid lines.
                label_text = value_label_fmt.format(value=x_value)
                ax.annotate(
                    label_text,
                    xy=(x_value, float(pct)),
                    xytext=(-6, 6),
                    textcoords="offset points",
                    fontsize=8,
                    color="#2C3E50",
                    ha="right",
                    va="bottom",
                    zorder=13,
                    bbox={"boxstyle": "round,pad=0.15", "facecolor": "white",
                          "edgecolor": "none", "alpha": 0.85},
                )

    ax.set_xlabel(x_axis_label, fontsize=11)
    ax.set_ylabel("Cumulative probability (%)", fontsize=11)
    ax.set_title(title, fontsize=13, pad=12)
    ax.set_ylim(0, 100)
    ax.grid(linestyle=":", color="#BDC3C7", alpha=0.7)

    # Beta-14 §2: legend headline-first, then comparators in insertion order.
    if headline_first_handle is not None:
        legend_handles = [headline_first_handle, *comparator_handles]
        legend_labels = [headline_first_label, *comparator_labels]
        ax.legend(legend_handles, legend_labels, loc="lower right", fontsize=9, framealpha=0.9)
    else:
        ax.legend(loc="lower right", fontsize=9, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()


# ----------------------------------------------------------------------------
# Density histogram
# ----------------------------------------------------------------------------

# Beta-11 §2: schedule MC distributions are right-skewed with a high
# probability spike at zero (no-fire iterations). Without annotation the
# spike dominates the chart visually and obscures the right tail where
# the contingency-sizing decisions live. ZERO_THRESHOLD_DAYS defines the
# bin "iteration that produced no schedule slip"; ZERO_ANNOTATION_FLOOR is
# the minimum p_zero that triggers the callout (below it the spike is
# small enough that the chart reads cleanly without annotation).
ZERO_THRESHOLD_DAYS: float = 0.5
ZERO_ANNOTATION_FLOOR: float = 0.05


def make_density_histogram(
    samples: np.ndarray,
    title: str,
    output_path: Path | str,
    mean_value: float | None = None,
    percentile_markers: dict[int, float] | None = None,
    x_axis_label: str = "Schedule slip (days)",
    bins: int = 60,
    color: str = "#2980B9",
    nil_bucket_annotation: bool = True,
) -> Path:
    """Generate density histogram with mean and percentile reference lines.

    Parameters
    ----------
    samples : np.ndarray
        1D array of sample values.
    title : str
        Chart title.
    output_path : Path or str
        Where to write PNG.
    mean_value : float or None
        If provided, drawn as a vertical line.
    percentile_markers : dict or None
        {percentile_int: value_float} - vertical reference lines.
    x_axis_label : str
        Default "Schedule slip (days)".
    bins : int
        Histogram bin count.
    color : str
        Hex colour for histogram bars.
    nil_bucket_annotation : bool
        Beta-16 Item 2: schedule-specific "P(no schedule slip)" callout.
        Default ``True`` preserves the Beta-11 behaviour for schedule
        density charts. Set ``False`` for the cost-side density chart;
        cost MC distributions are unimodal right-skewed with no zero
        spike to highlight (per brief Decision 4).

    Returns
    -------
    Path

    Notes
    -----
    Beta-11 §2: when the leftmost bin holds at least
    :data:`ZERO_ANNOTATION_FLOOR` of iterations (i.e. the "no schedule
    slip" probability is material), a callout is drawn pointing at the
    bar with text ``P(no schedule slip) = X%`` and the underlying count.
    The reader otherwise mistakes the spike for a numerical artefact.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    arr = np.asarray(samples, dtype=float)
    fig, ax = plt.subplots(figsize=(10, 5))

    if arr.size > 0:
        counts, bin_edges = np.histogram(arr, bins=bins)
        ax.hist(arr, bins=bins, color=color, edgecolor="white", alpha=0.85)

        # Beta-11 §2: nil-bucket annotation.
        # Beta-11a Fix 2: dropped the "(N of M iterations)" sub-line —
        # the count came from the leftmost bin (a wider window than the
        # ZERO_THRESHOLD_DAYS strict-zero check used for p_zero), so the
        # rendered "499 of 1,000 iterations" did not divide to the
        # rendered "43%". Both numbers were individually correct but the
        # combination looked inconsistent. The percentage alone tells
        # the story; the prose sub-caption below the chart explains the
        # underlying fraction so no information is lost.
        # Beta-16 Item 2: caller can disable via `nil_bucket_annotation`
        # for the cost-side density chart (no zero spike to surface).
        p_zero = float((arr < ZERO_THRESHOLD_DAYS).mean())
        if nil_bucket_annotation and p_zero >= ZERO_ANNOTATION_FLOOR:
            leftmost_count = int(counts[0])
            x_left = float((bin_edges[0] + bin_edges[1]) / 2)
            x_span = float(bin_edges[-1] - bin_edges[0])
            y_max = float(counts.max())
            ax.annotate(
                f"P(no schedule slip) = {p_zero:.0%}",
                xy=(x_left, leftmost_count),
                xytext=(x_left + x_span * 0.15, max(leftmost_count, y_max) * 0.85),
                fontsize=9,
                arrowprops={"arrowstyle": "->", "color": "#444444", "lw": 0.8},
                bbox={
                    "boxstyle": "round,pad=0.4",
                    "fc": "#FFF8E1",
                    "ec": "#444444",
                    "lw": 0.5,
                },
            )

        if mean_value is not None:
            ax.axvline(mean_value, color="#E67E22", linewidth=2, label=f"Mean = {mean_value:.2f}")
        if percentile_markers:
            for pct, val in sorted(percentile_markers.items()):
                ax.axvline(
                    val,
                    color="#34495E",
                    linewidth=1.2,
                    linestyle="--",
                    label=f"P{pct} = {val:.2f}",
                )
        ax.legend(loc="upper right", fontsize=9, framealpha=0.9)

    ax.set_xlabel(x_axis_label, fontsize=11)
    ax.set_ylabel("Iteration count", fontsize=11)
    ax.set_title(title, fontsize=13, pad=12)
    ax.grid(linestyle=":", color="#BDC3C7", alpha=0.6)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()


# ----------------------------------------------------------------------------
# Risk matrix (traditional + probability-weighted side-by-side)
# ----------------------------------------------------------------------------

def make_risk_matrix(
    risks: list[dict],
    output_path: Path | str,
    label_top_n: int = 8,
    title_left: str = "Traditional risk matrix (probability vs mean impact)",
    title_right: str = "Probability-weighted risk matrix (probability vs prob-weighted impact)",
) -> Path:
    """Generate two side-by-side risk matrices.

    Parameters
    ----------
    risks : list of dict
        Each dict requires keys: risk_id, probability (0-1), mean_impact
        (in chosen unit, e.g. days), prob_weighted_impact (probability *
        mean_impact). Optional: color_category for left-panel marker
        colour.
    output_path : Path or str
    label_top_n : int
        Number of top probability-weighted risks to label with their
        risk_id; the rest are unlabelled markers.
    title_left, title_right : str
        Panel titles.

    Returns
    -------
    Path
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    ax_left, ax_right = axes

    if not risks:
        for ax, title in zip(axes, (title_left, title_right)):
            ax.text(
                0.5, 0.5, "(no risks supplied)",
                ha="center", va="center", fontsize=12, color="#7F8C8D",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path.resolve()

    probs = np.array([float(r.get("probability", 0.0)) for r in risks])
    impacts = np.array([float(r.get("mean_impact", 0.0)) for r in risks])
    pw_impacts = np.array([float(r.get("prob_weighted_impact", 0.0)) for r in risks])
    risk_ids = [str(r.get("risk_id", "")) for r in risks]

    # Top-N indices by prob-weighted impact for labelling.
    top_idx = set(int(i) for i in np.argsort(pw_impacts)[::-1][:label_top_n])

    ax_left.scatter(
        impacts, probs * 100.0, s=70, c="#2980B9",
        edgecolor="black", linewidth=0.5, alpha=0.85,
    )
    for i, rid in enumerate(risk_ids):
        if i in top_idx:
            ax_left.annotate(
                rid, (impacts[i], probs[i] * 100.0),
                xytext=(5, 4), textcoords="offset points", fontsize=8,
            )
    ax_left.set_xlabel("Mean impact (days when fired)", fontsize=11)
    ax_left.set_ylabel("Probability (%)", fontsize=11)
    ax_left.set_title(title_left, fontsize=12, pad=10)
    ax_left.grid(linestyle=":", color="#BDC3C7", alpha=0.6)
    ax_left.set_ylim(bottom=0)

    ax_right.scatter(
        pw_impacts, probs * 100.0, s=70, c="#922B21",
        edgecolor="black", linewidth=0.5, alpha=0.85,
    )
    for i, rid in enumerate(risk_ids):
        if i in top_idx:
            ax_right.annotate(
                rid, (pw_impacts[i], probs[i] * 100.0),
                xytext=(5, 4), textcoords="offset points", fontsize=8,
            )
    ax_right.set_xlabel("Probability x mean impact (days)", fontsize=11)
    ax_right.set_ylabel("Probability (%)", fontsize=11)
    ax_right.set_title(title_right, fontsize=12, pad=10)
    ax_right.grid(linestyle=":", color="#BDC3C7", alpha=0.6)
    ax_right.set_ylim(bottom=0)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()


# ----------------------------------------------------------------------------
# Confidence-band waterfall
# ----------------------------------------------------------------------------

def make_methodology_convergence_chart(
    sample: np.ndarray,
    output_path: Path | str,
    percentile: float = 80.0,
    iter_grid: tuple[int, ...] = (1_000, 5_000, 10_000, 20_000, 50_000, 100_000),
    metric_label: str = "integrated P80 cost",
    *,
    seed: int,
) -> Path:
    """Render the Beta-15 §7 convergence diagnostic chart.

    Wraps :func:`src.bootstrap.bootstrap_convergence` for the bootstrap
    CI band and renders an iteration-vs-percentile line chart with a
    95% bootstrap confidence ribbon. Used by Beta-15 Item 2; distinct
    from the legacy cost-side :func:`src.charts.generate_convergence`
    which is hardcoded to P90 labelling.

    Parameters
    ----------
    sample : np.ndarray
        One-dimensional sample array (the cost or integrated array from
        the canonical 100,000-iteration production run). Element i is
        the i-th MC draw of the metric being measured.
    output_path : Path or str
        Where to write the PNG. Parent directory is created if missing.
    percentile : float
        Percentile to track across the iter_grid; default 80 (matches
        the deliverable's recommended-contingency P-level).
    iter_grid : tuple of int
        Iteration counts at which to evaluate the percentile.
        bootstrap_convergence falls back to a single point at n_iter
        when every grid entry exceeds the sample size (e.g. smoke run).
    metric_label : str
        Free-text label that goes into the chart title and y-axis.
    seed : int
        RNG seed for the bootstrap resample: the run's own, so the chart reproduces from the
        seed the run records (SEEDZERO-01). There is no default.

    Returns
    -------
    Path
        Absolute path to the rendered PNG.
    """
    from src.bootstrap import bootstrap_convergence  # local import to keep
                                                      # cold-import light

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    arr = np.asarray(sample).ravel()
    boot = bootstrap_convergence(
        arr, percentile=percentile, iter_grid=iter_grid, seed=seed,
    )

    fig, ax = plt.subplots(figsize=(8, 4.5))

    # Values plotted in $M for cost-axis legibility (matches the rest of
    # the deliverable). Comma the iteration ticks for the same reason.
    x_vals = list(boot["iter_grid"])
    point_m = [float(v) / 1e6 for v in boot["point"]]
    p025_m = [float(v) / 1e6 for v in boot["p025"]]
    p975_m = [float(v) / 1e6 for v in boot["p975"]]

    ax.fill_between(
        x_vals, p025_m, p975_m,
        color="#2980B9", alpha=0.20,
        label=f"95% bootstrap CI (Monte-Carlo error at P{int(percentile)})",
    )
    ax.plot(
        x_vals, point_m,
        marker="o", color="#2980B9", linewidth=2, markersize=7,
        label=f"P{int(percentile)} point estimate",
    )

    # Annotate each grid point with the dollar value.
    for xv, val in zip(x_vals, point_m):
        ax.annotate(
            f"${val:,.1f}M",
            xy=(xv, val), xytext=(0, -16),
            textcoords="offset points", ha="center",
            fontsize=8, color="#555555",
        )

    import matplotlib.ticker as mticker
    ax.xaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f"{int(x / 1000)}k")
    )
    ax.set_xticks(x_vals)
    ax.set_xlabel("Iterations", fontsize=11)
    ax.set_ylabel(f"{metric_label} ($M)", fontsize=11)
    ax.set_title(
        f"Convergence diagnostic: {metric_label} stability vs iteration count",
        fontsize=12, pad=12,
    )
    ax.grid(axis="y", linestyle=":", color="#BDC3C7", alpha=0.6)
    ax.set_axisbelow(True)
    ax.legend(loc="best", fontsize=9)

    ax.text(
        0.99, -0.18,
        "CI band reflects Monte-Carlo simulation error only, does not "
        "reflect uncertainty in inputs or methodology.",
        transform=ax.transAxes, ha="right", va="top",
        fontsize=8, style="italic", color="#555555",
    )

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()


def make_confidence_waterfall(
    components: list[dict],
    title: str,
    output_path: Path | str,
    y_axis_label: str = "Contingency ($M)",
) -> Path:
    """Generate a waterfall chart showing P80 component build-up.

    Parameters
    ----------
    components : list of dict
        Each dict: label (str), value (float, in millions), category
        (str, optional: "base" / "delta" / "total"; controls colour).
    title : str
    output_path : Path or str
    y_axis_label : str

    Returns
    -------
    Path
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(11, 6))

    if not components:
        ax.text(
            0.5, 0.5, "(no components supplied)",
            ha="center", va="center", fontsize=12, color="#7F8C8D",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path.resolve()

    labels = [str(c.get("label", "")) for c in components]
    values = [float(c.get("value", 0.0)) for c in components]
    categories = [str(c.get("category", "delta")) for c in components]

    color_for = {
        "base": "#34495E",
        "delta": "#2980B9",
        "delta_neg": "#E67E22",
        "total": "#922B21",
    }

    running = 0.0
    bottoms = []
    heights = []
    colors = []
    for val, cat in zip(values, categories):
        if cat == "base" or cat == "total":
            bottoms.append(0.0)
            heights.append(val)
            running = val
        else:
            if val >= 0:
                bottoms.append(running)
                heights.append(val)
                colors.append(color_for.get(cat, color_for["delta"]))
                running += val
                continue
            bottoms.append(running + val)
            heights.append(-val)
            colors.append(color_for.get("delta_neg"))
            running += val
            continue
        colors.append(color_for.get(cat, color_for["delta"]))

    x_pos = np.arange(len(labels))
    ax.bar(x_pos, heights, bottom=bottoms, color=colors, edgecolor="black", linewidth=0.5)
    for i, (b, h, val) in enumerate(zip(bottoms, heights, values)):
        ax.text(
            i, b + h + 0.05, f"${val:+.2f}M" if categories[i] == "delta" else f"${val:.2f}M",
            ha="center", va="bottom", fontsize=9,
        )

    ax.set_xticks(x_pos)
    ax.set_xticklabels(labels, rotation=15, ha="right", fontsize=10)
    ax.set_ylabel(y_axis_label, fontsize=11)
    ax.set_title(title, fontsize=13, pad=12)
    ax.grid(axis="y", linestyle=":", color="#BDC3C7", alpha=0.6)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()


# ---------------------------------------------------------------------------
# SR10.B — Float histogram with criticality overlay (Chart 4)
# ---------------------------------------------------------------------------

#: Float bucket boundaries per SR10.B Decision 4 (deep-research note §5.1
#: chart 4). Boundaries are inclusive on the lower side, exclusive on the
#: upper. The first bucket isolates the zero-float (deterministic critical
#: path) cohort; the >180 bucket captures the slack-rich tail.
SR10B_FLOAT_BUCKET_BOUNDARIES: tuple[float, ...] = (
    0.0, 1.0, 6.0, 21.0, 61.0, 181.0, float("inf"),
)

#: Human-readable labels for the float buckets. Order matches
#: :data:`SR10B_FLOAT_BUCKET_BOUNDARIES`.
SR10B_FLOAT_BUCKET_LABELS: tuple[str, ...] = (
    "0",
    "1-5",
    "6-20",
    "21-60",
    "61-180",
    ">180",
)


def make_float_histogram_with_ci_overlay(
    ci_table: pd.DataFrame,
    output_path: Path | str,
    *,
    float_days_col: str = "total_float_mean_days",
    ci_band_col: str = "mode_independent_ci_band",
    float_bucket_boundaries: tuple[float, ...] = SR10B_FLOAT_BUCKET_BOUNDARIES,
    float_bucket_labels: tuple[str, ...] = SR10B_FLOAT_BUCKET_LABELS,
    title: str | None = None,
) -> Path:
    """Stacked-bar float histogram with criticality-band overlay (Chart 4).

    SR10.B Decision 4. Buckets on the x-axis: 0, 1-5, 6-20, 21-60, 61-180,
    >180 working days. Each bar is stacked by the activity's
    Mode-independent CI band (five-band Beta-12 taxonomy:
    ``never / rarely / near / often / always``). Shows the project's
    structural margin and reveals constraint-driven zero-float activities
    that may not be currently mapped to any risk driver.

    Parameters
    ----------
    ci_table : pd.DataFrame
        Extended CI table. Must carry ``float_days_col`` (working-day
        float, float) and ``ci_band_col`` (band string from the
        five-band taxonomy). Rows missing or NaN in either column are
        silently dropped — the chart degrades gracefully when an upstream
        engine omits the float fields.
    output_path : Path | str
    float_days_col : str
        Column name for working-day float values. Default
        ``"total_float_mean_days"``.
    ci_band_col : str
        Column name for the CI band label. Default
        ``"mode_independent_ci_band"`` so the primary view is the
        AACE-correct Mode-independent measurement (Decision 1).
    float_bucket_boundaries, float_bucket_labels
        Bucket boundaries (length N+1) and labels (length N). Defaults
        match the deep-research note §5.1 chart 4 spec; override only
        for unit testing.
    title : str | None
        Override the auto-generated title.

    Returns
    -------
    Path
        Absolute path of the written PNG.

    Notes
    -----
    Reuses :data:`_CI_BAND_DISPLAY_ORDER` and :data:`_CI_BAND_COLORS` so
    the Chart 4 palette stays consistent with the Beta-12 banded
    distribution chart already in the deliverable.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if len(float_bucket_boundaries) != len(float_bucket_labels) + 1:
        raise ValueError(
            "float_bucket_boundaries must have one more entry than "
            f"float_bucket_labels; got {len(float_bucket_boundaries)} vs "
            f"{len(float_bucket_labels)}"
        )

    # Empty-table placeholder render — matches the other chart helpers'
    # graceful degradation pattern.
    n_total = 0 if ci_table is None else len(ci_table)
    if n_total == 0 or float_days_col not in ci_table.columns:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.text(
            0.5, 0.5,
            "No activity-level criticality data available",
            ha="center", va="center", fontsize=12, color="#999999",
        )
        ax.set_axis_off()
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path.resolve()

    # Pull the two columns and drop NaN rows in either. The CI band
    # column defaults to the five-band taxonomy; rows with band values
    # outside that taxonomy are silently treated as "never (<10%)" so
    # the chart degrades cleanly when an upstream engine omits the MI
    # CI for an activity (the engine returns ``None`` and the composer
    # encodes that as 0.0 → "never").
    float_days = pd.to_numeric(ci_table[float_days_col], errors="coerce")
    if ci_band_col in ci_table.columns:
        band_series = ci_table[ci_band_col].astype(str)
    else:
        band_series = pd.Series(
            [_CI_BAND_DISPLAY_ORDER[0]] * n_total, index=ci_table.index,
        )
    mask = float_days.notna() & band_series.notna()
    float_days = float_days[mask].to_numpy(dtype=np.float64)
    bands = band_series[mask].to_numpy(dtype=object)
    n_kept = len(float_days)

    # Assign each activity to its float bucket. The right edge of bucket
    # i is float_bucket_boundaries[i+1] (exclusive), the left edge is
    # float_bucket_boundaries[i] (inclusive). np.digitize with right=False
    # gives bucket index = number of edges <= value, so the first bucket
    # (zero-float exact) needs the >= 0 left-inclusive handling.
    n_buckets = len(float_bucket_labels)
    # digitize returns indices in [1, N]; clip to [0, N-1] for direct
    # array indexing.
    bucket_idx = np.digitize(float_days, float_bucket_boundaries[1:-1], right=False)
    bucket_idx = np.clip(bucket_idx, 0, n_buckets - 1)

    # Per-(bucket, band) counts.
    band_to_idx = {label: i for i, label in enumerate(_CI_BAND_DISPLAY_ORDER)}
    n_bands = len(_CI_BAND_DISPLAY_ORDER)
    counts = np.zeros((n_bands, n_buckets), dtype=np.int64)
    for b_idx, band_label in zip(bucket_idx, bands):
        band_i = band_to_idx.get(str(band_label))
        if band_i is None:
            # Defensive fallback to the lowest band so all activities
            # contribute to the chart even if the upstream column has
            # an unexpected value.
            band_i = 0
        counts[band_i, b_idx] += 1

    fig, ax = plt.subplots(figsize=(10, 5.5))
    x_pos = np.arange(n_buckets)
    bottoms = np.zeros(n_buckets, dtype=np.int64)
    for i, band_label in enumerate(_CI_BAND_DISPLAY_ORDER):
        heights = counts[i]
        ax.bar(
            x_pos, heights, bottom=bottoms,
            color=_CI_BAND_COLORS[band_label],
            edgecolor="white", linewidth=0.6,
            label=band_label,
        )
        bottoms = bottoms + heights

    # Total-count labels above each stack. Beta-19b item 8: the loop covers
    # every non-zero bucket including the rightmost >180 bucket (typically
    # the largest bar). The legend is anchored to upper-left so it does not
    # occlude the rightmost label.
    totals = counts.sum(axis=0)
    y_max = totals.max() if totals.size else 1
    pad = max(1.0, 0.02 * float(y_max))
    for i, total in enumerate(totals):
        if total > 0:
            ax.text(
                x_pos[i], float(total) + pad,
                str(int(total)),
                ha="center", va="bottom", fontsize=10,
            )

    ax.set_xticks(x_pos)
    ax.set_xticklabels(float_bucket_labels, fontsize=10)
    ax.set_xlabel("Total float (working days)", fontsize=11)
    ax.set_ylabel("Number of activities", fontsize=11)

    if title is None:
        title = (
            "Float distribution with Mode-independent CI overlay "
            f"({n_kept} activities)"
        )
    ax.set_title(title, fontsize=13, pad=12)

    ax.grid(axis="y", linestyle=":", color="#BDC3C7", alpha=0.6)
    ax.set_axisbelow(True)
    # Extra headroom (1.25 vs 1.18) so the rightmost label always sits above
    # the bar with clearance from the title.
    ax.set_ylim(0, max(float(y_max) * 1.25, 1.0))
    ax.legend(
        loc="upper left", fontsize=9, framealpha=0.9,
        title="Mode-independent CI band",
    )

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()


# ---------------------------------------------------------------------------
# SR10.B — Sorted Top-N dual criticality bar chart (Chart 1)
# ---------------------------------------------------------------------------

#: Bar fill colour for activities on the deterministic critical path —
#: distinguished from off-CP activities so the reader can see at a glance
#: which top-N activities are structurally critical (not just emergent
#: under the Mode-conditioned or Mode-independent measurement).
_SR10B_CHART1_DETERMINISTIC_CP_COLOR = "#2C3E50"   # navy
_SR10B_CHART1_OFF_CP_COLOR = "#7F8C8D"             # mid-grey

#: Border (edge) colour for activities that appear in only one of the two
#: panels' top-N — the visual signal Decision 1 calls for.
_SR10B_CHART1_PANEL_ONLY_EDGE_COLOR = "#E74C3C"    # red


def make_sorted_criticality_bar_chart(
    ci_table: pd.DataFrame,
    output_path: Path | str,
    *,
    top_n: int = 30,
    mc_column: str = "ci_mode_conditioned",
    mi_column: str = "ci_mode_independent",
    title: str | None = None,
) -> Path:
    """Render the SR10.B Chart 1 dual sorted bar chart.

    Two horizontal-bar panels side-by-side. Left panel sorts activities
    by Mode-conditioned CI descending, right panel by Mode-independent
    CI descending; each shows the top ``top_n``. Activities that appear
    in one panel's top_n but not the other's get a red border to make
    the ranking shift visible. Bar fill colour is by deterministic-CP
    membership (navy for on-CP, grey for off-CP).

    Parameters
    ----------
    ci_table : pd.DataFrame
        Extended CI table from :func:`compute_extended_ci_table`. Must
        carry ``activity_id``, ``activity_name``, ``mc_column``,
        ``mi_column``, ``on_deterministic_cp``.
    output_path : Path | str
    top_n : int
        Top-N cap per panel. Default 30 per Decision 1.
    mc_column / mi_column : str
        Column names for the two CI series. Defaults match
        :func:`compute_extended_ci_table`.
    title : str | None
        Override the auto-generated chart title.

    Returns
    -------
    Path
        Absolute path of the written PNG.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if (
        ci_table is None
        or len(ci_table) == 0
        or mc_column not in ci_table.columns
        or mi_column not in ci_table.columns
    ):
        fig, ax = plt.subplots(figsize=(14, 6))
        ax.text(
            0.5, 0.5,
            "No activity-level criticality data available",
            ha="center", va="center", fontsize=12, color="#999999",
        )
        ax.set_axis_off()
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path.resolve()

    # Defensive: a missing deterministic-CP column is treated as
    # "no activity on the CP" so the chart still renders.
    if "on_deterministic_cp" not in ci_table.columns:
        ci_table = ci_table.assign(on_deterministic_cp=False)

    # Top-N rankings under each measurement. Stable sort + secondary
    # alphabetical sort on activity_id so the rendering is
    # bit-reproducible across runs and platforms.
    mc_sorted = ci_table.sort_values(
        [mc_column, "activity_id"], ascending=[False, True], kind="stable",
    ).head(top_n)
    mi_sorted = ci_table.sort_values(
        [mi_column, "activity_id"], ascending=[False, True], kind="stable",
    ).head(top_n)

    mc_ids = set(mc_sorted["activity_id"].astype(str))
    mi_ids = set(mi_sorted["activity_id"].astype(str))
    only_in_mc = mc_ids - mi_ids
    only_in_mi = mi_ids - mc_ids

    fig, axes = plt.subplots(
        1, 2, figsize=(14, max(6.0, 0.32 * top_n + 1.5)), sharex=True,
    )
    ax_left, ax_right = axes

    def _draw_panel(
        ax: "plt.Axes",
        panel_df: pd.DataFrame,
        value_col: str,
        panel_only_ids: set[str],
        panel_title: str,
    ) -> None:
        # Reverse so the top-ranked bar sits at the top of the panel.
        values = panel_df[value_col].astype(float).to_numpy()[::-1]
        ids = panel_df["activity_id"].astype(str).to_numpy()[::-1]
        names = panel_df["activity_name"].astype(str).to_numpy()[::-1]
        det_cp = panel_df["on_deterministic_cp"].astype(bool).to_numpy()[::-1]

        fill_colors = [
            _SR10B_CHART1_DETERMINISTIC_CP_COLOR if d
            else _SR10B_CHART1_OFF_CP_COLOR
            for d in det_cp
        ]
        edge_colors = [
            _SR10B_CHART1_PANEL_ONLY_EDGE_COLOR
            if a in panel_only_ids else "black"
            for a in ids
        ]
        linewidths = [
            1.6 if a in panel_only_ids else 0.4 for a in ids
        ]
        y_pos = np.arange(len(values))
        ax.barh(
            y_pos, values,
            color=fill_colors,
            edgecolor=edge_colors,
            linewidth=linewidths,
        )

        # Y-tick labels: prefix asterisk for panel-only activities so
        # readers in monochrome printouts can still spot the shift.
        tick_labels = []
        for a, n in zip(ids, names):
            marker = "* " if a in panel_only_ids else "  "
            label = n if len(n) <= 40 else n[:38] + "…"
            tick_labels.append(f"{marker}{a} {label}")
        ax.set_yticks(y_pos)
        ax.set_yticklabels(tick_labels, fontsize=8)
        ax.set_xlim(0, 1.0)
        ax.set_xlabel("Criticality index", fontsize=11)
        ax.set_title(panel_title, fontsize=12, pad=10)
        ax.grid(axis="x", linestyle=":", color="#BDC3C7", alpha=0.6)
        ax.set_axisbelow(True)

        # Inline value labels.
        for y, v in zip(y_pos, values):
            ax.text(
                v + 0.01, y, f"{v:.0%}",
                va="center", ha="left", fontsize=8, color="#2C3E50",
            )

    _draw_panel(
        ax_left, mc_sorted, mc_column, only_in_mc,
        f"Mode-conditioned CI: top {top_n}",
    )
    _draw_panel(
        ax_right, mi_sorted, mi_column, only_in_mi,
        f"Mode-independent CI (AACE 65R-11): top {top_n}",
    )

    if title is None:
        title = (
            f"Top {top_n} criticality activities: dual ranking "
            "(Mode-conditioned vs Mode-independent)"
        )
    fig.suptitle(title, fontsize=13, y=0.995)

    # Legend on the figure (one row, anchored bottom-centre): fill
    # categories + edge marker.
    legend_handles = [
        plt.Rectangle(
            (0, 0), 1, 1,
            color=_SR10B_CHART1_DETERMINISTIC_CP_COLOR,
            label="Deterministic critical path",
        ),
        plt.Rectangle(
            (0, 0), 1, 1,
            color=_SR10B_CHART1_OFF_CP_COLOR,
            label="Off deterministic CP",
        ),
        plt.Rectangle(
            (0, 0), 1, 1,
            facecolor="white",
            edgecolor=_SR10B_CHART1_PANEL_ONLY_EDGE_COLOR,
            linewidth=1.6,
            label="Top-N in this panel only (* in label)",
        ),
    ]
    fig.legend(
        handles=legend_handles, loc="lower center", ncol=3, fontsize=9,
        framealpha=0.9, bbox_to_anchor=(0.5, -0.02),
    )

    fig.tight_layout(rect=(0, 0.04, 1.0, 0.96))
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()


# ---------------------------------------------------------------------------
# SR10.B — Criticality density Gantt by phase (Chart 2)
# ---------------------------------------------------------------------------

def _build_monthly_bin_edges(
    schedule_start: "pd.Timestamp",
    schedule_finish: "pd.Timestamp",
) -> "pd.DatetimeIndex":
    """Monthly bin edges spanning [schedule_start, schedule_finish].

    Bins are month-start anchored; the final bin includes the finish.
    Returns a DatetimeIndex of length N+1 (N bins → N+1 edges) so the
    caller iterates ``zip(edges[:-1], edges[1:])`` to walk bins.
    """
    start_anchor = pd.Timestamp(schedule_start).normalize().replace(day=1)
    end_anchor = (
        (pd.Timestamp(schedule_finish).normalize().replace(day=1))
        + pd.offsets.MonthBegin(1)
    )
    edges = pd.date_range(start_anchor, end_anchor, freq="MS")
    # Guarantee at least two edges (one bin) even for degenerate
    # schedule windows (e.g., zero-duration test fixtures).
    if len(edges) < 2:
        edges = pd.DatetimeIndex(
            [start_anchor, start_anchor + pd.offsets.MonthBegin(1)]
        )
    return edges


def make_criticality_density_gantt(
    ci_table: pd.DataFrame,
    activity_dates: pd.DataFrame,
    phase_map: dict[str, str],
    schedule_start: "pd.Timestamp | str",
    schedule_finish: "pd.Timestamp | str",
    output_path: Path | str,
    *,
    bin_freq: str = "MS",
    use_mode_independent: bool = True,
    mc_column: str = "ci_mode_conditioned",
    mi_column: str = "ci_mode_independent",
    phase_order: tuple[str, ...] | None = None,
    title: str | None = None,
) -> Path:
    """Render the SR10.B Chart 2 criticality density Gantt by phase.

    Primary view (per Decision 1): mean Mode-independent CI across
    activities present in each (phase, month) bin, rendered as a 2D
    heatmap with project time on the x-axis and RBS Level 1 phase on
    the y-axis. A small inset in the bottom-right shows the same heatmap
    under Mode-conditioned CI for methodology transparency.

    Parameters
    ----------
    ci_table : pd.DataFrame
        Extended CI table from :func:`compute_extended_ci_table`. Must
        carry ``activity_id`` and the two CI columns.
    activity_dates : pd.DataFrame
        Columns: ``activity_id`` (str), ``start_date`` (datetime-like),
        ``finish_date`` (datetime-like). Rows missing dates are silently
        dropped — they cannot be placed on the time axis.
    phase_map : dict[str, str]
        ``activity_id → RBS Level 1 phase`` label. Activities missing
        from this map are bucketed into ``"Unmapped"``.
    schedule_start, schedule_finish : Timestamp or str
        Project start / finish; sourced from the project's strawman
        ``Run_Config_Preview`` cells (Decision 3).
    output_path : Path | str
    bin_freq : str
        ``pd.date_range`` frequency. Default ``"MS"`` (month-start) per
        Decision 3. The helper guarantees at least one bin even if the
        schedule window is shorter than the frequency.
    use_mode_independent : bool
        When ``True`` (default), the main heatmap renders Mode-independent
        CI. The inset always shows the *other* measurement for direct
        comparison, regardless of this flag.
    mc_column / mi_column : str
        Column names for the two CI series. Defaults match
        :func:`compute_extended_ci_table`.
    phase_order : tuple[str, ...] | None
        Override the phase row ordering (top-to-bottom). When ``None``,
        phases are sorted alphabetically with ``"Unmapped"`` last —
        keeps the chart deterministic without forcing the caller to
        supply an order.
    title : str | None
        Override the auto-generated chart title.

    Returns
    -------
    Path
        Absolute path of the written PNG.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    schedule_start_ts = pd.Timestamp(schedule_start)
    schedule_finish_ts = pd.Timestamp(schedule_finish)

    if pd.isna(schedule_start_ts) or pd.isna(schedule_finish_ts):
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.text(
            0.5, 0.5,
            "Schedule start/finish missing: Chart 2 not rendered",
            ha="center", va="center", fontsize=12, color="#999999",
        )
        ax.set_axis_off()
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path.resolve()

    # Join activity_dates with the two CI series and the phase map.
    if ci_table is None or len(ci_table) == 0:
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.text(
            0.5, 0.5, "No activity-level criticality data available",
            ha="center", va="center", fontsize=12, color="#999999",
        )
        ax.set_axis_off()
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path.resolve()

    ci_subset = ci_table[["activity_id", mc_column, mi_column]].copy()
    ci_subset["activity_id"] = ci_subset["activity_id"].astype(str)
    if activity_dates is None or len(activity_dates) == 0:
        joined = pd.DataFrame(columns=[
            "activity_id", mc_column, mi_column, "start_date", "finish_date",
        ])
    else:
        dates = activity_dates[["activity_id", "start_date", "finish_date"]].copy()
        dates["activity_id"] = dates["activity_id"].astype(str)
        dates["start_date"] = pd.to_datetime(dates["start_date"], errors="coerce")
        dates["finish_date"] = pd.to_datetime(dates["finish_date"], errors="coerce")
        joined = ci_subset.merge(dates, on="activity_id", how="inner")
        joined = joined.dropna(subset=["start_date", "finish_date"])

    if len(joined) == 0:
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.text(
            0.5, 0.5,
            "No activities with dated bindings: Chart 2 placeholder",
            ha="center", va="center", fontsize=12, color="#999999",
        )
        ax.set_axis_off()
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path.resolve()

    joined["phase"] = joined["activity_id"].map(
        lambda a: str(phase_map.get(a, "Unmapped"))
    )

    if phase_order is None:
        phases = sorted({p for p in joined["phase"] if p != "Unmapped"})
        if (joined["phase"] == "Unmapped").any():
            phases = phases + ["Unmapped"]
        phase_row_order = tuple(phases) if phases else ("Unmapped",)
    else:
        phase_row_order = tuple(phase_order)

    # Monthly bin edges. ``bin_freq`` falls back to month-start when the
    # caller hands a deprecated alias.
    if bin_freq.upper() in ("M", "MS"):
        edges = _build_monthly_bin_edges(schedule_start_ts, schedule_finish_ts)
    else:
        edges = pd.date_range(
            schedule_start_ts, schedule_finish_ts, freq=bin_freq,
        )
        if len(edges) < 2:
            edges = pd.DatetimeIndex([schedule_start_ts, schedule_finish_ts])

    n_phases = len(phase_row_order)
    n_bins = len(edges) - 1

    def _build_heatmap(value_col: str) -> np.ndarray:
        """For each (phase, bin) cell compute mean CI of overlapping activities.

        Returns an ``(n_phases, n_bins)`` float64 array. Cells with no
        overlapping activity are NaN so the imshow renders them as the
        colormap's "bad" colour (a clean visual placeholder).
        """
        grid = np.full((n_phases, n_bins), np.nan, dtype=np.float64)
        if n_bins == 0 or n_phases == 0:
            return grid
        sums = np.zeros_like(grid)
        counts = np.zeros_like(grid)
        phase_to_row = {p: i for i, p in enumerate(phase_row_order)}
        for _, row in joined.iterrows():
            phase = str(row["phase"])
            if phase not in phase_to_row:
                continue
            r = phase_to_row[phase]
            start = row["start_date"]
            finish = row["finish_date"]
            ci_val = float(row[value_col])
            # Iterate the bins that overlap [start, finish].
            for j in range(n_bins):
                bin_lo, bin_hi = edges[j], edges[j + 1]
                if finish < bin_lo or start >= bin_hi:
                    continue
                sums[r, j] += ci_val
                counts[r, j] += 1.0
        mask = counts > 0
        grid[mask] = sums[mask] / counts[mask]
        return grid

    # SR14b D6: Chart 2 redesigned from "MI primary + MC embedded inset"
    # to two stacked vertical panels (MI top 60% / MC bottom 40%, shared
    # x-axis), per Director sign-off 2026-05-15. Reads Steve's
    # accessibility critique: the embedded inset was too small to be
    # readable; vertical stacking gives both panels their own readable
    # surface. Underlying data unchanged — same _build_heatmap helper,
    # same viridis colormap, same density binning. Presentation only.
    mi_grid = _build_heatmap(mi_column)
    mc_grid = _build_heatmap(mc_column)

    # SR17 Workstream D — sequential chart cmap replaces viridis here. The
    # white-to-navy ramp preserves the same density-encoding semantics
    # (low → light, high → dark) and matches the rest of the deliverable.
    from src.final.chart_theme import get_sequential_cmap
    cmap = get_sequential_cmap().copy()
    cmap.set_bad(color="#ECEFF1")  # cool grey for empty cells

    # Figure: 10 inches wide × 14 inches tall (D6 spec). The 60/40
    # height split gives the MI panel ~7.6 inches and the MC panel
    # ~5.6 inches with a 0.4-inch gap and ~0.4-inch top/bottom margins
    # (gridspec hspace handles the gap).
    fig = plt.figure(figsize=(10.0, 14.0))
    gs = fig.add_gridspec(
        nrows=2,
        ncols=1,
        height_ratios=[0.60, 0.40],
        hspace=0.32,  # ~0.4-inch gap between panels (D6 spec)
        left=0.13,
        right=0.92,
        top=0.94,
        bottom=0.07,
    )
    ax_mi = fig.add_subplot(gs[0, 0])
    ax_mc = fig.add_subplot(gs[1, 0], sharex=ax_mi)

    # SR18 Item 1: Y-axis tick labels render through the shared
    # rbs_mapping.resolve_rbs_l1_label so PROJWBS numeric short-names
    # ("01", "10", "20", ...) display as discipline names ("Key Milestones",
    # "Power Station Sitewide", "Power Island", ...). The underlying
    # phase_row_order keys stay as raw short-names so the grid lookup and
    # phase_to_row mapping in _build_heatmap continue unchanged; only the
    # displayed tick labels are transformed. Unknown codes pass through.
    from src.final.rbs_mapping import resolve_rbs_l1_label
    y_tick_labels = [resolve_rbs_l1_label(p) for p in phase_row_order]

    # MI panel (top, ~60% of figure height).
    im_mi = ax_mi.imshow(
        mi_grid, aspect="auto", origin="lower", cmap=cmap,
        vmin=0.0, vmax=1.0,
    )
    ax_mi.set_yticks(np.arange(n_phases))
    ax_mi.set_yticklabels(y_tick_labels, fontsize=10)
    ax_mi.set_ylabel("RBS Level 1 phase", fontsize=11)
    ax_mi.set_title(
        "AACE Mode-independent measurement\n"
        "Mode-independent CI (AACE 65R-11)",
        fontsize=12, pad=10, loc="left",
    )

    # MC panel (bottom, ~40% of figure height; shared x-axis with MI).
    im_mc = ax_mc.imshow(
        mc_grid, aspect="auto", origin="lower", cmap=cmap,
        vmin=0.0, vmax=1.0,
    )
    ax_mc.set_yticks(np.arange(n_phases))
    ax_mc.set_yticklabels(y_tick_labels, fontsize=10)
    ax_mc.set_ylabel("RBS Level 1 phase", fontsize=11)
    ax_mc.set_title(
        "Mode-conditioned measurement (current Stage 2.5 baseline)\n"
        "Mode-conditioned CI",
        fontsize=12, pad=10, loc="left",
    )

    # Shared x-axis at month-start positions; place labels only on the
    # bottom panel so the dual-stack reads naturally.
    max_xticks = 12
    stride = max(1, n_bins // max_xticks)
    tick_positions = np.arange(0, n_bins, stride)
    tick_labels = [edges[i].strftime("%b %Y") for i in tick_positions]
    ax_mc.set_xticks(tick_positions)
    ax_mc.set_xticklabels(tick_labels, rotation=45, ha="right", fontsize=9)
    ax_mc.set_xlabel("Project month", fontsize=11)
    plt.setp(ax_mi.get_xticklabels(), visible=False)

    # Shared colorbar on the right of the figure — applies to both
    # panels by construction (both use the same vmin/vmax/cmap).
    cbar_ax = fig.add_axes((0.94, 0.10, 0.018, 0.80))
    cbar = fig.colorbar(im_mi, cax=cbar_ax)
    cbar.set_label("Mean CI per (phase, month) bin", fontsize=10)

    # Suptitle override falls through to the per-panel titles above when
    # the caller doesn't supply one. The legacy ``title`` arg is still
    # accepted for backwards compat; when supplied it becomes the
    # figure-level suptitle.
    if title is not None:
        fig.suptitle(title, fontsize=13, y=0.985)

    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()


# ---------------------------------------------------------------------------
# Beta-12 — activity-level criticality distribution chart
# ---------------------------------------------------------------------------

# CI band constants (_CI_BAND_DISPLAY_ORDER, _CI_BAND_COLORS) live at the top
# of this module alongside the other palette constants; the SR10.B chart
# suite shares them.


def make_ci_distribution_chart(
    ci_table: pd.DataFrame,
    output_path: Path | str,
    *,
    n_iter: int | None = None,
    title: str | None = None,
) -> Path:
    """Banded bar chart of activity counts in the five CI reporting bands.

    Beta-12 §3.4 — the headline visual indicator for the activity-level
    criticality section. Bimodal shape (most bars at "never" and
    "always") signals a stable deterministic critical path; flat shape
    (substantial bars in "rarely" / "near" / "often") signals path
    crossover risk and contingency doing more work than the
    deterministic schedule alone suggests.

    Parameters
    ----------
    ci_table : pd.DataFrame
        Output of :func:`src.final.composer.compute_criticality_table`.
        Must carry a ``ci_band`` column with values from the five-band
        taxonomy.
    output_path : Path | str
        PNG write target. Parent directory is created if missing.
    n_iter : int | None
        Iteration count, used in the chart title when provided. ``None``
        falls back to a generic title.
    title : str | None
        Override the auto-generated title entirely. When ``None``,
        renders ``"Activity criticality across {n_iter:,} simulated
        futures"``.

    Returns
    -------
    Path
        Absolute path of the written PNG.

    Notes
    -----
    Each bar is annotated with the count and percentage. No legend —
    band labels on the x-axis are self-explanatory and the colour code
    (greys → amber → reds) is intuitive without a legend.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if ci_table is None or len(ci_table) == 0:
        # Render a placeholder rather than raising; aligns with the
        # other chart helpers that handle empty inputs gracefully.
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.text(
            0.5, 0.5,
            "No activity-level criticality data available",
            ha="center", va="center", fontsize=12, color="#999999",
        )
        ax.set_axis_off()
        fig.tight_layout()
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path.resolve()

    counts = [
        int((ci_table["ci_band"] == band).sum())
        for band in _CI_BAND_DISPLAY_ORDER
    ]
    n_total = sum(counts)
    pcts = [c / n_total if n_total else 0.0 for c in counts]
    colors = [_CI_BAND_COLORS[band] for band in _CI_BAND_DISPLAY_ORDER]

    fig, ax = plt.subplots(figsize=(10, 5))
    x_pos = np.arange(len(_CI_BAND_DISPLAY_ORDER))
    bars = ax.bar(x_pos, counts, color=colors, edgecolor="white", linewidth=1.5)

    # Annotate each bar with count + percentage.
    y_max = max(counts) if counts else 1
    pad = max(1.0, 0.02 * float(y_max))
    for bar, count, pct in zip(bars, counts, pcts):
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            height + pad,
            f"{count}\n({pct:.0%})",
            ha="center", va="bottom",
            fontsize=10,
        )

    ax.set_xticks(x_pos)
    ax.set_xticklabels(_CI_BAND_DISPLAY_ORDER, fontsize=10)
    ax.set_ylabel("Number of activities", fontsize=11)

    if title is None:
        if n_iter is not None and n_iter > 0:
            title = f"Activity criticality across {n_iter:,} simulated futures"
        else:
            title = "Activity criticality"
    ax.set_title(title, fontsize=13, pad=12)

    ax.grid(axis="y", linestyle=":", color="#BDC3C7", alpha=0.6)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(y_max * 1.15, 1.0))

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path.resolve()
