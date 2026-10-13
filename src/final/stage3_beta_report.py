"""SR11, Stage 3 Beta sibling deliverable composer + renderers.

Single source for:

* :func:`build_stage3_beta_composed`, composer assembly for the Stage
  3 Beta sibling deliverable. Reads a :class:`Stage3IntegratedResult`
  and emits the nested dict the sibling HTML and docx renderers
  consume.
* :func:`render_stage3_beta_report_html`, sibling HTML renderer
  (standalone; no Jupyter dependency).
* :func:`generate_stage3_beta_report_docx`, sibling docx renderer
  using python-docx.

Output filename pattern:
``outputs/sra_stage3_beta_report_PROD_{variant}_{date}.{html,docx}``

The preview banner appears on every "page" (every major section in
the HTML; in the docx it appears on the cover page, after the Page 1
table, and in the footer block). The cover-page caveat references
``docs/research/SR_S3_mapping_reasonableness_review.md``.

Per the SR11 brief §3 director-confirmed decisions: D1=A (new engine
module, already built), D2=A (sibling deliverable, this module),
D3=B (produce every run), D4=A (variant suffixing), D5=banner verbatim
from §3.5.
"""

from __future__ import annotations

import base64
import html as _html
import logging
import os
from datetime import date as _date
from pathlib import Path, PureWindowsPath
from typing import Mapping, Any

import numpy as np


from src.integrated.integrated_simulation_stage3 import (
    Stage3IntegratedResult,
    adapt_to_integrated_results_shape,
)
from src.final.product import MAKER, PRODUCT_NAME, TITLE_SUFFIX
from src.integrated.run_config_contract import require_day_rate


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Preview banner & cover-page caveat (§3.5 wording, Director-confirmed)
# ---------------------------------------------------------------------------

#: Preview-banner text rendered on every page. Binding-first (stage 4 F-33, 08/09/2026): the
#: §3.5 wording verbatim is the REFERENCE PROJECT's banner - it names that engagement's SR16
#: collapse figures, its five-of-eight gating collision and its electrical-instrumentation
#: activity - and it now lives in that binding's ``NARRATIVE_TEMPLATES["stage3_preview_banner"]``,
#: byte-identical, where the cover caveat already lived. Until then every project's standalone
#: report printed it, tokens and all (stage 4 ran a road project and the report said
#: "<pre_sr16_p80>d" six times). This generic fallback carries no project figure and is what a
#: binding without its own banner gets. Read it through :func:`resolve_preview_banner` or the
#: module attribute ``PREVIEW_BANNER_TEXT``; do not bind it at import (see ``__getattr__``).
_GENERIC_PREVIEW_BANNER_TEXT: str = (
    "Stage 3 preview. Risk-driver schedule bindings are auto-mapped from the register's "
    "mapping rules; mapping-workshop validation of those bindings is pending. Not for "
    "funding decisions or commercial commitment without workshop sign-off on the "
    "gating-activity selection."
)


def resolve_preview_banner() -> str:
    """Stage 3 preview banner for the active project (binding-first)."""
    from src.sra.cpm.bindings import get_active_binding

    return get_active_binding().narrative("stage3_preview_banner") or _GENERIC_PREVIEW_BANNER_TEXT

#: Cover-page caveat. SR14b D3.1 reword: reframes the preview banner
#: with a self-contained, section-leading voice. Pre-SR14b text framed
#: the Stage 3 Beta as a sibling to Stage 2.5; SR14b strips the Stage
#: 2.5 reference so Stage 3 reads as a deliverable in its own right
#: and renames the explicit not-for-funding gate to point at workshop
#: validation rather than the Stage 2.5 headline.
# Stage 3 Beta cover caveat + schedule-basis note (Director-locked, SR14b
# D3.1). The project-specific copy lives in the active binding's
# NARRATIVE_TEMPLATES (keys stage3_cover_caveat / stage3_schedule_basis,
# byte-identical to the prior literals); these generic fallbacks carry no
# project name and are used when the binding supplies none. The module
# __getattr__ at the bottom resolves COVER_PAGE_CAVEAT_TEXT to the active
# project's copy, so external readers (and the verbatim-text tests) see the
# a project's own text unchanged. (Showcase-P2 WS2-B.)
_GENERIC_COVER_PAGE_CAVEAT: str = (
    "This deliverable presents the Stage 3 integrated cost-plus-schedule "
    "contingency for the project scope. Risk-driver schedule assignments "
    "are auto-mapped pending mapping-workshop validation; until that "
    "workshop is complete, this is not for funding decisions or commercial "
    "commitment."
)

#: The GN4 escalation hand-off. Director ruling 06/09/2026 ("escalation is required"), taken as
#: the LIGHTER of the review's two ESC-01 options - a documented client-side hand-off, not the
#: module. That distinction matters at the spec level: D-1/R-5 rule this product **contingency
#: only**, and a hand-off does not compute escalation, it states that the product does not. So
#: R-5 stands untouched. Reversing D-1 to build the GN4 module remains a Director decision, and
#: reopens D-2 (the GN3B deterministic layer, currently "moot under R-5").
#:
#: Why it is APPENDED rather than written into the generic caveat: `resolve_cover_caveat` prefers
#: a binding's own narrative, and **both** shipped bindings override it
#: (`synthetic_wind.py:62`). Placed in the generic text this statement would
#: never reach a single real reader. A statement about what the PRODUCT does not do must not be
#: a project's to drop.
#:
#: No base date is quoted because the product has none: there is no base-date field anywhere in
#: `src/`. Saying so is the honest form of the hand-off - a reader who needs an outturn figure
#: needs to know the base date is theirs to establish, not ours to assume.
_ESCALATION_HANDOFF: str = (
    " Escalation is not applied. These figures are REAL TERMS at the base date of the underlying "
    "estimate, which this product does not record and which the estimator must state. GN4 "
    "Appendix C reserves \"outturn\" for the post-escalation nominal figure, so nothing here is "
    "an outturn figure in that sense. To reach one, apply an escalation index to a cash-flow "
    "profile of these costs - a step outside this product."
)

#: The caveat names the product that made the figures (PUBLICFACE-01), so a reader holding only this
#: page knows whose analysis it is.
_PRODUCT_LINE: str = f" Produced by {PRODUCT_NAME}, a {MAKER} product."

_GENERIC_SCHEDULE_BASIS: str = (
    "Stage 3 CPM-replay against the project Primavera P6 schedule. "
    "Risk-driver assignments come from the strawman's auto-mapper rules "
    "(pattern-prefix matching with a float filter); workshop validation of "
    "these assignments is the production transition gate."
)


def resolve_cover_caveat() -> str:
    """Stage 3 cover caveat for the active project (binding-first)."""
    from src.sra.cpm.bindings import get_active_binding

    project = get_active_binding().narrative("stage3_cover_caveat")
    return (project or _GENERIC_COVER_PAGE_CAVEAT) + _ESCALATION_HANDOFF + _PRODUCT_LINE


def resolve_schedule_basis() -> str:
    """Stage 3 schedule-basis note for the active project (binding-first)."""
    from src.sra.cpm.bindings import get_active_binding

    return get_active_binding().narrative("stage3_schedule_basis") or _GENERIC_SCHEDULE_BASIS


# ---------------------------------------------------------------------------
# SR14b methodology-bearing text rewordings (D3.2 - D3.5)
# Director-signed-off 2026-05-15. The constants below are the canonical
# text for the four inline strings that previously lived at the render
# sites; pinned here so tests/test_sr14b_text_rewordings.py can verify
# them verbatim and so the new SR14b stage3_composer can import them.
# ---------------------------------------------------------------------------

#: D3.2, Cost arm summary note. SR14b strips the "bit-identical to
#: Stage 2.5" reference and replaces with a self-contained description
#: of the cost-arm joint-sampling structure.
COST_ARM_NOTE: str = (
    "The cost arm uses the standard PERT severity sampler with joint "
    "dual-coded risk sharing. Per iteration, dual-coded risks "
    "(Time=Yes) draw one shared severity uniform that drives both the "
    "cost-arm PERT and the schedule-arm CPM-replay sampler; cost-only "
    "risks use independent severity uniforms."
)

#: D3.3, Diversification line annotation. SR14b strips the "can flip
#: relative to Stage 2.5" reference; sign behaviour is a property of
#: the joint correlation structure under the Stage 3 Beta schedule
#: branch alone.
DIVERSIFICATION_LINE: str = (
    "The diversification line is the joint MC adjustment (integrated "
    "minus naive sum). Its sign reflects the joint correlation "
    "structure under the Stage 3 Beta schedule branch."
)

#: D3.4, Footer line. SR14b strips the "Stage 2.5 production
#: deliverable remains the headline" reminder and renames the
#: generator module to ``src.final.stage3_composer`` (the new SR14b
#: composer that supersedes the SR11 thin composer for the rich Stage
#: 3 standalone deliverable). The ``{date}`` placeholder is filled by
#: the renderer at format time.
FOOTER_TEMPLATE: str = (
    f"Stage 3 Beta deliverable. Generated by {PRODUCT_NAME} "
    "on {date}."
)

#: D3.5, Methodology summary joint-sampling paragraph. SR14b strips
#: the "matches the Stage 2.5 joint-sampling architecture" reference
#: and reframes the description as the standard joint-sampling
#: architecture for cost-plus-schedule integration.
METHODOLOGY_SUMMARY_JOINT_SAMPLING: str = (
    "Per iteration, dual-coded risks (Time=Yes) draw ONE shared "
    "severity uniform that drives both the cost-arm PERT and the "
    "Stage 3 Beta schedule-arm CPM-replay sampler. Cost-only risks "
    "use independent severity uniforms. This is the standard "
    "joint-sampling architecture for cost-plus-schedule integration."
)


# ---------------------------------------------------------------------------
# Page 1 table assembly
# ---------------------------------------------------------------------------

def _format_signed_dollars_m(value_dollars: float) -> str:
    """Render a signed-dollar-millions value as ``+$X.XXM`` / ``-$X.XXM``."""
    sign = "+" if value_dollars >= 0 else "-"
    return f"{sign}${abs(value_dollars) / 1e6:.2f}M"


def build_page1_stage3_beta_table(
    result: Stage3IntegratedResult,
    day_rate: float,
    p_level: int = 80,
) -> list[dict[str, Any]]:
    """Build the Page 1 contingency table for the Stage 3 Beta sibling.

    Five rows × three numeric columns (plus Component name + Notes):

    * Row 1, Cost contingency
    * Row 2, Schedule contingency (dollarised)
    * Row 3, Naive sum
    * Row 4, Diversification effect
    * Row 5, Integrated total

    Columns: P80, Mean, Value (Value aliases P80 for legacy consumers).

    The diversification line carries an explicit sign, its sign can
    flip depending on the joint correlation structure under the Stage
    3 Beta schedule branch. The composer renders whatever the engine
    produces; the preview banner explains the over-binding context.

    Parameters
    ----------
    result : Stage3IntegratedResult
        Engine output from :func:`run_integrated_simulation_stage3`.
    day_rate : float
        Dollar-per-working-day rate from
        ``Run_Config_Preview.Day_rate_default``, the project's own rate.
    p_level : int
        Percentile used for the P-column. Default 80 (matches
        production headline metric).

    Returns
    -------
    list[dict[str, Any]]
        Five rows, ready to render in HTML or docx.
    """
    cost_arr = np.asarray(result.cost_result["cost_dollars_array"], dtype=np.float64)
    sched_arr = np.asarray(result.schedule_days_array, dtype=np.float64)
    if cost_arr.size == 0 or sched_arr.size == 0:
        return []

    day_rate = float(day_rate)
    p_level = int(p_level)

    cost_p = float(np.percentile(cost_arr, p_level))
    sched_p_days = float(np.percentile(sched_arr, p_level))
    sched_p_dollars = sched_p_days * day_rate
    naive_sum_p = cost_p + sched_p_dollars
    integrated_total_p = float(
        np.percentile(cost_arr + sched_arr * day_rate, p_level)
    )
    diversification_p = integrated_total_p - naive_sum_p

    cost_mean = float(np.mean(cost_arr))
    sched_mean_days = float(np.mean(sched_arr))
    sched_mean_dollars = sched_mean_days * day_rate
    naive_sum_mean = cost_mean + sched_mean_dollars
    integrated_total_mean = float(np.mean(cost_arr + sched_arr * day_rate))
    diversification_mean = integrated_total_mean - naive_sum_mean

    return [
        {
            "Component": "Cost contingency",
            "P80": f"${cost_p / 1e6:.2f}M",
            "Mean": f"${cost_mean / 1e6:.2f}M",
            "Value": f"${cost_p / 1e6:.2f}M",
            "Notes": "Mode-independent",
        },
        {
            "Component": "Schedule contingency (dollarised)",
            "P80": f"${sched_p_dollars / 1e6:.2f}M",
            "Mean": f"${sched_mean_dollars / 1e6:.2f}M",
            "Value": f"${sched_p_dollars / 1e6:.2f}M",
            "Notes": (
                "Stage 3 Beta CPM-replay schedule, dollarised at "
                f"${day_rate:,.0f}/working-day"
            ),
        },
        {
            "Component": "Naive sum",
            "P80": f"${naive_sum_p / 1e6:.2f}M",
            "Mean": f"${naive_sum_mean / 1e6:.2f}M",
            "Value": f"${naive_sum_p / 1e6:.2f}M",
            "Notes": "Cost + schedule, no joint adjustment",
        },
        {
            "Component": "Diversification effect",
            "P80": _format_signed_dollars_m(diversification_p),
            "Mean": _format_signed_dollars_m(diversification_mean),
            "Value": _format_signed_dollars_m(diversification_p),
            "Notes": "Joint MC adjustment (integrated minus naive sum)",
        },
        {
            "Component": "Integrated total",
            "P80": f"${integrated_total_p / 1e6:.2f}M",
            "Mean": f"${integrated_total_mean / 1e6:.2f}M",
            "Value": f"${integrated_total_p / 1e6:.2f}M",
            "Notes": "Stage 3 Beta integrated cost + schedule",
        },
    ]


def _file_name(path: Any) -> str | None:
    """The file's name alone, whichever separator the recorded path used."""
    return PureWindowsPath(str(path)).name if path else None


def _active_project_display_name() -> str:
    from src.sra.cpm.bindings import get_active_binding, project_display_name

    return project_display_name(get_active_binding())


def _report_title(composed: Mapping[str, Any], variant: Any, run_date: Any) -> str:
    """Project, then what the document is, then the product (as the deliverable HTML's title)."""
    project = str(composed.get("project_display_name") or "")
    head = f"{project}: " if project else ""
    return (f"{head}Stage 3 Beta integrated contingency, {variant} variant ({run_date})"
            f"{TITLE_SUFFIX}")


def build_stage3_beta_composed(
    result: Stage3IntegratedResult,
    *,
    day_rate: float | None = None,
    p_level: int = 80,
    run_date: str | None = None,
    register_path: Path | str | None = None,
    strawman_path: Path | str | None = None,
    xer_path: Path | str | None = None,
    calibration_tolerances: Mapping[str, float],
) -> dict[str, Any]:
    """Compose the nested dict the sibling-renderers consume.

    Returns a dict with these top-level keys:

    * ``preview_banner``, banner string (rendered on every page)
    * ``cover_caveat``, cover-page caveat text
    * ``run_date``, YYYY-MM-DD
    * ``variant_label``, Hybrid / Series / etc
    * ``iterations``, int
    * ``page1_table``, list[dict] with 5 rows × {Component, P80,
      Mean, Value, Notes}
    * ``headline``, dict with P80 and Mean integrated totals as
      formatted strings; surfaced for the cover page
    * ``methodology_summary``, dict with calibration tolerances,
      joint-sampling description, schedule basis (Stage 3 Beta
      CPM-replay)
    * ``cost_summary``, dict with cost-arm P-values and mean
    * ``schedule_summary``, dict with schedule-arm P-values (days
      and $) and mean
    * ``audit_trail``, dict with paths to register / strawman / .xer
      / auto-mapper audit parquet
    * ``beta_flag``, bool
    """
    if run_date is None:
        run_date = _date.today().isoformat()

    # Resolve day_rate: explicit kwarg wins; otherwise pull from the
    # result's config_summary (sourced upstream from
    # IntegratedConfig.day_rate, which is itself populated from
    # Run_Config_Preview.Day_rate_default, the strawman is the
    # methodology source of truth).
    #
    # DAYRATE-02, Director ruling 31/08: the last-resort fallback to
    # the old module day-rate constant is REMOVED. It was described as being for
    # "synthetic-test inputs that bypass config plumbing", which is the
    # problem stated as though it were the justification: a synthetic input
    # that bypasses the plumbing would have been dollarised at another project's
    # client rate. Every hardcoded number belongs to some other project, so
    # on this one it is wrong - silently. Absent a rate, this stops.
    if day_rate is None:
        day_rate = require_day_rate(
            result.config_summary.get("day_rate"),
            caller="build_stage3_beta_report",
        )

    page1 = build_page1_stage3_beta_table(result, day_rate=day_rate, p_level=p_level)

    cost_arr = np.asarray(
        result.cost_result["cost_dollars_array"], dtype=np.float64,
    )
    sched_arr = np.asarray(result.schedule_days_array, dtype=np.float64)
    integrated_total_arr = cost_arr + sched_arr * float(day_rate)

    headline = {
        "integrated_p80_dollars": float(np.percentile(integrated_total_arr, p_level)),
        "integrated_p80_m_str": (
            f"${float(np.percentile(integrated_total_arr, p_level)) / 1e6:.2f}M"
        ),
        "integrated_mean_dollars": float(np.mean(integrated_total_arr)),
        "integrated_mean_m_str": f"${float(np.mean(integrated_total_arr)) / 1e6:.2f}M",
        "p_level": int(p_level),
    }

    cost_summary = {
        "p50_m_str": f"${float(np.percentile(cost_arr, 50)) / 1e6:.2f}M",
        "p80_m_str": f"${float(np.percentile(cost_arr, 80)) / 1e6:.2f}M",
        "p90_m_str": f"${float(np.percentile(cost_arr, 90)) / 1e6:.2f}M",
        "mean_m_str": f"${float(np.mean(cost_arr)) / 1e6:.2f}M",
    }

    schedule_summary = {
        "p50_days": float(np.percentile(sched_arr, 50)),
        "p80_days": float(np.percentile(sched_arr, 80)),
        "p90_days": float(np.percentile(sched_arr, 90)),
        "mean_days": float(np.mean(sched_arr)),
        "p50_dollars_m_str": (
            f"${float(np.percentile(sched_arr, 50)) * day_rate / 1e6:.2f}M"
        ),
        "p80_dollars_m_str": (
            f"${float(np.percentile(sched_arr, 80)) * day_rate / 1e6:.2f}M"
        ),
        "p90_dollars_m_str": (
            f"${float(np.percentile(sched_arr, 90)) * day_rate / 1e6:.2f}M"
        ),
        "mean_dollars_m_str": (
            f"${float(np.mean(sched_arr)) * day_rate / 1e6:.2f}M"
        ),
        "day_rate_dollars": float(day_rate),
        "day_rate_str": f"${day_rate:,.0f}/working-day",
    }

    _tolerances = dict(calibration_tolerances)  # RS-D-2: the caller's config values
    methodology_summary = {
        "joint_sampling": METHODOLOGY_SUMMARY_JOINT_SAMPLING,
        "schedule_basis": resolve_schedule_basis(),
        # RS-D-2 (D-14): the register's tolerances, not literals.
        "calibration_tolerance_cost_dollars": _tolerances["cost_calibration_tolerance_dollars"],
        "calibration_tolerance_schedule_days": _tolerances["schedule_calibration_tolerance_days"],
        "calibration_tolerance_cost_pct": _tolerances["cost_calibration_tolerance_pct"],
        "calibration_tolerance_schedule_pct": _tolerances["schedule_calibration_tolerance_pct"],
        "p_level": int(p_level),
    }

    # The reader gets file names, not the analyst's folders; the full paths stay in provenance.json.
    audit_trail = {
        "register_path": _file_name(register_path),
        "strawman_path": _file_name(strawman_path),
        "xer_path": _file_name(xer_path),
        "auto_mapper_audit_path": _file_name(result.auto_mapper_audit_path),
        "iterations": int(result.iterations),
        "seed_used": int(result.seed_used),
        "criticality_measurement_mode": (
            result.config_summary.get("criticality_measurement_mode", "")
        ),
    }

    return {
        "project_display_name": _active_project_display_name(),
        "preview_banner": resolve_preview_banner(),
        "cover_caveat": resolve_cover_caveat(),
        "run_date": run_date,
        "variant_label": result.variant_label,
        "iterations": int(result.iterations),
        "seed_used": int(result.seed_used),
        "page1_table": page1,
        "headline": headline,
        "methodology_summary": methodology_summary,
        "cost_summary": cost_summary,
        "schedule_summary": schedule_summary,
        "audit_trail": audit_trail,
        "beta_flag": bool(result.beta_flag),
    }


# ---------------------------------------------------------------------------
# Sibling HTML renderer
# ---------------------------------------------------------------------------

_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
       'Helvetica Neue', Arial, sans-serif; max-width: 980px;
       margin: 2em auto; padding: 0 1em; color: #222; line-height: 1.45; }
h1 { color: #1f3864; border-bottom: 2px solid #1f3864; padding-bottom: .3em; }
h2 { color: #2e5597; margin-top: 1.8em; }
table { border-collapse: collapse; width: 100%; margin: 0.6em 0 1.2em 0;
        font-size: 0.92em; }
th, td { border: 1px solid #bbb; padding: 5px 8px; text-align: left;
         vertical-align: top; }
th { background: #f0f3fa; font-weight: bold; }
.preview-banner { background: #ffe6cc; border: 2px solid #cc6600;
                  padding: 0.8em 1em; margin: 0.6em 0 1.4em 0;
                  font-weight: bold; color: #663300; }
.cover-caveat { background: #faf7e8; border: 1px solid #c5b471;
                padding: 0.8em 1em; margin: 0.6em 0 1.4em 0;
                color: #4a4023; font-style: italic; }
.audit { font-size: 0.85em; color: #666; margin-top: 2em;
         padding-top: 0.6em; border-top: 1px solid #ddd; }
.headline-figure { font-size: 1.2em; font-weight: bold; color: #1f3864; }
"""


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return _html.escape(str(value), quote=False)


def _render_page1_table_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p><em>Page 1 table is empty (engine returned no data).</em></p>"
    cols = ["Component", "P80", "Mean", "Value", "Notes"]
    parts: list[str] = ["<table>", "<thead><tr>"]
    parts.extend("<th>" + _esc(c) + "</th>" for c in cols)
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        for c in cols:
            parts.append("<td>" + _esc(row.get(c, "")) + "</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def render_stage3_beta_report_html(
    composed: dict[str, Any],
    output_path: Path | str,
) -> dict[str, Any]:
    """Render the Stage 3 Beta sibling deliverable as standalone HTML.

    Parameters
    ----------
    composed : dict
        Output of :func:`build_stage3_beta_composed`.
    output_path : Path | str
        Destination path. Caller chooses the
        ``sra_stage3_beta_report_PROD_{variant}_{date}.html`` filename.

    Returns
    -------
    dict
        ``output_path``, ``size_bytes``, ``sections_rendered``.
    """
    output_path = Path(output_path)
    variant = composed.get("variant_label", "")
    run_date = composed.get("run_date", "")
    iterations = composed.get("iterations", 0)
    seed = composed["seed_used"]  # never printed as 0 when absent (SEEDZERO-01)
    headline = composed.get("headline", {}) or {}
    page1 = composed.get("page1_table", []) or []
    cost = composed.get("cost_summary", {}) or {}
    sched = composed.get("schedule_summary", {}) or {}
    methodology = composed.get("methodology_summary", {}) or {}
    audit = composed.get("audit_trail", {}) or {}

    sections = 0

    title = _report_title(composed, variant, run_date)
    body_parts: list[str] = ["<h1>" + _esc(title) + "</h1>"]

    body_parts.append(
        '<div class="preview-banner">'
        + _esc(composed.get("preview_banner", ""))
        + "</div>"
    )
    sections += 1

    body_parts.append(
        '<div class="cover-caveat">'
        + _esc(composed.get("cover_caveat", ""))
        + "</div>"
    )
    sections += 1

    body_parts.append("<h2>Headline integrated contingency (P80)</h2>")
    body_parts.append(
        '<p class="headline-figure">'
        + _esc(headline.get("integrated_p80_m_str", ""))
        + " (Mean: "
        + _esc(headline.get("integrated_mean_m_str", ""))
        + ")</p>"
    )
    body_parts.append(
        "<p>This is the Stage 3 Beta integrated cost-plus-schedule "
        "contingency at the P80 confidence level. The Mean figure is "
        "the arithmetic mean of the integrated distribution and is "
        "shown for completeness. See the table below for the component "
        "breakdown.</p>"
    )
    sections += 1

    body_parts.append("<h2>Page 1, Component breakdown</h2>")
    body_parts.append(
        '<div class="preview-banner">'
        + _esc(composed.get("preview_banner", ""))
        + "</div>"
    )
    body_parts.append(_render_page1_table_html(page1))
    body_parts.append("<p>" + _esc(DIVERSIFICATION_LINE) + "</p>")
    sections += 1

    body_parts.append("<h2>Cost arm summary</h2>")
    body_parts.append(
        '<div class="preview-banner">'
        + _esc(composed.get("preview_banner", ""))
        + "</div>"
    )
    body_parts.append(
        "<table><thead><tr>"
        + "<th>Metric</th><th>Value</th>"
        + "</tr></thead><tbody>"
        + "<tr><td>P50</td><td>" + _esc(cost.get("p50_m_str", "")) + "</td></tr>"
        + "<tr><td>P80</td><td>" + _esc(cost.get("p80_m_str", "")) + "</td></tr>"
        + "<tr><td>P90</td><td>" + _esc(cost.get("p90_m_str", "")) + "</td></tr>"
        + "<tr><td>Mean</td><td>" + _esc(cost.get("mean_m_str", "")) + "</td></tr>"
        + "</tbody></table>"
    )
    body_parts.append("<p>" + _esc(COST_ARM_NOTE) + "</p>")
    sections += 1

    body_parts.append("<h2>Schedule arm summary</h2>")
    body_parts.append(
        '<div class="preview-banner">'
        + _esc(composed.get("preview_banner", ""))
        + "</div>"
    )
    body_parts.append(
        "<table><thead><tr>"
        + "<th>Metric</th><th>Working days</th><th>Dollarised at "
        + _esc(sched.get("day_rate_str", "")) + "</th>"
        + "</tr></thead><tbody>"
        + "<tr><td>P50</td><td>"
        + _esc(f"{sched.get('p50_days', 0.0):.0f}") + "</td><td>"
        + _esc(sched.get("p50_dollars_m_str", "")) + "</td></tr>"
        + "<tr><td>P80</td><td>"
        + _esc(f"{sched.get('p80_days', 0.0):.0f}") + "</td><td>"
        + _esc(sched.get("p80_dollars_m_str", "")) + "</td></tr>"
        + "<tr><td>P90</td><td>"
        + _esc(f"{sched.get('p90_days', 0.0):.0f}") + "</td><td>"
        + _esc(sched.get("p90_dollars_m_str", "")) + "</td></tr>"
        + "<tr><td>Mean</td><td>"
        + _esc(f"{sched.get('mean_days', 0.0):.0f}") + "</td><td>"
        + _esc(sched.get("mean_dollars_m_str", "")) + "</td></tr>"
        + "</tbody></table>"
    )
    sections += 1

    body_parts.append("<h2>Methodology summary</h2>")
    body_parts.append(
        '<div class="preview-banner">'
        + _esc(composed.get("preview_banner", ""))
        + "</div>"
    )
    body_parts.append(
        "<p><strong>Joint sampling: </strong>"
        + _esc(methodology.get("joint_sampling", ""))
        + "</p>"
    )
    body_parts.append(
        "<p><strong>Schedule basis: </strong>"
        + _esc(methodology.get("schedule_basis", ""))
        + "</p>"
    )
    body_parts.append(
        "<p><strong>Calibration tolerances: </strong>"
        + "$" + _esc(f"{int(methodology.get('calibration_tolerance_cost_dollars', 0)):,}")
        + " cost / "
        + _esc(f"{methodology.get('calibration_tolerance_schedule_days', 0):.0f}")
        + " day schedule, against Stage 3 Beta standalone marginals.</p>"
    )
    sections += 1

    body_parts.append("<h2>Audit trail</h2>")
    body_parts.append(
        '<div class="preview-banner">'
        + _esc(composed.get("preview_banner", ""))
        + "</div>"
    )
    audit_lines = [
        "<table><tbody>",
        "<tr><th>Iterations</th><td>" + _esc(iterations) + "</td></tr>",
        "<tr><th>Seed</th><td>" + _esc(seed) + "</td></tr>",
        "<tr><th>Variant</th><td>" + _esc(variant) + "</td></tr>",
        "<tr><th>Register</th><td>"
        + _esc(audit.get("register_path", "") or "(not recorded)")
        + "</td></tr>",
        "<tr><th>Strawman</th><td>"
        + _esc(audit.get("strawman_path", "") or "(not recorded)")
        + "</td></tr>",
        "<tr><th>P6 (.xer)</th><td>"
        + _esc(audit.get("xer_path", "") or "(not recorded)")
        + "</td></tr>",
        "<tr><th>Auto-mapper audit</th><td>"
        + _esc(audit.get("auto_mapper_audit_path", "") or "(not recorded)")
        + "</td></tr>",
        "<tr><th>Criticality mode</th><td>"
        + _esc(audit.get("criticality_measurement_mode", ""))
        + "</td></tr>",
        "</tbody></table>",
    ]
    body_parts.extend(audit_lines)
    sections += 1

    body_parts.append(
        '<p class="audit">'
        + _esc(FOOTER_TEMPLATE.format(date=run_date))
        + "</p>"
    )

    html_doc = (
        "<!DOCTYPE html>\n<html lang='en'><head>"
        + "<meta charset='utf-8'>"
        + "<title>" + _esc(title) + "</title>"
        + "<style>" + _CSS + "</style>"
        + "</head><body>\n"
        + "\n".join(body_parts)
        + "\n</body></html>"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_doc, encoding="utf-8")
    return {
        "output_path": str(output_path.resolve()),
        "size_bytes": output_path.stat().st_size,
        "sections_rendered": sections,
    }


# ---------------------------------------------------------------------------
# Sibling docx renderer
# ---------------------------------------------------------------------------

def generate_stage3_beta_report_docx(
    composed: dict[str, Any],
    output_path: Path | str,
) -> dict[str, Any]:
    """Render the Stage 3 Beta sibling deliverable as docx.

    Imports python-docx lazily so callers that only render HTML do not
    pull in the dependency.
    """
    # Lazy imports, python-docx is heavy and the HTML-only path
    # should not pay the import cost.
    from docx import Document
    from docx.shared import Pt, RGBColor

    output_path = Path(output_path)
    variant = composed.get("variant_label", "")
    run_date = composed.get("run_date", "")
    iterations = composed.get("iterations", 0)
    seed = composed["seed_used"]  # never printed as 0 when absent (SEEDZERO-01)
    headline = composed.get("headline", {}) or {}
    page1 = composed.get("page1_table", []) or []
    cost = composed.get("cost_summary", {}) or {}
    sched = composed.get("schedule_summary", {}) or {}
    methodology = composed.get("methodology_summary", {}) or {}
    audit = composed.get("audit_trail", {}) or {}

    doc = Document()

    # ---- Cover heading ------------------------------------------------
    title = _report_title(composed, variant, run_date)
    doc.add_heading(title, level=1)
    sections = 0

    # ---- Preview banner (cover page) ----------------------------------
    _add_preview_banner(doc, composed.get("preview_banner", ""))
    sections += 1

    # ---- Cover caveat -------------------------------------------------
    para = doc.add_paragraph()
    run = para.add_run(composed.get("cover_caveat", ""))
    run.italic = True
    sections += 1

    # ---- Headline -----------------------------------------------------
    doc.add_heading("Headline integrated contingency (P80)", level=2)
    para = doc.add_paragraph()
    run = para.add_run(headline.get("integrated_p80_m_str", ""))
    run.bold = True
    run.font.size = Pt(14)
    para.add_run(
        " (Mean: " + str(headline.get("integrated_mean_m_str", "")) + ")"
    )
    doc.add_paragraph(
        "This is the Stage 3 Beta integrated cost-plus-schedule "
        "contingency at the P80 confidence level. The Mean figure is "
        "the arithmetic mean of the integrated distribution and is "
        "shown for completeness. See the table below for the component "
        "breakdown."
    )
    sections += 1

    # ---- Page 1 component breakdown ----------------------------------
    doc.add_heading("Page 1, Component breakdown", level=2)
    _add_preview_banner(doc, composed.get("preview_banner", ""))
    _add_page1_table(doc, page1)
    doc.add_paragraph(DIVERSIFICATION_LINE)
    sections += 1

    # ---- Cost arm summary --------------------------------------------
    doc.add_heading("Cost arm summary", level=2)
    _add_preview_banner(doc, composed.get("preview_banner", ""))
    _add_two_col_table(
        doc,
        [
            ("P50", cost.get("p50_m_str", "")),
            ("P80", cost.get("p80_m_str", "")),
            ("P90", cost.get("p90_m_str", "")),
            ("Mean", cost.get("mean_m_str", "")),
        ],
        header=("Metric", "Value"),
    )
    doc.add_paragraph(COST_ARM_NOTE)
    sections += 1

    # ---- Schedule arm summary -----------------------------------------
    doc.add_heading("Schedule arm summary", level=2)
    _add_preview_banner(doc, composed.get("preview_banner", ""))
    _add_three_col_table(
        doc,
        [
            (
                "P50",
                f"{sched.get('p50_days', 0.0):.0f}",
                sched.get("p50_dollars_m_str", ""),
            ),
            (
                "P80",
                f"{sched.get('p80_days', 0.0):.0f}",
                sched.get("p80_dollars_m_str", ""),
            ),
            (
                "P90",
                f"{sched.get('p90_days', 0.0):.0f}",
                sched.get("p90_dollars_m_str", ""),
            ),
            (
                "Mean",
                f"{sched.get('mean_days', 0.0):.0f}",
                sched.get("mean_dollars_m_str", ""),
            ),
        ],
        header=(
            "Metric",
            "Working days",
            "Dollarised at " + str(sched.get("day_rate_str", "")),
        ),
    )
    sections += 1

    # ---- Methodology summary ------------------------------------------
    doc.add_heading("Methodology summary", level=2)
    _add_preview_banner(doc, composed.get("preview_banner", ""))
    para = doc.add_paragraph()
    para.add_run("Joint sampling: ").bold = True
    para.add_run(methodology.get("joint_sampling", ""))
    para = doc.add_paragraph()
    para.add_run("Schedule basis: ").bold = True
    para.add_run(methodology.get("schedule_basis", ""))
    para = doc.add_paragraph()
    para.add_run("Calibration tolerances: ").bold = True
    para.add_run(
        "$"
        + f"{int(methodology.get('calibration_tolerance_cost_dollars', 0)):,}"
        + " cost / "
        + f"{methodology.get('calibration_tolerance_schedule_days', 0):.0f}"
        + " day schedule, against Stage 3 Beta standalone marginals."
    )
    sections += 1

    # ---- Audit trail --------------------------------------------------
    doc.add_heading("Audit trail", level=2)
    _add_preview_banner(doc, composed.get("preview_banner", ""))
    _add_two_col_table(
        doc,
        [
            ("Iterations", str(iterations)),
            ("Seed", str(seed)),
            ("Variant", str(variant)),
            ("Register", str(audit.get("register_path", "") or "(not recorded)")),
            ("Strawman", str(audit.get("strawman_path", "") or "(not recorded)")),
            ("P6 (.xer)", str(audit.get("xer_path", "") or "(not recorded)")),
            (
                "Auto-mapper audit",
                str(audit.get("auto_mapper_audit_path", "") or "(not recorded)"),
            ),
            (
                "Criticality mode",
                str(audit.get("criticality_measurement_mode", "")),
            ),
        ],
        header=("Field", "Value"),
    )
    sections += 1

    # ---- Footer note --------------------------------------------------
    para = doc.add_paragraph()
    run = para.add_run(FOOTER_TEMPLATE.format(date=str(run_date)))
    run.italic = True
    run.font.size = Pt(9)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return {
        "output_path": str(output_path.resolve()),
        "size_bytes": int(os.path.getsize(str(output_path))),
        "sections_rendered": sections,
    }


# ---------------------------------------------------------------------------
# docx helpers (local, no cross-module dependency)
# ---------------------------------------------------------------------------

def _add_preview_banner(doc: Any, text: str) -> None:
    """Render the preview banner as a bold, single-paragraph block.

    The banner is rendered as a paragraph (not a table) so it survives
    docx-to-PDF conversion cleanly across reader versions.
    """
    if not text:
        return
    from docx.shared import Pt, RGBColor

    para = doc.add_paragraph()
    run = para.add_run(text)
    run.bold = True
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(0x66, 0x33, 0x00)


def _add_page1_table(doc: Any, rows: list[dict[str, Any]]) -> None:
    """Render the 5-row component-breakdown table."""
    if not rows:
        doc.add_paragraph("(Page 1 table is empty.)")
        return
    cols = ["Component", "P80", "Mean", "Value", "Notes"]
    table = doc.add_table(rows=1 + len(rows), cols=len(cols))
    try:
        table.style = "Light Grid Accent 1"
    except KeyError:
        pass
    for j, col in enumerate(cols):
        cell = table.rows[0].cells[j]
        cell.text = col
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
    for i, row in enumerate(rows, start=1):
        for j, col in enumerate(cols):
            table.rows[i].cells[j].text = str(row.get(col, ""))


def _add_two_col_table(
    doc: Any,
    rows: list[tuple[str, str]],
    *,
    header: tuple[str, str] = ("Field", "Value"),
) -> None:
    table = doc.add_table(rows=1 + len(rows), cols=2)
    try:
        table.style = "Light Grid Accent 1"
    except KeyError:
        pass
    table.rows[0].cells[0].text = header[0]
    table.rows[0].cells[1].text = header[1]
    for paragraph in table.rows[0].cells[0].paragraphs:
        for run in paragraph.runs:
            run.bold = True
    for paragraph in table.rows[0].cells[1].paragraphs:
        for run in paragraph.runs:
            run.bold = True
    for i, (label, value) in enumerate(rows, start=1):
        table.rows[i].cells[0].text = label
        table.rows[i].cells[1].text = value


def _add_three_col_table(
    doc: Any,
    rows: list[tuple[str, str, str]],
    *,
    header: tuple[str, str, str],
) -> None:
    table = doc.add_table(rows=1 + len(rows), cols=3)
    try:
        table.style = "Light Grid Accent 1"
    except KeyError:
        pass
    for j, label in enumerate(header):
        cell = table.rows[0].cells[j]
        cell.text = label
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
    for i, row in enumerate(rows, start=1):
        for j, value in enumerate(row):
            table.rows[i].cells[j].text = value


# ---------------------------------------------------------------------------
# Filename helper
# ---------------------------------------------------------------------------

def resolve_sibling_filename(
    variant_label: str,
    run_date: str,
    *,
    extension: str,
    output_dir: Path | str | None = None,
) -> Path:
    """Resolve the sibling-deliverable filename.

    Pattern: ``sra_stage3_beta_report_PROD_{variant}_{date}.{ext}``
    placed under ``output_dir`` (default ``outputs/``).

    Parameters
    ----------
    variant_label : str
        "Hybrid", "Series", etc.
    run_date : str
        YYYY-MM-DD.
    extension : str
        "html" or "docx".
    output_dir : Path | str | None
        Destination directory. Defaults to ``Path("outputs")``.
    """
    output_dir = Path(output_dir) if output_dir is not None else Path("outputs")
    return output_dir / (
        f"sra_stage3_beta_report_PROD_{variant_label}_{run_date}.{extension}"
    )


def __getattr__(name: str):
    """Lazily resolve binding-sourced module attributes (PEP 562).

    ``stage3_beta_report.COVER_PAGE_CAVEAT_TEXT`` - attribute access - resolves against the
    **currently active** binding on every read.

    ``from src.final.stage3_beta_report import COVER_PAGE_CAVEAT_TEXT`` does **not**. That form
    binds once, at import, and captures whichever project was active then; in a process that
    changes project afterwards it silently keeps the first one's text. This docstring used to
    say the from-form was "kept working", which was true only while one project existed and
    was corrected under BINDINGSNAPSHOT-01 (3c Part A) after the claim was measured false.

    So: read it as an attribute at the point of use, or call
    :func:`resolve_cover_caveat` directly. Do not bind it at import.

    ``PREVIEW_BANNER_TEXT`` joined it under stage 4 F-33 for the same reason.
    """
    if name == "COVER_PAGE_CAVEAT_TEXT":
        return resolve_cover_caveat()
    if name == "PREVIEW_BANNER_TEXT":
        return resolve_preview_banner()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
