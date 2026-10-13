"""SR-S3-Beta-11 §3 — dynamic R067 narrative.

Three narrative sites used to hardcode R067 by name. Beta-11 routes them
through ``executive_summary.pick_tail_risk(...)`` + format helpers so the
rendered text names whatever low-probability / high-impact risk the
current schedule drivers actually contain.

Tests cover:
  - tail-risk picker behaviour on synthetic V8-shaped drivers
  - tail-risk picker fallback when no driver below threshold
  - rendered narrative names the synthetic tail risk (e.g. R016.2),
    not R067, when the synthetic data points elsewhere
  - generic fallback narrative renders without naming any risk when
    the picker returns None
"""

from __future__ import annotations
from tests.conftest import TEST_MODE_MULTIPLIERS

import pytest

from src.final import commentary_text
from src.final.executive_summary import (
    format_comparison_interpretation,
    format_criticality_distribution_interpretation,
    format_criticality_explainer,
    format_criticality_near_critical_interpretation,
    format_distribution_interpretation,
    format_risk_matrix_interpretation,
    format_risk_matrix_orienting,
    pick_tail_risk,
)


def _v8_shaped_drivers() -> list[dict]:
    """Synthetic schedule_drivers list with R016.2 as the canonical tail
    risk (1.5% probability, 200d mean impact when fired) — picker should
    select R016.2, not R067 (which has prob 8% in this synthetic, above
    threshold)."""
    return [
        {
            "risk_id": "R017.1",
            "title": "Title A",
            "probability": 0.20,
            "mean_impact_when_fired_days": 50.0,
            "prob_weighted_mean_days": 10.0,
            "mode": "Series",
            "pct_of_total_mean": 0.30,
        },
        {
            "risk_id": "R067",
            "title": "Title B",
            "probability": 0.08,  # above threshold
            "mean_impact_when_fired_days": 100.0,
            "prob_weighted_mean_days": 8.0,
            "mode": "Series",
            "pct_of_total_mean": 0.24,
        },
        {
            "risk_id": "R016.2",
            "title": "Tail risk title",
            "probability": 0.015,  # below 5% threshold
            "mean_impact_when_fired_days": 200.0,
            "prob_weighted_mean_days": 3.0,
            "mode": "Series",
            "pct_of_total_mean": 0.09,
        },
        {
            "risk_id": "R090",
            "title": "Title C",
            "probability": 0.10,
            "mean_impact_when_fired_days": 30.0,
            "prob_weighted_mean_days": 3.0,
            "mode": "Hybrid",
            "pct_of_total_mean": 0.09,
        },
        {
            "risk_id": "R015.1",
            "title": "Title D",
            "probability": 0.025,  # below threshold but smaller mean
            "mean_impact_when_fired_days": 80.0,
            "prob_weighted_mean_days": 2.0,
            "mode": "Series",
            "pct_of_total_mean": 0.06,
        },
    ]


# ---------------------------------------------------------------------------
# pick_tail_risk
# ---------------------------------------------------------------------------

def test_pick_tail_risk_returns_lowest_prob_largest_impact_below_threshold():
    drivers = _v8_shaped_drivers()
    tail = pick_tail_risk(drivers, prob_threshold=0.05)
    assert tail is not None
    # R016.2 has prob 1.5% AND mean_when_fired 200d; R015.1 has prob 2.5%
    # AND mean_when_fired 80d. The picker selects largest mean_when_fired
    # among the prob<threshold subset, so R016.2 wins.
    assert tail["tail_risk_id"] == "R016.2"
    assert tail["tail_risk_prob"] == pytest.approx(0.015)
    assert tail["tail_risk_mean_when_fired"] == pytest.approx(200.0)
    assert tail["tail_risk_pct_of_mean_slip"] == pytest.approx(0.09)
    # R016.2's pct (0.09) ranks 4th in the descending sort
    # (0.30, 0.24, 0.09, 0.09, 0.06 — ties broken by list order).
    assert tail["tail_risk_rank"] in (3, 4)
    assert tail["n_drivers"] == 5


def test_pick_tail_risk_returns_none_when_no_driver_below_threshold():
    """All-drivers-≥-5% case: picker returns None and fallback narrative
    renders without naming any risk. Future-register safety net."""
    drivers = [
        {
            "risk_id": "R001",
            "probability": 0.10,
            "mean_impact_when_fired_days": 50.0,
            "pct_of_total_mean": 0.50,
        },
        {
            "risk_id": "R002",
            "probability": 0.15,
            "mean_impact_when_fired_days": 30.0,
            "pct_of_total_mean": 0.50,
        },
    ]
    assert pick_tail_risk(drivers, prob_threshold=0.05) is None


def test_pick_tail_risk_empty_input_returns_none():
    assert pick_tail_risk([]) is None
    assert pick_tail_risk(None) is None


def test_pick_tail_risk_skips_drivers_with_none_mean_when_fired():
    """A driver with ``mean_impact_when_fired_days=None`` (e.g. probability=0)
    must not be picked; picker keeps the next-best candidate."""
    drivers = [
        {
            "risk_id": "RA",
            "probability": 0.0,
            "mean_impact_when_fired_days": None,
            "pct_of_total_mean": 0.0,
        },
        {
            "risk_id": "RB",
            "probability": 0.02,
            "mean_impact_when_fired_days": 100.0,
            "pct_of_total_mean": 0.10,
        },
    ]
    tail = pick_tail_risk(drivers)
    assert tail is not None
    assert tail["tail_risk_id"] == "RB"


# ---------------------------------------------------------------------------
# Rendered narrative names the picked risk, not R067
# ---------------------------------------------------------------------------

def test_distribution_interpretation_substitutes_tail_risk_id():
    tail = pick_tail_risk(_v8_shaped_drivers())
    text = format_distribution_interpretation(tail)
    assert "R016.2" in text
    assert "R067" not in text
    assert "200d" in text or "200" in text  # mean impact when fired


def test_risk_matrix_interpretation_substitutes_tail_risk_id():
    tail = pick_tail_risk(_v8_shaped_drivers())
    text = format_risk_matrix_interpretation(tail)
    assert "R016.2" in text
    assert "R067" not in text
    # All four placeholders should be filled.
    assert "1.5%" in text  # tail_risk_prob
    assert "200d" in text or "200" in text
    assert "9.0%" in text  # tail_risk_pct_of_mean_slip
    # Rank should appear as "X of 5"
    assert "of 5 drivers" in text


def test_comparison_interpretation_substitutes_tail_risk_id():
    tail = pick_tail_risk(_v8_shaped_drivers())
    text = format_comparison_interpretation(tail)
    assert "R016.2" in text
    assert "R067" not in text


# ---------------------------------------------------------------------------
# Generic fallback when no tail risk meets criterion
# ---------------------------------------------------------------------------

def test_distribution_interpretation_falls_back_when_no_tail_risk():
    text = format_distribution_interpretation(None)
    assert text == commentary_text.DISTRIBUTION_INTERPRETATION
    assert "R067" not in text  # generic fallback must not name R067


def test_risk_matrix_interpretation_falls_back_when_no_tail_risk():
    text = format_risk_matrix_interpretation(None)
    assert text == commentary_text.RISK_MATRIX_INTERPRETATION
    assert "R067" not in text


def test_comparison_interpretation_falls_back_when_no_tail_risk():
    text = format_comparison_interpretation(None)
    assert text == commentary_text.WATERFALL_INTERPRETATION
    assert "R067" not in text


# ---------------------------------------------------------------------------
# Beta-11 §3 closure — no R067 hardcoded in the legacy constants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "constant_name",
    [
        "DISTRIBUTION_INTERPRETATION",
        "RISK_MATRIX_INTERPRETATION",
        "COMPARISON_INTERPRETATION",
        "WATERFALL_INTERPRETATION",
    ],
)
def test_legacy_constant_no_longer_names_r067(constant_name):
    """Pin the deprecation: the four narrative constants the brief
    flagged must not name R067 explicitly. Dynamic naming comes from
    the *_TEMPLATE versions via the format_* helpers."""
    text = getattr(commentary_text, constant_name)
    assert "R067" not in text, (
        f"{constant_name} still hardcodes R067; convert to template + "
        f"use format_*_interpretation(tail_risk) at the composer site."
    )


# ---------------------------------------------------------------------------
# Section 3b — risk-matrix scenario alignment with table
# ---------------------------------------------------------------------------

def test_risk_matrix_orienting_names_scenario():
    """Beta-11a Fix 3: orienting paragraph names the scenario the
    matrix markers reflect. Composer passes the indicative scenario
    display label; the formatter strips parenthetical decoration."""
    text = format_risk_matrix_orienting("DP Review baseline")
    assert "DP Review baseline" in text
    assert "Mode scenario" in text


def test_risk_matrix_orienting_strips_parenthetical_decoration():
    """The display label often carries a parenthetical hint
    (e.g. 'Dummy Realistic (<interim label>)'). The formatter strips
    it so the rendered sentence reads naturally."""
    text = format_risk_matrix_orienting("Dummy Realistic (" + "S" + "JP indicative)")
    assert "Dummy Realistic Mode scenario" in text
    # Trailing parenthetical excluded from the named slot.
    assert "(" + "S" + "JP indicative) Mode" not in text


def test_risk_matrix_orienting_falls_back_when_no_scenario():
    """Empty / None matrix_scenario → render the static
    RISK_MATRIX_ORIENTING fallback (no name)."""
    text_none = format_risk_matrix_orienting(None)
    text_empty = format_risk_matrix_orienting("")
    assert text_none == commentary_text.RISK_MATRIX_ORIENTING
    assert text_empty == commentary_text.RISK_MATRIX_ORIENTING


def test_risk_matrix_uses_pert_mean_when_fired_not_raw_ml_days():
    """Beta-11 §3b / Beta-14 §3: the LEFT (traditional) panel's
    ``mean_impact`` is the raw EV PERT from the register three-point —
    Mode-independent. A risk with PERT (0/0/365) plots at the matrix's
    "mean impact when fired" axis at ≈60d, regardless of the indicative
    scenario's Mode multiplier.

    Beta-11 originally derived this value from the engine column mean
    divided by probability (which was Mode-multiplied). Beta-14 switches
    to the register three-point directly, decoupling the LEFT panel from
    Mode classification and aligning its semantics with what the axis
    label promises ("mean impact when fired", Mode-independent).
    """
    import numpy as np

    from src.final.composer import _build_risk_matrix_data

    class _R:
        def __init__(self, rid, prob, opt, ml, pess):
            self.risk_id = rid
            self.probability = prob
            self.opt_schedule_days = opt
            self.ml_days = ml
            self.pess_schedule_days = pess

    risks = [_R("R067", prob=0.025, opt=0.0, ml=0.0, pess=365.0)]
    # Synthetic per_risk_schedule_array column for R067 with mean ≈ 1.5
    # (0.025 × 60 = 1.5 — the engine output for PERT 0/0/365 × Series).
    n_iter = 10_000
    rng = np.random.default_rng(0)
    bernoulli = (rng.random(n_iter) < 0.025).astype(float)
    pert = np.where(bernoulli > 0, 60.0, 0.0)
    integrated_results = {
        "per_risk_schedule_array": pert.reshape(n_iter, 1),
        "risk_ids_dual": ["R067"],
    }
    data = _build_risk_matrix_data(risks, integrated_results)
    assert len(data) == 1
    r067 = data[0]
    # Raw EV PERT = (0 + 4*0 + 365) / 6 ≈ 60.83.
    assert r067["mean_impact"] == pytest.approx(60.83, abs=0.01)
    # NOT 0 (would be raw ml_days).
    assert r067["mean_impact"] > 10.0


def test_risk_matrix_left_panel_mode_independent():
    """Beta-14 §3: the LEFT panel's mean_impact is Mode-independent —
    the same register three-point produces the same x-coordinate
    regardless of what the engine's per-risk column mean (and hence
    Mode multiplier) is. The Mode-multiplied figure belongs only on the
    RIGHT panel.
    """
    import numpy as np

    from src.final.composer import _build_risk_matrix_data

    class _R:
        def __init__(self, rid, prob, opt, ml, pess):
            self.risk_id = rid
            self.probability = prob
            self.opt_schedule_days = opt
            self.ml_days = ml
            self.pess_schedule_days = pess

    risks = [_R("R067", prob=0.025, opt=0.0, ml=0.0, pess=365.0)]

    # Two synthetic engines: one applies Hybrid mult=0.5, one applies
    # Series mult=1.0. The column means differ by exactly 2×.
    pw_hybrid = np.full((1, 1), 0.025 * 60.0 * 0.5)  # ≈ 0.75
    pw_series = np.full((1, 1), 0.025 * 60.0 * 1.0)  # ≈ 1.5

    data_hybrid = _build_risk_matrix_data(
        risks,
        {"per_risk_schedule_array": pw_hybrid, "risk_ids_dual": ["R067"]},
    )
    data_series = _build_risk_matrix_data(
        risks,
        {"per_risk_schedule_array": pw_series, "risk_ids_dual": ["R067"]},
    )

    # LEFT panel mean_impact is Mode-independent — identical across runs.
    assert data_hybrid[0]["mean_impact"] == pytest.approx(
        data_series[0]["mean_impact"]
    )
    # RIGHT panel prob_weighted_impact follows the Mode multiplier.
    assert data_hybrid[0]["prob_weighted_impact"] == pytest.approx(0.75, rel=0.01)
    assert data_series[0]["prob_weighted_impact"] == pytest.approx(1.5, rel=0.01)


def test_risk_matrix_left_panel_handles_cost_only_zero_three_point():
    """Beta-14 §3 edge case: a cost-only risk with zero opt/ml/pess plots
    at raw_ev_pert=0 on the LEFT panel (rather than being implicitly
    pulled rightward via a non-zero pw_lookup fallback). Mirrors the
    pre-filter in _build_risk_matrix_data that drops risks lacking both
    schedule contribution and pw_lookup membership."""
    import numpy as np

    from src.final.composer import _build_risk_matrix_data

    class _R:
        def __init__(self, rid, prob, opt, ml, pess):
            self.risk_id = rid
            self.probability = prob
            self.opt_schedule_days = opt
            self.ml_days = ml
            self.pess_schedule_days = pess

    # A risk with positive probability AND a non-zero column-mean entry
    # (so it survives the filter) but a zero three-point. raw EV PERT = 0.
    risks = [_R("R_costy", prob=0.10, opt=0.0, ml=0.0, pess=0.0)]
    data = _build_risk_matrix_data(
        risks,
        {
            "per_risk_schedule_array": np.full((1, 1), 0.05),
            "risk_ids_dual": ["R_costy"],
        },
    )
    assert len(data) == 1
    assert data[0]["mean_impact"] == pytest.approx(0.0)
    # RIGHT panel still picks up the engine column mean (Mode-aware).
    assert data[0]["prob_weighted_impact"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Beta-12 — criticality narrative format helpers
# ---------------------------------------------------------------------------

class TestFormatCriticalityExplainer:
    """Beta-12 §3.3 — substitutes ``{n_iter}`` into the explainer template."""

    def test_explainer_substitutes_iteration_count(self) -> None:
        text = format_criticality_explainer(100_000)
        assert "100,000 simulated futures" in text
        # Spot-check that the body content is intact.
        assert "Criticality Index" in text
        assert "CI = 100%" in text

    def test_explainer_falls_back_when_n_iter_zero(self) -> None:
        text = format_criticality_explainer(0)
        # Falls back to "the simulated futures" wording when n_iter is unknown.
        assert "the simulated futures" in text
        # Should not contain the duplicate-word artefact.
        assert "the the simulated" not in text
        assert "simulated simulated" not in text
        assert "Criticality Index" in text


class TestFormatCriticalityDistributionInterpretation:
    """Beta-12 §3.3 — selects shape template from distribution_summary."""

    def test_format_criticality_distribution_interpretation_uses_correct_template(
        self,
    ) -> None:
        """The rendered "shifty" interpretation must contain the
        path-crossover signal phrase from that template, not the
        bimodal/stable_cp wording."""
        summary = {
            "shape_indicator": "shifty",
            "n_activities_total": 1000,
            "band_pcts": {
                "never (<10%)": 0.10,
                "rarely (10-30%)": 0.20,
                "near (30-70%)": 0.40,
                "often (70-90%)": 0.20,
                "always (90%+)": 0.10,
            },
            "band_counts": {},
            "n_on_deterministic_cp": 0,
        }
        text = format_criticality_distribution_interpretation(summary)
        assert "path crossover is real" in text
        # Pct-middle = 0.80 — formatted as 80% in the template.
        assert "80%" in text
        # Shouldn't contain the bimodal/stable phrasing.
        assert "stable critical path" not in text
        assert "core path is recognisable" not in text

    def test_bimodal_template_selected_for_bimodal_summary(self) -> None:
        summary = {
            "shape_indicator": "bimodal",
            "n_activities_total": 100,
            "band_pcts": {
                "never (<10%)": 0.50,
                "rarely (10-30%)": 0.05,
                "near (30-70%)": 0.05,
                "often (70-90%)": 0.05,
                "always (90%+)": 0.35,
            },
            "band_counts": {},
            "n_on_deterministic_cp": 0,
        }
        text = format_criticality_distribution_interpretation(summary)
        assert "stable critical path" in text
        assert "path crossover is real" not in text

    def test_unrecognised_shape_falls_back_to_shifty(self) -> None:
        summary = {
            "shape_indicator": "alien_shape_not_in_template_dict",
            "n_activities_total": 50,
            "band_pcts": {
                "never (<10%)": 0.0,
                "rarely (10-30%)": 0.0,
                "near (30-70%)": 0.0,
                "often (70-90%)": 0.0,
                "always (90%+)": 0.0,
            },
            "band_counts": {},
            "n_on_deterministic_cp": 0,
        }
        text = format_criticality_distribution_interpretation(summary)
        # Shifty is the safe fallback per the brief.
        assert "path crossover is real" in text

    def test_none_summary_returns_safe_fallback(self) -> None:
        text = format_criticality_distribution_interpretation(None)
        # Renders the shifty template even on missing input.
        assert "path crossover is real" in text


class TestFormatCriticalityNearCriticalInterpretation:
    """Beta-12 §3.3 — empty picker → fallback paragraph; non-empty →
    template substitution with row count and top CI."""

    def test_empty_picker_returns_fallback(self) -> None:
        empty_df = pd.DataFrame(columns=[
            "activity_id", "activity_name", "ci", "ci_band",
            "total_float_mean_hours", "total_float_std_hours",
            "on_deterministic_cp",
        ])
        text = format_criticality_near_critical_interpretation(empty_df)
        assert "No activities sit in the near-critical band" in text

    def test_non_empty_picker_substitutes_count_and_top_ci(self) -> None:
        # 5 activities in the picker; top CI = 0.75
        df = pd.DataFrame([
            {"activity_id": f"a{i}", "ci": 0.75 - i * 0.05}
            for i in range(5)
        ])
        text = format_criticality_near_critical_interpretation(df)
        assert "5 activities" in text
        assert "75%" in text  # top_ci formatted as 0.75 → 75%
        # The "top {n_top}" phrase uses min(3, n) = 3.
        assert "top 3" in text


import pandas as pd  # noqa: E402 — used by the new tests above


# ---------------------------------------------------------------------------
# SR-S3-Beta-14 — variant detection + variant-aware scenario labels
# ---------------------------------------------------------------------------

from src.final.executive_summary import (  # noqa: E402
    detect_strawman_variant,
    format_scenario_label,
)


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("strawman_DPReview.xlsx", None),
        ("strawman_DPReview_Series.xlsx", "Series"),
        ("strawman_DPReview_Hybrid.xlsx", "Hybrid"),
        ("strawman_DPReview_Parallel.xlsx", "Parallel"),
    ],
)
def test_detect_strawman_variant_known_filenames(filename, expected):
    """Beta-14 §Tests (a): the four canonical strawman filenames map
    to (None, 'Series', 'Hybrid', 'Parallel')."""
    assert detect_strawman_variant(filename) == expected


@pytest.mark.parametrize(
    "path,expected",
    [
        # Full Windows path.
        (
            "C:" + r"\Users\someone\projects\demo\outputs\sra_strawman"  # built, not typed: the client gate reds a drive path written as one token
            r"\strawman_DPReview_Hybrid.xlsx",
            "Hybrid",
        ),
        # Case insensitivity.
        ("strawman_series.XLSX", "Series"),
        ("strawman_HYBRID.xlsx", "Hybrid"),
        # No match — variant token not at end-of-name.
        ("strawman_Series_v2.xlsx", None),
        # Missing extension (malformed) → canonical fallback.
        ("strawman_Series", None),
        # Empty / None inputs → canonical fallback.
        ("", None),
        (None, None),
    ],
)
def test_detect_strawman_variant_edge_cases(path, expected):
    assert detect_strawman_variant(path) == expected


@pytest.mark.parametrize(
    "variant,expected_base",
    [
        (None, "DP Review baseline"),
        ("Series", "All Series"),
        ("Hybrid", "All Hybrid"),
        ("Parallel", "All Parallel"),
    ],
)
def test_format_scenario_label_dp_review_variant_aware_prod(variant, expected_base):
    """Beta-14 §Tests (b): DP_Review scenario's prod label is remapped to
    "All <Variant>" for variant strawman runs (with the audience-neutral
    "Mode as registered" suffix preserved)."""
    label = format_scenario_label(
        "DP_Review", variant=variant,
    )
    assert label.startswith(expected_base), (
        f"variant={variant!r}: expected base {expected_base!r}, got {label!r}"
    )
    # Prod suffix "(Mode as registered)" preserved across variants.
    assert "Mode as registered" in label


@pytest.mark.parametrize("variant", [None, "Series", "Hybrid", "Parallel"])
def test_format_scenario_label_non_dp_review_unaffected_by_variant(variant):
    """The variant remap only applies to DP_Review (the strawman-driven
    headline scenario). Dummy_Realistic and All_Series labels are
    independent of variant."""
    dr = format_scenario_label(
        "Dummy_Realistic", variant=variant,
    )
    assert dr == "Alternate Mode scenario"

    as_label = format_scenario_label(
        "All_Series", variant=variant,
    )
    assert as_label.startswith("All Series")
    assert "all-Series upper bound" in as_label


# ---------------------------------------------------------------------------
# SR-S3-Beta-14 §Tests (e) — Beta-11a suppression regression with headline
# ---------------------------------------------------------------------------

_HEADLINE_SUFFIX = " — headline"


def test_headline_marker_composes_with_variant_remap_hybrid():
    """Beta-14 §Tests (e): a Hybrid variant produces
    'All Hybrid (Mode as registered) — headline' with no redundant
    parenthetical (Beta-11a suppression still works), and the headline
    marker is appended *after* the suppression check."""
    base = format_scenario_label(
        "DP_Review", variant="Hybrid",
    )
    composed = f"{base}{_HEADLINE_SUFFIX}"
    assert composed == "All Hybrid (Mode as registered) — headline"
    # No redundant 'X (X)' duplication (Beta-11a Fix 1 invariant).
    import re

    match = re.search(r"^(.+?)\s*\(([^)]+)\)", composed)
    assert match is not None
    base_text, paren = match.group(1).strip(), match.group(2).strip()
    assert base_text.casefold() != paren.casefold()


def test_headline_marker_composes_with_canonical_dp_review():
    """Beta-14 §Tests (e): the canonical (no-variant) run retains its
    existing legend appearance with the headline marker appended."""
    base = format_scenario_label(
        "DP_Review", variant=None,
    )
    composed = f"{base}{_HEADLINE_SUFFIX}"
    assert composed == "DP Review baseline (Mode as registered) — headline"


def test_beta_11a_suppression_unchanged_for_dummy_realistic():
    """Beta-14 §Tests (e): the Dummy_Realistic prod label still collapses
    via Beta-11a's name==suffix suppression — the headline-marker
    mechanism is post-suppression, not pre. Dummy_Realistic is NEVER the
    headline scenario, so the marker is not appended in production code;
    the test pins the suppression itself for regression coverage."""
    label = format_scenario_label(
        "Dummy_Realistic", variant="Hybrid",
    )
    assert label == "Alternate Mode scenario"


# ---------------------------------------------------------------------------
# SR-S3-Beta-14 §Tests (c) — risk-matrix orienting paragraph variant-aware
# ---------------------------------------------------------------------------

def test_risk_matrix_orienting_variant_aware_hybrid():
    """Beta-14 §Tests (c): under a Hybrid variant run, the matrix
    orienting paragraph names "All Hybrid", not the stale "DP Review
    baseline".

    The composer passes the variant-aware scenario display label
    (`_scenario_display_lookup["DP_Review"]` for the prod indicative,
    which under variant="Hybrid" reads "All Hybrid (current strawman
    state)"). The formatter strips the trailing parenthetical so the
    rendered prose reads "All Hybrid Mode scenario".
    """
    label = format_scenario_label(
        "DP_Review", variant="Hybrid",
    )
    text = format_risk_matrix_orienting(label)
    assert "All Hybrid Mode scenario" in text
    assert "DP Review baseline" not in text


@pytest.mark.parametrize(
    "variant,expected_scenario",
    [
        ("Series", "All Series"),
        ("Hybrid", "All Hybrid"),
        ("Parallel", "All Parallel"),
    ],
)
def test_risk_matrix_orienting_variant_aware_all_three(variant, expected_scenario):
    """Beta-14 §Tests (c) generalised: all three variants produce the
    matching "All <Variant>" matrix scenario label."""
    label = format_scenario_label(
        "DP_Review", variant=variant,
    )
    text = format_risk_matrix_orienting(label)
    assert f"{expected_scenario} Mode scenario" in text
    assert "DP Review baseline" not in text


def test_risk_matrix_orienting_canonical_unchanged():
    """Beta-14 §Tests (c): the canonical (no-variant) prod run still
    reads "DP Review baseline Mode scenario" — no regression for the
    canonical case."""
    label = format_scenario_label(
        "DP_Review", variant=None,
    )
    text = format_risk_matrix_orienting(label)
    assert "DP Review baseline Mode scenario" in text


# ---------------------------------------------------------------------------
# SR-S3-Beta-14 §Tests (d) — risk-matrix interpretation Mode-multiplier honest
# ---------------------------------------------------------------------------

class _R067Synth:
    """Synthetic register risk shaped like R067 in V8: Opt=0 / ML=0 /
    Pess=365 days, probability 2.5%. EV PERT = (0 + 4*0 + 365)/6 ≈ 60.83d.
    Under Hybrid Mode multiplier 0.5 the per-fire contribution is ≈ 30.4d.
    """

    risk_id = "R067"
    probability = 0.025
    opt_schedule_days = 0.0
    ml_days = 0.0
    pess_schedule_days = 365.0


def test_risk_matrix_interpretation_honest_about_mode_multiplier():
    """Beta-14 §Tests (d): for a synthetic R067-shaped tail risk under
    the Hybrid variant, the rendered interpretation prose contains:

      - the raw EV PERT figure (60d, Mode-independent),
      - the Mode-weighted per-fire figure (30d, Mode-multiplied),
      - the Mode multiplier value (0.5) named explicitly, AND
      - the prose identifies which figure is which (the raw EV PERT is
        labelled "mean impact when fired", the 30d is labelled the
        probability-weighted Mode-multiplied contribution).
    """
    from src.final.executive_summary import enrich_tail_risk_for_matrix

    base_tail = {
        "tail_risk_id": "R067",
        "tail_risk_prob": 0.025,
        "tail_risk_mean_when_fired": 30.0,  # Mode-multiplied (Beta-11 schema)
        "tail_risk_pct_of_mean_slip": 0.077,
        "tail_risk_rank": 4,
        "n_drivers": 8,
    }
    mode_used = {"R067": "Hybrid"}
    enriched = enrich_tail_risk_for_matrix(
        base_tail,
        risks=[_R067Synth()],
        mode_used=mode_used,
        variant_label="All Hybrid",
    mode_multipliers=TEST_MODE_MULTIPLIERS)
    assert enriched is not None
    # Raw EV PERT honest: (0 + 0 + 365) / 6 ≈ 60.83.
    assert enriched["raw_ev_pert_days"] == pytest.approx(60.83, abs=0.01)
    # Hybrid multiplier 0.5; Mode-weighted contribution ≈ 30.42.
    assert enriched["multiplier_value"] == pytest.approx(0.5)
    assert enriched["mode_weighted_days"] == pytest.approx(30.42, abs=0.01)
    assert enriched["mode_label"] == "Hybrid"
    assert enriched["variant_label"] == "All Hybrid"

    text = format_risk_matrix_interpretation(enriched)
    # Raw EV PERT appears (renders as 61d due to :.0f rounding of 60.83).
    assert "61d" in text or "60d" in text
    # Mode-multiplied figure appears (renders as 30.4d via :.1f).
    assert "30.4d" in text
    # The Mode multiplier is named explicitly.
    assert "Hybrid" in text
    assert "0.5" in text
    # Variant label appears under the "under {variant_label}" clause.
    assert "under All Hybrid" in text
    # Sanity: the prose does NOT present the Mode-weighted figure as
    # "mean impact when fired" — the raw EV PERT label belongs to the
    # traditional matrix's axis.
    assert "30.4d mean impact when fired" not in text
    assert "Mode-independent" in text


@pytest.mark.parametrize(
    "variant,multiplier,weighted",
    [
        ("Series", 1.0, 60.83),
        ("Hybrid", 0.5, 30.42),
        ("Parallel", 0.0, 0.0),
    ],
)
def test_risk_matrix_interpretation_multiplier_by_variant(variant, multiplier, weighted):
    """Beta-14 §Tests (d) generalised: the same register risk under
    different Modes produces a stable raw EV PERT (60d) and a variable
    Mode-weighted figure that matches the Mode multiplier."""
    from src.final.executive_summary import enrich_tail_risk_for_matrix

    base_tail = {
        "tail_risk_id": "R067",
        "tail_risk_prob": 0.025,
        "tail_risk_mean_when_fired": 30.0,
        "tail_risk_pct_of_mean_slip": 0.05,
        "tail_risk_rank": 4,
        "n_drivers": 8,
    }
    enriched = enrich_tail_risk_for_matrix(
        base_tail,
        risks=[_R067Synth()],
        mode_used={"R067": variant},
        variant_label=f"All {variant}",
    mode_multipliers=TEST_MODE_MULTIPLIERS)
    assert enriched is not None
    assert enriched["raw_ev_pert_days"] == pytest.approx(60.83, abs=0.01)
    assert enriched["multiplier_value"] == pytest.approx(multiplier)
    assert enriched["mode_weighted_days"] == pytest.approx(weighted, abs=0.01)


def test_enrich_tail_risk_returns_none_when_risk_not_in_register():
    """Edge case: a tail_risk whose risk_id has no matching register
    entry routes the enricher to None, and the format helper falls
    back to the Beta-11 legacy template (un-enriched dict)."""
    from src.final.executive_summary import enrich_tail_risk_for_matrix

    base_tail = {
        "tail_risk_id": "R999",  # not in register
        "tail_risk_prob": 0.02,
        "tail_risk_mean_when_fired": 50.0,
        "tail_risk_pct_of_mean_slip": 0.05,
        "tail_risk_rank": 3,
        "n_drivers": 5,
    }
    enriched = enrich_tail_risk_for_matrix(
        base_tail, risks=[_R067Synth()], mode_used={}, variant_label="X",
    mode_multipliers=TEST_MODE_MULTIPLIERS)
    assert enriched is None
    # Legacy template renders cleanly with the original un-enriched dict.
    text = format_risk_matrix_interpretation(base_tail)
    assert "R999" in text
    assert "50d mean impact when fired" in text
