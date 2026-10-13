"""SR17 Workstream D — chart theme.

Replaces matplotlib's default viridis colourmap and prop_cycle with a
brand-coherent palette per the SR17 brief §6.2 (Director D8.3
locked). One config module applied uniformly across all chart-
generating code in the deliverable.

Four palettes:

* **Sequential** (heatmaps, criticality density Gantt, sensitivity
  tables): white-through-deep-navy single-hue ramp. Replaces viridis as
  the default ``image.cmap``.
* **Categorical** (tornado bars, distribution overlays, risk-matrix
  bubbles): five-colour brand palette used in priority order. Wired
  into ``axes.prop_cycle``.
* **Diverging** (variance from baseline, gain/pain, residual vs
  inherent): red-side and blue-side anchored at neutral grey,
  desaturated for print readability.
* **Reference percentile lines** (P50 / P80 / P90 / P95 verticals on
  S-curves and histograms): consistent colour + linestyle across every
  chart that draws them.

Usage::

    from src.final.chart_theme import apply_theme
    apply_theme()  # call once before any plotting

Apply at the top of every chart-generating module. The function is
idempotent (rcParams writes overwrite cleanly) and safe to call multiple
times. Hex codes are Director-locked per SR17 §6.2; if future formal
brand hex codes arrive, swap them in PALETTES /
PERCENTILE_LINES only and every chart picks up the change.
"""
from __future__ import annotations

from typing import Final

import matplotlib as mpl
from matplotlib.colors import LinearSegmentedColormap


SEQUENTIAL_HEX: Final[tuple[str, ...]] = (
    "#FFFFFF",
    "#D0DCE8",
    "#6F8FB0",
    "#2E5C8A",
    "#1F3A5F",
)

CATEGORICAL_HEX: Final[tuple[str, ...]] = (
    "#1F3A5F",
    "#D4793A",
    "#2E5C8A",
    "#6B6B6B",
    "#8C2929",
)

DIVERGING_HEX: Final[tuple[str, ...]] = (
    "#8C2929",
    "#C77D7D",
    "#BFBFBF",
    "#6F8FB0",
    "#1F3A5F",
)

PALETTES: Final[dict[str, tuple[str, ...]]] = {
    "sequential": SEQUENTIAL_HEX,
    "categorical": CATEGORICAL_HEX,
    "diverging": DIVERGING_HEX,
}

PERCENTILE_LINES: Final[dict[str, dict[str, object]]] = {
    "p50": {"color": "#BFBFBF", "linestyle": "--", "linewidth": 1.0},
    "p80": {"color": "#1F3A5F", "linestyle": "-",  "linewidth": 1.5},
    "p90": {"color": "#D4793A", "linestyle": "-",  "linewidth": 1.0},
    "p95": {"color": "#8C2929", "linestyle": "-",  "linewidth": 1.0},
}


_SEQUENTIAL_CMAP_NAME = "chart_sequential"
_DIVERGING_CMAP_NAME = "chart_diverging"


def _ensure_registered_cmap(name: str, hex_list: tuple[str, ...]) -> LinearSegmentedColormap:
    """Register a colormap derived from hex stops if not already present.

    Matplotlib raises ``ValueError`` on duplicate registration; the
    idempotent check makes ``apply_theme`` safe to call multiple times
    (e.g. once per module, once per notebook cell re-run).
    """
    try:
        existing = mpl.colormaps[name]
    except KeyError:
        cmap = LinearSegmentedColormap.from_list(name, list(hex_list), N=256)
        mpl.colormaps.register(cmap=cmap, name=name)
        return cmap
    if isinstance(existing, LinearSegmentedColormap):
        return existing
    return existing  # type: ignore[return-value]


def get_sequential_cmap() -> LinearSegmentedColormap:
    return _ensure_registered_cmap(_SEQUENTIAL_CMAP_NAME, SEQUENTIAL_HEX)


def get_diverging_cmap() -> LinearSegmentedColormap:
    return _ensure_registered_cmap(_DIVERGING_CMAP_NAME, DIVERGING_HEX)


def apply_theme() -> None:
    """Apply the chart theme to matplotlib rcParams.

    Sets categorical prop_cycle, replaces the default viridis cmap with
    the sequential ramp, dials axis/grid/font defaults to neutral
    greys suitable for docx / PDF rendering. Idempotent.
    """
    seq_cmap = get_sequential_cmap()
    get_diverging_cmap()

    mpl.rcParams.update({
        "axes.prop_cycle": mpl.cycler(color=list(CATEGORICAL_HEX)),
        "image.cmap": seq_cmap.name,
        "axes.grid": True,
        "grid.color": "#D0D0D0",
        "grid.alpha": 0.6,
        "grid.linewidth": 0.6,
        "axes.edgecolor": "#6B6B6B",
        "axes.labelcolor": "#1F1F1F",
        "axes.titlecolor": "#1F3A5F",
        "axes.titleweight": "bold",
        "xtick.color": "#6B6B6B",
        "ytick.color": "#6B6B6B",
        "xtick.labelcolor": "#1F1F1F",
        "ytick.labelcolor": "#1F1F1F",
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "DejaVu Sans", "Liberation Sans", "sans-serif"],
        "axes.titlesize": 14,
        "axes.labelsize": 11,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "figure.titlesize": 14,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    })
