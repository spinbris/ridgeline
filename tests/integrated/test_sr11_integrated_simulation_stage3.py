"""SR11 — Stage 3 Beta integrated engine tests.

Synthetic-input tests covering:

* Engine joint-sampling preservation across cost + Stage 3 Beta schedule.
* Cost-arm bit-identity parity with the Stage 2.5 integrated engine at
  the seed-paired level (Acceptance Criterion 3).
* Output dict shape compatible with composer adapter.
* IterationConfig __post_init__ guards.
* Variant-label resolution.
* Schedule-days-array semantics (zero-baseline at the floor).

These tests construct synthetic ScheduleGraph + RiskDriver objects and
synthetic RiskInput lists; no RefProject .xer or register .xlsx is touched.
The reusability invariant per Beta-00.3 is locked.
"""

from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES
from tests.conftest import TEST_MODE_MULTIPLIERS

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config import RiskInput
from src.integrated.integrated_simulation import (
    IntegratedConfig,
    run_integrated_simulation,
)
from src.integrated.integrated_simulation_stage3 import (
    IntegratedConfigStage3,
    Stage3IntegratedResult,
    adapt_to_integrated_results_shape,
    run_integrated_simulation_stage3,
    _resolve_variant_label,
)
from src.integrated.stage3_inputs import (
    Stage3BindingConfig,
    build_joint_severity_uniforms,
)
from src.sra.cpm.calendar import Calendar
from src.sra.cpm.cpm_simulation import ScheduleMCConfig
from src.sra.cpm.graph import Activity, Link, ScheduleGraph
from src.sra.cpm.risk_driver_schema import RiskDriver
from src.sra.methodology_defaults_reader import build_test_methodology_defaults
from tests._fixture_values import FIXTURE_DAY_RATE


# ---------------------------------------------------------------------------
# Synthetic helpers
# ---------------------------------------------------------------------------

_CAL = Calendar()


def _risk(
    risk_id: str,
    *,
    probability: float = 0.5,
    opt_cost: float = 100.0,
    ml_cost: float = 200.0,
    pess_cost: float = 400.0,
    correlation_group: str = "CG_UNASSIGNED",
) -> RiskInput:
    return RiskInput(
        risk_id=risk_id,
        description=f"Synthetic {risk_id}",
        owner="BOP Contractor",
        distribution="PERT",
        correlation_group=correlation_group,
        probability=probability,
        opt_cost=opt_cost,
        ml_cost=ml_cost,
        pess_cost=pess_cost,
    )


def _scope_row(
    rid: str, *, mode: str = "Series",
    opt_d: float = 1.0, ml_d: float = 5.0, pess_d: float = 10.0,
    prob_time: float = 0.5,
) -> dict:
    return {
        "risk_id": rid,
        "time_impact": "Yes",
        "mode_aggregated": mode,
        "probability_time": prob_time,
        "opt_days": opt_d,
        "ml_days": ml_d,
        "pess_days": pess_d,
    }


def _make_graph() -> ScheduleGraph:
    """3-activity chain: a1→a2→a3 each 80 hours = 10 working days."""
    acts = [
        Activity(
            id=f"a{i}", code=f"10.{i}.X", name=f"a{i}", task_type="TT_Task",
            original_duration_hours=80.0,
            total_float_hours=0.0, calendar_id=None,
        )
        for i in (1, 2, 3)
    ]
    links = [
        Link(pred_id="a1", succ_id="a2", link_type="FS", lag_hours=0.0),
        Link(pred_id="a2", succ_id="a3", link_type="FS", lag_hours=0.0),
    ]
    act_map = {a.id: a for a in acts}
    for link in links:
        act_map[link.pred_id].successor_links.append(link)
        act_map[link.succ_id].predecessor_links.append(link)
    return ScheduleGraph(
        activities=act_map, links=links,
        topo_order=["a1", "a2", "a3"],
        project_default_calendar=_CAL,
    )


def _make_drivers(risk_ids: tuple[str, ...]) -> dict[str, RiskDriver]:
    return {
        rid: RiskDriver(
            risk_id=rid,
            affected_activity_ids=("a1", "a2"),
            injection_method="additive_pert_days",
            opt_pert=1.0,
            ml_pert=2.0,
            pess_pert=4.0,
            probability=0.5,
            derived_at_run_time=False,
            workshop_validated=True,
            mode="Series",
        )
        for rid in risk_ids
    }


def _make_config(
    *,
    iterations: int = 200,
    seed: int = 42,
    binding_strawman_path: Path | None = None,
) -> IntegratedConfigStage3:
    bind = Stage3BindingConfig(
        register_path=Path("/synthetic/register.xlsx"),
        xer_path=Path("/synthetic/full_report.xer"),
        strawman_path=binding_strawman_path
        or Path("/synthetic/strawman.xlsx"),
        float_threshold_hours=480.0,
    default_injection_method="discrete_event_additive_days")
    int_cfg = IntegratedConfig(
        register_path=bind.register_path,
        p6_path=bind.xer_path,
        strawman_path=bind.strawman_path,
        iterations=iterations,
        random_seed=seed,
        day_rate=100_000.0,
        methodology_defaults=build_test_methodology_defaults(),
    **TEST_CALIBRATION_TOLERANCES)
    sched_cfg = ScheduleMCConfig(
        n_iter=iterations, batch_size=min(50, iterations), seed=seed,
    mode_multipliers=TEST_MODE_MULTIPLIERS)
    return IntegratedConfigStage3(
        integrated_config=int_cfg,
        schedule_mc_config=sched_cfg,
        binding_config=bind,
    )


def _build_inputs(
    iterations: int = 200,
    seed: int = 42,
    n_cost_only: int = 3,
    dual_coded: tuple[str, ...] = ("R013", "R067"),
):
    """Construct (cfg, risks, scope_df, graph, drivers, severity_uniforms)."""
    cfg = _make_config(iterations=iterations, seed=seed)
    risks = (
        [_risk(f"R{i:03d}_co", probability=0.3) for i in range(n_cost_only)]
        + [_risk(rid, probability=0.5) for rid in dual_coded]
    )
    scope_df = pd.DataFrame([_scope_row(rid) for rid in dual_coded])
    graph = _make_graph()
    drivers = _make_drivers(dual_coded)
    rng = np.random.default_rng(seed)
    risk_ids_all = tuple(r.risk_id for r in risks)
    severity = build_joint_severity_uniforms(
        risk_ids=risk_ids_all, n_iter=iterations, rng=rng, precision="float32",
    )
    xer_tables = {"TASK": pd.DataFrame(), "PROJWBS": pd.DataFrame()}
    return cfg, risks, scope_df, graph, drivers, severity, xer_tables


# ---------------------------------------------------------------------------
# Test 1 — Config validates iteration-count parity
# ---------------------------------------------------------------------------

def test_iteration_count_mismatch_raises_at_config_construction():
    int_cfg = IntegratedConfig(
        register_path=Path("/x/register.xlsx"),
        p6_path=Path("/x/p6.xlsx"),
        strawman_path=Path("/x/strawman.xlsx"),
        iterations=100,
        methodology_defaults=build_test_methodology_defaults(),
        day_rate=FIXTURE_DAY_RATE,
    **TEST_CALIBRATION_TOLERANCES)
    sched_cfg = ScheduleMCConfig(n_iter=200, mode_multipliers=TEST_MODE_MULTIPLIERS)  # mismatch
    with pytest.raises(ValueError, match="iteration counts differ"):
        IntegratedConfigStage3(
            integrated_config=int_cfg, schedule_mc_config=sched_cfg,
            binding_config=Stage3BindingConfig(
                register_path=Path("/x/register.xlsx"), xer_path=Path("/x/p6.xer"),
                strawman_path=Path("/x/strawman.xlsx"), float_threshold_hours=480.0),
        )


# ---------------------------------------------------------------------------
# Test 2 — Smoke run: engine produces both arms' outputs
# ---------------------------------------------------------------------------

def test_smoke_engine_produces_both_arms():
    cfg, risks, scope_df, graph, drivers, severity, xer_tables = _build_inputs(
        iterations=200, seed=42,
    )
    result = run_integrated_simulation_stage3(
        cfg,
        risks=risks,
        risk_scope_df=scope_df,
        schedule_graph=graph,
        risk_drivers=drivers,
        xer_tables=xer_tables,
        severity_uniforms_by_risk_id=severity,
    )
    assert isinstance(result, Stage3IntegratedResult)
    assert result.iterations == 200
    assert result.cost_result["cost_dollars_array"].shape == (200,)
    assert result.schedule_days_array.shape == (200,)
    assert result.schedule_result.n_iter == 200


# ---------------------------------------------------------------------------
# Test 3 — Joint sampling preserved: cost arm bit-identical with Stage 2.5
# ---------------------------------------------------------------------------

def test_cost_parity_with_stage25_at_seed_paired_level():
    """The cost arm output is bit-for-bit identical to the Stage 2.5
    integrated engine invoked with the SAME severity_uniforms.

    This is Acceptance Criterion 3: cost-contingency parity with Stage 2.5
    integrated engine at the seed-paired level.
    """
    cfg, risks, scope_df, graph, drivers, severity, xer_tables = _build_inputs(
        iterations=200, seed=42,
    )

    s3_result = run_integrated_simulation_stage3(
        cfg,
        risks=risks,
        risk_scope_df=scope_df,
        schedule_graph=graph,
        risk_drivers=drivers,
        xer_tables=xer_tables,
        severity_uniforms_by_risk_id=severity,
    )

    s25_result = run_integrated_simulation(
        config=cfg.integrated_config,
        risks=risks,
        risk_scope_df=scope_df,
        precomputed_severity_uniforms=severity,
    )

    np.testing.assert_array_equal(
        s3_result.cost_result["cost_dollars_array"],
        s25_result["cost_dollars_array"],
    )
    np.testing.assert_array_equal(
        s3_result.cost_result["per_risk_cost_array"],
        s25_result["per_risk_cost_array"],
    )


# ---------------------------------------------------------------------------
# Test 4 — Joint sampling shared uniform: dual-coded risks correlated
# ---------------------------------------------------------------------------

def test_joint_sampling_shared_uniform_correlates_dual_coded_risks():
    """When a dual-coded risk samples high cost, it samples high schedule.

    The empirical Spearman-correlation between cost-arm and schedule-arm
    severity for any dual-coded risk should be 1.0 (or numerically very
    close) because both arms consume the same severity uniform per
    iteration for that risk.
    """
    cfg, risks, scope_df, graph, drivers, severity, xer_tables = _build_inputs(
        iterations=500, seed=42, dual_coded=("R001",),
    )
    result = run_integrated_simulation_stage3(
        cfg,
        risks=risks,
        risk_scope_df=scope_df,
        schedule_graph=graph,
        risk_drivers=drivers,
        xer_tables=xer_tables,
        severity_uniforms_by_risk_id=severity,
    )
    # The per-risk cost array column for R001 + the schedule sample
    # uniform should both be driven by the same severity uniform.
    risk_ids_all = list(result.cost_result["risk_ids_all"])
    r001_col = risk_ids_all.index("R001")
    # When R001 fires, its cost is a deterministic function of its
    # severity uniform. So per_risk_cost_array > 0 happens at iterations
    # where R001 fired; the severity uniform at those iterations is
    # the same one consumed by the schedule arm.
    fired = np.asarray(result.cost_result["fired_array"])[:, r001_col]
    assert int(fired.sum()) > 0, "Expected R001 to fire at least once"
    # If joint sampling is preserved, the per-risk cost on fired
    # iterations must rank-correlate perfectly with the severity uniform
    # for R001 (both monotone in u_severity under PERT).
    u_r001 = severity["R001"]
    cost_r001 = np.asarray(result.cost_result["per_risk_cost_array"])[:, r001_col]
    # Restrict to fired iterations (cost > 0)
    mask = fired
    if mask.sum() >= 2:
        # Spearman = Pearson of ranks
        from scipy.stats import spearmanr
        rho, _ = spearmanr(u_r001[mask], cost_r001[mask])
        assert rho == pytest.approx(1.0, abs=1e-9), (
            f"Joint sampling broken — Spearman rho={rho}, expected 1.0"
        )


# ---------------------------------------------------------------------------
# Test 5 — Schedule-arm severity uniforms come from the joint dict
# ---------------------------------------------------------------------------

def test_schedule_arm_consumes_joint_severity_uniforms():
    """The schedule arm sees a (n_iter, n_dual) matrix built by
    column-projection from the joint per-risk dict. This locks the
    contract that swapping in a different schedule arm preserves the
    joint-sampling property."""
    cfg, risks, scope_df, graph, drivers, severity, xer_tables = _build_inputs(
        iterations=200, seed=42, dual_coded=("R001", "R002"),
    )
    result = run_integrated_simulation_stage3(
        cfg,
        risks=risks,
        risk_scope_df=scope_df,
        schedule_graph=graph,
        risk_drivers=drivers,
        xer_tables=xer_tables,
        severity_uniforms_by_risk_id=severity,
    )
    # Schedule arm should have run with shape (200, 2)
    assert result.schedule_result.n_risks == 2
    assert result.schedule_result.n_iter == 200
    # Risk_ids_dual order on the schedule arm matches drivers iteration order
    assert result.schedule_result.risk_ids == ("R001", "R002")


# ---------------------------------------------------------------------------
# Test 6 — Adapter projects to composer-compatible shape
# ---------------------------------------------------------------------------

def test_adapt_to_integrated_results_shape_returns_required_keys():
    cfg, risks, scope_df, graph, drivers, severity, xer_tables = _build_inputs(
        iterations=200, seed=42,
    )
    result = run_integrated_simulation_stage3(
        cfg,
        risks=risks,
        risk_scope_df=scope_df,
        schedule_graph=graph,
        risk_drivers=drivers,
        xer_tables=xer_tables,
        severity_uniforms_by_risk_id=severity,
    )
    adapted = adapt_to_integrated_results_shape(result)
    required = {
        "cost_dollars_array", "schedule_days_array",
        "per_risk_cost_array", "risk_ids_all", "iterations",
        "seed_used", "beta_flag",
    }
    assert required.issubset(adapted.keys())
    assert adapted["cost_dollars_array"].shape == (200,)
    assert adapted["schedule_days_array"].shape == (200,)
    assert adapted["iterations"] == 200


# ---------------------------------------------------------------------------
# Test 7 — schedule_days_array is zero-baseline (min == 0)
# ---------------------------------------------------------------------------

def test_schedule_days_array_zero_baseline_at_floor():
    """The per-iteration schedule_days_array is the delay BEYOND the
    deterministic baseline. Its minimum across iterations is zero (the
    iteration where no risk fired or all firings had zero impact)."""
    cfg, risks, scope_df, graph, drivers, severity, xer_tables = _build_inputs(
        iterations=300, seed=42,
    )
    result = run_integrated_simulation_stage3(
        cfg,
        risks=risks,
        risk_scope_df=scope_df,
        schedule_graph=graph,
        risk_drivers=drivers,
        xer_tables=xer_tables,
        severity_uniforms_by_risk_id=severity,
    )
    assert float(result.schedule_days_array.min()) == pytest.approx(0.0, abs=1e-9)
    assert float(result.schedule_days_array.max()) > 0.0


# ---------------------------------------------------------------------------
# Test 8 — Reproducibility under seed
# ---------------------------------------------------------------------------

def test_reproducibility_under_same_seed():
    """Two runs at the same seed produce bit-identical output."""
    cfg1, risks, scope_df, graph, drivers, severity, xer_tables = _build_inputs(
        iterations=200, seed=42,
    )
    cfg2, _, _, _, _, _, _ = _build_inputs(iterations=200, seed=42)

    r1 = run_integrated_simulation_stage3(
        cfg1, risks=risks, risk_scope_df=scope_df,
        schedule_graph=graph, risk_drivers=drivers,
        xer_tables=xer_tables, severity_uniforms_by_risk_id=severity,
    )
    r2 = run_integrated_simulation_stage3(
        cfg2, risks=risks, risk_scope_df=scope_df,
        schedule_graph=graph, risk_drivers=drivers,
        xer_tables=xer_tables, severity_uniforms_by_risk_id=severity,
    )
    np.testing.assert_array_equal(
        r1.cost_result["cost_dollars_array"],
        r2.cost_result["cost_dollars_array"],
    )
    np.testing.assert_array_equal(
        r1.schedule_days_array, r2.schedule_days_array,
    )


# ---------------------------------------------------------------------------
# Test 9 — Different seeds produce different output
# ---------------------------------------------------------------------------

def test_different_seeds_produce_different_output():
    cfg_a = _make_config(iterations=200, seed=42)
    cfg_b = _make_config(iterations=200, seed=99)
    risks = [_risk(f"R{i:03d}_co", probability=0.3) for i in range(2)] + [
        _risk("R001", probability=0.6),
    ]
    scope_df = pd.DataFrame([_scope_row("R001")])
    graph = _make_graph()
    drivers = _make_drivers(("R001",))
    xer_tables = {"TASK": pd.DataFrame()}
    # Build SEPARATE severity uniforms — different seeds → different draws.
    risk_ids_all = tuple(r.risk_id for r in risks)
    sev_a = build_joint_severity_uniforms(
        risk_ids=risk_ids_all, n_iter=200,
        rng=np.random.default_rng(42), precision="float32",
    )
    sev_b = build_joint_severity_uniforms(
        risk_ids=risk_ids_all, n_iter=200,
        rng=np.random.default_rng(99), precision="float32",
    )
    r_a = run_integrated_simulation_stage3(
        cfg_a, risks=risks, risk_scope_df=scope_df,
        schedule_graph=graph, risk_drivers=drivers,
        xer_tables=xer_tables, severity_uniforms_by_risk_id=sev_a,
    )
    r_b = run_integrated_simulation_stage3(
        cfg_b, risks=risks, risk_scope_df=scope_df,
        schedule_graph=graph, risk_drivers=drivers,
        xer_tables=xer_tables, severity_uniforms_by_risk_id=sev_b,
    )
    assert not np.array_equal(
        r_a.cost_result["cost_dollars_array"],
        r_b.cost_result["cost_dollars_array"],
    )


# ---------------------------------------------------------------------------
# Test 10 — Missing severity uniforms raises
# ---------------------------------------------------------------------------

def test_missing_severity_uniforms_raises():
    cfg, risks, scope_df, graph, drivers, severity, xer_tables = _build_inputs(
        iterations=200, seed=42,
    )
    # Drop one risk
    incomplete = {k: v for k, v in severity.items() if k != risks[0].risk_id}
    with pytest.raises(ValueError, match="missing entries"):
        run_integrated_simulation_stage3(
            cfg, risks=risks, risk_scope_df=scope_df,
            schedule_graph=graph, risk_drivers=drivers,
            xer_tables=xer_tables,
            severity_uniforms_by_risk_id=incomplete,
        )


# ---------------------------------------------------------------------------
# Test 11 — Variant label resolution
# ---------------------------------------------------------------------------

def test_variant_label_resolution_dpreview_is_hybrid():
    assert _resolve_variant_label(
        Path("outputs/sra_strawman/strawman_DPReview.xlsx")
    ) == "Hybrid"
    assert _resolve_variant_label(
        Path("outputs/sra_strawman/strawman_All_Series.xlsx")
    ) == "Series"
    assert _resolve_variant_label(
        Path("outputs/sra_strawman/strawman_Hybrid.xlsx")
    ) == "Hybrid"


# ---------------------------------------------------------------------------
# Test 12 — Result carries config summary and audit metadata
# ---------------------------------------------------------------------------

def test_result_carries_audit_metadata():
    cfg, risks, scope_df, graph, drivers, severity, xer_tables = _build_inputs(
        iterations=200, seed=42,
    )
    result = run_integrated_simulation_stage3(
        cfg, risks=risks, risk_scope_df=scope_df,
        schedule_graph=graph, risk_drivers=drivers,
        xer_tables=xer_tables, severity_uniforms_by_risk_id=severity,
    )
    cs = result.config_summary
    assert cs["iterations"] == 200
    assert cs["seed"] == 42
    assert cs["criticality_measurement_mode"] == "mode_conditioned"
    assert "binding" in cs and "schedule_mc" in cs
    assert "deterministic_baseline_days" in cs
    assert cs["variant_label"] in ("Hybrid", "Series")


# ---------------------------------------------------------------------------
# Test 13 — Stage 2.5 production engine bit-identical when stage3 also runs
# (Acceptance Criterion 9 — backwards compatibility)
# ---------------------------------------------------------------------------

def test_stage25_engine_unchanged_when_stage3_runs_alongside():
    """Running the Stage 3 Beta integrated engine in the same process
    must not perturb the Stage 2.5 integrated engine's output for the
    same inputs. The Stage 2.5 engine is imported as a dependency but
    not modified.

    This locks Acceptance Criterion 9: backwards compatibility — the
    production deliverable continues to render bit-for-bit unchanged
    when the Stage 3 sibling is produced alongside.
    """
    cfg, risks, scope_df, graph, drivers, severity, xer_tables = _build_inputs(
        iterations=200, seed=42,
    )

    # Run Stage 2.5 BEFORE Stage 3 — capture baseline
    s25_before = run_integrated_simulation(
        config=cfg.integrated_config,
        risks=risks,
        risk_scope_df=scope_df,
        precomputed_severity_uniforms=severity,
    )

    # Run Stage 3 Beta integrated engine
    _ = run_integrated_simulation_stage3(
        cfg, risks=risks, risk_scope_df=scope_df,
        schedule_graph=graph, risk_drivers=drivers,
        xer_tables=xer_tables, severity_uniforms_by_risk_id=severity,
    )

    # Run Stage 2.5 AFTER Stage 3 — same inputs must produce same output
    s25_after = run_integrated_simulation(
        config=cfg.integrated_config,
        risks=risks,
        risk_scope_df=scope_df,
        precomputed_severity_uniforms=severity,
    )

    np.testing.assert_array_equal(
        s25_before["cost_dollars_array"],
        s25_after["cost_dollars_array"],
    )
    np.testing.assert_array_equal(
        s25_before["schedule_days_array"],
        s25_after["schedule_days_array"],
    )


# ---------------------------------------------------------------------------
# REFRETIRE-01 (D-3, P-4): a retired route refuses; it does not fall through
# ---------------------------------------------------------------------------

def test_a_call_with_no_drivers_is_refused_and_names_what_retired():
    """The engine built drivers itself when a caller passed none, through a pattern-catalogue
    builder that belonged to one project's binding. Both retired: a caller that passes no
    drivers is told so, and told where drivers come from, rather than silently taking a route
    that no longer exists."""
    cfg, risks, scope_df, graph, _drivers, severity, xer_tables = _build_inputs(
        iterations=50, seed=42,
    )
    with pytest.raises(ValueError, match="no risk_drivers supplied"):
        run_integrated_simulation_stage3(
            cfg, risks=risks, risk_scope_df=scope_df, schedule_graph=graph,
            xer_tables=xer_tables, severity_uniforms_by_risk_id=severity,
        )


def test_the_loader_refuses_an_input_it_cannot_resolve(monkeypatch):
    """Each of the three inputs fell through to one project's own file, so a caller who named
    none of them silently ran somebody else's register. Each missing one is now named."""
    from src.integrated.integrated_simulation_stage3 import load_integrated_config_stage3

    for var in ("REGISTER_FILE", "P6_FILE", "STRAWMAN_FILE"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(ValueError) as exc:
        load_integrated_config_stage3()
    message = str(exc.value)
    for named in ("register", "schedule (.xer)", "strawman", "no default project"):
        assert named in message, f"the refusal does not name {named!r}: {message}"
