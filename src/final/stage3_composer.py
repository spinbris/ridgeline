"""SR14b Stage 3 standalone composer.

Builds the Stage 3 standalone deliverable that mirrors the Stage 2.5
final report's structure. Wraps the nine shared section-builders SR14a
+ SR14a.2 produced (consumed via :func:`src.final.composer.compose_final_report_data`)
and applies Stage 3 narrative text on top — the five SR14b D3-locked
constants from :mod:`src.final.stage3_beta_report` plus the preview
banner so the renderer banner hook fires on every page.

Two outputs per run, both at the AC4 filename pattern
``outputs/sra_stage3_standalone_PROD_<variant>_<date>.{html,docx}``:

* docx — generated via :func:`src.final.word_generator.generate_word_summary`
  consuming the rich Stage 3 composed dict (full section-builder shape;
  preview banner on every section via the SR14b D2 hook).
* html — generated via :func:`src.final.stage3_beta_report.render_stage3_beta_report_html`
  consuming the SR11 thin composed dict. The HTML structure stays
  Stage 3-thin-shape under SR14b session 2; the rich notebook-driven
  HTML form is a future SR14c amendment (the rich Stage 2.5 HTML comes
  from nbconvert rendering ``final_runner.ipynb``; producing a separate
  rich HTML for Stage 3 would require a parallel notebook, deferred to
  SR14c per close-out scope).

Decision D3=A continues to hold: Stage 3 narrative belongs to this
composer + the renderer hook; Stage 2.5 narrative stays in
``src.final.composer``. Decision D2 Option A: the
:func:`_maybe_render_preview_banner` and :func:`get_preview_banner`
hooks added to the Stage 2.5 renderers fire only when
``composed["preview_banner"]`` is set — this composer sets the key;
Stage 2.5's composer does not.

The Stage 2.5 production deliverable is unaffected. SR14b session 1's
lock proof (D5 reword the single named exception; everything else
byte-identical at content equivalence) carries forward; SR14b session
2 adds the Stage 3 standalone artefacts as additive output.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from src.final import commentary_text
from src.final.composer import compose_final_report_data
from src.final.executive_summary import detect_strawman_variant
from src.final.sections.correlation_sensitivity import (
    ELICITED_MISMATCH,
    build_correlation_sensitivity_section,
)
from src.final.sections.model_validation import build_model_validation_section
from src.rng_streams import require_seed
from src.final.stage3_beta_report import (
    COST_ARM_NOTE,
    DIVERSIFICATION_LINE,
    FOOTER_TEMPLATE,
    METHODOLOGY_SUMMARY_JOINT_SAMPLING,
    build_stage3_beta_composed,
    resolve_cover_caveat,
    resolve_preview_banner,
    render_stage3_beta_report_html,
)
from src.final.word_generator import generate_word_summary
from src.integrated.integrated_simulation import IntegratedConfig
from src.integrated.integrated_simulation_stage3 import (
    IntegratedConfigStage3,
    run_integrated_simulation_stage3,
)
from src.sra import strawman_reader
from src.integrated.stage3_inputs import (
    Stage3BindingConfig,
    resolve_float_threshold_hours,
)
from src.sra.cpm.cpm_simulation import ScheduleMCConfig


logger = logging.getLogger(__name__)


__all__ = [
    "compose_stage3_standalone_data",
    "emit_stage3_standalone_artefacts",
    "resolve_stage3_standalone_filename",
    # Re-exported D3 constants (Director-locked text the renderer hook +
    # cover caveat reference; surfaced here so downstream consumers
    # don't import from stage3_beta_report directly).
    "PREVIEW_BANNER_TEXT",
    "COVER_PAGE_CAVEAT_TEXT",
    "COST_ARM_NOTE",
    "DIVERSIFICATION_LINE",
    "FOOTER_TEMPLATE",
    "METHODOLOGY_SUMMARY_JOINT_SAMPLING",
]


# ---------------------------------------------------------------------------
# SR15.1 — Stage 3 schedule-arm wiring for the production-pipeline docx
# ---------------------------------------------------------------------------


def _build_stage3_integrated_scenario(
    *,
    stage3_beta_result: dict[str, Any],
    integrated_dp_review: dict[str, Any],
    config: IntegratedConfig,
    strawman_path: Path | str,
) -> dict[str, Any]:
    """Compute the Stage 3 schedule-arm flavoured DP_Review scenario dict.

    SR15.1 — replaces the Stage 2.5 integrated engine's
    ``schedule_days_array`` (which is Mode-multiplier-suppressed under
    the canonical Mode mix) with the Stage 3 CPM-replay
    schedule output (``apply_mode_multipliers=False`` per SR15). Cost
    arm and per-risk cost data flow through from the Stage 2.5
    integrated result (bit-identical to the Stage 3 integrated engine's
    cost arm at the seed-paired level per the SR11 cost-arm parity
    invariant; brief §4.3 Path 1).

    Schedule-driver per-risk ranking (Table 6) reads from the Stage 2.5
    integrated engine's ``per_risk_schedule_pre_mode_array`` (the
    pre-Mode-multiplier per-risk PERT-on-days contributions) so the
    seven currently-Parallel-mode risks surface non-zero contributions
    instead of being suppressed to 0%. The Stage 2.5 integrated engine
    already produces both ``per_risk_schedule_array`` (post-Mode) and
    ``per_risk_schedule_pre_mode_array`` (pre-Mode) on every run; SR15.1
    swaps the rendered ranking onto the pre-Mode variant. This is the
    closest available proxy for "what each risk would contribute without
    Mode suppression"; under Stage 3's full-CPM mechanic the per-risk
    contribution shape is fundamentally different (no simple summation
    across risks because the kernel walks the network), but the
    pre-Mode PERT-on-days ranking is a reasonable approximation of the
    relative ranking under the unsuppressed methodology and is what the
    methodology brief expects Table 6 to surface (Director-locked at
    SR15.1 §4.4).

    Parameters
    ----------
    stage3_beta_result : dict
        Output from the Stage 3 route — provides
        pre-loaded ``risk_drivers``, ``schedule_graph``, ``xer_tables``,
        and ``severity_uniforms_by_risk_id`` for the Stage 3 integrated
        engine re-run, avoiding duplicate XER parsing.
    integrated_dp_review : dict
        Existing Stage 2.5 integrated result for the DP_Review scenario;
        the cost arm and per-risk cost data flow through unchanged, and
        the per-risk schedule ranking flows through via the pre-Mode
        variant.
    config : IntegratedConfig
        Stage 2.5 integrated configuration; provides iteration count,
        seed, register / strawman / p6 paths.
    strawman_path : Path | str
        Strawman workbook path; reads ``Risk_Scope`` for the Stage 3
        engine's risk_scope_df input.

    Returns
    -------
    dict[str, Any]
        Stage 3-flavoured integrated result dict, same key shape as the
        Stage 2.5 integrated result (consumable by
        :func:`compose_final_report_data` without further changes). Keys
        replaced under SR15.1:

        * ``schedule_days_array`` ← Stage 3 CPM-replay output
        * ``per_risk_schedule_array`` ← Stage 2.5
          ``per_risk_schedule_pre_mode_array`` (pre-Mode-multiplier)

        Keys passed through from ``integrated_dp_review``:
        ``cost_dollars_array``, ``per_risk_cost_array``, ``fired_array``,
        ``risk_ids_all``, ``risk_ids_dual``, ``dual_lookup``,
        ``per_risk_schedule_pre_mode_array`` (retained alongside the
        replaced ``per_risk_schedule_array``).

    Notes
    -----
    Engine determinism: ``run_integrated_simulation_stage3`` is invoked
    with pre-loaded ``severity_uniforms_by_risk_id`` from the existing
    ``stage3_beta_result``, so the per-risk fire mask and PERT magnitudes
    are bit-identical to the smoke-runner output at the same seed. The
    Stage 3 cost arm output also bit-matches the Stage 2.5 cost arm at
    the seed-paired level (SR11 invariant).
    """
    # Construct the Stage 3 integrated config. apply_mode_multipliers=False
    # is the SR15 methodology default; explicit here so a reader of the
    # composer doesn't need to follow the binding-default chain.
    # REFRETIRE-01: this run's own schedule input, which is what the caller parsed the
    # ``xer_tables`` below from. The omitted field used to take one project's canonical .xer as
    # its default, on every project: inert only because the caller passes ``xer_tables``, so
    # nothing parsed the path - it reached the config summary and was discarded.
    bind_cfg = Stage3BindingConfig(
        register_path=Path(config.register_path),
        xer_path=Path(config.p6_path),
        strawman_path=Path(strawman_path),
        float_threshold_hours=resolve_float_threshold_hours(),
        populate_modes_from_strawman=True,
    )
    s3_int_cfg = IntegratedConfigStage3(
        integrated_config=config,
        schedule_mc_config=ScheduleMCConfig(
            n_iter=int(config.iterations),
            seed=require_seed(config.random_seed, where="src.final.stage3_composer"),
            apply_mode_multipliers=False,
            mode_multipliers=config.methodology_defaults.mode_multipliers,  # RS-D-3b
        ),
        binding_config=bind_cfg,
    )

    # Read Risk_Scope once; the Stage 3 integrated engine needs it.
    risk_scope_df = strawman_reader.read_risk_scope(Path(strawman_path))

    # Re-run the Stage 3 integrated engine with pre-loaded inputs from
    # the existing stage3_beta_result. The cost arm runs the Stage 2.5
    # cost engine internally; severity_uniforms_by_risk_id pre-load keeps
    # it bit-identical to the seed-paired Stage 2.5 run.
    s3_result = run_integrated_simulation_stage3(
        s3_int_cfg,
        risk_scope_df=risk_scope_df,
        schedule_graph=stage3_beta_result.get("schedule_graph"),
        risk_drivers=stage3_beta_result.get("risk_drivers"),
        xer_tables=stage3_beta_result.get("xer_tables"),
        severity_uniforms_by_risk_id=stage3_beta_result.get(
            "severity_uniforms_by_risk_id",
        ),
    )

    # Build the synthetic DP_Review-shape dict for the composer.
    s3_dp = dict(integrated_dp_review)
    s3_dp["schedule_days_array"] = np.asarray(s3_result.schedule_days_array)
    # Per-risk schedule ranking: swap to the pre-Mode variant so the
    # 7 currently-Parallel-mode risks surface non-zero contribution.
    pre_mode = integrated_dp_review.get("per_risk_schedule_pre_mode_array")
    if pre_mode is not None:
        s3_dp["per_risk_schedule_array"] = np.asarray(pre_mode)
    # Cost arm: prefer the Stage 3 engine's cost output for the
    # single-source-of-truth audit trail; bit-identical to the Stage 2.5
    # cost arm at seed-paired level per the SR11 invariant.
    s3_dp["cost_dollars_array"] = np.asarray(
        s3_result.cost_result["cost_dollars_array"],
    )
    if "per_risk_cost_array" in s3_result.cost_result:
        s3_dp["per_risk_cost_array"] = np.asarray(
            s3_result.cost_result["per_risk_cost_array"],
        )

    return s3_dp


# PRESENT-01 (D-6): the SR17 notebook-rewiring pair - a public alias over
# ``_build_stage3_integrated_scenario`` and a ``schedule_results`` proxy that subtracted
# ``min(project_finish_days)`` - retired here. Nothing called either: the deliverable's
# cross-validation reference is ``schedule_by_scenario['DP_Review']``
# (``deliverable.py:113``), and the only importer was a script that patched a notebook cell
# the rebuilt ``final_runner.ipynb`` does not have. The proxy's docstring still claimed it
# mirrored the integrated arm's baseline, which stopped being true at STAGE3HEADLINE-01 D-7.


# ---------------------------------------------------------------------------
# Stage 3 rich composer
# ---------------------------------------------------------------------------


def compose_stage3_standalone_data(
    cost_results: dict[str, Any],
    schedule_results: dict[str, Any],
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    schedule_results_by_scenario: dict[str, dict[str, Any]],
    strawman_path: Path | str,
    register_path: Path | str,
    cross_validation: dict[str, Any],
    *,
    stage3_beta_result: dict[str, Any] | None,
    risk_titles: dict[str, str] | None = None,
    config: IntegratedConfig | None = None,
    appendix_counterfactual: Any = None,
    run_date: str | None = None,
    engine_versions: dict[str, str] | None = None,
    risks: Iterable[Any] | None = None,
    chart_output_dir: Path | str | None = None,
    programme_duration_days: float | None = None,
    p6_path: Path | str | None = None,
    headline_metric: str = "P80",
    single_iteration_transparency_df: Any = None,
    cg_descriptions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the Stage 3 standalone composed dict.

    Calls :func:`compose_final_report_data` to obtain
    the rich Stage 2.5-shape composed dict, then overlays Stage 3
    narrative:

    * ``preview_banner`` set to ``PREVIEW_BANNER_TEXT`` so the renderer
      banner hook fires on every section.
    * ``cover_caveat`` set to ``COVER_PAGE_CAVEAT_TEXT`` (Director-locked
      D3.1 wording).
    * ``footer`` set to ``FOOTER_TEMPLATE.format(date=run_date)``
      (Director-locked D3.4 wording).
    * ``deliverable_kind`` set to ``"stage3_standalone"`` so renderers
      can vary section headings or table titles without re-deriving.

    The Stage 3 Beta engine result is threaded into the composer via
    the standard ``stage3_beta_result`` kwarg; this populates the
    ``page4b_criticality`` + ``criticality_note`` keys that the
    appendix renderer uses.

    Parameters
    ----------
    All arguments mirror :func:`compose_final_report_data` except
    ``stage3_beta_result`` is keyword-only and required (Stage 3
    standalone is meaningless without the Stage 3 engine output).
    ``mode`` is forced to ``"prod"`` (Stage 3 dev mode is not a
    supported deliverable status).

    Returns
    -------
    dict[str, Any]
        Stage 3 composed dict same-shape as the Stage 2.5 composer
        output, with the Stage 3 narrative keys overlaid. Renderer
        pipeline (``generate_word_summary``) consumes it unchanged.
    """
    if stage3_beta_result is None:
        raise ValueError(
            "compose_stage3_standalone_data requires stage3_beta_result "
            "to be non-None. Stage 3 standalone deliverable cannot be "
            "produced without the Stage 3 engine output. To produce a "
            "Stage 2.5 deliverable, use src.final.composer.compose_final_report_data."
        )

    # SR15.1 — Production-pipeline wiring catch-up. The Stage 3 standalone
    # composer previously wrapped the Stage 2.5 composer + overlaid Stage 3
    # narrative; the data tables underneath were rendered from the Stage
    # 2.5 integrated engine (Mode-multiplier-suppressed). SR15.1 replaces
    # the DP_Review scenario's integrated dict with a Stage 3-flavoured
    # version that uses the Stage 3 CPM-replay schedule output (built via
    # ``run_integrated_simulation_stage3`` with
    # ``apply_mode_multipliers=False`` per SR15) before the composer
    # consumes it; cost arm + per-risk cost data flow through unchanged
    # (bit-identical at seed-paired level per the SR11 invariant), and
    # the per-risk schedule ranking swaps to the Stage 2.5 engine's
    # ``per_risk_schedule_pre_mode_array`` so Parallel-mode risks surface
    # non-zero contributions. Brief §4.4 lists the docx tables that
    # change as a result (Tables 1, 2, 3, 6, 9, 12); Stage 2.5 lock
    # unaffected because ``compose_final_report_data`` itself is not
    # modified and the Stage 2.5 composer is not invoked via this branch
    # for Stage 2.5 deliverables. ``config`` is required to construct
    # the Stage 3 integrated config; if it is None we cannot rewire and
    # fall back to the pre-SR15.1 behaviour (Stage 2.5 numbers).
    s3_integrated_results_by_scenario = integrated_results_by_scenario
    if config is not None:
        _stage25_dp = integrated_results_by_scenario.get("DP_Review")
        if isinstance(_stage25_dp, dict):
            try:
                _stage3_dp = _build_stage3_integrated_scenario(
                    stage3_beta_result=stage3_beta_result,
                    integrated_dp_review=_stage25_dp,
                    config=config,
                    strawman_path=strawman_path,
                )
            except Exception as exc:
                # DELIVERABLE-SWALLOW-01 (3c Part A). This used to log and fall through to
                # the Stage 2.5 numbers - producing an artefact still titled and shipped as
                # Stage 3, carrying figures from a different methodology, with a log line as
                # the only signal. A client deliverable that is quietly the wrong stage is a
                # worse outcome than one not produced, so the failure now propagates.
                #
                # It costs D-11 nothing: the caller writes what it can and fails afterwards
                # (src/final/deliverable.write_artefacts), so the Word document and the state
                # cache still reach disk and the run still exits non-zero. What changes is
                # that the Stage 3 artefact is ABSENT and loud rather than present and wrong.
                logger.error(
                    "Stage 3 schedule-arm rewiring failed: %s", exc, exc_info=True)
                raise RuntimeError(
                    "Stage 3 schedule-arm rewiring failed, so the Stage 3 standalone "
                    "artefact cannot be built from Stage 3 numbers. Refusing to emit it from "
                    "the Stage 2.5 arm instead - it would be titled Stage 3 and carry another "
                    f"methodology's figures. Cause: {exc}"
                ) from exc
            else:
                s3_integrated_results_by_scenario = dict(
                    integrated_results_by_scenario,
                )
                s3_integrated_results_by_scenario["DP_Review"] = _stage3_dp
                logger.info(
                    "SR15.1: Stage 3 schedule-arm rewired into DP_Review; "
                    "schedule P80 days = %.2f (was %.2f under Stage 2.5)",
                    float(
                        np.percentile(_stage3_dp["schedule_days_array"], 80),
                    ),
                    float(
                        np.percentile(
                            np.asarray(
                                _stage25_dp.get("schedule_days_array", [0]),
                            ),
                            80,
                        ),
                    ),
                )

    composed = compose_final_report_data(
        cost_results=cost_results,
        schedule_results=schedule_results,
        integrated_results_by_scenario=s3_integrated_results_by_scenario,
        schedule_results_by_scenario=schedule_results_by_scenario,
        strawman_path=strawman_path,
        register_path=register_path,
        cross_validation=cross_validation,
        risk_titles=risk_titles,
        config=config,
        appendix_counterfactual=appendix_counterfactual,
        run_date=run_date,
        engine_versions=engine_versions,
        risks=risks,
        chart_output_dir=chart_output_dir,
        programme_duration_days=programme_duration_days,
        p6_path=p6_path,
        headline_metric=headline_metric,
        stage3_beta_result=stage3_beta_result,
        single_iteration_transparency_df=single_iteration_transparency_df,
        cg_descriptions=cg_descriptions,
    )

    resolved_run_date = run_date or _date.today().isoformat()

    # Stage 3 narrative overlay. Decision D3=A: Stage 3 narrative belongs
    # to this composer + the renderer hook; Stage 2.5 narrative stays
    # untouched in src.final.composer.
    composed["preview_banner"] = resolve_preview_banner()
    composed["cover_caveat"] = resolve_cover_caveat()
    composed["footer"] = FOOTER_TEMPLATE.format(date=resolved_run_date)
    composed["deliverable_kind"] = "stage3_standalone"

    # Tag the report_mode so renderers downstream of the prod-mode
    # overrides know they're rendering Stage 3 standalone, not Stage 2.5.
    composed["report_mode_stage3"] = "stage3_standalone"

    # SR14b AC5 — zero "Stage 2.5" references in the rendered Stage 3
    # docx body. The Stage 2.5 composer feeds the auto-mapper
    # interpretation field with text that names the comparison against
    # Stage 2.5's P80 (which is appropriate for the Stage 2.5
    # deliverable). For Stage 3 standalone we replace it with the
    # Stage 3 variant (commentary_text.AUTO_MAPPER_AUDIT_INTERPRETATION_TEMPLATE_STAGE3
    # — the §4.1 brief-amended _STAGE3 additive constant; same file,
    # additive only, Stage 2.5 lock preserved). The Stage 3 figure
    # speaks for itself; the comparison clause is dropped.
    audit_table = composed.get("stage3_beta_audit_table")
    stage3_p80_days = composed.get("stage3_beta_p80_schedule_days")
    if audit_table is not None and stage3_p80_days is not None:
        from src.final.executive_summary import (
            format_auto_mapper_audit_interpretation_stage3,
        )
        from src.final.sections.criticality import _run_activity_count
        composed["auto_mapper_audit_interpretation"] = (
            format_auto_mapper_audit_interpretation_stage3(
                audit_table=audit_table,
                stage3_p80_days=stage3_p80_days,
                schedule_size=_run_activity_count(stage3_beta_result),
            )
        )

    # SR14b AC5 — second Stage 2.5 reference in the SR10.B §10.5
    # risk-to-CP linkage prose's amplified-cohort note. The Stage 2.5
    # composer renders "...indicating the Stage 2.5 Mode tuning is..."
    # (appropriate for a Stage 2.5 deliverable referencing its own
    # baseline). For Stage 3 standalone the audience reads the
    # paragraph without the comparison frame; the same SR14b D3 audit
    # logic that strips the cover-caveat comparison applies here. We
    # substitute the single rendered prose line on the two
    # composed-dict sites that carry it (page4b_criticality + the
    # SR14b-deprecated criticality_note section); the rest of the
    # paragraph stays Stage 2.5-equivalent because the data is the
    # same. Future refactor (queued as a brief follow-up) threads the
    # ``amplified_mode_tuning_note`` kwarg through
    # ``_apply_criticality_keys`` → ``_apply_stage3_beta_keys`` →
    # ``compose_final_report_data`` so the substitution happens at the
    # formatter call site rather than as a composer-level reword.
    _stage25_amp_phrase = "indicating the Stage 2.5 Mode tuning is"
    _stage3_amp_phrase = "indicating the Mode-conditioned tuning is"
    for _key in ("page4b_criticality", "criticality_note"):
        _section = composed.get(_key)
        if not isinstance(_section, dict):
            continue
        _prose = _section.get("risk_to_cp_linkage_prose")
        if isinstance(_prose, str) and _stage25_amp_phrase in _prose:
            _section["risk_to_cp_linkage_prose"] = _prose.replace(
                _stage25_amp_phrase, _stage3_amp_phrase,
            )

    # SR15 — Decision 3 + Decision 4. Inject the new methodology
    # subsection text into the Methodology and caveats H1 (D3, rendered
    # by word_generator.py between the Methodology summary and Standards
    # references subsections) and the schedule drivers Table 6 footnote
    # (D4, rendered immediately under the drivers_table). Stage 2.5
    # composer does not set these keys; the renderer skips them when
    # absent, preserving the Stage 2.5 lock by construction.
    _p7 = composed.get("page7_methodology")
    if isinstance(_p7, dict):
        _p7["mode_multipliers_full_cpm_heading"] = (
            commentary_text.MODE_MULTIPLIERS_FULL_CPM_HEADING_STAGE3
        )
        _p7["mode_multipliers_full_cpm_paragraphs"] = (
            commentary_text.resolve_mode_multipliers_full_cpm_paragraphs()
        )
    _p4 = composed.get("page4_schedule_drivers")
    if isinstance(_p4, dict):
        _p4["mode_column_footnote_stage3"] = (
            commentary_text.SCHEDULE_DRIVERS_MODE_COLUMN_FOOTNOTE_STAGE3
        )

    # REPORT01 F-B (D-2): model-validation evidence belongs to the analytical document,
    # not the executive summary. Built from the Stage 3 result's own firing records, so
    # what it validates is the arm that produces the headline.
    if stage3_beta_result:
        composed.update(
            build_model_validation_section(
                stage3_beta_result, risks or [], risk_titles,
            )
        )

        # REPORT01 F-E (D-1): both correlation measures. `correlation_curves` is None
        # when the elicited counterfactual failed to reproduce the run's cost arm, and
        # the section then carries ELICITED_MISMATCH instead of a table nobody can trust.
        curves = stage3_beta_result.get("correlation_curves")
        corr = build_correlation_sensitivity_section(
            curves,
            stage3_beta_result.get("per_risk_cost_array"),
            stage3_beta_result.get("risk_ids_all"),
            risks or [],
            (config.methodology_defaults.cg_coefficients if config is not None else {}),
        )
        if curves is None:
            corr["page_correlation_sensitivity"]["withheld_reason"] = ELICITED_MISMATCH
        composed.update(corr)

    return composed


# ---------------------------------------------------------------------------
# Artefact emission
# ---------------------------------------------------------------------------


def resolve_stage3_standalone_filename(
    base_dir: Path | str,
    variant: str | None,
    run_date: str | None = None,
    suffix: str = ".docx",
) -> Path:
    """Return ``outputs/sra_stage3_standalone_PROD_<variant>_<date><suffix>``.

    Per AC4 filename pattern. ``variant`` falls back to ``"DPReview"``
    when ``None`` (the canonical un-tagged strawman case).
    """
    base_dir = Path(base_dir)
    if run_date is None:
        run_date = _date.today().isoformat()
    if variant is None or not str(variant).strip():
        variant = "DPReview"
    variant = str(variant).replace("_", "")
    return base_dir / f"sra_stage3_standalone_PROD_{variant}_{run_date}{suffix}"


def emit_stage3_standalone_artefacts(
    cost_results: dict[str, Any],
    schedule_results: dict[str, Any],
    integrated_results_by_scenario: dict[str, dict[str, Any]],
    schedule_results_by_scenario: dict[str, dict[str, Any]],
    strawman_path: Path | str,
    register_path: Path | str,
    cross_validation: dict[str, Any],
    output_dir: Path | str,
    *,
    stage3_beta_result: dict[str, Any] | None,
    stage3_beta_thin_result: Any | None = None,
    risk_titles: dict[str, str] | None = None,
    config: IntegratedConfig | None = None,
    appendix_counterfactual: Any = None,
    run_date: str | None = None,
    engine_versions: dict[str, str] | None = None,
    risks: Iterable[Any] | None = None,
    chart_output_dir: Path | str | None = None,
    programme_duration_days: float | None = None,
    p6_path: Path | str | None = None,
    headline_metric: str = "P80",
    single_iteration_transparency_df: Any = None,
    cg_descriptions: dict[str, str] | None = None,
    variant: str | None = None,
) -> dict[str, Any]:
    """Build + render the Stage 3 standalone HTML + docx pair (AC4).

    Pipeline
    --------
    1. Build the rich Stage 3 composed dict via
       :func:`compose_stage3_standalone_data`.
    2. Render docx via :func:`generate_word_summary` consuming the rich
       composed dict. The renderer banner hook fires because
       ``composed["preview_banner"]`` is set.
    3. Render HTML via :func:`render_stage3_beta_report_html` consuming
       the SR11 thin composed dict (built via
       :func:`build_stage3_beta_composed`). The thin renderer already
       embeds the SR14b D3 rewordings (the constants were updated in
       session 1). SR14c may replace this with a rich-notebook path.

    Filename per AC4:
    ``outputs/sra_stage3_standalone_PROD_<variant>_<date>.{html,docx}``.

    Parameters
    ----------
    output_dir : Path | str
        Where to write the two artefacts.
    stage3_beta_thin_result : Stage3IntegratedResult | None
        The Stage 3 engine result object the SR11 thin composer
        consumes. Required for HTML emission. ``None`` skips HTML
        emission (docx still produced).
    variant : str | None
        Strawman variant tag (Hybrid / Series / Parallel) for the
        filename. Falls back to detection via
        :func:`detect_strawman_variant` against ``strawman_path``;
        further falls back to ``"DPReview"`` for the canonical
        un-suffixed strawman.

    Returns
    -------
    dict[str, Any]
        ``{"docx_path": ..., "html_path": ..., "docx_size_bytes": ...,
        "html_size_bytes": ...}`` — paths are :class:`Path` objects
        (absolute); html_path is ``None`` when the thin engine result
        wasn't supplied.
    """
    composed = compose_stage3_standalone_data(
        cost_results=cost_results,
        schedule_results=schedule_results,
        integrated_results_by_scenario=integrated_results_by_scenario,
        schedule_results_by_scenario=schedule_results_by_scenario,
        strawman_path=strawman_path,
        register_path=register_path,
        cross_validation=cross_validation,
        stage3_beta_result=stage3_beta_result,
        risk_titles=risk_titles,
        config=config,
        appendix_counterfactual=appendix_counterfactual,
        run_date=run_date,
        engine_versions=engine_versions,
        risks=risks,
        chart_output_dir=chart_output_dir,
        programme_duration_days=programme_duration_days,
        p6_path=p6_path,
        headline_metric=headline_metric,
        single_iteration_transparency_df=single_iteration_transparency_df,
        cg_descriptions=cg_descriptions,
    )

    # Resolve variant for filenames.
    if variant is None:
        variant = detect_strawman_variant(strawman_path)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # docx — full SR14a/SR14a.2 section-builder shape, rendered by the
    # Stage 2.5 renderer pipeline + banner hook. ``generate_word_summary``
    # auto-prepends ``BETA_`` to the filename when ``composed["beta_flag"]``
    # is truthy (Beta-08 convention; the Stage 2.5 docx is named
    # ``BETA_sra_executive_summary_PROD_*.docx`` for the same reason).
    # The Stage 3 standalone filename per AC4 is
    # ``sra_stage3_standalone_PROD_*`` without the BETA_ prefix — the
    # filename itself communicates Stage 3, no further marker needed.
    # We therefore (a) let ``generate_word_summary`` write to its
    # BETA-prefixed path, (b) move the file to the AC4 path post-write.
    docx_path = resolve_stage3_standalone_filename(
        output_dir, variant=variant, run_date=run_date, suffix=".docx",
    )
    word_meta = generate_word_summary(
        summary_data=composed["executive_summary"],
        audit_trail_data=composed["appendix_audit_trail"],
        disclaimer_paragraphs=composed["disclaimer_paragraphs"],
        cross_validation=composed.get("cross_validation", {}),
        output_path=docx_path,
        composed=composed,
    )
    actual_docx_path = Path(word_meta["output_path"])
    if actual_docx_path.resolve() != docx_path.resolve():
        # generate_word_summary wrote to a BETA-prefixed path. Move to
        # the AC4 filename so the deliverable name is exactly what the
        # brief specifies.
        if docx_path.exists():
            docx_path.unlink()
        actual_docx_path.replace(docx_path)
    docx_size = docx_path.stat().st_size if docx_path.exists() else 0
    logger.info("Stage 3 standalone docx: %s (%d bytes)", docx_path, docx_size)

    # HTML — SR11 thin renderer path (close-out documents SR14c notebook
    # rich-HTML follow-up). Skipped when the thin engine result wasn't
    # supplied (test paths that only verify the docx surface).
    html_path: Path | None = None
    html_size = 0
    if stage3_beta_thin_result is not None:
        html_path = resolve_stage3_standalone_filename(
            output_dir, variant=variant, run_date=run_date, suffix=".html",
        )
        thin_composed = build_stage3_beta_composed(
            stage3_beta_thin_result,
            run_date=run_date,
            register_path=register_path,
            strawman_path=strawman_path,
            xer_path=p6_path,
        calibration_tolerances={k: getattr(config, k) for k in ('cost_calibration_tolerance_dollars', 'cost_calibration_tolerance_pct', 'schedule_calibration_tolerance_days', 'schedule_calibration_tolerance_pct')},  # RS-D-2
    )
        render_stage3_beta_report_html(
            thin_composed,
            output_path=html_path,
        )
        html_size = html_path.stat().st_size if html_path.exists() else 0
        logger.info("Stage 3 standalone html: %s (%d bytes)", html_path, html_size)

    return {
        "docx_path": docx_path,
        "html_path": html_path,
        "docx_size_bytes": int(docx_size),
        "html_size_bytes": int(html_size),
        "composed": composed,
    }


def __getattr__(name: str):
    """Resolve the binding-sourced cover caveat live (PEP 562). BINDINGSNAPSHOT-01.

    This module used to carry ``COVER_PAGE_CAVEAT_TEXT`` as a plain ``from`` import, which
    binds **once, at import**, capturing whichever project happened to be active then. In a
    process that changes project afterwards - the test suite does it per test, and a single
    install serving several projects (D-7) does it per run - the composer's copy stayed on the
    first project's text. Measured at 3c Part A: import under one project, switch, and the
    re-export still returned the first project's caveat while ``resolve_cover_caveat()``
    returned the right one.

    The composer's own use was already correct (``resolve_cover_caveat()`` at the ``cover_caveat``
    assignment), so no deliverable ever shipped the wrong caveat. What is closed here is the
    trap: the attribute is now resolved per access, so a future consumer reading
    ``stage3_composer.COVER_PAGE_CAVEAT_TEXT`` gets the active project's text.

    The ``from ... import`` form still snapshots - that is Python, not a design choice - which
    is why the constant is resolved at the point of use rather than held in a module global.
    """
    if name == "COVER_PAGE_CAVEAT_TEXT":
        return resolve_cover_caveat()
    if name == "PREVIEW_BANNER_TEXT":  # stage 4 F-33: same trap, same fix
        return resolve_preview_banner()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
