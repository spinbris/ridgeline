"""INTVIEW-01 stage 2a: period JSON 1.6, the integrated numbers the app needs.

The gate the brief names first is the period-0 agreement test: for the same register, seed and
iterations with no pinning, the period JSON's JCL, budget-alone confidence and base-drawn total
equal the report's ``stage3_jcl`` and total-cost values exactly, and its per-risk dollars equal
the report's masked leave-one-out. Below it, one unit test per new field.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.am.integrated_views import (
    build_up,
    contingency_block,
    day_rate_derivation,
    period_jcl,
    period_leave_one_out,
    period_total_cost,
    within_noise,
)
from tests.input_skips import skip_missing

REPO = Path(__file__).resolve().parents[1]
WIND_DIR = REPO / "tests" / "fixtures" / "synthetic_wind"
WIND_REGISTER = WIND_DIR / "wind_register.xlsx"
WIND_XER = WIND_DIR / "wind_schedule.xer"
WIND_01 = REPO / "status_periods" / "wind_period_01.xlsx"
ITERATIONS = 2000
SEED = 42
DAY_RATE = 35_000.0


# --- property 2: build-up and day-rate derivation --------------------------------------------

def test_the_build_up_reconciles_and_its_joint_row_is_the_contingency():
    rng = np.random.default_rng(1)
    cost = rng.gamma(2.0, 1e6, 5000)
    days = rng.gamma(2.0, 20.0, 5000)
    rows = build_up(cost, days, DAY_RATE)
    assert [r["p_level"] for r in rows] == [50, 80, 90]
    for r in rows:
        assert r["standalone_sum_dollars"] == pytest.approx(
            r["event_cost_dollars"] + r["delay_cost_dollars"], abs=0.02)
        assert r["diversification_dollars"] == pytest.approx(
            r["standalone_sum_dollars"] - r["joint_contingency_dollars"], abs=0.02)
        assert r["delay_cost_dollars"] == pytest.approx(r["delay_days"] * DAY_RATE, abs=20)
    p80 = rows[1]
    assert p80["joint_contingency_dollars"] == round(float(np.percentile(cost + days * DAY_RATE,
                                                                         80)), 2)


def test_without_prelims_the_rate_is_stated_and_not_derived():
    d = day_rate_derivation({"schedule_duration_weeks": 90.0, "avg_prelims_weekly": None},
                            day_rate=DAY_RATE, programme_working_days=590.0)
    assert d["day_rate_used"] == DAY_RATE and d["day_rate_derived"] is None
    assert d["gap_flagged"] is False and "average prelims per week" in d["note"]


def test_a_derivation_that_agrees_is_not_flagged():
    d = day_rate_derivation({"schedule_duration_weeks": 100.0, "avg_prelims_weekly": 175_000.0},
                            day_rate=DAY_RATE, programme_working_days=500.0)
    assert d["day_rate_derived"] == DAY_RATE and d["gap_flagged"] is False


def test_a_derivation_that_differs_is_flagged_and_the_stated_rate_still_used():
    """DAYRATE-01: shown and flagged, never re-derived."""
    d = day_rate_derivation({"schedule_duration_weeks": 90.0, "avg_prelims_weekly": 175_000.0},
                            day_rate=DAY_RATE, programme_working_days=590.0)
    assert d["gap_flagged"] is True
    assert d["day_rate_used"] == DAY_RATE
    assert d["day_rate_derived"] == round(175_000.0 * 90.0 / 590.0, 2)
    assert d["gap_dollars"] == round(175_000.0 * 90.0 / 590.0 - DAY_RATE, 2)


# --- property 1 and 6: Layer 1 off ------------------------------------------------------------

def _result(cost, days, *, base_layer=None):
    return SimpleNamespace(
        cost_dollars_array=np.asarray(cost, float), schedule_days_array=np.asarray(days, float),
        project_finish_days=300.0 + np.asarray(days, float), day_rate=DAY_RATE,
        base_layer=base_layer)


def test_layer1_off_draws_no_base_and_says_so():
    from src.am.integrated_views import jcl_basis_sentence

    rng = np.random.default_rng(2)
    r = _result(rng.gamma(2.0, 1e6, 2000), rng.gamma(2.0, 20.0, 2000))
    assert period_total_cost(r) is None
    j = period_jcl(r, None)
    assert j["base_drawn"] is False and j["declared_base_dollars"] == 0.0
    assert "no base drawn (Layer 1 off)" in jcl_basis_sentence(j)


def test_with_a_base_the_budget_is_base_plus_contingency():
    rng = np.random.default_rng(3)
    n = 2000
    base = {"base_array": rng.normal(50e6, 2e6, n), "base_total_dollars": 50e6,
            "excluded_factors": []}
    r = _result(rng.gamma(2.0, 1e6, n), rng.gamma(2.0, 20.0, n), base_layer=base)
    total = period_total_cost(r)
    j = period_jcl(r, total)
    contingency = float(np.percentile(r.cost_dollars_array + r.schedule_days_array * DAY_RATE, 80))
    assert j["base_drawn"] is True
    assert j["cost_target"] == 50e6 + contingency
    assert j["jcl"] <= min(j["cost_confidence"], j["finish_confidence"])


# --- property 3 and 4: masked leave-one-out on the period route --------------------------------

def _masked_case(n: int = 4000):
    """Three risks: two drive delay, the third is cost-only and the second has zero impact."""
    rng = np.random.default_rng(4)
    fire = rng.random((n, 3)) < np.array([0.5, 0.4, 0.3])
    per_risk_cost = fire * np.array([1e6, 0.0, 4e5]) * rng.random((n, 3))
    weights = np.array([30.0, 0.0])

    def replay(mask: np.ndarray) -> np.ndarray:
        return (np.asarray(mask, float) * weights).sum(axis=1)

    sched_mask = fire[:, :2]
    result = SimpleNamespace(
        cost_dollars_array=per_risk_cost.sum(axis=1), per_risk_cost_array=per_risk_cost,
        risk_ids_all=("R1", "R2", "R3"), schedule_days_array=replay(sched_mask),
        day_rate=DAY_RATE)
    return result, sched_mask, replay


def test_a_risk_with_no_impact_saves_exactly_zero():
    """The point of masking over the force-close re-run: every other draw is held fixed."""
    result, mask, replay = _masked_case()
    loo = period_leave_one_out(result, schedule_risk_ids=("R1", "R2"), fire_mask=mask,
                               replay_delay_days=replay)
    r2 = loo["rows"]["R2"]
    assert r2["saved_dollars"] == 0.0 and r2["delay_days_saved"] == 0.0
    assert loo["rows"]["R1"]["saved_dollars"] > 0
    # A cost-only risk is never replayed: its delay part is zero by construction.
    assert loo["rows"]["R3"]["delay_part_dollars"] == 0.0
    assert loo["replays"] == 2


def test_a_replay_that_does_not_reproduce_the_run_is_refused():
    """Positive control. No fallback to the force-close re-run (brief property 3)."""
    result, mask, replay = _masked_case()
    with pytest.raises(ValueError, match="does not reproduce"):
        period_leave_one_out(result, schedule_risk_ids=("R1", "R2"), fire_mask=mask,
                             replay_delay_days=lambda m: replay(m) + 1e-9)


def test_within_noise_compares_against_the_measured_noise():
    assert within_noise(5.0, 10.0) is True
    assert within_noise(-5.0, 10.0) is True
    assert within_noise(15.0, 10.0) is False
    assert within_noise(1.0, float("nan")) is False


def test_mitigation_dollars_follow_the_counterfactual_rule():
    from src.am.json_writer import _mitigation_dollars

    rows = {"R1": {"saved_dollars": 1000.0, "noise_dollars": 10.0,
                   "delay_days_saved": 0.1, "noise_days": 0.5}}
    m = _mitigation_dollars(rows, "R1", "Proposed")
    assert m["dollars_saved_p80"] == 1000.0
    assert m["within_noise"]["dollars"] is False and m["within_noise"]["days"] is True
    assert _mitigation_dollars(rows, "R1", "Actioned") == {
        "dollars_saved_p80": None, "within_noise": None}
    assert _mitigation_dollars(None, "R1", "Proposed")["dollars_saved_p80"] is None


def test_risk_dollars_are_null_without_the_arm_and_zero_for_a_risk_it_removed():
    from src.am.json_writer import _risk_dollars

    assert set(_risk_dollars(None, "R1").values()) == {None}
    assert set(_risk_dollars({}, "R1").values()) == {0.0}


# --- property 5 and 7: movement, period 0, contingency -----------------------------------------

def test_period_0_carries_null_dollar_movement(tmp_path: Path):
    from src.am.json_writer import _build_delta, _build_trend

    d = _build_delta(headline={"p80_finish": "2026-06-30"}, current_risks=[],
                     previous_period_path=None, current_p80_dollars=7.0e6)
    assert d["period_0"] is True and d["p80_delta_dollars"] is None
    t = _build_trend(data_dir=tmp_path, current_p80="2026-06-30", current_period_end="2026-02-28",
                     current_p80_dollars=7.0e6)
    assert t["periods"] == [{"period_end": "2026-02-28", "p80_finish": "2026-06-30",
                             "contingency_p80_dollars": 7.0e6}]


def _prior(tmp_path: Path, *, integrated: bool) -> Path:
    doc = {"meta": {"period_end_date": "2026-02-28"},
           "headline": {"p80_finish": "2026-06-30"},
           "risks": [{"risk_id": "R1", "title": "one", "days_at_risk_p80": 2.0, "status": "open",
                      **({"cost_p80_contribution_dollars": 100_000.0} if integrated else {})}]}
    if integrated:
        doc["integrated"] = {"p80_dollars": 7.0e6}
    p = tmp_path / "period_20260228.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_dollar_movement_against_a_1_6_prior(tmp_path: Path):
    from src.am.json_writer import _build_delta, _build_trend

    prev = _prior(tmp_path, integrated=True)
    curr = [{"risk_id": "R1", "title": "one", "days_at_risk_p80": 6.0, "status": "open",
             "cost_p80_contribution_dollars": 350_000.0}]
    d = _build_delta(headline={"p80_finish": "2026-07-10"}, current_risks=curr,
                     previous_period_path=prev, current_p80_dollars=7.5e6)
    assert d["p80_delta_dollars"] == 500_000.0
    assert d["worse"][0]["delta_dollars"] == 250_000.0
    t = _build_trend(data_dir=tmp_path, current_p80="2026-07-10", current_period_end="2026-03-31",
                     current_p80_dollars=7.5e6)
    assert [p["contingency_p80_dollars"] for p in t["periods"]] == [7.0e6, 7.5e6]


def test_a_1_5_prior_gives_null_dollar_movement_not_a_guess(tmp_path: Path):
    from src.am.json_writer import _build_delta

    prev = _prior(tmp_path, integrated=False)
    curr = [{"risk_id": "R1", "title": "one", "days_at_risk_p80": 6.0, "status": "open",
             "cost_p80_contribution_dollars": 350_000.0}]
    d = _build_delta(headline={"p80_finish": "2026-07-10"}, current_risks=curr,
                     previous_period_path=prev, current_p80_dollars=7.5e6)
    assert d["p80_delta_dollars"] is None and d["worse"][0]["delta_dollars"] is None


def test_the_contingency_block_is_phase_one_with_the_2b_shape():
    c = contingency_block(7_366_574.6)
    assert c["phase"] == "recommended" and c["label"] == "Recommended at P80"
    assert c["required_p80_dollars"] == 7_366_574.6 and c["held_dollars"] is None
    for key in ("commitment_date", "opening_held_dollars", "approved_draws_dollars",
                "pending_draws_dollars", "releases_dollars", "shortfall_dollars",
                "jcl_against_held", "bridge"):
        assert key in c and c[key] is None


# --- the gate: period 0 agrees with the report exactly -----------------------------------------

@pytest.fixture(scope="module")
def wind_project():
    import src.sra.cpm.bindings.synthetic_wind  # noqa: F401  self-registers

    saved = os.environ.get("QRA_PROJECT")
    os.environ["QRA_PROJECT"] = "synthetic_wind"
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("QRA_PROJECT", None)
        else:
            os.environ["QRA_PROJECT"] = saved


@pytest.fixture(scope="module")
def report_side(wind_project) -> dict:
    """The report's numbers, by the deliverable's own Stage 3 sequence (``run_engines``)."""
    from src.final.deliverable import _stage3_beta_dict
    from src.final.sections.integrated_total import (
        SUMMARY_P_LEVELS, stage3_jcl, total_cost_data,
    )
    from src.integrated.base_layer import deliverable_base_layer
    from src.integrated.integrated_simulation_stage3 import run_integrated_simulation_stage3
    from src.integrated.leave_one_out import stage3_leave_one_out
    from src.integrated.stage3_config import build_stage3_config, build_stage3_rules_from_scope
    from src.sra.cpm.auto_mapper import expand_auto_rules
    from src.sra.cpm.graph_builder import build_schedule_graph
    from src.sra.cpm.xer_reader import parse_xer
    from src.sra.strawman_reader import read_risk_scope
    from src.v5_register_reader import read_risks_v5

    s3 = build_stage3_config(
        register_path=WIND_REGISTER, xer_path=WIND_XER, strawman_path=WIND_REGISTER,
        iterations=ITERATIONS, seed=SEED, project="synthetic_wind",
        caller_module="tests/test_intview01_stage2.py")
    risks = read_risks_v5(str(WIND_REGISTER))
    scope = read_risk_scope(str(WIND_REGISTER))
    xer = parse_xer(str(WIND_XER))
    graph = build_schedule_graph(xer)
    drivers = expand_auto_rules(build_stage3_rules_from_scope(scope, graph, s3.binding_config),
                                graph)
    r = run_integrated_simulation_stage3(s3, risks=risks, risk_scope_df=scope,
                                         schedule_graph=graph, risk_drivers=drivers,
                                         xer_tables=xer)
    rate = s3.integrated_config.day_rate
    # RISKDRV-01 stage 2: the report side carries the register's shared drivers as
    # src.final.deliverable.run_engines does, so both sides read the owner view.
    from src.integrated.driver_pass import (
        build_duration_shift, driver_rows, load_checked_drivers, stage3_owner_view)
    shared = load_checked_drivers(WIND_REGISTER, xer)
    base = deliverable_base_layer(WIND_REGISTER, ITERATIONS, SEED, shared_drivers=shared)
    if shared:
        shift = build_duration_shift(shared, base["driver_deltas"], graph, xer)
        base["owner_view"] = stage3_owner_view(r, s3.schedule_mc_config, shift)
        base["shared_drivers"] = driver_rows(shared, base["owner_view"], base["driver_deltas"])
    cost = np.asarray(r.cost_result["cost_dollars_array"], float)
    days = np.asarray(r.schedule_days_array, float)
    total = total_cost_data(base, cost, days, rate, p_levels=SUMMARY_P_LEVELS)
    return {
        "cost": cost, "days": days, "rate": rate, "total": total,
        "jcl": stage3_jcl(_stage3_beta_dict(r), total, rate),
        "loo": stage3_leave_one_out(r, s3.schedule_mc_config, day_rate=rate),
    }


@pytest.fixture(scope="module")
def period_side(wind_project, tmp_path_factory: pytest.TempPathFactory) -> dict:
    from src.am.run_period import run_period

    if not WIND_01.is_file():
        skip_missing(WIND_01, detail="run scripts/build_wind_am_periods.py")
    path = run_period(
        workbook_path=WIND_01, project="synthetic_wind",
        output_dir=tmp_path_factory.mktemp("intview01"), main_iterations=ITERATIONS,
        days_at_risk_iterations=500, counterfactual_iterations=500, seed=SEED,
        criticality_measurement_mode="both",
        allow_dirty=True)
    return json.loads(path.read_bytes().decode("utf-8"))


@pytest.mark.integration
class TestPeriodZeroAgreesWithTheReport:
    def test_the_period_is_unpinned(self, period_side: dict):
        p = period_side["integrated"]["pinning"]
        assert p["risks_removed"] == p["risks_closed"] == p["risks_reprobabilised"] == 0

    def test_the_jcl_equals_stage3_jcl(self, period_side: dict, report_side: dict):
        j, rj = period_side["integrated"]["jcl"], report_side["jcl"]
        assert j["base_drawn"] is True and rj["base_drawn"] is True
        assert j["jcl"] == round(rj["jcl"], 4)
        assert j["cost_confidence"] == round(rj["cost_confidence"], 4)
        assert j["finish_confidence"] == round(rj["finish_confidence"], 4)
        assert j["cost_target_dollars"] == round(rj["cost_target"], 2)
        assert j["declared_base_dollars"] == round(rj["declared_base_dollars"], 2)

    def test_the_total_cost_equals_the_reports_table(self, period_side: dict, report_side: dict):
        tc, rt = period_side["integrated"]["total_cost"], report_side["total"]
        assert tc["declared_base_dollars"] == round(rt["base_total_dollars"], 2)
        assert {r["p_level"]: r["total_dollars"] for r in tc["rows"]} == {
            p: round(v, 2) for p, v in rt["percentiles_dollars"].items()}

    def test_the_contingency_is_the_reports_headline(self, period_side: dict, report_side: dict):
        p80 = float(np.percentile(report_side["cost"] + report_side["days"] * report_side["rate"],
                                  80))
        assert period_side["integrated"]["p80_dollars"] == round(p80, 2)
        assert period_side["contingency"]["required_p80_dollars"] == round(p80, 2)
        assert period_side["integrated"]["build_up"][1]["joint_contingency_dollars"] == round(
            p80, 2)

    def test_per_risk_dollars_equal_the_reports_leave_one_out(
            self, period_side: dict, report_side: dict):
        want = {r["risk_id"]: r for r in report_side["loo"]["rows"]}
        rows = period_side["risks"]
        assert rows and all(r["cost_p80_contribution_dollars"] is not None for r in rows)
        for r in rows:
            w = want[r["risk_id"]]
            assert r["cost_p80_contribution_dollars"] == round(w["saved_dollars"], 2)
            assert r["cost_part_dollars"] == round(w["cost_part_dollars"], 2)
            assert r["delay_part_dollars"] == round(w["delay_part_dollars"], 2)
        assert period_side["integrated"]["leave_one_out"]["replays"] == report_side["loo"][
            "replays"]

    def test_period_0_carries_nulls(self, period_side: dict):
        assert period_side["delta"]["period_0"] is True
        assert period_side["delta"]["p80_delta_dollars"] is None
        assert len(period_side["trend"]["periods"]) == 1
