"""The deliverable's §6a sequence, as pure data. The notebook renders; this computes.

3c Part A, A-1 to A-3. SPEC 1.2 §6a fixes the sequence:

    engine re-run in memory -> cross-validation -> compose -> Word -> Stage-3 standalone
    -> state cache -> HTML render

Everything up to the HTML render happens here, so it is testable without nbconvert and so
the pure-data rule holds: ``src/`` returns DataFrames and dicts, the notebook does the
rendering and owns the one ``display`` layer.

**D-11 lives in this module's shape.** On a cross-validation FAIL, every artefact is still
written, carrying the FAIL banner, and *then* the run fails. So :func:`run_deliverable` never
raises on ``all_pass == False`` - it composes, writes, and returns a result whose ``all_pass``
is False. The notebook's last cell is what raises, after the files exist, which is what makes
an nbconvert run exit non-zero with the evidence on disk rather than aborting mid-sequence and
leaving the specialist a stack trace. A caller that wants the refusal without the notebook
calls :meth:`DeliverableRun.raise_if_failed` last, in that order, for the same reason.

Project-generic (A-1): every path comes from the environment and every methodology value from
the selected project's register, through :func:`src.integrated.stage3_config.build_stage3_config`
and the one pre-flight in :mod:`src.final.deliverable_preflight`. No literal path, no default
project, and no other project's constant can reach a run.
"""
from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from src.final.deliverable_preflight import (
    DeliverablePreflightError,
    assert_ready,
    iteration_override,
    seed_override,
)
from src.final.run_diagnostic import format_run_diagnostic
from src.final.sections.correlation_sensitivity import (
    elicited_reproduces_run,
    run_stage3_bounding,
)
from src.integrated.stage3_config import (
    build_stage3_config,
    build_stage3_rules_from_scope,
    register_carries_pattern_catalogue,
    stage3_config_summary,
)

#: Mode scenarios the deliverable runs. ``DP_Review`` is the register's own classification -
#: the headline - and ``All_Series`` is the generic upper-bound comparator, available to any
#: project because it is derived from the register's own simulating risks rather than declared.
#:
#: The reference project's hardcoded third scenario is not run here (PUBLICFACE-01): a production
#: run runs, plots and prints these two Mode scenarios and the Stage 3 headline, and no other.
#: Which scenarios ran is recorded in the provenance manifest rather than assumed.
BASE_SCENARIOS = ("DP_Review", "All_Series")

#: The deliverable runs prod, and only prod (3c Part A, Director 04/09/2026).
#:
#: SR9 v3.5 deprecated dev mode and said SR10 would retire it structurally; the agent manual has
#: called it deprecated since. Dev injects the hardcoded ``Dummy_Realistic`` scenario into the
#: headline slot - eight reference-project risk IDs - which is both the anti-generic shape 3c
#: exists to remove and extant architectural debt.
#:
#: What is retired here is the **product surface**: the one report path runs prod, the entry
#: point offers no ``--mode``, and an explicit request for dev is refused rather than quietly
#: honoured. The ``mode`` parameter threaded through ``src/final`` is NOT removed - that is a
#: refactor across the composer, the executive summary, the word generator and four section
#: modules, and it is SR10's structural job, not Part A's. So this is a narrower decision than
#: "dev mode is gone", and saying so is the point: the plumbing survives, the door does not.
DELIVERABLE_MODE = "prod"


@dataclass(frozen=True)
class DeliverableInputs:
    """Everything one run was pointed at, after the pre-flight passed."""

    project: str
    project_display_name: str
    #: The project's public name (RIDGELINE-01): what the run identity prints, never the key.
    project_public_name: str
    #: A statement the project's front page must carry, or "" (Tropic Ridge: it is synthetic).
    project_note: str
    register_path: Path
    p6_path: Path
    strawman_path: Path
    output_dir: Path
    headline_metrics: tuple[str, ...]
    mode: str
    iterations: int | None
    seed: int | None
    #: CONFIGTRUTH-01: "override" (SR9_SEED) or "drawn" (unset, blank or 0), for the manifest.
    seed_source: str | None = None
    preflight: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class EngineResults:
    """The in-memory engine re-run: §6a's first step."""

    risks: list[Any]
    risk_scope: Any
    risk_titles: dict[str, str]
    cost_results: dict[str, Any]
    schedule_by_scenario: dict[str, dict[str, Any]]
    integrated_by_scenario: dict[str, dict[str, Any]]
    stage3_result: Any
    stage3_beta_result: dict[str, Any]
    stage3_config: Any
    programme_duration_days: float

    @property
    def schedule_results(self) -> dict[str, Any]:
        return self.schedule_by_scenario["DP_Review"]

    @property
    def integrated_results(self) -> dict[str, Any]:
        return self.integrated_by_scenario["DP_Review"]

    @property
    def headline_integrated_array(self) -> np.ndarray:
        """The A-5 headline: cost + dollarised Stage 3 schedule, the array the golden pins."""
        cost = np.asarray(self.stage3_result.cost_result["cost_dollars_array"], dtype=float)
        days = np.asarray(self.stage3_result.schedule_days_array, dtype=float)
        from src.integrated.run_config_contract import require_day_rate

        rate = require_day_rate(self.stage3_config.integrated_config.day_rate,
                                caller="EngineResults.headline_integrated_array")
        return cost + days * float(rate)


@dataclass(frozen=True)
class DeliverableRun:
    """One completed run: what it produced, and whether it may be distributed."""

    inputs: DeliverableInputs
    engines: EngineResults
    cross_validation: dict[str, Any]
    composed: dict[str, Any]
    artefacts: list[Path]
    provenance: dict[str, Any]
    #: Set when the Stage 3 standalone pair could not be produced from Stage 3 numbers
    #: (DELIVERABLE-SWALLOW-01). A run that is missing one of §6a's outputs has not passed,
    #: whatever the four checks said, so it counts against the verdict below.
    stage3_standalone_error: str | None = None

    @property
    def all_pass(self) -> bool:
        return bool(self.cross_validation.get("all_pass", False)
                    and self.stage3_standalone_error is None)

    def raise_if_failed(self) -> None:
        """D-11's second half. Call this LAST - the artefacts exist by now, bannered."""
        if self.all_pass:
            return
        written = "\n".join(f"  - {p}" for p in self.artefacts)
        if self.stage3_standalone_error is not None:
            raise RuntimeError(
                "THIS DELIVERABLE IS INCOMPLETE - it must not be distributed.\n\n"
                "The Stage 3 standalone pair could not be produced from Stage 3 numbers, and "
                "emitting it from the Stage 2.5 arm was refused: it would have been titled "
                "Stage 3 and carried another methodology's figures "
                f"(DELIVERABLE-SWALLOW-01).\n\n  {self.stage3_standalone_error}\n\n"
                f"What was written before the failure:\n{written}"
            )
        raise RuntimeError(
            "CROSS-VALIDATION FAILED - this deliverable must not be distributed.\n\n"
            f"{self.cross_validation.get('interpretation', '')}\n\n"
            "Every artefact below was written and carries the FAIL banner (D-11: write, then "
            "fail), so the evidence is on disk for investigation:\n"
            f"{written}"
        )


def resolve_inputs(
    env: dict[str, str] | None = None,
    *,
    output_dir: Path | str | None = None,
) -> DeliverableInputs:
    """Run the one pre-flight and resolve everything the run needs, or refuse (A-1)."""
    import os

    from src.sra.cpm.bindings import get_active_binding, project_display_name

    checks = assert_ready(env)
    env = dict(os.environ if env is None else env)

    binding = get_active_binding()
    metric = (env.get("FINAL_REPORT_HEADLINE_METRIC") or "P80").strip()
    metrics = ("P80", "Mean") if metric.lower() == "both" else (metric,)
    iterations = iteration_override(env)
    seed, seed_source = seed_override(env)

    return DeliverableInputs(
        project=binding.name,
        # A-1: the title is the binding's, never a literal in the notebook.
        project_display_name=binding.narrative("report_cover_title") or binding.project_name,
        project_public_name=project_display_name(binding),
        project_note=binding.narrative("project_note"),
        register_path=Path(env["REGISTER_FILE"].strip()),
        p6_path=Path(env["P6_FILE"].strip()),
        strawman_path=Path(env["STRAWMAN_FILE"].strip()),
        output_dir=Path(output_dir) if output_dir is not None else Path("outputs"),
        headline_metrics=metrics,
        mode=_resolve_mode(env),
        iterations=iterations,
        seed=seed,
        seed_source=seed_source,
        preflight=checks,
    )


def _resolve_mode(env: dict[str, str]) -> str:
    """Always ``prod``, and refuse anything else rather than ignoring it.

    Silently ignoring ``FINAL_REPORT_MODE=dev`` would leave an operator believing they had
    produced a dev report; refusing says what happened. Setting it to ``prod`` explicitly is
    allowed, because that is what the run does.
    """
    requested = (env.get("FINAL_REPORT_MODE") or DELIVERABLE_MODE).strip()
    if requested.lower() != DELIVERABLE_MODE:
        raise DeliverablePreflightError(
            f"FINAL_REPORT_MODE={requested!r} was requested, and the deliverable runs "
            f"{DELIVERABLE_MODE!r} only (3c Part A). Dev mode injected a hardcoded "
            f"indicative Mode scenario belonging to one project into the headline slot; it "
            f"was deprecated at SR9 v3.5 and is retired from this entry point. Unset "
            f"FINAL_REPORT_MODE, or set it to 'prod'."
        )
    return DELIVERABLE_MODE


def refuse_a_catalogue_register(strawman_path: Path | str) -> None:
    """Stop a register that carries a pattern catalogue, naming what retired.

    REFRETIRE-01 (D-3): such a register took a second route into a driver builder that belonged
    to one project's binding, and retired with it. The detector stays - a register reaching
    Stage 3 with sheets nothing joins is a wrong answer waiting to happen, not a missing feature.
    """
    if register_carries_pattern_catalogue(strawman_path):
        raise ValueError(
            f"{strawman_path} carries a pattern catalogue (Risk_Activity_Patterns + "
            f"Risk_Pattern_Assignments). The builder that joined those sheets retired with the "
            f"reference binding at REFRETIRE-01; a register reaches Stage 3 through each "
            f"Time=Yes row's Prefix_List. Convert the catalogue to Prefix_List rows, or raise a "
            f"brief to bring the catalogue route back."
        )


def run_engines(inputs: DeliverableInputs) -> EngineResults:
    """§6a step 1: cost MC, schedule MC, integrated per scenario, Stage 3 - all in memory."""
    from src.config import ChainConfig, SimConfig
    from src.integrated.integrated_simulation import run_integrated_simulation
    from src.integrated.run_config_contract import require_day_rate
    from src.integrated.integrated_simulation_stage3 import (
        adapt_to_integrated_results_shape,
        run_integrated_simulation_stage3,
    )
    from src.simulation import MonteCarloEngine
    from src.sra.cpm.auto_mapper import expand_auto_rules
    from src.sra.cpm.graph_builder import build_schedule_graph
    from src.sra.cpm.xer_reader import parse_xer
    from src.sra.methodology_defaults_reader import read_cg_coefficients, read_mode_multipliers
    from src.sra.sra_config import SRAConfig
    from src.sra.sra_simulation import (
        run_schedule_simulation,
        simulating_risk_ids,
    )
    from src.integrated.run_config_contract import (
        read_run_config_strict,
        resolve_programme_days,
    )
    from src.sra import strawman_reader
    from src.sra.strawman_reader import read_risk_scope
    from src.v5_register_reader import read_risks_v5

    # Before anything computes: the Stage 3 route such a register would need retired with the
    # binding that owned it, and a run that discovers that after the cost MC has finished has
    # spent minutes to say so (REFRETIRE-01 numerics review).
    refuse_a_catalogue_register(inputs.strawman_path)

    s3_cfg = build_stage3_config(
        register_path=inputs.register_path,
        xer_path=inputs.p6_path,
        strawman_path=inputs.strawman_path,
        iterations=inputs.iterations,
        seed=inputs.seed,
        project=inputs.project,
        caller_module="src/final/deliverable.py",
    )
    config = s3_cfg.integrated_config
    n_iter = int(config.iterations)
    seed = int(config.random_seed)  # build_stage3_config refuses a missing one (SEEDZERO-01)

    risks = read_risks_v5(str(inputs.register_path))
    risk_scope = read_risk_scope(str(inputs.strawman_path))
    risk_titles = {r.risk_id: r.description for r in risks}
    cg_coefficients = read_cg_coefficients(inputs.register_path, caller_module="src/final/deliverable.py")

    # --- cost MC standalone (the cross-validation reference for the cost marginal) -------
    raw = MonteCarloEngine(
        config=SimConfig(n_iter=n_iter, seed=seed, view=config.cost_view),
        buckets=[], chains=ChainConfig(), risks=risks,
        corr_coefficients=cg_coefficients, seed=seed,
    ).run()
    cost_results = {
        "cost_dollars_array": raw.ev_costs.sum(axis=1),
        "per_risk_cost_array": raw.ev_costs,
        "risk_ids": [r.risk_id for r in risks],
    }

    # --- Mode scenarios ------------------------------------------------------------------
    overrides: dict[str, dict[str, str] | None] = {
        "DP_Review": None,
        "All_Series": {rid: "Series" for rid in simulating_risk_ids(risk_scope)},
    }

    sra_cfg = SRAConfig(
        register_path=inputs.register_path, p6_path=inputs.p6_path,
        strawman_path=inputs.strawman_path, iterations=n_iter, random_seed=seed,
        day_rate=require_day_rate(config.day_rate, caller="src/final/deliverable.run_engines"),
        mode_multipliers=read_mode_multipliers(
            inputs.register_path, caller_module="src/final/deliverable.py"),
    )
    schedule_by_scenario: dict[str, dict[str, Any]] = {}
    integrated_by_scenario: dict[str, dict[str, Any]] = {}
    for name, override in overrides.items():
        schedule_by_scenario[name] = run_schedule_simulation(
            sra_cfg, risk_scope, **({"mode_override": override} if override else {}))
        integrated_by_scenario[name] = run_integrated_simulation(
            config, risks, risk_scope, **({"mode_overrides": override} if override else {}))

    # --- Stage 3: the production headline since SR17, and the array A-5 pins -------------
    # Rules come from each Time=Yes row's Prefix_List, through the builder the showcase and the
    # deliverable share. REFRETIRE-01 (D-3): a register carrying a pattern catalogue used to take
    # a second route into a driver builder that belonged to one project's binding, and retired
    # with it. The detector stays, and says so, rather than letting such a register run down a
    # route that no longer joins its pattern sheets.
    xer_tables = parse_xer(str(inputs.p6_path))
    graph = build_schedule_graph(xer_tables)
    drivers = expand_auto_rules(
        build_stage3_rules_from_scope(risk_scope, graph, s3_cfg.binding_config), graph)
    stage3_result = run_integrated_simulation_stage3(
        s3_cfg, risks=risks, risk_scope_df=risk_scope, schedule_graph=graph,
        risk_drivers=drivers, xer_tables=xer_tables,
    )

    # --- INTSCURVE-01 P3: integrated leave-one-out at the reporting P-level --------------
    # One masked Stage 3 replay per Time=Yes risk at the run's own iteration count, seed and
    # joint sampling (measured 28/10/2026: 2.5 s per replay at n=100,000, ten replays on wind).
    from src.integrated.leave_one_out import stage3_leave_one_out
    leave_one_out = stage3_leave_one_out(
        stage3_result, s3_cfg.schedule_mc_config,
        day_rate=require_day_rate(config.day_rate, caller="src/final/deliverable.run_engines"),
        p_level=int(config.reporting_p_level),
    )

    # --- INTSCURVE-01 Part B: the base layer, on its own stream (Reviewer R1) ------------
    # Never through config.layer1_config, which run_cost_layer would add into the cost arm and
    # so into every headline. A separate draw on layer1_generator(seed): every event-risk array
    # above and below is byte-identical with it on or off. None when the register's
    # Set_Layer1_Enabled is not TRUE, and the report then renders as Part A.
    from src.integrated.base_layer import deliverable_base_layer
    if getattr(config, "layer1_config", None) is not None:
        raise ValueError(
            "INTSCURVE-01 R1: the deliverable's IntegratedConfig carries a layer1_config, which "
            "would add the base into the event-risk cost arm and move the headline")
    base_layer = deliverable_base_layer(inputs.register_path, n_iter, seed)

    # --- F-E: GN3A section 4.1 correlation bounding, against the arm that just ran ------
    # Reproduction, not re-derivation: the same run_integrated_simulation, the same joint
    # severity uniforms, the same risk scope, varying only the CG coefficients. Two extra
    # cost-arm passes, measured at 16.1 s each at n=100,000 on the build machine (REPORT01 D-1).
    corr_curves = run_stage3_bounding(
        run_integrated_simulation,
        integrated_config=config,
        risks=risks,
        risk_scope_df=risk_scope,
        severity_uniforms_by_risk_id=stage3_result.severity_uniforms_by_risk_id,
    )
    # The elicited mode must be the run's own cost arm, byte for byte. If it is not, an
    # argument drifted and the zero-to-full gap would carry that drift rather than the
    # correlation effect - so the table is withheld and says so, rather than printed and
    # believed. Withheld, not raised: D-11 keeps the artefact on disk.
    corr_reproduces = elicited_reproduces_run(
        corr_curves, stage3_result.cost_result["cost_dollars_array"])
    if not corr_reproduces:
        logging.getLogger(__name__).error(
            "REPORT01 F-E: the elicited correlation counterfactual did not reproduce the "
            "run's cost arm; the bounding table is withheld from this run's artefacts.")

    # One home for this derivation: run_config_contract, the same module build_stage3_config
    # already reads it through. Two derivations for one number is how they come to disagree.
    programme_days = resolve_programme_days(
        read_run_config_strict(inputs.strawman_path, strawman_reader.read_run_config))

    return EngineResults(
        risks=risks, risk_scope=risk_scope, risk_titles=risk_titles,
        cost_results=cost_results,
        schedule_by_scenario=schedule_by_scenario,
        integrated_by_scenario=integrated_by_scenario,
        stage3_result=stage3_result,
        stage3_beta_result={
            **_stage3_beta_dict(
                stage3_result, corr_curves=corr_curves if corr_reproduces else None),
            "leave_one_out": leave_one_out,
            "base_layer": base_layer,
        },
        stage3_config=s3_cfg,
        programme_duration_days=float(programme_days),
    )


def _stage3_beta_dict(
    stage3_result, corr_curves: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The Beta-06 result-dict shape the composer reads, from a ``Stage3IntegratedResult``.

    ``adapt_to_integrated_results_shape`` projects the arrays the component-breakdown
    arithmetic needs; the composer's path-crossover section additionally reads
    ``schedule_result`` (for ``project_finish_days``), ``cost_result`` and ``risk_drivers`` -
    the keys the Stage 3 route returns. Both are carried here rather than one,
    because the composer reads both and a partial dict fails deep inside it with a message
    about a drifted binding contract rather than about the caller.
    """
    from src.integrated.integrated_simulation_stage3 import adapt_to_integrated_results_shape

    return {
        **adapt_to_integrated_results_shape(stage3_result),
        "cost_result": stage3_result.cost_result,
        "schedule_result": stage3_result.schedule_result,
        "risk_drivers": stage3_result.risk_drivers,
        "schedule_days_array": stage3_result.schedule_days_array,
        # REFRETIRE-01: the two behaviours the rest of this note described are gone - the
        # composer re-raises rather than substituting Stage 2.5 numbers (DELIVERABLE-SWALLOW-01),
        # and an omitted xer_path is now a required field rather than one project's default.
        # What still matters is the pre-loaded inputs. stage3_composer re-runs the
        # Stage 3 engine to rewire the DP_Review schedule arm, and takes the graph, the .xer
        # tables and the severity uniforms from THIS dict; without them it reconstructs a
        # binding config whose xer_path falls back to the reference project's default and
        # raises FileNotFoundError - which that module catches, logs, and silently substitutes
        # Stage 2.5 numbers for (stage3_composer.py:400). The artefact would still be written,
        # still be titled Stage 3, and carry Stage 2.5 figures. Passing them is what keeps the
        # deliverable's Stage 3 arm actually Stage 3.
        "schedule_graph": stage3_result.schedule_graph,
        "xer_tables": stage3_result.xer_tables,
        "severity_uniforms_by_risk_id": stage3_result.severity_uniforms_by_risk_id,
        # F-E. None when the elicited mode did not reproduce the run (see run_engines):
        # the composer then omits the bounding table and names the reason.
        "correlation_curves": corr_curves,
    }


def stage3_cross_surface(inputs: DeliverableInputs, engines: EngineResults) -> dict[str, Any]:
    """STAGE3HEADLINE-01 G-1: the app's period engine run on the deliverable's inputs.

    The deliverable's Stage 3 P80 delay against the period engine's, same register, .xer,
    seed and iteration count, with no period status (an empty workbook), so what is compared
    is how the two surfaces assemble a Stage 3 run. Tolerances are the register's schedule
    calibration tolerances (RS-D-2, D-14 shape: days OR percent); D-4 asked that they be
    settled after this limb was measured on both projects at matched iterations, and they
    were (brief §14).
    """
    import numpy as np
    from src.am.conditional_runner import ConditionalRunInputs, run_conditional_mc
    from src.am.workbook_reader import WorkbookData
    from src.sra.cpm.deterministic import deterministic_finish_hours

    n_iter = int(engines.stage3_result.iterations)
    seed = int(engines.stage3_result.seed_used)
    result = run_conditional_mc(ConditionalRunInputs(
        workbook_data=WorkbookData(period_info={}, risk_status=[], milestones=[], mitigations=[],
                                   am_risk_ids=[]),
        register_path=Path(inputs.register_path), xer_path=Path(inputs.p6_path),
        strawman_path=Path(inputs.strawman_path), n_iter=n_iter, seed=seed,
        project=inputs.project,
    ))
    graph = engines.stage3_result.schedule_graph
    hours_per_day = float(graph.project_default_calendar.working_hours_per_day)
    # Precision must match the run's own stochastic batch (review re-review: precision
    # coupling) - deterministic_finish_hours hardcoded float32 regardless of the run.
    precision = engines.stage3_result.config_summary["schedule_mc"]["precision"]
    deterministic_days = deterministic_finish_hours(graph, precision=precision) / hours_per_day
    finish_days = np.asarray(result.schedule_result.project_finish_hours, dtype=float) / hours_per_day
    period_delay = np.maximum(finish_days - deterministic_days, 0.0)
    ic = engines.stage3_config.integrated_config
    p_level = int(ic.reporting_p_level)
    return {
        "deliverable_delay_days": float(np.percentile(
            np.asarray(engines.stage3_result.schedule_days_array, dtype=float), p_level)),
        "period_delay_days": float(np.percentile(period_delay, p_level)),
        "p_level": p_level,
        "n_iter": n_iter, "seed": seed,
        "tolerance_days": float(ic.schedule_calibration_tolerance_days),
        "tolerance_pct": float(ic.schedule_calibration_tolerance_pct),
    }


def cross_validate(inputs: DeliverableInputs, engines: EngineResults) -> dict[str, Any]:
    """§6a step 2. Tolerances come from the register (RS-D-2); nothing is relaxed here.

    STAGE3HEADLINE-01: the schedule limbs run on Stage 3 - check 4 ranks against the Stage 3
    contributors (D-3) and check 2 is the cross-surface comparison (F-42, D-4).
    """
    from src.final.cross_validator import cross_validate_reports
    return cross_validate_reports(
        cost_results=engines.cost_results,
        schedule_results=engines.schedule_results,
        integrated_results=engines.integrated_results,
        strawman_path=inputs.strawman_path,
        config=engines.stage3_config.integrated_config,
        stage3_results=engines.stage3_beta_result,
        cross_surface=stage3_cross_surface(inputs, engines),
    )


def compose(inputs: DeliverableInputs, engines: EngineResults,
            cross_validation: dict[str, Any], *, run_date: str | None = None) -> dict[str, Any]:
    """§6a step 3. Runs whether or not the gate passed - D-11 writes, then fails.

    ``run_date`` is the run's one date (RIDGELINE-01 round 3); a caller without one gets today's.
    """
    from src.final.composer import compose_final_report_data

    chart_dir = inputs.output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    # DELIVFIX-01 (R-3): what the audit trail calls "Engine versions" is the package version and
    # the commit the run executed - the same identity provenance.json stamps - not sprint codes.
    from src import __version__ as _package_version
    from src.am._provenance import resolve_engine_sha, resolve_tree_dirty
    _sha = resolve_engine_sha()
    _engine = f"{_sha} (working tree dirty)" if (_sha and resolve_tree_dirty()) else (_sha or "unknown")

    composed = compose_final_report_data(
        engine_versions={"package": _package_version, "engine": _engine},
        cost_results=engines.cost_results,
        schedule_results=engines.schedule_results,
        integrated_results_by_scenario=engines.integrated_by_scenario,
        schedule_results_by_scenario=engines.schedule_by_scenario,
        strawman_path=inputs.strawman_path,
        register_path=inputs.register_path,
        cross_validation=cross_validation,
        risk_titles=engines.risk_titles,
        config=engines.stage3_config.integrated_config,
        run_date=run_date or date.today().isoformat(),
        risks=engines.risks,
        chart_output_dir=chart_dir,
        programme_duration_days=engines.programme_duration_days,
        p6_path=inputs.p6_path,
        headline_metric=inputs.headline_metrics[0],
        stage3_beta_result=engines.stage3_beta_result,
    )
    # STAGE3HEADLINE-01 P1: a production run does not ship without the Stage 3 headline. The
    # section seam records absence (hand-built dicts in tests); this seam refuses it.
    if composed.get("executive_summary", {}).get("headline_stage3") is None:
        raise RuntimeError(
            "the composed deliverable carries no Stage 3 headline: "
            f"{composed.get('executive_summary', {}).get('headline_stage3_absent_reason', 'unknown')}. "
            "The headline is the Stage 3 distribution (D-1); a deliverable without one is not "
            "the product.")
    return composed


def write_artefacts(inputs: DeliverableInputs, engines: EngineResults,
                    composed: dict[str, Any],
                    cross_validation: dict[str, Any], *,
                    run_date: str | None = None) -> tuple[list[Path], str | None]:
    """§6a steps 4-6: Word, Stage-3 standalone, state cache. **No PDF** (D-12).

    Every one of these runs on a FAIL as well as a pass (D-11). The Word generator injects the
    banner itself from ``cross_validation["all_pass"]``, so nothing here has to remember to.
    """
    from src.final.stage3_composer import emit_stage3_standalone_artefacts
    from src.final.state_cache import write_state_cache
    from src.final.word_generator import generate_word_summary

    # RIDGELINE-01 round 4: the run's one date, passed in by run_deliverable. It used to be read
    # from composed["run_date"], a key the real composer never sets (it keeps the date in
    # appendix_audit_trail), so every production run fell back to a second clock read here.
    # The fallback is reachable only by a direct caller that passes no date.
    run_date = run_date or date.today().isoformat()
    inputs.output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for metric in inputs.headline_metrics:
        suffix = "" if metric.upper() == "P80" else f"_{metric.upper()}"
        path = inputs.output_dir / f"executive_summary{suffix}_{run_date}.docx"
        meta = generate_word_summary(
            summary_data=composed["executive_summary"],
            audit_trail_data=composed["appendix_audit_trail"],
            disclaimer_paragraphs=composed["disclaimer_paragraphs"],
            cross_validation=cross_validation,
            output_path=path,
            composed=composed,
        )
        written.append(Path(meta["output_path"]))

    # DELIVERABLE-SWALLOW-01: the emitter now raises rather than silently substituting Stage
    # 2.5 numbers into a Stage-3-titled artefact. D-11 still governs what happens next - the
    # Word document above is already on disk, the state cache below still gets written, and
    # the run fails at the end. The Stage 3 artefact is absent and named, not present and
    # wrong, and `stage3_standalone_error` carries the reason into the manifest.
    stage3_error: str | None = None
    stage3: Any = {}
    try:
        stage3 = emit_stage3_standalone_artefacts(
            cost_results=engines.cost_results,
            schedule_results=engines.schedule_results,
            integrated_results_by_scenario=engines.integrated_by_scenario,
            schedule_results_by_scenario=engines.schedule_by_scenario,
            strawman_path=inputs.strawman_path,
            register_path=inputs.register_path,
            cross_validation=cross_validation,
            output_dir=inputs.output_dir,
            stage3_beta_result=engines.stage3_beta_result,
            stage3_beta_thin_result=engines.stage3_result,
            risk_titles=engines.risk_titles,
            config=engines.stage3_config.integrated_config,
            run_date=run_date,
            risks=engines.risks,
            chart_output_dir=inputs.output_dir / "charts",
            programme_duration_days=engines.programme_duration_days,
            p6_path=inputs.p6_path,
            headline_metric=inputs.headline_metrics[0],
        )
    except Exception as exc:  # the emitter's own refusal, or anything under it
        stage3_error = f"{type(exc).__name__}: {exc}"
        logging.getLogger(__name__).error(
            "Stage 3 standalone artefacts not written: %s", stage3_error)
    else:
        written.extend(Path(p) for p in _artefact_paths(stage3))

    cache_dir = inputs.output_dir / "runs" / f"{run_date}_{inputs.project}"
    write_state_cache(
        {
            "composed": composed,
            "cv_result": cross_validation,
            "run_date": run_date,
            "project": inputs.project,
            "engine_versions": composed["appendix_audit_trail"]["engine_versions"],
            "register_path": str(inputs.register_path),
            "strawman_path": str(inputs.strawman_path),
            "headline_metric": inputs.headline_metrics[0],
            "stage3_config": stage3_config_summary(engines.stage3_config),
        },
        cache_dir,
    )
    written.append(cache_dir)
    return written, stage3_error


#: The keys ``emit_stage3_standalone_artefacts`` returns its written files under.
STAGE3_ARTEFACT_KEYS = ("docx_path", "html_path")


def _artefact_paths(emitted: Any) -> list[str]:
    """The Stage 3 standalone files, by name rather than by guessing at key names.

    The first version matched any key containing "path" or "file", which would have dropped
    an artefact silently the day a key was renamed - the D-11 raise message and the provenance
    manifest would then under-report what exists on disk, with nothing red. Naming the keys
    means a rename fails here instead.
    """
    if not isinstance(emitted, dict):
        raise TypeError(
            f"emit_stage3_standalone_artefacts returned {type(emitted).__name__}, not a dict; "
            f"the Stage 3 artefact paths cannot be recorded")
    out: list[str] = []
    for key in STAGE3_ARTEFACT_KEYS:
        value = emitted.get(key)
        if isinstance(value, (str, Path)):
            out.append(str(value))
    if not out:
        raise KeyError(
            f"none of {STAGE3_ARTEFACT_KEYS} is in the Stage 3 emitter's return "
            f"({sorted(emitted)}); the manifest would under-report what was written")
    return out


def build_provenance(inputs: DeliverableInputs, engines: EngineResults,
                     cross_validation: dict[str, Any],
                     artefacts: list[Path], *, run_date: str | None = None) -> dict[str, Any]:
    """One provenance record for the run (SPEC §3 limb 3, F-C).

    Same shape ``src/am/_provenance.py`` produces for a period - engine SHA, tree-dirty flag,
    per-file input digests (per file, never concatenated, so a same-filename re-issue of one
    input is diagnosable) - plus the seed and parameters a production run must record.
    """
    from src.am._provenance import resolve_engine_sha, resolve_tree_dirty
    from src.am.run_period import _input_digest

    return {
        "engine_sha": resolve_engine_sha(),
        "engine_tree_dirty": resolve_tree_dirty(),
        "input_sha256": {
            "register": _input_digest(inputs.register_path),
            "xer": _input_digest(inputs.p6_path),
            "strawman": _input_digest(inputs.strawman_path),
        },
        "project": inputs.project,
        "run_date": run_date or date.today().isoformat(),
        "timestamp": _now_iso(),
        "run_token": _run_token(),
        "params": {**stage3_config_summary(engines.stage3_config), "seed_source": inputs.seed_source},
        "mode": inputs.mode,
        "headline_metrics": list(inputs.headline_metrics),
        "scenarios_run": sorted(engines.integrated_by_scenario),
        "cross_validation_all_pass": bool(cross_validation.get("all_pass", False)),
        "schedule_top3_basis": cross_validation.get("schedule_top3_basis"),
        "artefacts": [str(p) for p in artefacts],
    }


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


#: Environment variable carrying one invocation's identity, set by the entry point.
RUN_TOKEN_ENV = "QRA_RUN_TOKEN"


def _run_token() -> str | None:
    """The token the entry point generated for THIS invocation, if it set one."""
    import os

    return os.environ.get(RUN_TOKEN_ENV, "").strip() or None


@contextlib.contextmanager
def captured_engine_log() -> Iterator[list[logging.LogRecord]]:
    """Hold the engines' log records instead of letting them reach the report.

    The deliverable HTML is a rendered notebook, so whatever the engines write to stderr is
    captured into the artefact a client opens: on the 5b run it opened with twelve auto-mapper
    warnings above the project's own title (F5B-14). The records are evidence - the auto-mapper's
    expansion audit among them - so they are kept and filed beside the provenance, not silenced.

    Installing any handler on the root logger is also what stops the emission: with no handler
    configured, logging falls back to its lastResort handler, which writes to stderr.

    **It holds what would otherwise have gone to stderr, and no more.** The root level is left
    alone: raising it would make every logger in the process emit INFO to whatever handlers a
    caller had configured, which is not this function's business. Where a caller has already
    configured logging - ``run_period`` and ``publish_period`` both call ``basicConfig`` - their
    handler still receives the records, as it should; the suppression matters on the notebook
    path, where nothing is configured and logging falls back to stderr.
    """
    records: list[logging.LogRecord] = []

    class _Hold(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Hold()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield records
    finally:
        root.removeHandler(handler)


def write_engine_log(path: Path, records: list[logging.LogRecord]) -> None:
    """File the held records, and never raise doing it.

    This runs after the manifest is written, so a raise here would leave a token-matched PASS
    manifest behind a call that crashed, and `--gate` would read it as a completed run. A log
    that cannot be written is worth a line on stderr, not a failed deliverable.
    """
    lines = []
    for record in records:
        try:
            message = record.getMessage()
        except Exception:  # a malformed log call in the engines is not this function's failure
            message = f"<unformattable record from {record.name}>"
        lines.append(f"{record.levelname} {record.name}: {message}\n")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(lines), encoding="utf-8", newline="\n")
    except OSError as exc:
        print(f"WARNING: the engine log could not be written to {path}: {exc}", file=sys.stderr)


def run_deliverable(env: dict[str, str] | None = None, *,
                    output_dir: Path | str | None = None) -> DeliverableRun:
    """The whole §6a sequence bar the HTML render, which is nbconvert's.

    **Does not raise on a cross-validation FAIL** - that is D-11, and it is the point: the
    artefacts are written bannered first, and the caller raises afterwards via
    :meth:`DeliverableRun.raise_if_failed`. It does raise, before computing anything, when the
    pre-flight is not satisfied.
    """
    import json

    inputs = resolve_inputs(env, output_dir=output_dir)
    # RIDGELINE-01 round 3 (gate 3 WARN 1): the clock is read ONCE per run. Three reads - the
    # engine log's folder here, the state cache's in compose, the manifest's in build_provenance -
    # let a run crossing midnight write two run folders, and Cell 7 then named the stray one's
    # binding key. Every artefact's date, and the one provenance records, is this one.
    run_date = date.today().isoformat()
    engine_log = manifest_path(inputs.output_dir, inputs.project, run_date).parent / "engine_log.txt"
    with captured_engine_log() as log_records:
        try:
            engines = run_engines(inputs)
            cross_validation = cross_validate(inputs, engines)
            composed = compose(inputs, engines, cross_validation, run_date=run_date)
            artefacts, stage3_error = write_artefacts(
                inputs, engines, composed, cross_validation, run_date=run_date)
        finally:
            # A run that raised is the run whose log matters most, and holding the records has
            # already taken away the stderr they used to reach. Write on both paths.
            write_engine_log(engine_log, log_records)
    artefacts.append(engine_log)  # recorded in the provenance built below, like every artefact
    provenance = build_provenance(inputs, engines, cross_validation, artefacts, run_date=run_date)
    provenance["stage3_standalone_error"] = stage3_error
    provenance["cross_validation_all_pass"] = bool(
        provenance["cross_validation_all_pass"] and stage3_error is None)

    manifest = manifest_path(inputs.output_dir, inputs.project, provenance["run_date"])
    manifest.parent.mkdir(parents=True, exist_ok=True)

    # REPORT01 F-G. Written from what this run already holds, so the one-pager cannot
    # disagree with the manifest beside it - and written on a FAIL too, bannered, because
    # a failed gate is when a reader most wants one page (D-11: write, then fail).
    #
    # P-7: appended to the provenance's artefact list BEFORE the manifest is serialised.
    # The manifest is absent from its own list for want of exactly this ordering; the
    # diagnostic does not repeat it.
    diagnostic = manifest.parent / f"run_diagnostic_{provenance['run_date']}.txt"
    artefacts.append(diagnostic)
    provenance["artefacts"] = [str(a) for a in artefacts]
    diagnostic.write_text(
        format_run_diagnostic(
            composed=composed,
            cross_validation=cross_validation,
            provenance=provenance,
            artefacts=artefacts,
        ),
        encoding="utf-8", newline="\n",
    )

    manifest.write_text(json.dumps(provenance, indent=2, default=str), encoding="utf-8")
    artefacts.append(manifest)

    return DeliverableRun(
        inputs=inputs, engines=engines, cross_validation=cross_validation,
        composed=composed, artefacts=artefacts, provenance=provenance,
        stage3_standalone_error=stage3_error,
    )


#: The run's provenance manifest. Its folder is the run folder, which Cell 7 names by role.
MANIFEST_NAME = "provenance.json"


def manifest_path(output_dir: Path | str, project: str, run_date: str) -> Path:
    """Where one run's provenance manifest lives. One construction, two callers.

    ``run_deliverable`` writes it here and ``gate_exit_code`` reads it here. Computing the
    path in two places is how an entry point comes to check the wrong artefact and report a
    pass for a run that failed.
    """
    return Path(output_dir) / "runs" / f"{run_date}_{project}" / MANIFEST_NAME


def gate_exit_code(manifest: Path | str, expected_token: str | None = None) -> int:
    """D-11's exit code, read from the manifest **this invocation** wrote.

    ``RUN_FINAL.bat`` runs nbconvert with ``--allow-errors`` so the HTML is written even when
    the last cell raises - without it nbconvert aborts and the one artefact a reader actually
    opens is the one that does not exist, which is the contradiction D-11 was ruled to settle.
    The cost of ``--allow-errors`` is that nbconvert then exits 0 whatever happened, so the
    run's own verdict has to come from what it wrote.

    **Which is why the token matters.** The manifest path is keyed by date and project, so a
    run that crashes today after a successful run earlier today would find the earlier run's
    manifest sitting there and report its PASS - a gate passing against the wrong artefact,
    and the failure mode most worth engineering out of a client deliverable. The entry point
    generates a token per invocation, the run stamps it into the manifest, and this compares
    them. A manifest that is absent, unreadable, or carries a different token means this run
    did not complete: exit 2, "nothing to judge", never 0.

    Returns 0 only when the manifest is this run's AND its gate passed.
    """
    import json

    manifest = Path(manifest)
    if not manifest.exists():
        print(f"INCOMPLETE: no provenance manifest at {manifest} - the run did not complete.")
        return 2
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"INCOMPLETE: provenance manifest at {manifest} is unreadable ({exc}).")
        return 2

    if expected_token is not None:
        found = payload.get("run_token")
        if found != expected_token:
            print(
                f"INCOMPLETE: the manifest at {manifest} is not from this run "
                f"(expected token {expected_token!r}, found {found!r}). A run that crashed "
                f"before writing its manifest must not inherit an earlier run's verdict."
            )
            return 2

    if payload.get("cross_validation_all_pass") is True:
        print(f"PASS: cross-validation passed; artefacts listed in {manifest}.")
        return 0
    print(
        f"FAIL: cross-validation failed. Every artefact was written and carries the FAIL "
        f"banner (D-11); see {manifest}. DO NOT DISTRIBUTE."
    )
    return 1


def manifests_by_token(output_dir: Path | str, project: str, token: str) -> list[Path]:
    """Every manifest carrying this run's token, found by the token rather than by today's date.

    RIDGELINE-01 round 4: ``RUN_FINAL.bat`` calls the gate with no date, and the gate used to
    look under its own read of today's. A run that crossed midnight wrote its manifest under the
    earlier date, so the gate exited 2 INCOMPLETE on a completed run. Only this project's run
    folders (``<YYYY-MM-DD>_<project>``) are read.

    All matches are returned, not the first (round 5): a token carried by two manifests has been
    reused, and neither can be told to be this run's. The caller fails closed on that, as it does
    on none.
    """
    import json

    found = []
    for manifest in sorted(Path(output_dir, "runs").glob(f"*_{project}/{MANIFEST_NAME}")):
        if manifest.parent.name[11:] != project:
            continue
        try:
            if json.loads(manifest.read_text(encoding="utf-8")).get("run_token") == token:
                found.append(manifest)
        except (OSError, ValueError):
            continue
    return found


def _cli(argv: list[str] | None = None) -> int:
    """``python -m src.final.deliverable --gate`` - the entry point's exit code."""
    import argparse
    import os
    from datetime import date

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", action="store_true",
                        help="exit non-zero unless the last run's manifest records a pass")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--run-date", default=None)
    args = parser.parse_args(argv)

    project = os.environ.get("QRA_PROJECT", "").strip()
    if not project:
        print("FAIL: QRA_PROJECT is unset; there is no default project.")
        return 2
    if args.gate:
        token = os.environ.get(RUN_TOKEN_ENV, "").strip() or None
        found = (manifests_by_token(args.output_dir, project, token)
                 if token is not None and args.run_date is None else [])
        if len(found) > 1:
            print(f"INCOMPLETE: {len(found)} manifests carry this run's token {token!r}, so it was "
                  f"reused and none can be taken as this run's:\n  "
                  + "\n  ".join(str(m) for m in found))
            return 2
        return gate_exit_code(
            found[0] if found else manifest_path(args.output_dir, project,
                                                 args.run_date or date.today().isoformat()),
            expected_token=token,
        )
    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised through RUN_FINAL.bat
    raise SystemExit(_cli())
