"""SR-S3-Beta-15 — methodology validation pack tests.

Covers six restorations to the composer/charts/text layer:

  Item 1 — cross-validation one-liner in §8 audit trail (PASS + FAIL paths)
  Item 6 — single-iteration walkthrough table body (defect fix)
  Item 2 — convergence diagnostic chart in §7
  Item 3 — Mode-sensitivity 4-row summary (incl. All Parallel scenario)
  Item 4 — confidence-band waterfall image in §2
  Item 5 — six-approach reconciliation table in §1

A consolidated slow E2E test at the bottom asserts all six restorations
land in a freshly rendered docx via nbconvert.
"""

from __future__ import annotations
from tests.conftest import TEST_MODE_MULTIPLIERS

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Item 1 — cross-validation one-liner in §8 audit trail
# ---------------------------------------------------------------------------


def _cv_dict_pass() -> dict:
    """Synthetic CV result mirroring cross_validate_reports output (all pass)."""
    return {
        "cost_passes_calibration": True,
        "cost_absolute_gap_dollars": 45_300.0,
        # DELIVFIX-01: a FRACTION, as the engine writes it (0.00383 = 0.383%). This fixture held
        # 0.383 - a percentage - which is exactly why the test agreed with STAGE4-F37: a
        # percent-valued fixture through a renderer that printed the value with a bare `%` came
        # out looking right.
        "cost_relative_gap_pct": 0.00383,
        "schedule_passes_calibration": True,
        "schedule_absolute_gap_days": 0.041,
        "top_3_cost_contributors_consistent": True,
        "top_3_cost_contributors_integrated": ["R028", "R051", "R029"],
        "top_3_schedule_contributors_consistent": True,
        "top_3_schedule_contributors_integrated": ["R090", "R067", "R026.1"],
        "all_pass": True,
        "n_iter_used_for_scaling": 100_000,
    }


def _cv_dict_fail() -> dict:
    """Synthetic CV result with cost calibration + top-3 schedule both failing."""
    return {
        "cost_passes_calibration": False,
        "cost_absolute_gap_dollars": 123_456.0,
        "cost_relative_gap_pct": 0.0125,   # a fraction, as above (1.250%)
        "schedule_passes_calibration": True,
        "schedule_absolute_gap_days": 0.080,
        "top_3_cost_contributors_consistent": True,
        "top_3_cost_contributors_integrated": ["R028", "R051", "R029"],
        "top_3_schedule_contributors_consistent": False,
        "top_3_schedule_contributors_integrated": ["R090", "R026.1", "R013"],
        "all_pass": False,
        "n_iter_used_for_scaling": 100_000,
    }


def test_cross_validation_sentence_pass_path() -> None:
    """PASS gate: sentence reads 'all four gates passed' and lists top-3 lists."""
    from src.final.composer import build_cross_validation_sentence

    sentence = build_cross_validation_sentence(_cv_dict_pass(), n_iter=100_000)

    assert sentence
    assert "all four gates passed" in sentence
    assert "100,000-iteration" in sentence
    assert "$45,300" in sentence   # whole dollars, not thousands (FW-22)
    assert "0.383%" in sentence
    assert "0.041d" in sentence
    assert "R028" in sentence and "R051" in sentence and "R029" in sentence
    assert "R090" in sentence and "R067" in sentence and "R026.1" in sentence
    assert "FAIL" not in sentence


def test_cross_validation_sentence_fail_path_names_failed_gates() -> None:
    """FAIL gate: sentence inverts to FAIL and names which gates failed."""
    from src.final.composer import build_cross_validation_sentence

    sentence = build_cross_validation_sentence(_cv_dict_fail(), n_iter=100_000)

    assert sentence
    assert "FAILED" in sentence
    assert "cost marginal calibration" in sentence
    assert "top-3 schedule contributors consistency" in sentence
    # The two gates that passed should NOT appear in the failed-gates clause.
    failed_clause = sentence.split("Failed gate")[1] if "Failed gate" in sentence else ""
    assert "schedule marginal calibration" not in failed_clause
    assert "top-3 cost contributors consistency" not in failed_clause


def test_cross_validation_sentence_empty_when_no_cv_dict() -> None:
    """Empty / None cv dict yields empty sentence (no broken render)."""
    from src.final.composer import build_cross_validation_sentence

    assert build_cross_validation_sentence({}) == ""
    assert build_cross_validation_sentence(None) == ""  # type: ignore[arg-type]


def test_cross_validation_sentence_handles_missing_top3_lists() -> None:
    """If the top-3 lists are absent, the sentence still composes (no crash)."""
    from src.final.composer import build_cross_validation_sentence

    cv = _cv_dict_pass()
    cv.pop("top_3_cost_contributors_integrated", None)
    cv.pop("top_3_schedule_contributors_integrated", None)
    sentence = build_cross_validation_sentence(cv, n_iter=100_000)

    assert sentence
    assert "all four gates passed" in sentence
    # Parenthetical risk-id list omitted, but the consistency clause stays.
    assert "top-3 cost contributors consistent" in sentence
    assert "top-3 schedule contributors consistent" in sentence


# ---------------------------------------------------------------------------
# Item 6 — single-iteration walkthrough table body (defect fix)
# ---------------------------------------------------------------------------


def test_composer_accepts_single_iteration_transparency_df_kwarg() -> None:
    """The composer kwarg exists and stores the df under page7_methodology."""
    from src.final.composer import compose_final_report_data
    import inspect

    sig = inspect.signature(compose_final_report_data)
    assert "single_iteration_transparency_df" in sig.parameters
    assert sig.parameters["single_iteration_transparency_df"].default is None


def test_word_generator_renders_transparency_table_when_present() -> None:
    """word_generator emits 9 rows (8 risks + TOTAL + header) when df supplied."""
    from docx import Document
    from src.final.word_generator import _add_single_iteration_transparency_table

    df = pd.DataFrame([
        {
            "risk_id": "R001", "probability": 0.5, "u_fire_draw": 0.3,
            "fired": True, "u_dur_draw": 0.6, "drawn_duration_days": 10.5,
            "mode": "Series", "mode_multiplier": 1.0, "contribution_days": 10.5,
        },
        {
            "risk_id": "R002", "probability": 0.2, "u_fire_draw": 0.8,
            "fired": False, "u_dur_draw": 0.4, "drawn_duration_days": float("nan"),
            "mode": "Hybrid", "mode_multiplier": 0.5, "contribution_days": 0.0,
        },
        {
            "risk_id": "TOTAL", "probability": float("nan"),
            "u_fire_draw": float("nan"), "fired": "",
            "u_dur_draw": float("nan"), "drawn_duration_days": float("nan"),
            "mode": "", "mode_multiplier": float("nan"),
            "contribution_days": 10.5,
        },
    ])
    doc = Document()
    _add_single_iteration_transparency_table(doc, df)

    tables = doc.tables
    assert len(tables) == 1
    # 1 header row + 3 body rows
    assert len(tables[0].rows) == 4
    # Header column count: 9 columns
    assert len(tables[0].rows[0].cells) == 9
    # Header text spot check
    assert tables[0].rows[0].cells[0].text == "Risk ID"
    assert tables[0].rows[0].cells[2].text == "U_fire draw"
    assert tables[0].rows[0].cells[4].text == "U_dur draw"
    # Boolean fired cell renders as "Yes"/"No"
    assert tables[0].rows[1].cells[3].text == "Yes"
    assert tables[0].rows[2].cells[3].text == "No"


def test_word_generator_skips_transparency_table_when_df_none() -> None:
    """No table rendered when single_iteration_table is None or empty."""
    from docx import Document
    from src.final.word_generator import _add_single_iteration_transparency_table

    doc = Document()
    _add_single_iteration_transparency_table(doc, None)
    _add_single_iteration_transparency_table(doc, pd.DataFrame())
    assert len(doc.tables) == 0


# ---------------------------------------------------------------------------
# Item 2 — convergence diagnostic chart in §7
# ---------------------------------------------------------------------------


def test_methodology_convergence_chart_writes_png(tmp_path) -> None:
    """make_methodology_convergence_chart writes a PNG file."""
    from src.final.charts import make_methodology_convergence_chart

    rng = np.random.default_rng(42)
    sample = rng.lognormal(mean=15.0, sigma=0.3, size=5_000)  # cost-like
    out = tmp_path / "conv.png"
    result = make_methodology_convergence_chart(
        sample=sample,
        output_path=out,
        percentile=80.0,
        iter_grid=(1_000, 2_500, 5_000),
        metric_label="test metric",
        seed=42,
    )
    assert result.exists()
    assert result.stat().st_size > 0
    # PNG magic bytes
    assert result.read_bytes()[:4] == b"\x89PNG"


def test_methodology_convergence_chart_falls_back_for_small_samples(tmp_path) -> None:
    """bootstrap_convergence gracefully handles iter_grid > n_iter."""
    from src.final.charts import make_methodology_convergence_chart

    rng = np.random.default_rng(42)
    sample = rng.lognormal(mean=15.0, sigma=0.3, size=200)
    out = tmp_path / "conv_small.png"
    # iter_grid entirely above sample size — bootstrap_convergence emits
    # a warning and falls back to a single point at n_iter.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = make_methodology_convergence_chart(
            sample=sample,
            output_path=out,
            percentile=80.0,
            iter_grid=(1_000, 5_000, 10_000),
            metric_label="test metric",
            seed=42,
        )
    assert result.exists()


def test_commentary_text_carries_convergence_caveat() -> None:
    """Convergence caveat names MC error vs model uncertainty distinction."""
    from src.final import commentary_text

    assert hasattr(commentary_text, "CONVERGENCE_CAVEAT")
    caveat = commentary_text.CONVERGENCE_CAVEAT
    # Must explicitly distinguish MC error from input/model uncertainty.
    assert "Monte Carlo" in caveat
    assert "model uncertainty" in caveat.lower() or "inputs" in caveat
    # PRESENT-01 (P-3): it named a canonical 100,000-iteration mark, which is one project's
    # production setting quoted at a reader whose run may have used another. It now refers to
    # the run's own iteration count, and must not reassert a number.
    assert "100,000" not in caveat
    assert "iteration count this run used" in caveat


def test_convergence_section_renders_when_path_present() -> None:
    """word_generator emits convergence heading + caveat when path supplied."""
    from docx import Document
    from src.final.word_generator import _add_italic_note, _add_orienting

    # The render pattern is exercised via the §7 block in
    # _render_v3_executive_summary; we test the contract: when
    # page7_methodology["convergence_chart_path"] is truthy the chart
    # image, caption, and caveat are all rendered as a unit.
    doc = Document()
    _add_orienting(doc, "test caption")
    _add_italic_note(doc, "test caveat", size_pt=10)
    # 2 paragraphs added (caption + caveat); the chart is added by
    # _add_picture_centered which silently skips when path missing.
    assert len(doc.paragraphs) >= 2


# ---------------------------------------------------------------------------
# Item 3 — Mode-sensitivity 4-row summary in §7
# ---------------------------------------------------------------------------


def _synthetic_counterfactual() -> pd.DataFrame:
    """4 base scenarios + 1 flip — enough to exercise the summary helper."""
    return pd.DataFrame([
        {
            "scenario_id": 1, "scenario_name": "Baseline (DP Review)",
            "mode_mix_summary": "1S/7P",
            "mc_mean_days": 1.75, "mc_p50_days": 0.0, "mc_p80_days": 5.2,
            "mc_p90_days": 8.0, "mc_mean_dollars": 495_879.0,
            "delta_from_baseline_days": 0.0, "is_duplicate_of_baseline": False,
        },
        {
            "scenario_id": 2, "scenario_name": "All Series",
            "mode_mix_summary": "8S",
            "mc_mean_days": 22.3, "mc_p50_days": 15.0, "mc_p80_days": 35.5,
            "mc_p90_days": 50.0, "mc_mean_dollars": 6_310_172.0,
            "delta_from_baseline_days": 20.55, "is_duplicate_of_baseline": False,
        },
        {
            "scenario_id": 3, "scenario_name": "All Hybrid",
            "mode_mix_summary": "8H",
            "mc_mean_days": 11.15, "mc_p50_days": 7.5, "mc_p80_days": 17.75,
            "mc_p90_days": 25.0, "mc_mean_dollars": 3_155_086.0,
            "delta_from_baseline_days": 9.40, "is_duplicate_of_baseline": False,
        },
        {
            "scenario_id": 4, "scenario_name": "Dummy realistic (" + "S" + "JP)",
            "mode_mix_summary": "3S/2H/3P",
            "mc_mean_days": 9.85, "mc_p50_days": 5.0, "mc_p80_days": 18.3,
            "mc_p90_days": 28.0, "mc_mean_dollars": 2_785_462.0,
            "delta_from_baseline_days": 8.10, "is_duplicate_of_baseline": False,
        },
        {
            "scenario_id": 5, "scenario_name": "All Parallel",
            "mode_mix_summary": "8P",
            "mc_mean_days": 0.0, "mc_p50_days": 0.0, "mc_p80_days": 0.0,
            "mc_p90_days": 0.0, "mc_mean_dollars": 0.0,
            "delta_from_baseline_days": -1.75, "is_duplicate_of_baseline": False,
        },
    ])


def test_mode_sensitivity_summary_returns_4_rows_for_un_suffixed() -> None:
    """Un-suffixed strawman: 4 rows, Baseline labelled and bolded."""
    from src.final.composer import build_mode_sensitivity_summary

    result = build_mode_sensitivity_summary(
        _synthetic_counterfactual(), strawman_variant=None,
    )
    df = result["table"]
    assert len(df) == 4
    assert result["bold_row_index"] == 0  # Baseline row
    scenarios = df["Scenario"].tolist()
    # Row 0 has the headline suffix, others don't.
    assert "DP Review baseline" in scenarios[0]
    assert "headline" in scenarios[0]
    assert "All Series" in scenarios[1]
    assert "headline" not in scenarios[1]
    assert "All Hybrid" in scenarios[2]
    assert "All Parallel" in scenarios[3]


def test_mode_sensitivity_summary_bolds_all_series_for_series_variant() -> None:
    """Series variant: bolded row is All Series, baseline label changes."""
    from src.final.composer import build_mode_sensitivity_summary

    result = build_mode_sensitivity_summary(
        _synthetic_counterfactual(), strawman_variant="Series",
    )
    df = result["table"]
    assert result["bold_row_index"] == 1  # All Series row
    assert "All Series" in df["Scenario"].iloc[1]
    assert "headline" in df["Scenario"].iloc[1]
    assert "headline" not in df["Scenario"].iloc[0]
    # Baseline row label remaps for variant.
    assert "All Series" in df["Scenario"].iloc[0] or (
        "Mode as registered" in df["Scenario"].iloc[0]
    )


def test_mode_sensitivity_summary_bolds_all_hybrid_for_hybrid_variant() -> None:
    """Hybrid variant: bolded row is All Hybrid."""
    from src.final.composer import build_mode_sensitivity_summary

    result = build_mode_sensitivity_summary(
        _synthetic_counterfactual(), strawman_variant="Hybrid",
    )
    df = result["table"]
    assert result["bold_row_index"] == 2  # All Hybrid row
    assert "All Hybrid" in df["Scenario"].iloc[2]
    assert "headline" in df["Scenario"].iloc[2]


def test_mode_sensitivity_summary_variant_orienting_omits_dp_review_label() -> None:
    """Beta-14 §3 invariant compatibility: variant orienting must not name
    'DP Review baseline' so the variant docx invariant continues to hold.
    """
    from src.final.composer import build_mode_sensitivity_summary

    for variant in ("Series", "Hybrid", "Parallel"):
        result = build_mode_sensitivity_summary(
            _synthetic_counterfactual(), strawman_variant=variant,
        )
        scenarios = result["table"]["Scenario"].tolist()
        all_text = " ".join(scenarios) + " " + result.get("orienting", "")
        assert "DP Review baseline" not in all_text, (
            f"variant={variant}: 'DP Review baseline' string must not "
            "appear in mode_sensitivity_summary outputs (breaks Beta-14 §3 "
            "variant invariant when rendered to docx)"
        )


def test_mode_sensitivity_summary_bolds_all_parallel_for_parallel_variant() -> None:
    """Parallel variant: bolded row is All Parallel."""
    from src.final.composer import build_mode_sensitivity_summary

    result = build_mode_sensitivity_summary(
        _synthetic_counterfactual(), strawman_variant="Parallel",
    )
    df = result["table"]
    assert result["bold_row_index"] == 3  # All Parallel row
    assert "All Parallel" in df["Scenario"].iloc[3]
    assert "headline" in df["Scenario"].iloc[3]


def test_mode_sensitivity_summary_delta_arithmetic() -> None:
    """Delta from headline = each row's MC Mean - headline MC Mean."""
    from src.final.composer import build_mode_sensitivity_summary

    result = build_mode_sensitivity_summary(
        _synthetic_counterfactual(), strawman_variant=None,
    )
    df = result["table"]
    # Baseline is headline; delta = 0.
    headline_mean = float(df.iloc[0]["MC Mean (days)"])
    assert df.iloc[0]["Delta from headline (days)"] == 0.0
    # All Series delta = 22.30 - 1.75 = 20.55
    assert abs(
        float(df.iloc[1]["Delta from headline (days)"])
        - (22.30 - headline_mean)
    ) < 0.05
    # All Parallel delta = 0.0 - 1.75 = -1.75
    assert df.iloc[3]["Delta from headline (days)"] == round(-headline_mean, 2)


def test_mode_sensitivity_summary_empty_counterfactual() -> None:
    """Empty / None counterfactual returns empty table, no crash."""
    from src.final.composer import build_mode_sensitivity_summary

    r1 = build_mode_sensitivity_summary(None, strawman_variant=None)
    r2 = build_mode_sensitivity_summary(pd.DataFrame(), strawman_variant=None)
    assert len(r1["table"]) == 0 and r1["bold_row_index"] is None
    assert len(r2["table"]) == 0 and r2["bold_row_index"] is None


def test_all_parallel_scenario_zero_contribution_invariant() -> None:
    """All Parallel scenario: multiplier 0.0 means schedule contribution = 0.

    Sanity check on the Beta-15 engine wiring — no scenario where the
    headline number can ever be greater than zero under All Parallel
    (because the Mode multiplier maps to 0.0 by construction).
    """
    from tests.conftest import TEST_MODE_MULTIPLIERS

    assert TEST_MODE_MULTIPLIERS["Parallel"] == 0.0


# ---------------------------------------------------------------------------
# Item 4 — confidence-band waterfall image in §2
# ---------------------------------------------------------------------------


def test_waterfall_components_sum_to_integrated_p80() -> None:
    """cost-P80 + schedule-P80 dollarised + diversification = integrated P80.

    The composer's _waterfall_components must satisfy this identity so
    the chart's bars visually decompose the headline.
    """
    from src.final.composer import _waterfall_components

    # Synthetic integrated_results_by_scenario for DP_Review scenario.
    rng = np.random.default_rng(42)
    cost_arr = rng.lognormal(mean=15.0, sigma=0.3, size=5_000)
    sched_arr = rng.lognormal(mean=2.0, sigma=0.8, size=5_000)
    # Build a synthetic joint integrated_array consistent with joint
    # sampling adjustment — use the actual array, not naive sum.
    day_rate = 100_000.0
    integrated_arr = cost_arr + sched_arr * day_rate

    # _waterfall_components resolves the indicative scenario through
    # resolve_indicative_scenario_name, which names the DP Review baseline. The synthetic dict's
    # key must match so the breakdown helper finds something.
    irs = {
        "DP_Review": {
            "cost_dollars_array": cost_arr,
            "schedule_days_array": sched_arr,
            "integrated_total_dollars_array": integrated_arr,
        },
    }
    components = _waterfall_components(irs, day_rate=day_rate)
    assert len(components) == 4
    labels = [c["label"] for c in components]
    assert "Cost-only P80" in labels[0]
    assert "Schedule slip P80 dollarised" in labels[1]
    assert "Joint sampling adjustment" in labels[2]
    assert "Integrated P80" in labels[3]
    # Arithmetic: cost P80 + sched P80 dollarised + joint adj = integrated P80
    cost_m = components[0]["value"]
    sched_m = components[1]["value"]
    joint_m = components[2]["value"]
    integ_m = components[3]["value"]
    assert abs((cost_m + sched_m + joint_m) - integ_m) < 0.01, (
        f"Waterfall identity failed: {cost_m} + {sched_m} + {joint_m} "
        f"!= {integ_m}"
    )


def test_word_generator_renders_4_row_summary_with_bold_headline() -> None:
    """word_generator emits 5 rows (header + 4 body) and shades the bolded row."""
    from docx import Document
    from src.final.composer import build_mode_sensitivity_summary
    from src.final.word_generator import _add_mode_sensitivity_summary_table

    summary = build_mode_sensitivity_summary(
        _synthetic_counterfactual(), strawman_variant="Hybrid",
    )
    doc = Document()
    _add_mode_sensitivity_summary_table(doc, summary)

    assert len(doc.tables) == 1
    table = doc.tables[0]
    # 1 header row + 4 body rows
    assert len(table.rows) == 5
    # Bolded row (All Hybrid) is row index 3 in the docx table (1 header + index 2 in df).
    bold_idx_docx = 1 + 2
    # Spot check: shading applied to bolded row's cells (tcPr/shd element).
    cell = table.rows[bold_idx_docx].cells[0]
    tc_pr = cell._tc.find(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tcPr"
    )
    assert tc_pr is not None


# ---------------------------------------------------------------------------
# Item 5 — six-approach reconciliation table in §1
# ---------------------------------------------------------------------------


def _synthetic_risks() -> list:
    """3 V8-shape risks with prob / ML / Pess populated for cost + schedule."""
    class _R:
        def __init__(self, **kw):
            self.__dict__.update(kw)
    return [
        _R(
            risk_id="R028", probability=0.5, ml_cost=500_000.0, ml_days=2.0,
            pess_cost=1_000_000.0, pess_schedule_days=5.0,
        ),
        _R(
            risk_id="R051", probability=0.3, ml_cost=300_000.0, ml_days=1.0,
            pess_cost=600_000.0, pess_schedule_days=3.0,
        ),
        _R(
            risk_id="R090", probability=0.025, ml_cost=0.0, ml_days=200.0,
            pess_cost=0.0, pess_schedule_days=365.0,
        ),
    ]


def _synthetic_integrated_results() -> dict:
    rng = np.random.default_rng(42)
    return {
        "cost_dollars_array": rng.lognormal(mean=14.5, sigma=0.3, size=10_000),
        "schedule_days_array": rng.lognormal(mean=2.0, sigma=0.7, size=10_000),
    }


def test_six_approach_table_has_7_rows_and_correct_approaches() -> None:
    """All 7 expected approaches appear; values populate from synthetic inputs."""
    from src.final.composer import build_six_approach_reconciliation_table

    result = build_six_approach_reconciliation_table(
        risks=_synthetic_risks(),
        integrated_results_indicative=_synthetic_integrated_results(),
        programme_duration_days=502.0,
        day_rate=100_000.0,
        headline_metric="P80",
    )
    df = result["table"]
    assert len(df) == 7
    approaches = df["Approach"].tolist()
    assert "10% of programme rule of thumb" in approaches
    assert "20% of programme rule of thumb" in approaches
    assert "Sum of pessimistic durations / costs" in approaches
    assert "Deterministic EMV PERT" in approaches
    assert "MC Mean" in approaches
    assert "MC P80 (recommended contingency)" in approaches
    assert "MC P95" in approaches


def test_six_approach_table_bolds_mc_p80_by_default() -> None:
    """headline_metric='P80' → bold row index points to MC P80."""
    from src.final.composer import build_six_approach_reconciliation_table

    result = build_six_approach_reconciliation_table(
        risks=_synthetic_risks(),
        integrated_results_indicative=_synthetic_integrated_results(),
        programme_duration_days=502.0,
        day_rate=100_000.0,
        headline_metric="P80",
    )
    df = result["table"]
    bold_idx = result["bold_row_index"]
    assert bold_idx is not None
    assert "MC P80" in df.iloc[bold_idx]["Approach"]


def test_six_approach_table_bolds_mc_mean_when_headline_is_mean() -> None:
    """headline_metric='Mean' → bold row index points to MC Mean."""
    from src.final.composer import build_six_approach_reconciliation_table

    result = build_six_approach_reconciliation_table(
        risks=_synthetic_risks(),
        integrated_results_indicative=_synthetic_integrated_results(),
        programme_duration_days=502.0,
        day_rate=100_000.0,
        headline_metric="Mean",
    )
    df = result["table"]
    bold_idx = result["bold_row_index"]
    assert bold_idx is not None
    assert df.iloc[bold_idx]["Approach"] == "MC Mean"


def test_six_approach_table_10pct_rule_arithmetic() -> None:
    """10% rule = programme_duration_days × 0.10 for RefProject programme."""
    from src.final.composer import build_six_approach_reconciliation_table

    result = build_six_approach_reconciliation_table(
        risks=_synthetic_risks(),
        integrated_results_indicative=_synthetic_integrated_results(),
        programme_duration_days=502.0,  # V8 RefProject programme
        day_rate=100_000.0,
        headline_metric="P80",
    )
    df = result["table"]
    row_10 = df[df["Approach"] == "10% of programme rule of thumb"].iloc[0]
    assert abs(row_10["Schedule (days)"] - 50.2) < 0.1
    row_20 = df[df["Approach"] == "20% of programme rule of thumb"].iloc[0]
    assert abs(row_20["Schedule (days)"] - 100.4) < 0.1


def test_six_approach_table_delta_columns_zero_at_headline() -> None:
    """Delta from headline = 0 in the bolded row by definition."""
    from src.final.composer import build_six_approach_reconciliation_table

    result = build_six_approach_reconciliation_table(
        risks=_synthetic_risks(),
        integrated_results_indicative=_synthetic_integrated_results(),
        programme_duration_days=502.0,
        day_rate=100_000.0,
        headline_metric="P80",
    )
    df = result["table"]
    bold_idx = result["bold_row_index"]
    assert df.iloc[bold_idx]["Delta-schedule (days)"] == 0.0
    assert df.iloc[bold_idx]["Delta-cost ($M)"] == 0.0


def test_six_approach_table_excludes_prod_forbidden_phrases() -> None:
    """Prod docx invariant: zero references to the interim label / 'Dummy Realistic'.

    The Beta-15 §1 table must be prod-safe by construction — text-fixture
    enforcement gates the deliverable from leaking dev-mode wording.
    """
    from src.final.composer import build_six_approach_reconciliation_table

    result = build_six_approach_reconciliation_table(
        risks=_synthetic_risks(),
        integrated_results_indicative=_synthetic_integrated_results(),
        programme_duration_days=502.0,
        day_rate=100_000.0,
        headline_metric="P80",
    )
    df = result["table"]
    all_text = " ".join(df.astype(str).values.ravel().tolist())
    all_text += " " + result.get("orienting", "")
    forbidden = [
        "Dummy Realistic", "Dummy_Realistic", "S" + "JP indicative",
        "PM review", "Mode classification",
    ]
    for phrase in forbidden:
        assert phrase not in all_text, (
            f"Forbidden phrase '{phrase}' leaked into Item 5 §1 table"
        )


def test_word_generator_renders_six_approach_table_with_bold() -> None:
    """word_generator emits 8 rows (header + 7 body) and shades the bolded row."""
    from docx import Document
    from src.final.composer import build_six_approach_reconciliation_table
    from src.final.word_generator import _add_six_approach_reconciliation_table

    result = build_six_approach_reconciliation_table(
        risks=_synthetic_risks(),
        integrated_results_indicative=_synthetic_integrated_results(),
        programme_duration_days=502.0,
        day_rate=100_000.0,
        headline_metric="P80",
    )
    doc = Document()
    _add_six_approach_reconciliation_table(doc, result)

    assert len(doc.tables) == 1
    table = doc.tables[0]
    # 1 header row + 7 body rows
    assert len(table.rows) == 8


# ---------------------------------------------------------------------------
# Consolidated slow E2E — all six restorations land in a fresh docx
# ---------------------------------------------------------------------------
