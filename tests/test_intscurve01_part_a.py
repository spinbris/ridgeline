"""INTSCURVE-01 Part A: the integrated result is drawn, on the headline's own numbers.

P1  the plotted integrated P80 is the Stage 3 headline P80, to the bit, and so is the top bar of
    the P80 build-up (Reviewer R3).
P3  leave-one-out holds every other risk's draws fixed: a risk with no impact saves exactly 0,
    and a replay that does not reproduce the run is refused (Reviewer R2).
P4  every new chart and table reaches both the HTML body and the Word document.
P5  the convergence chart samples the integrated total, not the cost arm.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.final import composer
from src.final.headline import STAGE3_SCENARIO_NAME, stage3_headline
from src.final.sections.integrated_total import (
    INTEGRATED_P_LEVELS,
    integrated_range_sentence,
    integrated_total_data,
    stage3_headline_block,
)
from src.final.sections.page1_table import _waterfall_components
from src.integrated.leave_one_out import integrated_leave_one_out

DAY_RATE = 35_000.0


def _arrays(n: int = 4_000, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    cost = rng.lognormal(15.0, 0.6, n)
    days = np.maximum(rng.normal(40.0, 25.0, n), 0.0)
    return cost, days


# ---------------------------------------------------------------------------
# P1 - plotted P80 = headline P80, exactly
# ---------------------------------------------------------------------------

def test_integrated_percentiles_are_the_headline_percentiles_exactly():
    cost, days = _arrays()
    tot = integrated_total_data(cost, days, DAY_RATE)
    head = stage3_headline(cost, days, DAY_RATE, p_levels=INTEGRATED_P_LEVELS)
    for p in INTEGRATED_P_LEVELS:
        assert tot["percentiles_dollars"][p] == head[f"p{p}_dollars"], f"P{p} differs"


def test_build_up_top_bar_is_the_headline_p80_exactly():
    cost, days = _arrays()
    family = {STAGE3_SCENARIO_NAME: {"cost_dollars_array": cost, "schedule_days_array": days}}
    bars = _waterfall_components(family, DAY_RATE, indicative_name=STAGE3_SCENARIO_NAME)
    top = next(b for b in bars if b["category"] == "total")
    assert top["value"] == stage3_headline(cost, days, DAY_RATE)["p80_dollars"] / 1e6


def _charts_with_spies(tmp_path, monkeypatch, *, leave_one_out=None):
    """Run the chart generator on a Stage 3 family, recording what each chart was handed."""
    calls: dict[str, list[dict]] = {"s_curve": [], "convergence": []}

    def spy_s_curve(**kw):
        calls["s_curve"].append(kw)
        Path(kw["output_path"]).write_bytes(b"png")
        return Path(kw["output_path"])

    def spy_convergence(**kw):
        calls["convergence"].append(kw)
        Path(kw["output_path"]).write_bytes(b"png")
        return Path(kw["output_path"])

    monkeypatch.setattr(composer, "make_s_curve", spy_s_curve)
    monkeypatch.setattr(composer, "make_methodology_convergence_chart", spy_convergence)
    cost, days = _arrays()
    family = {STAGE3_SCENARIO_NAME: {"cost_dollars_array": cost, "schedule_days_array": days}}
    paths = composer._generate_v3_charts(
        integrated_results_by_scenario=family, cost_drivers_top_n=[], schedule_drivers_top_n=[],
        risk_matrix_data=[], chart_output_dir=tmp_path, day_rate=DAY_RATE,
        indicative_name=STAGE3_SCENARIO_NAME, seed=42, leave_one_out=leave_one_out,
    )
    return calls, paths, cost, days


def test_the_integrated_s_curve_marks_the_headline_p80(tmp_path, monkeypatch):
    calls, paths, cost, days = _charts_with_spies(tmp_path, monkeypatch)
    lead = next(kw for kw in calls["s_curve"]
                if Path(kw["output_path"]).name == "page2_integrated_s_curve.png")
    head = stage3_headline(cost, days, DAY_RATE)
    assert lead["marker_values"][80] == head["p80_dollars"] / 1e6
    assert paths["integrated_s_curve_path"] and paths["buildup_s_curve_path"]


# ---------------------------------------------------------------------------
# P5 - convergence samples the integrated total
# ---------------------------------------------------------------------------

def test_convergence_samples_the_integrated_total(tmp_path, monkeypatch):
    calls, _, cost, days = _charts_with_spies(tmp_path, monkeypatch)
    (kw,) = calls["convergence"]
    assert np.array_equal(kw["sample"], cost + days * DAY_RATE)
    assert kw["metric_label"] == "integrated P80 cost"


# ---------------------------------------------------------------------------
# P3 - leave-one-out keeps common random numbers
# ---------------------------------------------------------------------------

def _loo_case(zero_days_risk: str = "R2"):
    """Three risks; R1 and R2 delay, R3 is cost-only. R2's delay is zero when it fires."""
    rng = np.random.default_rng(3)
    n = 3_000
    ids = ["R1", "R2", "R3"]
    sched_ids = ["R1", "R2"]
    fired = rng.random((n, 3)) < np.array([0.5, 0.4, 0.3])
    per_risk = fired * rng.lognormal(13.0, 0.5, (n, 3))
    per_risk[:, 1] = 0.0  # R2 carries no cost either: a risk with no impact at all
    sev_days = {"R1": rng.uniform(5, 40, n), "R2": np.zeros(n)}
    if zero_days_risk != "R2":
        sev_days["R2"] = rng.uniform(5, 40, n)

    def replay(mask: np.ndarray) -> np.ndarray:
        # A stand-in kernel: delay is the longer of the fired risks' delays (parallel paths).
        return np.max(np.stack([np.where(mask[:, k], sev_days[r], 0.0)
                                for k, r in enumerate(sched_ids)], axis=1), axis=1)

    fire_mask = fired[:, :2].copy()
    days = replay(fire_mask)
    return dict(cost_dollars_array=per_risk.sum(axis=1), per_risk_cost_array=per_risk,
                risk_ids_all=ids, schedule_days_array=days, schedule_risk_ids=sched_ids,
                fire_mask=fire_mask, replay_delay_days=replay, day_rate=DAY_RATE)


def test_a_risk_with_no_impact_saves_exactly_zero():
    out = integrated_leave_one_out(**_loo_case())
    r2 = next(r for r in out["rows"] if r["risk_id"] == "R2")
    assert r2["saved_dollars"] == 0.0
    assert r2["cost_part_dollars"] == 0.0 and r2["delay_part_dollars"] == 0.0


def test_parts_sum_to_the_saving_and_cost_only_risks_save_no_delay():
    out = integrated_leave_one_out(**_loo_case())
    assert out["replays"] == 2
    for r in out["rows"]:
        assert r["cost_part_dollars"] + r["delay_part_dollars"] == pytest.approx(
            r["saved_dollars"], abs=1e-6)
    r3 = next(r for r in out["rows"] if r["risk_id"] == "R3")
    assert r3["delay_part_dollars"] == 0.0 and r3["saved_dollars"] > 0.0
    assert [r["saved_dollars"] for r in out["rows"]] == sorted(
        (r["saved_dollars"] for r in out["rows"]), reverse=True)


def test_a_replay_that_does_not_reproduce_the_run_is_refused():
    case = _loo_case()
    base = case["replay_delay_days"]
    case["replay_delay_days"] = lambda m: base(m) + 0.5  # a different stream
    with pytest.raises(ValueError, match="does not reproduce"):
        integrated_leave_one_out(**case)


@pytest.mark.slow
def test_stage3_replay_reproduces_the_run_on_the_wind_fixture(monkeypatch):
    """The production replay is the run: the control inside stage3_leave_one_out passes."""
    fx = Path(__file__).resolve().parent / "fixtures" / "synthetic_wind"
    for k, v in dict(QRA_PROJECT="synthetic_wind", REGISTER_FILE=str(fx / "wind_register.xlsx"),
                     P6_FILE=str(fx / "wind_schedule.xer"),
                     STRAWMAN_FILE=str(fx / "wind_register.xlsx"),
                     SR9_ITERATIONS="1000", SR9_SEED="42").items():
        monkeypatch.setenv(k, v)
    from src.final.deliverable import resolve_inputs, run_engines

    eng = run_engines(resolve_inputs())
    loo = eng.stage3_beta_result["leave_one_out"]
    assert loo["iterations"] == 1000 and loo["replays"] == len(eng.stage3_result.risk_drivers)
    assert {r["risk_id"] for r in loo["rows"]} == set(eng.stage3_result.cost_result["risk_ids_all"])


# ---------------------------------------------------------------------------
# P4, P6 - what reaches the reader
# ---------------------------------------------------------------------------

def test_range_sentence_and_html_headline_block_carry_the_headline_figures():
    cost, days = _arrays()
    head = stage3_headline(cost, days, DAY_RATE, p_levels=INTEGRATED_P_LEVELS)
    sentence = integrated_range_sentence(head)
    for p in (50, 80, 90):
        assert f"P{p} ${head[f'p{p}_dollars'] / 1e6:.2f}M" in sentence
    assert sentence.index("P50") < sentence.index("P80") < sentence.index("P90")
    block = stage3_headline_block(head, "Headline contingency (P80, Stage 3)")
    assert [r["Percentile"] for r in block["stage3_headline_table"]] == [
        "P50", "P80", "P90", "P95", "Mean"]
    assert head["basis"] in block["stage3_headline_basis"]


NEW_CHART_KEYS = {
    "page2_distribution": ("integrated_s_curve_path", "integrated_density_path",
                           "buildup_s_curve_path", "cost_s_curve_path", "cost_density_path"),
    "page3_cost_drivers": ("integrated_tornado_path",),
}


def test_every_new_chart_renders_in_html_and_word(tmp_path):
    from docx import Document

    from src.final.charts import make_leave_one_out_tornado
    from src.final.html_blocks import blocks
    from src.final.word_generator import generate_word_summary
    from tests.test_sr9_v3_word_generator import _generate_v3_doc

    _, composed = _generate_v3_doc(tmp_path)
    loo = integrated_leave_one_out(**_loo_case(zero_days_risk="none"))
    composed["page3_cost_drivers"]["integrated_tornado_path"] = str(make_leave_one_out_tornado(
        loo["rows"], "Leave-one-out", tmp_path / "loo.png"))

    for section, keys in NEW_CHART_KEYS.items():
        images = {b[1] for b in blocks(composed[section], section=section) if b[0] == "image"}
        for key in keys:
            path = composed[section][key]
            assert path and Path(path).is_file(), f"{section}/{key} produced no chart"
            assert str(Path(path)) in images, f"{section}/{key} does not reach the HTML body"

    out = tmp_path / "with_tornado.docx"
    generate_word_summary(
        summary_data=composed["executive_summary"],
        audit_trail_data=composed["appendix_audit_trail"],
        disclaimer_paragraphs=composed["disclaimer_paragraphs"],
        cross_validation=composed["cross_validation"], output_path=out, composed=composed)
    doc = Document(str(out))
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    for h in ("Integrated contingency distribution", "Cumulative build-up",
              "Event-risk cost distribution", "Delay cost and risk cost impacts"):
        assert h in headings, f"Word lacks {h!r}"
    assert any(h.startswith("Integrated drivers - leave-one-out") for h in headings)
    # One picture per chart: the five new keys plus every chart Word drew before.
    pictures = len(doc.inline_shapes)
    assert pictures >= 6
