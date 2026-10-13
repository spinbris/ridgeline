"""SR-S3-Beta-19 §3 — sibling criticality note HTML renderer.

**DEPRECATED at SR14b.** The Stage 3 standalone report's appendix
(SR14b session 2's new ``src/final/stage3_composer.py`` + the
criticality appendix-mode extension of ``src/final/sections/criticality.py``)
carries equivalent content. Production runners stop emitting
``sra_criticality_note_PROD_*`` at SR14b merge per D4 Option A; this
module stays on disk through one release cycle and is removed at
SR14c. Do not call from new code; do not extend.

Produces ``sra_criticality_note_PROD_{variant}_{date}.html`` from
``composed["criticality_note"]``. Scaffold-only: placeholder image-frame
captions for Charts 1, 3, 4; Chart 2 renders the existing Beta-12 CI
distribution chart as a temporary stand-in until SR10.B lands the
criticality density Gantt by phase.

Pure data layer. No matplotlib; no nbconvert; standalone HTML
emission so the sibling deliverable doesn't depend on a Jupyter kernel.
The HTML uses minimal inline CSS — readable in a browser, printable to
PDF, and structurally compatible with the main-report's audit-trail
linkage.
"""
from __future__ import annotations

import base64
import html as _html
from datetime import date as _date
from pathlib import Path
from typing import Any


_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
       'Helvetica Neue', Arial, sans-serif; max-width: 980px;
       margin: 2em auto; padding: 0 1em; color: #222; line-height: 1.45; }
h1 { color: #1f3864; border-bottom: 2px solid #1f3864; padding-bottom: .3em; }
h2 { color: #2e5597; margin-top: 1.8em; }
/* Beta-19b item 9: table body shrunk from 0.92em to 0.82em (~9pt
   against the docx canonical baseline of 11pt body) for column-width
   relief on wide tables (especially Chart 3 risk-to-CP linkage). */
table { border-collapse: collapse; width: 100%; margin: 0.6em 0 1.2em 0;
        font-size: 0.82em; }
th, td { border: 1px solid #bbb; padding: 3px 6px; text-align: left;
         vertical-align: top; }
th { background: #f0f3fa; font-weight: bold; }
.placeholder { background: #faf7e8; border: 1px dashed #c5b471;
               padding: 0.8em 1em; margin: 0.6em 0; font-style: italic;
               color: #6a5b1f; }
.caption { font-style: italic; color: #555; margin-top: -0.4em; }
.caveat { font-size: 0.9em; color: #555; margin: 0.3em 0 1em 0;
          font-style: italic; }
.audit { font-size: 0.85em; color: #666; margin-top: 2em;
         padding-top: 0.6em; border-top: 1px solid #ddd; }
"""

_BOLD = "**"
_ITALIC = "_"


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return _html.escape(str(value), quote=False)


def _render_inline(text: str) -> str:
    """Render inline text with bold (**...**) and italic (_..._) support.

    Markers are processed before HTML-escaping so the markdown
    metacharacters themselves do not appear in the output. Escapes
    are applied chunk-by-chunk so the wrapper tags survive.
    """
    chunks = text.split(_BOLD)
    parts: list[str] = []
    for i, chunk in enumerate(chunks):
        if i % 2 == 1:
            parts.append("<strong>" + _esc(chunk) + "</strong>")
        else:
            ichunks = chunk.split(_ITALIC)
            inner: list[str] = []
            for j, ic in enumerate(ichunks):
                if j % 2 == 1 and ic:
                    inner.append("<em>" + _esc(ic) + "</em>")
                else:
                    inner.append(_esc(ic))
            parts.append("".join(inner))
    return "".join(parts)


def _render_para(text: str) -> str:
    return "<p>" + _render_inline(text) + "</p>"


def _render_caveat(text: str) -> str:
    return '<p class="caveat">' + _render_inline(text) + "</p>"


def _render_placeholder(text: str) -> str:
    return '<div class="placeholder">' + _render_inline(text) + "</div>"


def _render_table(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    cols = [k for k in records[0].keys() if k != "no_activity_bindings"]
    parts: list[str] = ["<table>", "<thead><tr>"]
    parts.extend("<th>" + _esc(c) + "</th>" for c in cols)
    parts.append("</tr></thead><tbody>")
    for row in records:
        parts.append("<tr>")
        for c in cols:
            val = row.get(c)
            if isinstance(val, (int, float)) and val == val:
                if c == "ci":
                    parts.append("<td>" + f"{val:.0%}" + "</td>")
                elif c.endswith("_hours"):
                    parts.append("<td>" + f"{val:.1f}" + "</td>")
                else:
                    parts.append("<td>" + str(val) + "</td>")
            else:
                parts.append("<td>" + _esc(val) + "</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _embed_image(path: str, alt_text: str = "") -> str:
    """Embed a PNG image as base64 inside an HTML <img> tag.

    Returns empty string when the path is empty or the file is missing —
    the caller then falls back to the placeholder caption.
    """
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    data = p.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    alt = alt_text or "Criticality chart"
    return (
        '<p><img src="data:image/png;base64,' + b64 + '" '
        'style="max-width: 100%; height: auto;" alt="' + _esc(alt) + '" /></p>'
    )


def render_criticality_note_html(
    composed: dict[str, Any],
    output_path: Path | str,
    *,
    variant: str = "Hybrid",
    run_date: str | None = None,
) -> dict[str, Any]:
    """Render the sibling criticality note to an HTML file.

    Parameters
    ----------
    composed : dict
        Output of ``compose_final_report_data``. Reads
        ``composed["criticality_note"]``.
    output_path : Path | str
        Where to write the HTML file.
    variant : str
        Strawman variant label (e.g. "Hybrid", "DPReview"). Used in
        the page title.
    run_date : str | None
        Run date in YYYY-MM-DD. Defaults to today.

    Returns
    -------
    dict with ``output_path``, ``size_bytes``, ``sections_rendered``.
    """
    cn = composed.get("criticality_note") or {}
    output_path = Path(output_path)
    if run_date is None:
        run_date = _date.today().isoformat()

    sections = 0
    body_parts: list[str] = []

    title = (
        "Criticality and float visibility note — "
        + str(variant)
        + " variant ("
        + str(run_date)
        + ")"
    )
    body_parts.append("<h1>" + _esc(title) + "</h1>")

    purpose = str(cn.get("purpose_and_audience", "")).strip()
    if purpose:
        body_parts.append(_render_para(purpose))
        sections += 1

    body_parts.append("<h2>CI explainer</h2>")
    explainer = str(cn.get("explainer", "")).strip()
    if explainer:
        for paragraph in explainer.split("\n\n"):
            cleaned = paragraph.strip()
            if cleaned:
                body_parts.append(_render_para(cleaned))
    sections += 1

    body_parts.append("<h2>Top-30 sorted criticality (Chart 1)</h2>")
    chart1_path = str(cn.get("chart1_path", "")).strip()
    chart1_img = _embed_image(
        chart1_path, alt_text="Chart 1 - Top-30 sorted criticality dual bar",
    )
    if chart1_img:
        body_parts.append(chart1_img)
    else:
        body_parts.append(_render_placeholder(cn.get("chart1_caption", "")))
    sections += 1

    body_parts.append("<h2>Criticality density Gantt by phase (Chart 2)</h2>")
    chart2_path = str(cn.get("chart2_path", "")).strip()
    chart2_img = _embed_image(
        chart2_path,
        alt_text="Chart 2 - Criticality density Gantt by phase",
    )
    if chart2_img:
        body_parts.append(chart2_img)
        caption = str(cn.get("chart2_caption", "")).strip()
        if caption:
            body_parts.append(_render_caveat(caption))
    else:
        body_parts.append(_render_placeholder(cn.get("chart2_caption", "")))
    sections += 1

    body_parts.append(
        "<h2>Near-critical activities (CI 20-80%) — 10-row detail</h2>"
    )
    near = cn.get("near_critical_table_10row") or []
    if near:
        body_parts.append(_render_table(near))
        caveat = str(cn.get("near_critical_table_caveat", "")).strip()
        if caveat:
            body_parts.append(_render_caveat(caveat))
    else:
        body_parts.append(
            "<p>No activities sit in the near-critical (CI 20-80%) "
            "band under the current inputs.</p>"
        )
    near_interp = str(cn.get("near_critical_interpretation", "")).strip()
    if near_interp:
        body_parts.append(_render_para(near_interp))
    sections += 1

    body_parts.append(
        "<h2>Risk-to-activity bridge (top-3 schedule risk drivers)</h2>"
    )
    bridge_interp = str(cn.get("risk_bridge_interpretation", "")).strip()
    if bridge_interp:
        body_parts.append(_render_para(bridge_interp))
    bridge = cn.get("risk_to_activity_bridge") or []
    if bridge:
        body_parts.append(_render_table(bridge))
        caveat = str(cn.get("risk_to_activity_bridge_caveat", "")).strip()
        if caveat:
            body_parts.append(_render_caveat(caveat))
    sections += 1

    body_parts.append(
        "<h2>Float histogram with criticality overlay (Chart 4)</h2>"
    )
    chart4_path = str(cn.get("chart4_path", "")).strip()
    chart4_img = _embed_image(
        chart4_path,
        alt_text="Chart 4 - Float histogram with CI overlay",
    )
    if chart4_img:
        body_parts.append(chart4_img)
    else:
        body_parts.append(_render_placeholder(cn.get("chart4_caption", "")))
    sections += 1

    body_parts.append("<h2>Risk-to-CP linkage (Chart 3)</h2>")
    chart3_path = str(cn.get("chart3_path", "")).strip()
    chart3_img = _embed_image(
        chart3_path,
        alt_text="Chart 3 - Risk-to-CP linkage table",
    )
    if chart3_img:
        body_parts.append(chart3_img)
    else:
        body_parts.append(_render_placeholder(cn.get("chart3_caption", "")))
    sections += 1

    caveat = str(cn.get("input_dependencies_caveat", "")).strip()
    if caveat:
        body_parts.append("<h2>Inputs that drive criticality accuracy</h2>")
        for paragraph in caveat.split("\n\n"):
            cleaned = paragraph.strip()
            if cleaned:
                body_parts.append(_render_para(cleaned))
        sections += 1

    audit_ref = str(cn.get("audit_trail_reference", "")).strip()
    if audit_ref:
        body_parts.append(
            '<p class="audit">' + _render_inline(audit_ref) + "</p>"
        )
        sections += 1

    html_doc = (
        "<!DOCTYPE html>\n<html lang='en'><head>"
        + "<meta charset='utf-8'>"
        + "<title>" + _esc(title) + "</title>"
        + "<style>" + _CSS + "</style>"
        + "</head><body>\n"
        + "\n".join(body_parts)
        + "\n</body></html>"
    )
    output_path.write_text(html_doc, encoding="utf-8")
    return {
        "output_path": str(output_path.resolve()),
        "size_bytes": output_path.stat().st_size,
        "sections_rendered": sections,
    }
