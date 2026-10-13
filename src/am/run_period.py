"""End-to-end monthly cycle: workbook -> engine -> metrics -> JSON.

Public entry point::

    python -m src.am.run_period --workbook status_periods/<name>.xlsx

Or programmatic::

    from src.am.run_period import run_period
    result = run_period(workbook_path=..., output_dir=...)

The runner orchestrates the five other modules in sequence:

1. Read the workbook via :mod:`src.am.workbook_reader`
2. Run the conditional Stage 3 MC via :mod:`src.am.conditional_runner`
   (with the workbook's pinned-risk and milestone state applied)
3. Compute AM metrics via :mod:`src.am.metrics`
   (lognormal P-bands, SSI, tornado, days-at-risk, counterfactual sweep)
4. Write the period JSON via :mod:`src.am.json_writer`
   (Doc 3 v2.2 contract)

Iteration counts default to production levels (100k main, 10k subsidiary).
Overrides available via CLI flags for smoke runs.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np

from src.git_identity import input_digest  # noqa: E402
from src.am._provenance import (  # noqa: E402
    resolve_engine_sha as _resolve_active_sha,
    resolve_tree_dirty as _resolve_tree_dirty,
)

from src.integrated.stage3_inputs import (  # noqa: E402
    Stage3BindingConfig,
    resolve_float_threshold_hours,
)
from src.rng_streams import SEED_SET, parse_seed, resolve_seed  # noqa: E402
from src.sra.cpm.bindings.registry import get_binding, list_bindings  # noqa: E402
from src.sra.cpm.graph_builder import build_schedule_graph  # noqa: E402
from src.sra.cpm.xer_reader import parse_xer  # noqa: E402

from src.am.conditional_runner import (
    ConditionalRunInputs,
    run_conditional_mc,
)
from src.am.json_writer import write_period_json
from src.am.metrics import (
    AMMetrics,
    DEFAULT_CI_THRESHOLD,
    DEFAULT_TOP_N_BY_CI,
    build_methodology_notes,
    compute_per_risk_criticality,
    compute_counterfactual_sweep,
    compute_leave_one_out_metrics,
    compute_per_activity_p_bands,
    compute_ssi_per_risk,
    compute_tornado_proxy_per_risk,
)
from src.am.integrated_period import (
    IntegratedUnavailable,
    run_integrated_period,
)
from src.am.project_binding import (
    build_drivers_for_project,
    resolve_project_inputs,
)
from src.am.workbook_reader import read_workbook


logger = logging.getLogger(__name__)

#: Where a period's seed came from, as ``meta.seed_source`` records it (SEEDZERO-01 P3).
SEED_SOURCE_BINDING = "binding"
SEED_SOURCE_OVERRIDE = "override"
SEED_SOURCE_DRAWN = "drawn"


class FiredRiskRefused(RuntimeError):
    """A period marks a risk Fired, which this engine cannot yet carry (FIREDDROP-01)."""


def refuse_fired_risks(risk_status: list[dict[str, Any]]) -> None:
    """Refuse a period whose status workbook marks any risk ``Fired`` (FIREDDROP-01 guard).

    A Fired risk leaves the Monte Carlo on both arms (``conditional_runner.py`` Branch 3,
    ``integrated_period._REMOVING_ACTIONS``), and its realised impact is recorded and then applied
    nowhere - so both forecasts IMPROVE the moment a risk occurs. Refused rather than warned: a
    warning would sit unread among the run's others. Same test as the runner's, so the guard
    cannot miss a risk the runner would drop. Lifted when AMGAP-01 decision (a) is built.
    """
    fired = [str(r.get("risk_id")) for r in risk_status if r.get("status_this_period") == "Fired"]
    if fired:
        raise FiredRiskRefused(
            f"this period marks {len(fired)} risk(s) Fired: {', '.join(fired)}. The engine cannot "
            f"yet carry a fired risk: it would drop out of both the cost and the schedule forecast, "
            f"and its realised impact would be recorded but applied nowhere, so both forecasts "
            f"would improve because a risk occurred (FIREDDROP-01). Until AMGAP-01 decision (a) - "
            f"how a realised risk enters the forecast - is ruled and built, leave these risks Open "
            f"and record the occurrence in the notes."
        )


def _sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file, streamed (inputs can be large)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _input_digest(path: Path) -> dict[str, str]:
    """Identify an input, recording HOW it was identified (PROVCRLF01).

    One implementation, shared with the golden harness: ``src.git_identity.input_digest``.
    Tracked inputs are a git blob OID; untracked or outside any repository, a byte hash; git
    not installed, a byte hash marked ``"git": "unavailable"``; any other git failure raises
    (DIGESTFALLBACK-01). The outcomes and how they are told apart are in its docstring.
    """
    return input_digest(path)


def _build_engine_provenance(
    *,
    engine_sha: str | None,
    engine_tree_dirty: bool | None,
    register_path: Path,
    xer_path: Path,
    workbook_path: Path,
) -> dict[str, Any]:
    """AM09: assemble the engine-provenance stamp for the period meta block.

    Per-file input digests (not concatenated) so a same-filename re-issue of
    any single input is diagnosable. ``engine_sha`` is None when the SHA could not
    be resolved (git absent): the attestation is then null and logged, never a false
    value (RS-A2 P-3; the pin fields are gone).
    """
    return {
        "engine_sha": engine_sha,
        "engine_tree_dirty": engine_tree_dirty,
        "input_sha256": {
            "register": _input_digest(register_path),
            "xer": _input_digest(xer_path),
            "workbook": _input_digest(workbook_path),
        },
    }


AM_REPO_ROOT = Path(__file__).resolve().parents[2]  # this repository; the engine lives here

# REFRETIRE-01: the DEFAULT_REGISTER / DEFAULT_XER / DEFAULT_STRAWMAN aliases were one
# project's three files, and nothing read them - a period run resolves its inputs from the
# project it names (``resolve_project_inputs``). They retired with that project's binding.
DEFAULT_OUTPUT_DIR = AM_REPO_ROOT / "data"
DEFAULT_PROJECT_START = _dt.date(2024, 1, 1)  # Heuristic anchor; future SR pulls from .xer


def _deterministic_finish_hours(xer_tables: dict[str, Any], graph: Any) -> float:
    """One zero-risk forward pass; the project EF.max in working hours.

    STAGE3HEADLINE-01 D-7: the pass itself lives in :mod:`src.sra.cpm.deterministic`, shared
    with the Stage 3 integrated result and the deliverable's cross-surface limb, so every
    delay in the product is measured from the same baseline. ``xer_tables`` is unused and
    kept for the callers' signature.
    """
    from src.sra.cpm.deterministic import deterministic_finish_hours
    return deterministic_finish_hours(graph)


def _activity_metadata(graph: Any) -> tuple[dict[str, float], dict[str, str]]:
    """Extract per-activity durations + names from the schedule graph."""
    durations: dict[str, float] = {}
    names: dict[str, str] = {}
    for a_id in graph.topo_order:
        act = graph.activities[a_id]
        durations[a_id] = float(act.original_duration_hours)
        names[a_id] = str(act.name)
    return durations, names


def _deterministic_ef_per_activity(graph: Any) -> dict[str, float]:
    """Per-activity deterministic EF via the shared zero-risk pass (D-7)."""
    from src.sra.cpm.deterministic import deterministic_ef_per_activity
    return deterministic_ef_per_activity(graph)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def _period_seed(seed: int | None, project: str) -> tuple[int, str]:
    """The period run's seed and its source: ``--seed`` if given, else the binding's declared one.

    SEEDZERO-01 P3 (Director, 11/10/2026): one seed per project, the same every period, so the
    movement between two periods is the register's and not sampling noise. This reverses
    PERIODSEED-01's code default of 42; the shipped bindings declare 42, so no period moves.
    ``--seed 0`` follows the one convention: drawn, and recorded as ``drawn``.
    """
    if seed is not None:
        value, how = resolve_seed(seed, where="the period run's --seed")
        return value, SEED_SOURCE_OVERRIDE if how == SEED_SET else SEED_SOURCE_DRAWN
    declared = get_binding(project).period_seed
    if declared is None:
        raise ValueError(
            f"project {project!r} declares no period_seed in its binding, and no --seed was "
            f"given. A period run has no default seed: declare one in the binding, or pass --seed.")
    return parse_seed(declared, where=f"binding {project!r} period_seed"), SEED_SOURCE_BINDING


def run_period(
    *,
    workbook_path: Path,
    project: str | None = None,
    register_path: Path | None = None,
    xer_path: Path | None = None,
    strawman_path: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    main_iterations: int = 100_000,
    days_at_risk_iterations: int = 10_000,
    counterfactual_iterations: int = 10_000,
    seed: int | None = None,
    criticality_measurement_mode: str = "both",
    project_start: _dt.date = DEFAULT_PROJECT_START,
    top_n_by_ci: int = DEFAULT_TOP_N_BY_CI,
    ci_threshold: float = DEFAULT_CI_THRESHOLD,
    p_band_method: str = "B",
    allow_dirty: bool = False,
) -> Path:
    """Run the full monthly cycle end-to-end.

    Returns the path of the written JSON file
    (``output_dir/period_YYYYMMDD.json``).

    AM09 dirty-tree guard: the run REFUSES to proceed if this repository's
    working tree has uncommitted changes, because a SHA stamped over a dirty
    tree is a false attestation. Pass ``allow_dirty=True`` (CLI:
    ``--allow-dirty``) to override; the override is stamped loudly as
    ``meta.engine_tree_dirty: true`` and logged at WARNING.
    """
    # AM09: resolve engine identity ONCE, up front, so the guard and the
    # stamp see the same tree state (no TOCTOU between guard and write).
    engine_sha = _resolve_active_sha()
    engine_tree_dirty = _resolve_tree_dirty()
    if engine_tree_dirty and not allow_dirty:
        raise RuntimeError(
            "AM09 dirty-tree guard: this repository's working tree has "
            "uncommitted changes. A SHA stamped over a dirty tree is a false "
            "attestation. Commit or stash the engine (or pass --allow-dirty "
            "to proceed, which stamps meta.engine_tree_dirty: true)."
        )
    if engine_tree_dirty and allow_dirty:
        logger.warning(
            "AM09: the engine tree is DIRTY; proceeding under --allow-dirty. "
            "meta.engine_tree_dirty will be stamped true - this artifact is "
            "NOT a clean-tree attestation."
        )
    # Resolve + activate the project: ``project`` or QRA_PROJECT, else raise (no
    # default, QRAXL-01). With default (None) paths a project resolves to this
    # repository's binding paths, so the archived cycle stays bit-identical when
    # those inputs are supplied.
    # FW-23 (R-4): the strawman is the register now. Without this, a run given --register and no
    # --strawman took the strawman from the BINDING's fixture - the reader's register in one role,
    # a different workbook in the other, silently.
    if strawman_path is None and register_path is not None:
        strawman_path = register_path
    pinputs = resolve_project_inputs(
        project,
        register_path=register_path,
        xer_path=xer_path,
        strawman_path=strawman_path,
    )
    register_path = pinputs.register_path
    xer_path = pinputs.xer_path
    strawman_path = pinputs.strawman_path
    logger.info(
        "AM project=%s register=%s xer=%s",
        pinputs.project, register_path.name, xer_path.name,
    )
    seed, seed_source = _period_seed(seed, pinputs.project)

    # Stage 7 part C (B-2), ruled 05/09/2026: the project key lives in the PATH as well as
    # in `meta.project_key`. D-7 rules one install serves many projects, and a field alone
    # cannot deliver that - `data/period_20260930.json` is ONE filename, so two projects
    # could not both close a period on 30 September. A directory per project can.
    #
    # It also fixes something that was already latent: `write_period_json` globs the output
    # directory for earlier periods to build `trend`. Flat, a second project's periods would
    # have been swept into the first project's trend line.
    _flat_root = Path(output_dir)
    output_dir = _flat_root / pinputs.project
    # Part C review W2: periods written before this change sit FLAT in the root, where the
    # delta and trend globs no longer look. Left alone - moving a client's artefacts is
    # not this run's business - but said out loud, because the visible symptom is a fresh
    # `delta.period_0: true` and a one-point trend on an engagement that has history, and
    # nothing else would explain it.
    _orphaned = sorted(p.name for p in _flat_root.glob("period_*.json"))
    if _orphaned:
        logger.warning(
            "%d period file(s) sit flat in %s and belong to no project: %s. They are "
            "invisible to this run, so delta and trend restart from this period. Move "
            "them into %s to restore the history.",
            len(_orphaned), _flat_root, ", ".join(_orphaned), output_dir,
        )

    logger.info("Reading workbook: %s", workbook_path)
    # AM06: am_risk_ids is sourced from the resolved master register, so the
    # slim AM workbook no longer needs an embedded "Risk Register" sheet.
    workbook_data = read_workbook(workbook_path, register_path=register_path)
    refuse_fired_risks(workbook_data.risk_status)

    period_end_raw = workbook_data.period_info.get("am_period_end")
    if isinstance(period_end_raw, _dt.datetime):
        period_end = period_end_raw.date()
    elif isinstance(period_end_raw, _dt.date):
        period_end = period_end_raw
    elif isinstance(period_end_raw, str) and period_end_raw:
        period_end = _dt.date.fromisoformat(period_end_raw)
    else:
        period_end = _dt.date.today()
        logger.warning(
            "am_period_end not populated in workbook; defaulting to today (%s)",
            period_end.isoformat(),
        )

    previous_period_raw = workbook_data.period_info.get("am_previous_period")
    previous_period: _dt.date | None
    if isinstance(previous_period_raw, _dt.datetime):
        previous_period = previous_period_raw.date()
    elif isinstance(previous_period_raw, _dt.date):
        previous_period = previous_period_raw
    elif isinstance(previous_period_raw, str) and previous_period_raw:
        previous_period = _dt.date.fromisoformat(previous_period_raw)
    else:
        previous_period = None

    # Conditional MC run.
    logger.info(
        "Running conditional Stage 3 MC at %d iterations (seed=%d, mode=%r)",
        main_iterations, seed, criticality_measurement_mode,
    )
    cond_inputs = ConditionalRunInputs(
        workbook_data=workbook_data,
        register_path=register_path,
        xer_path=xer_path,
        strawman_path=strawman_path,
        n_iter=main_iterations,
        seed=seed,
        criticality_measurement_mode=criticality_measurement_mode,
        project=pinputs.project,
    )
    cond_result = run_conditional_mc(cond_inputs)

    # Rebuild graph + drivers for metrics. (Cheaper would be to thread
    # them out of run_conditional_mc; for v1 we parse the .xer twice
    # and accept the cost. The .xer parse takes ~1 second for V8.)
    binding_cfg = Stage3BindingConfig(
        register_path=register_path,
        xer_path=xer_path,
        strawman_path=strawman_path,
        float_threshold_hours=resolve_float_threshold_hours(pinputs.project or None),
    )
    xer_tables = parse_xer(xer_path)
    schedule_graph = build_schedule_graph(xer_tables)
    risk_drivers_full = build_drivers_for_project(
        project=pinputs.project,
        binding_cfg=binding_cfg,
        schedule_graph=schedule_graph,
        xer_tables=xer_tables,
        strawman_path=strawman_path,
    )
    activity_durations, activity_names = _activity_metadata(schedule_graph)
    deterministic_ef = _deterministic_ef_per_activity(schedule_graph)
    deterministic_finish_h = max(deterministic_ef.values())

    # Stage 7 part B (A-1): the integrated cost-plus-schedule result reaches the cycle.
    # The cost arm is conditioned by the SAME pinning as the schedule arm (Director,
    # 05/09/2026), and both the config and the day rate come from the register through
    # build_stage3_config - the one construction src/final/deliverable.py also uses.
    hours_per_day = float(schedule_graph.project_default_calendar.working_hours_per_day)
    integrated_result = None
    integrated_unavailable_reason = None
    try:
        integrated_result = run_integrated_period(
            register_path=register_path,
            xer_path=xer_path,
            strawman_path=pinputs.strawman_path,
            project_finish_days=np.asarray(
                cond_result.schedule_result.project_finish_days, dtype=float),
            deterministic_finish_days=deterministic_finish_h / hours_per_day,
            pinned_states=cond_result.pinned_states,
            severity_uniforms_by_risk_id=cond_result.severity_uniforms_by_risk_id,
            iterations=main_iterations,
            seed=seed,
            project=pinputs.project,
        )
    except IntegratedUnavailable as exc:
        # The block is optional by ruling (§5.2 C2), so the period is still valid without
        # it. Recorded in the audit block and logged, never silently absent.
        integrated_unavailable_reason = str(exc)
        logger.warning("Integrated result unavailable for this period: %s", exc)

    # Metrics layer.
    logger.info("Computing AM metrics")
    per_activity_bands = compute_per_activity_p_bands(
        schedule_result=cond_result.schedule_result,
        activity_durations_hours=activity_durations,
        activity_names=activity_names,
        deterministic_ef_hours=deterministic_ef,
        hours_per_day=schedule_graph.project_default_calendar.working_hours_per_day,
        top_n=top_n_by_ci,
        ci_threshold=ci_threshold,
    )
    ssi = compute_ssi_per_risk(cond_result.schedule_result, risk_drivers_full)
    tornado = compute_tornado_proxy_per_risk(
        risk_drivers_full,
        hours_per_day=schedule_graph.project_default_calendar.working_hours_per_day,
    )

    # Days-at-risk: iterate only the risks present on the dashboard view.
    risks_to_evaluate = [
        r["risk_id"] for r in workbook_data.risk_status
        if r["risk_id"] in risk_drivers_full
    ]
    if not risks_to_evaluate:
        risks_to_evaluate = list(risk_drivers_full.keys())
    logger.info(
        "Computing leave-one-out metrics (days_at_risk + sample sigma) "
        "for %d risks at %d iterations each (single re-run loop)",
        len(risks_to_evaluate), days_at_risk_iterations,
    )
    # AM04: one leave-one-out loop yields BOTH days_at_risk_p80 and the
    # sample-based tornado sigma; the re-run count is unchanged from the
    # prior days_at_risk-only behaviour (one re-run per evaluated risk).
    leave_one_out = compute_leave_one_out_metrics(
        baseline_inputs=cond_inputs,
        baseline_schedule_result=cond_result.schedule_result,
        risks_to_iterate=risks_to_evaluate,
        n_iter=days_at_risk_iterations,
        p_level=80,
    )
    days_at_risk = {
        rid: m["days_at_risk_p80"] for rid, m in leave_one_out.items()
    }
    tornado_sample_sigma = {
        rid: m["sample_sigma_days"] for rid, m in leave_one_out.items()
    }

    # Counterfactual sweep across any Proposed mitigations.
    proposed = [m for m in workbook_data.mitigations if m.get("status") == "Proposed"]
    logger.info(
        "Counterfactual sweep across %d Proposed mitigations at %d iterations each",
        len(proposed), counterfactual_iterations,
    )
    counterfactual = compute_counterfactual_sweep(
        baseline_inputs=cond_inputs,
        baseline_schedule_result=cond_result.schedule_result,
        proposed_mitigations=proposed,
        n_iter=counterfactual_iterations,
        p_level=80,
    )

    methodology_notes = build_methodology_notes(
        p_band_method=p_band_method,
        days_at_risk_iterations=days_at_risk_iterations,
        counterfactual_iterations=counterfactual_iterations,
        project_label=pinputs.methodology_label,
    )

    # AM02.1 §3.A.3: per-risk Mode-conditioned + Mode-independent CI
    # aggregation, derived from the same ScheduleMCResult that drives
    # SSI. No additional engine run.
    per_risk_criticality = compute_per_risk_criticality(
        cond_result.schedule_result, risk_drivers_full,
    )

    am_metrics = AMMetrics(
        per_activity_p_bands=per_activity_bands,
        ssi_per_risk=ssi,
        tornado_sigma_days_per_risk=tornado,
        days_at_risk_p80_per_risk=days_at_risk,
        counterfactual_days_saved_p80_per_mitigation=counterfactual,
        methodology_notes=methodology_notes,
        per_risk_criticality=per_risk_criticality,
        tornado_sample_sigma_days_per_risk=tornado_sample_sigma,
    )

    # AM09: engine-provenance stamp (per-file input digests + engine SHA vs
    # pin + dirty flag). Computed here in the I/O layer where the resolved
    # input paths live, keeping json_writer pure-data.
    engine_provenance = _build_engine_provenance(
        engine_sha=engine_sha,
        engine_tree_dirty=engine_tree_dirty,
        register_path=register_path,
        xer_path=xer_path,
        workbook_path=workbook_path,
    )

    # JSON write.
    logger.info("Writing period JSON to %s", output_dir)
    period_json = write_period_json(
        conditional_result=cond_result,
        am_metrics=am_metrics,
        workbook_data=workbook_data,
        risk_drivers=risk_drivers_full,
        project_start=project_start,
        deterministic_finish_hours=deterministic_finish_h,
        project_key=pinputs.project,
        integrated_result=integrated_result,
        integrated_unavailable_reason=integrated_unavailable_reason,
        workbook_filename=workbook_path.name,
        xer_filename=xer_path.name,
        register_version=pinputs.register_version,
        project_display_name=pinputs.display_name,
        output_dir=output_dir,
        period_end_date=period_end,
        previous_period_end_date=previous_period,
        engine_run_date=_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None),
        iterations=main_iterations,
        seed=seed,
        seed_source=seed_source,
        p_band_method=p_band_method,
        top_n=top_n_by_ci,
        ci_threshold=ci_threshold,
        engine_provenance=engine_provenance,
    )
    logger.info("Done: %s (%d bytes)", period_json, period_json.stat().st_size)
    return period_json


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="src.am.run_period",
        description="Run the monthly AM cycle end-to-end",
    )
    parser.add_argument(
        "--workbook", type=Path, required=True,
        help="Path to the period status workbook (.xlsx)",
    )
    parser.add_argument(
        "--project", default=None,  # no default project (QRAXL-01); QRA_PROJECT or --project
        choices=list(list_bindings()),  # the registered bindings, never literals
        help="Active project binding; no default (QRAXL-01). synthetic_wind "
             "routes the cycle to the wind fixtures in this repository.",
    )
    parser.add_argument(
        "--register", type=Path, default=None,
        help="Override the register path (default: resolved from --project)",
    )
    parser.add_argument(
        "--xer", type=Path, default=None,
        help="Override the .xer schedule path (default: resolved from --project)",
    )
    parser.add_argument(
        "--strawman", type=Path, default=None,
        help="Override the strawman path (default: --register when given, else resolved "
             "from --project)",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help="Directory to write the period JSON into",
    )
    parser.add_argument(
        "--main-iter", type=int, default=100_000,
        help="Main MC iteration count (production: 100k)",
    )
    parser.add_argument(
        "--days-at-risk-iter", type=int, default=10_000,
        help="Days-at-risk leave-one-out iterations per risk",
    )
    parser.add_argument(
        "--counterfactual-iter", type=int, default=10_000,
        help="Counterfactual mitigation iterations per proposal",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Override the project's declared period seed for this run (recorded as 'override')",
    )
    parser.add_argument(
        "--mode", default="both",
        choices=["mode_conditioned", "mode_independent", "both"],
        help="criticality_measurement_mode passed to run_schedule_mc",
    )
    parser.add_argument(
        "--project-start", type=str, default=DEFAULT_PROJECT_START.isoformat(),
        help="Project start date (YYYY-MM-DD) for day -> date conversion",
    )
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N_BY_CI)
    parser.add_argument("--ci-threshold", type=float, default=DEFAULT_CI_THRESHOLD)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="AM09: proceed even if this repository's tree is dirty; stamps "
        "meta.engine_tree_dirty: true (a NON-clean attestation).",
    )
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        out = _run_from_args(args)
    except FiredRiskRefused as exc:
        print(f"\nRUN REFUSED: {exc}\n", file=sys.stderr)
        return 2
    print(f"Wrote {out}")
    return 0


def _run_from_args(args: argparse.Namespace) -> Path:
    return run_period(
        workbook_path=args.workbook,
        project=args.project,
        register_path=args.register,
        xer_path=args.xer,
        strawman_path=args.strawman,
        output_dir=args.output_dir,
        main_iterations=args.main_iter,
        days_at_risk_iterations=args.days_at_risk_iter,
        counterfactual_iterations=args.counterfactual_iter,
        seed=args.seed,
        criticality_measurement_mode=args.mode,
        project_start=_dt.date.fromisoformat(args.project_start),
        top_n_by_ci=args.top_n,
        ci_threshold=args.ci_threshold,
        allow_dirty=args.allow_dirty,
    )


if __name__ == "__main__":
    sys.exit(_main())
