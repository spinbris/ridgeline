"""Tests for SR-S3-Beta-18 composer hotfix.

Covers the five composer-only fixes commissioned 13 May 2026 after the
reviewer pass over ``sra_final_report_PROD_Hybrid_2026-05-13.html``:

1. Auto-mapper audit interpretation paragraph
   (:func:`src.final.executive_summary.format_auto_mapper_audit_interpretation`).
2. Action-implications placeholder swap + banner
   (:func:`src.final.composer._build_treatment_roi_table` +
   ``composed["page6_action_implications"]["banner"]``).
3. Pandas truncation fix on the action-implications HTML render.
4. S-curve drop-lines + per-percentile value labels
   (:func:`src.final.charts.make_s_curve` ``value_label_fmt`` param).
5. Calendar caveat inline under each activity-level table
   (``composed["page4b_criticality"]["near_critical_table_caveat"]`` and
   ``["risk_to_activity_bridge_caveat"]``).

The five fast unit tests stand alone with synthetic inputs — no engine
run required. The slow end-to-end test that rendered ``final_runner.ipynb``
against the retired register could only ever skip (SKIPDEAD-01); SNAPSHOTCUT-01
retired it (Director, 11/10/2026).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import matplotlib

matplotlib.use("Agg")  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.text import Annotation  # noqa: E402

from src.final import charts, commentary_text, composer  # noqa: E402
from src.final.composer import _build_treatment_roi_table  # noqa: E402
from src.final.executive_summary import (  # noqa: E402
    format_auto_mapper_audit_interpretation,
)


# ---------------------------------------------------------------------------
# §1 — Auto-mapper interpretation
# ---------------------------------------------------------------------------

def test_auto_mapper_interpretation_renders_with_p80_values() -> None:
    """Formatter classifies over-bound risks, names them, and frames the
    Stage 3 Beta P80 vs Stage 2.5 contrast as an auto-mapper artefact.

    Inputs mirror the 13 May audit table: 5 of 8 risks bind to
    <n>-<m> activities (R013, R015.1, R016.1, R016.2, R026.1) and 3 bind
    to ≤94 (R017.1, R067, R090). The over-bound fraction floor cleanly
    separates the two populations.
    """
    audit_table = [
        {"risk_id": "R013", "activity_count": 598},
        {"risk_id": "R015.1", "activity_count": 607},
        {"risk_id": "R016.1", "activity_count": 598},
        {"risk_id": "R016.2", "activity_count": 471},
        {"risk_id": "R017.1", "activity_count": 94},
        {"risk_id": "R026.1", "activity_count": 598},
        {"risk_id": "R067", "activity_count": 53},
        {"risk_id": "R090", "activity_count": 53},
    ]

    out = format_auto_mapper_audit_interpretation(
        audit_table=audit_table,
        stage25_p80_days=18.3,
        stage3_p80_days=2223.1,
        # PRESENT-01 (D-5): the denominator is the run's activity count, stated not defaulted.
        schedule_size=2025,
    )

    # Over-bound risks named, low-bound risks excluded.
    for over_bound in ("R013", "R015.1", "R016.1", "R016.2", "R026.1"):
        assert over_bound in out, f"missing over-bound risk {over_bound}"
    # The brief originally mis-named R090 as over-bound. R090 has 53
    # activities (under the floor); it must NOT appear in the over-bound
    # list. We assert on the substring around the named list to avoid
    # accidentally matching a hypothetical mention elsewhere in the copy.
    over_bound_clause = out.split("are currently bound to between")[0]
    assert "R090" not in over_bound_clause, "R090 wrongly listed as over-bound"
    assert "R017.1" not in over_bound_clause
    assert "R067" not in over_bound_clause

    # Activity-count range as observed (<n>-<m>).
    assert "between 471 and 607" in out

    # Headline numbers — Stage 3 P80 and Stage 2.5 P80, both injected
    # dynamically, not hardcoded in the template.
    assert "2223.1 days" in out
    assert "18.3 days" in out

    # Methodology framing — "artefact" not "model failure"; workshop
    # validation named as the remediation path.
    assert "artefact" in out
    assert "Workshop validation" in out


def test_auto_mapper_interpretation_empty_audit_returns_empty() -> None:
    """An empty / missing audit table degrades to empty string rather
    than raising. Belt-and-braces for the v3.6.1 zero-expansion case
    where every Time=Yes risk binds to zero activities."""
    assert format_auto_mapper_audit_interpretation(
        audit_table=None, stage25_p80_days=0.0, stage3_p80_days=0.0,
    ) == ""
    assert format_auto_mapper_audit_interpretation(
        audit_table=[], stage25_p80_days=0.0, stage3_p80_days=0.0,
    ) == ""


# ---------------------------------------------------------------------------
# §2 — Action-implications placeholder + banner
# ---------------------------------------------------------------------------

def test_action_implications_placeholder_text() -> None:
    """treatment_roi_table rows must show "Workshop input required" in
    both the Illustrative-treatment and Estimated-reduction columns,
    and the banner must carry the illustrative-only framing."""
    cost_drivers = [
        {"risk_id": "R067", "value": 1.64, "metric_name": "P80"},
        {"risk_id": "R013", "value": 1.36, "metric_name": "P80"},
        {"risk_id": "R055", "value": 0.79, "metric_name": "P80"},
    ]
    schedule_drivers = [
        {"risk_id": "R067", "prob_weighted_mean_days": 10.20},
        {"risk_id": "R013", "prob_weighted_mean_days": 1.83},
        {"risk_id": "R016.1", "prob_weighted_mean_days": 1.78},
    ]
    df = _build_treatment_roi_table(
        cost_drivers=cost_drivers,
        schedule_drivers=schedule_drivers,
        headline_metric="P80",
    )

    assert len(df) == 6
    placeholder = commentary_text.ACTION_IMPLICATIONS_PLACEHOLDER_CELL
    assert placeholder == "Workshop input required"
    assert all(df["Illustrative treatment"] == placeholder)
    assert all(df["Estimated reduction"] == placeholder)
    # Numeric "Current contribution" column still carries the live
    # value — only the workshop-input columns are placeholders.
    assert "$1.64M" in df.loc[0, "Current contribution"]
    assert "10.20 days" in df.loc[3, "Current contribution"]

    # The "~30% if effective" copy must not appear anywhere in the
    # table: that was the prior hardcoded placeholder.
    for col in df.columns:
        for val in df[col].astype(str):
            assert "30% if effective" not in val, (
                f"legacy '~30% if effective' copy leaked into {col}: {val!r}"
            )

    banner = commentary_text.ACTION_IMPLICATIONS_PLACEHOLDER_BANNER
    assert banner.startswith("**Illustrative only")
    assert "workshop input" in banner.lower()


# ---------------------------------------------------------------------------
# §3 — Pandas truncation fix
# ---------------------------------------------------------------------------

def test_action_implications_no_pandas_truncation() -> None:
    """Long treatment-description strings render fully under
    pd.option_context('display.max_colwidth', None) — no literal '...'
    appears in the HTML. The repo's pd._repr_html_ default truncates at
    50 chars; the notebook's render path explicitly opts out via
    option_context, and the explicit to_html() call.
    """
    long_desc = "A" * 200
    df = pd.DataFrame([{
        "Risk": "R001",
        "Type": "Cost",
        "Current contribution": "$1.00M (P80)",
        "Illustrative treatment": long_desc,
        "Estimated reduction": "B" * 200,
    }])

    # 1) Reproduce the prior truncation bug under default options to
    #    confirm the test guards against a real regression.
    assert "..." in df._repr_html_()

    # 2) Notebook render path: explicit to_html() inside option_context.
    with pd.option_context("display.max_colwidth", None):
        html = df.to_html(index=False, classes="action-implications", border=0)
    assert "..." not in html
    assert long_desc in html
    assert "B" * 200 in html
    # CSS table class must be applied so the inline rule can target it.
    assert 'class="dataframe action-implications"' in html or \
           'class="action-implications dataframe"' in html


# ---------------------------------------------------------------------------
# §4 — Cost S-curve drop-lines + per-percentile value labels
# ---------------------------------------------------------------------------

def _render_s_curve_and_capture(
    distributions: dict[str, np.ndarray],
    *,
    value_label_fmt: str | None,
    tmp_path: Path,
) -> dict:
    """Render an S-curve and capture the axes children (lines +
    annotations) before plt.close fires.
    """
    captured: dict = {"lines": [], "annotations": []}
    orig_close = plt.close

    def _capture_close(fig):
        if hasattr(fig, "axes") and fig.axes:
            ax = fig.axes[0]
            captured["lines"] = [
                (line.get_xdata(), line.get_ydata(), line.get_linestyle())
                for line in ax.lines
            ]
            captured["annotations"] = [
                (t.get_text(), t.xy)
                for t in ax.texts
                if isinstance(t, Annotation)
            ]
        orig_close(fig)

    out = tmp_path / "scurve_beta18.png"
    with mock.patch("matplotlib.pyplot.close", side_effect=_capture_close):
        charts.make_s_curve(
            distributions=distributions,
            percentile_markers=[50, 80, 90, 95],
            title="Beta-18 drop-line check",
            output_path=out,
            value_label_fmt=value_label_fmt,
        )
    return captured


def test_cost_s_curve_drop_lines_present(tmp_path: Path) -> None:
    """When value_label_fmt is supplied, the S-curve must render four
    vertical drop-lines (one per percentile, dotted, from y=0 to the
    P-level) AND four annotations (one per percentile, formatted via
    value_label_fmt). When value_label_fmt is None, neither is
    rendered — the prior behaviour is preserved.
    """
    rng = np.random.default_rng(42)
    samples = rng.lognormal(mean=2.5, sigma=0.4, size=10_000)

    # Beta-18 path: drop-lines + dollar labels.
    captured = _render_s_curve_and_capture(
        {"Cost outturn": samples},
        value_label_fmt="${value:.2f}M",
        tmp_path=tmp_path,
    )

    # Identify drop-lines: two-point segments anchored at y=0.
    drop_lines = [
        (xs, ys, ls) for xs, ys, ls in captured["lines"]
        if len(xs) == 2 and abs(float(ys[0])) < 1e-9
    ]
    assert len(drop_lines) == 4, (
        f"expected 4 drop-lines (one per percentile), got {len(drop_lines)}"
    )
    # Each drop-line lands at its corresponding P-level on top.
    drop_top_ys = sorted(float(ys[1]) for _, ys, _ in drop_lines)
    assert drop_top_ys == [50.0, 80.0, 90.0, 95.0]
    # Drop-line style is dotted to match the existing P-level reference
    # line convention.
    assert all(ls == ":" for _, _, ls in drop_lines)

    # Annotations: 4 dollar-formatted labels.
    assert len(captured["annotations"]) == 4
    texts = [t for t, _ in captured["annotations"]]
    for text in texts:
        assert text.startswith("$") and text.endswith("M"), (
            f"annotation {text!r} is not dollar-formatted"
        )

    # Backwards-compat: value_label_fmt=None must skip both renders.
    captured_default = _render_s_curve_and_capture(
        {"Cost outturn": samples},
        value_label_fmt=None,
        tmp_path=tmp_path,
    )
    drop_lines_default = [
        (xs, ys, ls) for xs, ys, ls in captured_default["lines"]
        if len(xs) == 2 and abs(float(ys[0])) < 1e-9
    ]
    assert drop_lines_default == []
    assert captured_default["annotations"] == []


def test_schedule_s_curve_drop_lines_use_day_format(tmp_path: Path) -> None:
    """Schedule S-curve uses ``{value:.1f}d`` formatter — confirms the
    same machinery works for both cost (dollar) and schedule (day)
    surfaces.
    """
    rng = np.random.default_rng(7)
    samples = rng.lognormal(mean=2.0, sigma=0.5, size=5_000)

    captured = _render_s_curve_and_capture(
        {"Schedule slip": samples},
        value_label_fmt="{value:.1f}d",
        tmp_path=tmp_path,
    )
    assert len(captured["annotations"]) == 4
    for text, _ in captured["annotations"]:
        assert text.endswith("d"), f"day-format annotation expected, got {text!r}"


# ---------------------------------------------------------------------------
# §5 — Calendar caveat inline under criticality tables
# ---------------------------------------------------------------------------

def test_calendar_caveat_inline_under_both_tables() -> None:
    """``_apply_criticality_keys`` must surface the calendar caveat as
    a sibling key under both the near-critical table and the
    risk-to-activity bridge, so the notebook + word_generator can
    render it inline at each table site.
    """
    # Build a minimal Stage-3 result stub containing the schedule_result
    # surface _apply_criticality_keys reads (criticality_index,
    # total_float_*, deterministic_critical_path, n_iter,
    # activity_ids), and a risk-drivers dict whose RiskDriver-shape
    # stubs carry affected_activity_ids the bridge join can consume.
    activity_ids = ("a1", "a2", "a3", "a4", "a5")
    ci_values = {"a1": 0.05, "a2": 0.25, "a3": 0.55, "a4": 0.85, "a5": 0.95}
    schedule_result = SimpleNamespace(
        activity_ids=activity_ids,
        criticality_index=ci_values,
        total_float_mean_hours=np.array([100.0, 50.0, 30.0, 10.0, 0.0],
                                        dtype=np.float32),
        total_float_std_hours=np.array([5.0, 4.0, 3.0, 2.0, 1.0],
                                       dtype=np.float32),
        deterministic_critical_path=("a5",),
        n_iter=1000,
    )
    risk_drivers = {
        "R001": SimpleNamespace(
            risk_id="R001", affected_activity_ids=("a2", "a3"),
        ),
    }
    stage3_beta_result = {
        "schedule_result": schedule_result,
        "risk_drivers": risk_drivers,
        # PRESENT-01 (D-5): the over-bind denominator is the run's own activity count.
        "activity_count": 120,
    }

    composed: dict = {
        "page4_schedule_drivers": {
            "drivers_table": [{"Risk": "R001"}],
        },
    }
    composer._apply_criticality_keys(
        composed, stage3_beta_result, chart_output_dir=None,
    )

    p4b = composed.get("page4b_criticality")
    assert p4b is not None, "_apply_criticality_keys did not populate page4b"

    # SR18 Item 3: root-cause fix for the duplicate caveat-lead
    # regression at HTML lines 8690 + 8893. The Beta-18 §5 intent
    # ("inline caveat under each activity-level table") rendered the
    # same string twice in §10.5 close enough to read as duplication.
    # Fix: first table (near-critical-activities) keeps the inline
    # caveat; second table (risk-to-activity bridge) is set to empty
    # so the notebook render guard short-circuits. The caveat reads
    # once and the bridge table inherits by section context.
    inline_caveat = commentary_text.CRITICALITY_CALENDAR_CAVEAT_INLINE
    assert p4b.get("near_critical_table_caveat") == inline_caveat
    assert p4b.get("risk_to_activity_bridge_caveat") == ""

    # The full caveat block (the "Inputs that drive criticality
    # accuracy" subsection) must stay unchanged.
    assert p4b.get("input_dependencies_caveat") == \
        commentary_text.CRITICALITY_INPUT_DEPENDENCIES_CAVEAT
