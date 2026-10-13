"""STAGE3HEADLINE-01: the deliverable's headline is the Stage 3 distribution, and the gate can fail.

Director, 10/09/2026, D-1 to D-5 signed as recommended: a percentile range on the one Stage 3
distribution (P50 / P80 / P95) with its basis said on the page; Stage 2.5 retained as a labelled
comparator beside the reconciliation, never the headline and never a gate; cross-validation's
schedule ranking re-based onto Stage 3; check 2 replaced by a cross-surface comparison of the
two surfaces' Stage 3 P80 delay, because the check it replaces compared two copies of one
additive formula and could not fail (F-42); the path-crossover diagnostic compares delay with
delay (F-40).

Everything here is synthetic except the last test, which runs both surfaces on the committed
road fixture and is the G-1 / G-2 evidence: the new limb goes RED at tolerance zero on real
inputs before its pass is trusted.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from src.final.cross_validator import cross_validate_reports
from src.final.headline import (
    STAGE3_HEADLINE_BASIS,
    STAGE3_SCENARIO_NAME,
    integrated_dollars_array,
    stage3_headline,
)
from src.final.sections.criticality import _apply_stage3_headline, _compute_path_crossover_delta
from src.final.sections.page1_table import _compute_component_breakdown

_RNG = np.random.default_rng(11)


def _arrays(n=4000, cost_mu=5.0e6, days_mu=60.0):
    cost = _RNG.gamma(20.0, cost_mu / 20.0, n)
    days = _RNG.gamma(4.0, days_mu / 4.0, n)
    return cost, days


# ---------------------------------------------------------------------------
# P1 / D-1: the headline block is percentiles of the one Stage 3 distribution
# ---------------------------------------------------------------------------

def test_headline_is_percentiles_of_one_distribution():
    cost, days = _arrays()
    h = stage3_headline(cost, days, day_rate=35_000.0)
    total = cost + days * 35_000.0
    assert h["p_levels"] == (50, 80, 95)
    for p in (50, 80, 95):
        assert h[f"p{p}_dollars"] == float(np.percentile(total, p))
    assert h["mean_dollars"] == float(np.mean(total))
    assert h["headline_dollars"] == h["p80_dollars"] and h["headline_metric"] == "P80"
    assert h["basis"] == STAGE3_HEADLINE_BASIS
    assert "lower_bound_dollars" not in h, "there is one distribution; nothing to label lower or upper"


def test_headline_metric_mean_leads_with_the_mean():
    cost, days = _arrays()
    h = stage3_headline(cost, days, day_rate=1.0, headline_metric="Mean")
    assert h["headline_dollars"] == h["mean_dollars"] and h["headline_metric"] == "Mean"


def test_the_two_surfaces_share_one_derivation():
    """P2: the app's period cycle and the deliverable dollarise through the same function."""
    cost, days = _arrays(n=50)
    assert np.array_equal(integrated_dollars_array(cost, days, 3.0), cost + days * 3.0)
    with pytest.raises(ValueError, match="differ"):
        integrated_dollars_array(cost, days[:-1], 3.0)


def test_the_composed_dict_leads_with_stage3_and_labels_the_mode_range_as_comparator():
    cost, days = _arrays()
    composed = {
        "integrated_section": {"day_rate": 35_000.0, "p_level": 80, "scenarios": {}},
        "executive_summary": {"headline_contingency_range_p80": {"lower_bound_dollars": 1.0,
                                                                  "headline_metric": "P80"}},
    }
    _apply_stage3_headline(composed, {"cost_dollars_array": cost, "schedule_days_array": days,
                                      "risk_ids_all": ["R1"], "risk_ids_dual": ["R1"],
                                      "iterations": cost.size})
    h = composed["executive_summary"]["headline_stage3"]
    assert h["p80_dollars"] == float(np.percentile(cost + days * 35_000.0, 80))
    assert "comparator" in composed["executive_summary"]["headline_contingency_range_p80"]["basis"]
    assert STAGE3_SCENARIO_NAME.lower() in composed["integrated_section"]
    assert composed["integrated_section"]["stage3"]["iterations"] == cost.size


def test_page_one_breakdown_reads_the_named_basis_not_the_resolver_default():
    """The page-one figure a reader sees comes from the named headline basis.

    PRESENT-01 (D-4): the contrast was against the mode-resolved default. The resolver still
    answers DP_Review; it just no longer takes a mode to answer it.
    """
    cost, days = _arrays()
    family = {
        "DP_Review": {"cost_dollars_array": cost * 0.5, "schedule_days_array": days * 0.5},
        STAGE3_SCENARIO_NAME: {"cost_dollars_array": cost, "schedule_days_array": days},
    }
    by_default = _compute_component_breakdown(family, day_rate=1.0)
    by_name = _compute_component_breakdown(family, day_rate=1.0,
                                           indicative_name=STAGE3_SCENARIO_NAME)
    assert by_default["integrated_p80_dollars"] == float(np.percentile(cost * 0.5 + days * 0.5, 80))
    assert by_name["integrated_p80_dollars"] == float(np.percentile(cost + days, 80))


def test_the_waterfall_decomposes_the_named_basis():
    """Review B3: every chart read the Mode family. The waterfall is the one with a data path
    that can be asserted without rendering; it must decompose the named headline basis."""
    from src.final.sections.page1_table import _waterfall_components
    cost, days = _arrays()
    family = {
        "DP_Review": {"cost_dollars_array": cost * 0.5, "schedule_days_array": days * 0.5},
        STAGE3_SCENARIO_NAME: {"cost_dollars_array": cost, "schedule_days_array": days},
    }
    # Unnamed, the resolver answers DP_Review and the waterfall decomposes that instead.
    by_default = _waterfall_components(family, 1.0)
    default_total = next(c for c in by_default if c["category"] == "total")
    assert abs(default_total["value"]
               - float(np.percentile(cost * 0.5 + days * 0.5, 80)) / 1e6) < 1e-9

    comps = _waterfall_components(family, 1.0, indicative_name=STAGE3_SCENARIO_NAME)
    total = next(c for c in comps if c["category"] == "total")
    assert abs(total["value"] - float(np.percentile(cost + days, 80)) / 1e6) < 1e-9


def test_the_executive_summary_names_its_bases_when_stage3_leads(tmp_path):
    """Review B2 / W4 / W7: the drivers' basis labels, the Mode column and the schedule note
    all say what they are when Stage 3 leads. The page-one HTML strings are built on the v3
    path, which reads real register files; they are evidenced by the production run in the
    brief's §15 rather than here."""
    from tests.final.test_composer_beta_passthrough import (
        _build_inputs, _build_synthetic_stage3_beta_result, _config_for_tmp,
    )
    from src.final.composer import compose_final_report_data
    cost, sched, integ_by, sched_by, cv, titles = _build_inputs()
    composed = compose_final_report_data(
        cost_results=cost, schedule_results=sched, integrated_results_by_scenario=integ_by,
        schedule_results_by_scenario=sched_by, strawman_path=tmp_path / "strawman.xlsx",
        register_path=tmp_path / "register.xlsx", cross_validation=cv, risk_titles=titles,
        stage3_beta_result=_build_synthetic_stage3_beta_result(), config=_config_for_tmp(tmp_path),
    )
    es = composed["executive_summary"]
    assert es["headline_stage3"] is not None
    assert "additive" in es["schedule_drivers_basis"]
    assert all(d["mode"] == "n/a" for d in es["top_3_schedule_drivers"])
    assert es["cost_drivers_basis"].startswith("Stage 3 cost arm")
    assert "comparator basis" in es["schedule_basis_note"] and "CPMATTRIB-01" in es["schedule_basis_note"]
    assert "comparator" in es["headline_contingency_range_p80"]["basis"]


# ---------------------------------------------------------------------------
# D-5 / F-40: delay against delay
# ---------------------------------------------------------------------------

def test_path_crossover_compares_delay_with_delay():
    s25 = np.full(100, 70.0)
    s3 = np.full(100, 91.0)
    s25_p80, s3_p80, delta, warn = _compute_path_crossover_delta(
        {"schedule_days_array": s25},
        {"schedule_days_array": s3, "schedule_result": SimpleNamespace(project_finish_days=np.full(100, 400.0))},
    )
    assert (s25_p80, s3_p80, delta, warn) == (70.0, 91.0, -21.0, False), (
        "the Stage 3 side must be the delay array, not the absolute finish the result object carries"
    )


# ---------------------------------------------------------------------------
# D-3 / F-42 / D-4: the gate's schedule limbs run on Stage 3, and check 2 can fail
# ---------------------------------------------------------------------------

def _gate_inputs(tmp_path):
    n, ids = 600, ["R1", "R2", "R3", "R4"]
    per_cost = _RNG.gamma(2.0, 10_000.0, size=(n, 4))
    cost_results = {"cost_dollars_array": per_cost.sum(axis=1), "per_risk_cost_array": per_cost, "risk_ids": ids}
    sr5 = _RNG.gamma(2.0, [1.0, 2.0, 3.0, 4.0], size=(n, 4))
    schedule_results = {"finish_delay_days_array": sr5.sum(axis=1), "contribution_array": sr5, "risk_ids": ids}
    integrated = {
        "cost_dollars_array": per_cost.sum(axis=1), "schedule_days_array": sr5.sum(axis=1),
        "per_risk_cost_array": per_cost, "per_risk_schedule_array": sr5,
        "risk_ids_all": ids, "risk_ids_dual": ids,
    }
    # Stage 3 ranks the contributors the other way round
    s3_sched = sr5[:, ::-1]
    stage3 = {**integrated, "per_risk_schedule_array": s3_sched, "risk_ids_dual": ids,
              "schedule_days_array": s3_sched.sum(axis=1)}
    strawman = tmp_path / "strawman.xlsx"
    strawman.write_bytes(b"")
    from dataclasses import replace
    from src.integrated.integrated_simulation import IntegratedConfig
    from src.sra.methodology_defaults_reader import build_test_methodology_defaults
    from tests._fixture_values import FIXTURE_DAY_RATE
    from tests.conftest import TEST_CALIBRATION_TOLERANCES
    cfg = replace(
        IntegratedConfig(register_path=strawman, p6_path=strawman, strawman_path=strawman,
                         methodology_defaults=build_test_methodology_defaults(),
                         day_rate=FIXTURE_DAY_RATE, **TEST_CALIBRATION_TOLERANCES),
        # calibration limbs are not under test here: only the ranking and cross-surface limbs
        cost_calibration_tolerance_dollars=1e12, cost_calibration_tolerance_pct=1.0,
        schedule_calibration_tolerance_days=1e9, schedule_calibration_tolerance_pct=1.0,
    )
    return cost_results, schedule_results, integrated, stage3, strawman, cfg


def test_check_4_ranks_against_stage3_when_supplied(tmp_path):
    cost, sched, integ, stage3, strawman, cfg = _gate_inputs(tmp_path)
    legacy = cross_validate_reports(cost, sched, integ, strawman, config=cfg)
    rebased = cross_validate_reports(cost, sched, integ, strawman, config=cfg, stage3_results=stage3)
    # D-6 Option A (Director, 10/09/2026): the Stage 3 result's per-risk schedule array is
    # the cost arm's additive, Mode-scaled draw and the kernel attributes nothing per risk,
    # so the ranking is additive on both sides and the gate must say so on its face.
    assert legacy["schedule_top3_engine"].startswith("Stage 2.5 integrated arm (additive")
    assert "NOT the CPM replay" in rebased["schedule_top3_engine"]
    assert legacy["top_3_schedule_contributors_consistent"] is True
    assert rebased["top_3_schedule_contributors_consistent"] is False, (
        "the supplied arrays rank the contributors the other way, and the check must see it"
    )
    assert "cannot fail on the headline engine" in rebased["coverage"]["check_4_schedule_ranking"]
    assert "CPMATTRIB-01" in rebased["coverage"]["check_4_schedule_ranking"]
    assert rebased["schedule_top3_basis"] == "stage3_cost_arm_additive"
    assert legacy["schedule_top3_basis"] == "register_mode_baseline"


def test_check_2_is_the_cross_surface_comparison_and_can_fail(tmp_path):
    cost, sched, integ, stage3, strawman, cfg = _gate_inputs(tmp_path)
    xs = dict(deliverable_delay_days=91.4, period_delay_days=90.9, p_level=80, n_iter=2000, seed=42,
              tolerance_days=1.0, tolerance_pct=0.0)
    passing = cross_validate_reports(cost, sched, integ, strawman, config=cfg, cross_surface=xs)
    failing = cross_validate_reports(cost, sched, integ, strawman, config=cfg,
                                     cross_surface={**xs, "tolerance_days": 0.0})
    assert passing["schedule_check_basis"] == "stage3_cross_surface"
    assert passing["schedule_passes_calibration"] is True
    assert failing["schedule_passes_calibration"] is False and failing["all_pass"] is False
    assert abs(passing["cross_surface_gap_days"] - 0.5) < 1e-9
    assert "shared kernel" in passing["coverage"]["check_2_schedule"]
    assert "FAIL" in failing["interpretation"] and "cross-surface" in failing["interpretation"]


def test_the_legacy_schedule_check_says_it_cannot_fail(tmp_path):
    """P4: without the cross-surface input the gate's own output states the limb has no power."""
    cost, sched, integ, stage3, strawman, cfg = _gate_inputs(tmp_path)
    legacy = cross_validate_reports(cost, sched, integ, strawman, config=cfg)
    assert legacy["schedule_check_basis"] == "stage25_sr5_legacy"
    assert "cannot fail" in legacy["coverage"]["check_2_schedule"]
    assert "F-42" in legacy["interpretation"]


# ---------------------------------------------------------------------------
# G-1 / G-2 on real inputs: both surfaces on the road fixture, matched iterations
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_cross_surface_agrees_exactly_and_reds_when_one_side_is_perturbed(monkeypatch, tmp_path):
    """G-1 and G-2 on real inputs. Both surfaces run the committed road fixture at 2,000
    iterations, seed 42: the deliverable through build_stage3_rules_from_scope, the period
    engine through the AM cycle's driver build and its pinning step with an empty workbook.

    Measured 10/09/2026: they agree EXACTLY (gap 0.0 days). The 0.41-day gap the brief
    evidenced was GENERICINJ-01's broadcast route, fixed the same day; with one rule builder
    and one kernel the two assemblies are the same computation. So the limb's power is
    shown the way G-1 says: perturb one side and the gate reds. A future divergence in how
    either surface assembles a Stage 3 run - the GENERICINJ-01 class - reds it the same way."""
    import importlib
    from pathlib import Path
    from src.final.deliverable import DeliverableInputs, stage3_cross_surface
    from src.integrated.integrated_simulation_stage3 import run_integrated_simulation_stage3
    from src.integrated.stage3_config import build_stage3_config, build_stage3_rules_from_scope
    from src.sra.cpm.auto_mapper import expand_auto_rules
    from src.sra.cpm.graph_builder import build_schedule_graph
    from src.sra.cpm.xer_reader import parse_xer
    from src.sra.strawman_reader import read_risk_scope
    from src.v5_register_reader import read_risks_v5

    monkeypatch.setenv("QRA_PROJECT", "synthetic_road")
    importlib.import_module("src.sra.cpm.bindings.synthetic_road")
    d = Path("tests/fixtures/synthetic_road")
    register, xer = d / "road_register.xlsx", d / "road_schedule.xer"
    s3_cfg = build_stage3_config(register_path=register, xer_path=xer, strawman_path=register,
                                 iterations=2000, seed=42, caller_module="tests")
    tables = parse_xer(xer)
    graph = build_schedule_graph(tables)
    scope = read_risk_scope(register)
    drivers = expand_auto_rules(build_stage3_rules_from_scope(scope, graph, s3_cfg.binding_config), graph)
    stage3 = run_integrated_simulation_stage3(
        s3_cfg, risks=read_risks_v5(str(register)), risk_scope_df=scope, schedule_graph=graph,
        risk_drivers=drivers, xer_tables=tables)
    inputs = SimpleNamespace(register_path=register, p6_path=xer, strawman_path=register,
                             project="synthetic_road")
    engines = SimpleNamespace(stage3_result=stage3, stage3_config=s3_cfg)
    xs = stage3_cross_surface(inputs, engines)
    assert xs["deliverable_delay_days"] == xs["period_delay_days"], xs

    # Positive control: the period side at a different seed is a different assembly, and
    # the gate must see it at the tolerance it will run with.
    perturbed = SimpleNamespace(stage3_result=SimpleNamespace(
        iterations=stage3.iterations, seed_used=stage3.seed_used + 1,
        schedule_graph=stage3.schedule_graph, xer_tables=stage3.xer_tables,
        schedule_days_array=stage3.schedule_days_array,
        config_summary=stage3.config_summary), stage3_config=s3_cfg)
    xs_bad = stage3_cross_surface(inputs, perturbed)
    assert xs_bad["deliverable_delay_days"] != xs_bad["period_delay_days"], xs_bad
    from src.final.cross_validator import cross_validate_reports as _cv
    cost, sched, integ, _, strawman, cfg = _gate_inputs(tmp_path)  # never the fixture directory
    assert _cv(cost, sched, integ, strawman, config=cfg,
               cross_surface={**xs_bad, "tolerance_days": 0.0, "tolerance_pct": 0.0})["all_pass"] is False


@pytest.mark.slow
def test_d7_baseline_coincides_with_minimum_finish_on_road_fixture(monkeypatch):
    """D-7 re-review NOTE (item 12): the zero-risk pass and the old ``min(project_finish_days)``
    proxy it replaced are bit-identical only when working_hours_per_day is a power of two and
    some iteration fires no risk. Both hold on the road fixture today, and nothing in the tree
    asserted it - the coincidence could silently stop holding under a future fixture or
    calendar change without anyone noticing the baseline had drifted. This pins it: a red here
    means one of the two preconditions broke, not that D-7's baseline (the pass, not the proxy)
    is wrong."""
    import importlib
    from pathlib import Path
    from src.integrated.integrated_simulation_stage3 import run_integrated_simulation_stage3
    from src.integrated.stage3_config import build_stage3_config, build_stage3_rules_from_scope
    from src.sra.cpm.auto_mapper import expand_auto_rules
    from src.sra.cpm.deterministic import deterministic_finish_hours
    from src.sra.cpm.graph_builder import build_schedule_graph
    from src.sra.cpm.xer_reader import parse_xer
    from src.sra.strawman_reader import read_risk_scope
    from src.v5_register_reader import read_risks_v5

    monkeypatch.setenv("QRA_PROJECT", "synthetic_road")
    importlib.import_module("src.sra.cpm.bindings.synthetic_road")
    d = Path("tests/fixtures/synthetic_road")
    register, xer = d / "road_register.xlsx", d / "road_schedule.xer"
    s3_cfg = build_stage3_config(register_path=register, xer_path=xer, strawman_path=register,
                                 iterations=2000, seed=42, caller_module="tests")
    tables = parse_xer(xer)
    graph = build_schedule_graph(tables)
    scope = read_risk_scope(register)
    drivers = expand_auto_rules(build_stage3_rules_from_scope(scope, graph, s3_cfg.binding_config), graph)
    stage3 = run_integrated_simulation_stage3(
        s3_cfg, risks=read_risks_v5(str(register)), risk_scope_df=scope, schedule_graph=graph,
        risk_drivers=drivers, xer_tables=tables)

    hpd = float(graph.project_default_calendar.working_hours_per_day)
    precision = stage3.config_summary["schedule_mc"]["precision"]
    pass_days = deterministic_finish_hours(graph, precision=precision) / hpd
    proxy_days = float(np.min(stage3.schedule_result.project_finish_days))

    assert pass_days == proxy_days, (
        f"pass={pass_days} proxy={proxy_days}: the road fixture no longer satisfies both "
        "D-7 preconditions (power-of-two hours-per-day; some iteration fires no risk)"
    )


@pytest.mark.slow
def test_stage3_leading_compose_never_feeds_mode_multiplier_the_page4_na_fill(monkeypatch, tmp_path):
    """Re-review-of-the-re-review BLOCKER (numerics, 10/09/2026): item 3's fix built
    ``mode_used = {rid: "n/a" for rid in ...}`` for the page-4 drivers table, but composer had
    only ONE mode_used variable, and a second consumer - ``enrich_tail_risk_for_matrix`` - feeds
    it to ``resolve_mode_multiplier``, which raises for any label the register's Mode grid does
    not define. "n/a" is such a label. The crash is register-data-dependent (only fires when
    the picked tail risk is dual-coded), so it did not show up on the Kestrel production run.

    Fixed by splitting into two variables: ``mode_used`` (the real, possibly-empty scenario
    dict, unchanged from before item 3) feeds the matrix enrichment; ``page4_mode_used`` (the
    "n/a" fill) feeds only the page-4 display table. This test does not depend on the road
    fixture happening to pick a dual-coded tail risk - it intercepts the call and asserts the
    dict handed to the multiplier-resolving function never carries the display-only fill,
    which is true regardless of which risk gets picked."""
    import src.final.composer as composer_module

    monkeypatch.setenv("QRA_PROJECT", "synthetic_road")
    monkeypatch.setenv("REGISTER_FILE", "tests/fixtures/synthetic_road/road_register.xlsx")
    monkeypatch.setenv("STRAWMAN_FILE", "tests/fixtures/synthetic_road/road_register.xlsx")
    monkeypatch.setenv("P6_FILE", "tests/fixtures/synthetic_road/road_schedule.xer")
    monkeypatch.setenv("SR9_ITERATIONS", "2000")
    monkeypatch.setenv("SR9_SEED", "42")

    real_enrich = composer_module.enrich_tail_risk_for_matrix
    captured: dict[str, dict] = {}

    def _spy(tail_risk, risks, mode_used, variant_label, *, mode_multipliers):
        captured["mode_used"] = dict(mode_used or {})
        captured["mode_multipliers"] = dict(mode_multipliers)
        return real_enrich(
            tail_risk, risks=risks, mode_used=mode_used, variant_label=variant_label,
            mode_multipliers=mode_multipliers,
        )

    monkeypatch.setattr(composer_module, "enrich_tail_risk_for_matrix", _spy)

    from src.final.deliverable import run_deliverable

    run = run_deliverable(output_dir=tmp_path)
    run.raise_if_failed()

    assert captured, "enrich_tail_risk_for_matrix was never called - fixture regressed under it"
    # schedule_results_by_scenario never carries a "Stage3" key, so when Stage 3 leads this is
    # deterministically {} regardless of which risk gets picked as the tail risk - not a
    # fixture-dependent check. The pre-fix bug population it with {rid: "n/a", ...} instead;
    # asserting emptiness here is equivalent to asserting no "n/a" (or anything else outside
    # the register's Mode grid) reaches resolve_mode_multiplier.
    assert captured["mode_used"] == {}, (
        f"expected {{}} (Stage 3 has no Mode-scenario family) but got {captured['mode_used']!r} "
        "- if this is the page-4 'n/a' fill leaking into the matrix-enrichment call again, "
        "resolve_mode_multiplier will raise on a real register whose tail risk is dual-coded"
    )
