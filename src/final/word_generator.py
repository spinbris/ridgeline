# SR9 v3 amendment - 2026-04-26 - presentation-layer reframe.
"""SR9 Word doc executive summary generator.

Uses python-docx (already installed; standard Python library). The
document-skills:docx skill provides JavaScript-based docx-js helpers
which we don't need here - python-docx covers the SR9 deliverable shape.

FAIL banner specification:
  Position : title page, ABOVE the document title
  Container: single-cell table, page-margin width, red border on all sides
  Text     : red bold sans-serif 14pt, verbatim three sentences on separate lines

Custom property:
  cross_validation_status = "FAILED" | "PASSED"
  Always set, regardless of cross_validation outcome. Enables a future
  programmatic check to filter failed deliverables.

Document body uses role-based language only ("the project risk register",
"the strawman methodology workbook"). Specific paths and version numbers
ONLY in the audit trail footer section.

SR9 v3 extension:
  When the optional `composed` parameter is supplied AND contains
  page1_headline, the document renders the 6-8 page v3 layout: headline +
  range table + callouts (page 1), distribution charts (page 2), cost
  tornado + drivers (page 3), schedule tornado + drivers + Mode
  sensitivity + risk matrix (page 4), reconciliation comparison +
  waterfall + cv panel (page 5), treatment ROI + recommendations
  (page 6), methodology + standards + DP review caveat + limitations +
  single-iteration walkthrough (page 7), audit trail + reproducibility +
  input hashes (page 8). Otherwise falls back to v2 layout for backward
  compatibility.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from src.final import contract_terms
from src.final.product import PRODUCT_LINE, TITLE_SUFFIX


# ----------------------------------------------------------------------------
# FAIL banner constants (verbatim per Director direction)
# ----------------------------------------------------------------------------

FAIL_BANNER_LINES = (
    "CROSS-VALIDATION FAILED.",
    "THIS REPORT MUST NOT BE DISTRIBUTED.",
    "INVESTIGATE BEFORE PROCEEDING.",
)


# ----------------------------------------------------------------------------
# SR14b D2: preview-banner hook
# ----------------------------------------------------------------------------


def _maybe_render_preview_banner(doc: "Document", composed: dict[str, Any]) -> None:
    """Render the Stage 3 preview banner if ``composed["preview_banner"]`` is set.

    SR14b D2 Option A: the Stage 2.5 renderer pipeline is extended with this
    additive hook so the Stage 3 standalone composer (SR14b session 2 +
    SR14c production wiring) can feed the same renderer with a Stage 3
    preview banner string. Stage 2.5's ``composed`` does NOT carry the key,
    so the hook no-ops on the Stage 2.5 path — Stage 2.5 lock-test
    byte-identity holds at the hook boundary by construction.
    """
    banner = composed.get("preview_banner") if isinstance(composed, dict) else None
    if not banner:
        return
    para = doc.add_paragraph()
    run = para.add_run(str(banner))
    run.italic = True
    run.font.size = Pt(10)

# Page-margin constants (US Letter assumed; 1in margins == standard python-docx default).
# Width = page width 21.59 cm minus 2 * 2.54 cm = 16.51 cm.
PAGE_MARGIN_WIDTH_CM = 16.51

BANNER_FONT_NAME = "Arial"          # sans-serif
BANNER_FONT_SIZE_PT = 14            # same as Heading 1, larger than body 11
BANNER_COLOR = RGBColor(0xC0, 0x00, 0x00)  # red
BANNER_BORDER_HEX = "C00000"        # matches BANNER_COLOR for border

# Custom property name (kept here as a constant so tests can reference it).
CUSTOM_PROPERTY_NAME = "cross_validation_status"
CUSTOM_PROPERTY_REPORT_MODE = "report_mode"
CUSTOM_PROPERTY_ENGINE_VERSION = "engine_version"
CUSTOM_PROPERTY_RECOMMENDATION_METRIC = "recommendation_metric"


# ----------------------------------------------------------------------------
# BETA banner constants - Beta-08 addition; parallels FAIL banner above.
# Distinct visual (orange/amber, not FAIL red) so a reviewer can tell the
# two states apart at a glance. Per Beta-00 §5 architectural anchor:
# there is no path through generate_word_summary that produces Stage 3
# beta output without this banner being applied.
# ----------------------------------------------------------------------------

BETA_BANNER_LINES = (
    "STAGE 3 + SR16: CURRENT PRODUCTION HEADLINE.",
    "FIGURES PENDING WORKSHOP VALIDATION OF AUTO-MAPPER BINDINGS.",
    "STAGE 2.5 HYBRID $<stage25_mean>M RETAINED AS HISTORICAL COMPARATOR ONLY.",
)

BETA_BANNER_COLOR = RGBColor(0xCC, 0x66, 0x00)        # amber/orange - distinct from BANNER_COLOR red
BETA_BANNER_BORDER_HEX = "CC6600"
BETA_BANNER_FONT_NAME = "Arial"                       # matches BANNER_FONT_NAME for consistency
BETA_BANNER_FONT_SIZE_PT = 12                         # smaller than FAIL (14pt) - visible but secondary

CUSTOM_PROPERTY_BETA_FLAG = "stage3_beta_present"


# ----------------------------------------------------------------------------
# Custom-property helpers (python-docx has no public API for these)
# ----------------------------------------------------------------------------

_CUSTOM_PROPS_XML_TEMPLATE = (
    '<Properties '
    'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
    'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
    '</Properties>'
)


def _set_custom_property(doc: Document, name: str, value: str) -> None:
    """Add or update a string custom document property.

    python-docx does not expose custom properties through its public API;
    we manipulate the underlying OPC package directly.
    """
    from docx.opc.constants import CONTENT_TYPE
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    from lxml import etree

    package = doc.part.package
    custom_uri = PackURI("/docProps/custom.xml")

    # Locate or create the customProperties part
    custom_part = None
    for part in package.iter_parts():
        if part.partname == custom_uri:
            custom_part = part
            break
    if custom_part is None:
        custom_part = Part(
            partname=custom_uri,
            content_type=CONTENT_TYPE.OFC_CUSTOM_PROPERTIES,
            blob=_CUSTOM_PROPS_XML_TEMPLATE.encode("utf-8"),
            package=package,
        )
        # Relate the custom part to the package.
        package.relate_to(custom_part, "http://schemas.openxmlformats.org/"
                                       "officeDocument/2006/relationships/custom-properties")

    blob = custom_part.blob
    root = etree.fromstring(blob)
    ns_cp = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
    ns_vt = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"

    existing = root.find(f"{{{ns_cp}}}property[@name='{name}']")
    if existing is not None:
        root.remove(existing)

    # Determine the next pid (must be >= 2 and unique among siblings).
    used_pids = [
        int(p.get("pid")) for p in root.findall(f"{{{ns_cp}}}property")
        if p.get("pid") and p.get("pid").isdigit()
    ]
    next_pid = max(used_pids + [1]) + 1

    prop = etree.SubElement(root, f"{{{ns_cp}}}property")
    prop.set("fmtid", "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}")
    prop.set("pid", str(next_pid))
    prop.set("name", name)
    lpwstr = etree.SubElement(prop, f"{{{ns_vt}}}lpwstr")
    lpwstr.text = str(value)

    custom_part._blob = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True,
    )


def _get_custom_property(docx_path: Path | str, name: str) -> str | None:
    """Read a string custom document property from a saved .docx file.

    Used by tests; opens the .docx as a zip and parses docProps/custom.xml.
    """
    import zipfile

    from lxml import etree
    with zipfile.ZipFile(str(docx_path)) as zf:
        if "docProps/custom.xml" not in zf.namelist():
            return None
        with zf.open("docProps/custom.xml") as f:
            root = etree.parse(f).getroot()
    ns_cp = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
    ns_vt = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
    prop = root.find(f"{{{ns_cp}}}property[@name='{name}']")
    if prop is None:
        return None
    val = prop.find(f"{{{ns_vt}}}lpwstr")
    return val.text if val is not None else None


# ----------------------------------------------------------------------------
# Banner injection
# ----------------------------------------------------------------------------

def _set_cell_border(cell, hex_color: str, sz: int = 8) -> None:
    """Apply a coloured single-line border to all four sides of a table cell."""
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        b = OxmlElement(f"w:{edge}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), str(sz))
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), hex_color)
        tc_borders.append(b)
    tc_pr.append(tc_borders)


# Beta-19b item 9: default body font for data tables. Exposed as a module
# constant so future tuning (e.g., dropping to 8pt for very wide tables) is
# a one-line change. Per D42 in the brief.
_TABLE_BODY_FONT_PT = 9
_TABLE_FONT_NAME = "Calibri"


def _apply_data_table_font(doc: Document) -> None:
    """Apply Calibri 9pt to body cells / 9pt bold to header cells across all
    data tables in the document.

    "Data tables" are identified by a python-docx Light Grid / Light List
    style. Banner tables (FAIL / BETA) carry no style attribute and have
    explicit per-run font sizes; this helper skips them. Header row is
    detected as the first row; subsequent rows are body.
    """
    for table in doc.tables:
        style = getattr(table, "style", None)
        style_name = getattr(style, "name", "") if style is not None else ""
        if not style_name.startswith("Light "):
            continue
        for row_idx, row in enumerate(table.rows):
            for cell in row.cells:
                for para in cell.paragraphs:
                    for run in para.runs:
                        run.font.name = _TABLE_FONT_NAME
                        run.font.size = Pt(_TABLE_BODY_FONT_PT)
                        if row_idx == 0:
                            run.font.bold = True


def _inject_fail_banner(doc: Document) -> None:
    """Insert the verbatim FAIL banner above the document title.

    Single-cell table, page-margin width, red border on all sides. Each
    verbatim sentence on its own paragraph inside the cell. Banner is the
    first content element so a recipient skimming the title page sees it
    before the document title.
    """
    table = doc.add_table(rows=1, cols=1)
    table.autofit = False
    table.allow_autofit = False
    table.columns[0].width = Cm(PAGE_MARGIN_WIDTH_CM)
    cell = table.cell(0, 0)
    cell.width = Cm(PAGE_MARGIN_WIDTH_CM)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    _set_cell_border(cell, BANNER_BORDER_HEX, sz=18)

    # Replace the cell's default empty paragraph with our three lines.
    cell.text = ""  # clears the auto-created paragraph
    for line in FAIL_BANNER_LINES:
        p = cell.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(line)
        run.bold = True
        run.font.name = BANNER_FONT_NAME
        run.font.size = Pt(BANNER_FONT_SIZE_PT)
        run.font.color.rgb = BANNER_COLOR

    # Move the table to the top of the document body.
    body = doc.element.body
    table_element = table._element
    body.remove(table_element)
    body.insert(0, table_element)


def _first_body_table_contains_text(doc: Document, needle: str) -> bool:
    """Return True iff the document's first body element is a table whose
    visible text contains ``needle``. Used to detect a pre-injected FAIL
    banner so the BETA banner can be inserted below it without disturbing
    its position.
    """
    body = doc.element.body
    if len(body) == 0:
        return False
    first_elem = body[0]
    if first_elem.tag != qn("w:tbl"):
        return False
    text = "".join(first_elem.itertext())
    return needle in text


def _inject_beta_banner(
    doc: Document,
    beta_metadata: dict[str, Any] | None = None,
) -> None:
    """Insert the BETA banner above the document title.

    Per Beta-00 §5 architectural anchor: this is the only mechanism by
    which a Stage 3 beta deliverable signals its provisional status to a
    reader. Parallels :func:`_inject_fail_banner` in shape: single-cell
    table, page-margin width, amber border on all sides, three verbatim
    lines each on its own paragraph, bold Arial 12pt, amber colour.

    Parameters
    ----------
    doc : Document
        The python-docx document being assembled.
    beta_metadata : dict | None
        Optional metadata. Currently the only consumed key is
        ``"auto_mapper_audit_path"``; when present (non-empty), an
        additional 4th line ``"Audit trail: <path>"`` is appended to
        the banner so a reviewer can trace the auto-mapper output.

    Behaviour
    ---------
    Borders match :data:`BETA_BANNER_BORDER_HEX` (amber #CC6600). When
    the document already has a FAIL banner injected above the title
    (detected by scanning the first body element for the verbatim FAIL
    banner text), the BETA banner is inserted *below* the FAIL banner
    so FAIL takes visual precedence. When only BETA is present, it is
    inserted at the top above the document title - same insertion point
    FAIL would use.
    """
    table = doc.add_table(rows=1, cols=1)
    table.autofit = False
    table.allow_autofit = False
    table.columns[0].width = Cm(PAGE_MARGIN_WIDTH_CM)
    cell = table.cell(0, 0)
    cell.width = Cm(PAGE_MARGIN_WIDTH_CM)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    _set_cell_border(cell, BETA_BANNER_BORDER_HEX, sz=12)

    # Replace the cell's default empty paragraph with the three verbatim lines.
    cell.text = ""  # clears the auto-created paragraph
    for line in BETA_BANNER_LINES:
        p = cell.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(line)
        run.bold = True
        run.font.name = BETA_BANNER_FONT_NAME
        run.font.size = Pt(BETA_BANNER_FONT_SIZE_PT)
        run.font.color.rgb = BETA_BANNER_COLOR

    # Optional 4th line: audit trail pointer.
    audit_path = None
    if beta_metadata is not None:
        audit_path = beta_metadata.get("auto_mapper_audit_path")
    if audit_path:
        p = cell.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(f"Audit trail: {audit_path}")
        run.bold = False
        run.italic = True
        run.font.name = BETA_BANNER_FONT_NAME
        # 1pt smaller than the headline lines, italic, so visually subordinate.
        run.font.size = Pt(max(1, BETA_BANNER_FONT_SIZE_PT - 2))
        run.font.color.rgb = BETA_BANNER_COLOR

    # Position the table:
    # - if FAIL banner is at body[0], insert BETA below it (body[1])
    # - otherwise insert BETA at body[0] (above the title)
    body = doc.element.body
    table_element = table._element
    body.remove(table_element)
    insert_idx = 0
    if _first_body_table_contains_text(doc, FAIL_BANNER_LINES[0]):
        insert_idx = 1
    body.insert(insert_idx, table_element)


def _apply_beta_filename_prefix(filename: str | Path, beta_flag: bool) -> str:
    """Prepend ``BETA_`` to ``filename`` when ``beta_flag`` is True.

    Idempotent: if the basename already starts with ``BETA_``, the
    filename is returned unchanged. Preserves any directory path
    component. Returns a string in all paths.

    Examples
    --------
    >>> _apply_beta_filename_prefix("wind_final_report.docx", True)
    'BETA_wind_final_report.docx'
    >>> _apply_beta_filename_prefix("BETA_wind_final_report.docx", True)
    'BETA_wind_final_report.docx'
    >>> _apply_beta_filename_prefix("wind_final_report.docx", False)
    'wind_final_report.docx'
    """
    if not beta_flag:
        return str(filename)
    p = Path(filename)
    if p.name.startswith("BETA_"):
        return str(filename)
    new_name = f"BETA_{p.name}"
    if str(p.parent) in ("", "."):
        return new_name
    return str(p.parent / new_name)


# ----------------------------------------------------------------------------
# Document section builders
# ----------------------------------------------------------------------------

def _project_title(key: str, fallback: str) -> str:
    """Report-title string for the active project (binding-sourced).

    Reads ``NARRATIVE_TEMPLATES[key]`` from the active project binding,
    falling back to a generic string when the binding supplies no copy.
    A project ships its titles in the binding, so the rendered docx is
    byte-identical to the pre-WS2-B literals.
    """
    from src.sra.cpm.bindings import get_active_binding

    return get_active_binding().narrative(key) or fallback


def _add_title_page(doc: Document, summary_data: dict[str, Any], audit_trail: dict[str, Any]) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(_project_title("report_cover_title", "Integrated Cost and Schedule Risk Analysis"))
    run.bold = True
    run.font.name = BANNER_FONT_NAME
    run.font.size = Pt(20)

    # RIDGELINE-01 P3: the product and its maker, beside the project's own title, not in its place.
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(PRODUCT_LINE)
    run.font.name = BANNER_FONT_NAME
    run.font.size = Pt(11)

    note = _project_title("project_note", "")
    if note:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(note)
        run.italic = True
        run.font.name = BANNER_FONT_NAME
        run.font.size = Pt(10)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Final Integrated Deliverable - Executive Summary")
    run.font.name = BANNER_FONT_NAME
    run.font.size = Pt(14)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(f"Run date: {audit_trail.get('run_date', '(unknown)')}")
    run.font.name = BANNER_FONT_NAME
    run.font.size = Pt(11)

    doc.add_paragraph()  # spacer


def _add_stage3_headline(doc: Document, headline: dict[str, Any]) -> None:
    """STAGE3HEADLINE-01 (D-1): the headline block - percentiles of the one Stage 3 distribution."""
    metric = str(headline.get("headline_metric", "P80"))
    # PRESENT-01 (D-3): "TOC" is a fact about the reader's contract, not about their project.
    # Neutral unless the binding declares a contract shape that has a target cost.
    label = contract_terms.term("headline_contingency_label")
    doc.add_heading(f"{label} ({metric}, Stage 3)", level=1)
    lead = headline.get("headline_dollars")
    if isinstance(lead, (int, float)):
        para = doc.add_paragraph()
        run = para.add_run(f"Recommended contingency: ${lead/1e6:.2f}M ({metric}, integrated cost plus schedule)")
        run.bold = True
    table = doc.add_table(rows=1, cols=2)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    hdr[0].text = "Percentile"
    hdr[1].text = "Integrated contingency ($M)"
    rows: list[tuple[str, float | None]] = [
        (f"P{p}", headline.get(f"p{p}_dollars")) for p in headline.get("p_levels", (50, 80, 95))
    ]
    rows.append(("Mean", headline.get("mean_dollars")))
    for label, value in rows:
        row = table.add_row().cells
        row[0].text = label
        row[1].text = (
            f"${value/1e6:.2f}M" if isinstance(value, (int, float)) and value is not None
            else "(not supplied)"
        )
    basis = str(headline.get("basis", "")).strip()
    if basis:
        _add_italic_note(doc, basis, size_pt=10)


def _add_headline_range(doc: Document, headline: dict[str, Any]) -> None:
    basis = str(headline.get("basis", "")).strip()
    doc.add_heading(
        ("Stage 2.5 comparator range (P{:d}, Mode scenarios)" if basis else
         contract_terms.term("headline_contingency_label") + " range (P{:d})"
         ).format(int(headline.get("p_level", 80))),
        level=1 if not basis else 2,
    )
    if basis:
        _add_italic_note(doc, basis, size_pt=10)

    table = doc.add_table(rows=1, cols=2)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    hdr[0].text = "Scenario"
    hdr[1].text = "P80 contingency ($M)"

    rows: list[tuple[str, float | None]] = [
        (str(headline.get("lower_bound_scenario", "")) + " (lower bound)",
         headline.get("lower_bound_dollars")),
        (str(headline.get("indicative_scenario", "")) + " (indicative)",
         headline.get("indicative_dollars")),
        (str(headline.get("upper_bound_scenario", "")) + " (upper bound)",
         headline.get("upper_bound_dollars")),
    ]
    for label, value in rows:
        row = table.add_row().cells
        row[0].text = label
        row[1].text = (
            f"${value/1e6:.2f}M" if isinstance(value, (int, float)) and value is not None
            else "(not supplied)"
        )


def _add_top_n_table(
    doc: Document,
    heading: str,
    drivers: list[dict[str, Any]],
    metric_label: str,
    units_label: str,
    extra_columns: list[tuple[str, str]] | None = None,
) -> None:
    """Add a Top-N drivers table.

    extra_columns : list of (column_header, dict_key) for any extra fields
                    (e.g., [("Mode", "mode")]).
    """
    doc.add_heading(heading, level=2)
    cols = ["Risk", "Title", metric_label]
    if extra_columns:
        for hdr, _ in extra_columns:
            cols.append(hdr)
    cols.append("% of P-level total")

    table = doc.add_table(rows=1, cols=len(cols))
    table.style = "Light Grid Accent 1"
    for i, c in enumerate(cols):
        table.rows[0].cells[i].text = c

    for d in drivers:
        row = table.add_row().cells
        row[0].text = str(d.get("risk_id", ""))
        row[1].text = str(d.get("title", ""))
        val = d.get("metric_value")
        if units_label == "dollars" and isinstance(val, (int, float)):
            row[2].text = f"${val/1e6:.2f}M"
        elif units_label == "days" and isinstance(val, (int, float)):
            row[2].text = f"{val:.2f} d"
        else:
            row[2].text = str(val)
        col_idx = 3
        if extra_columns:
            for _, key in extra_columns:
                row[col_idx].text = str(d.get(key, ""))
                col_idx += 1
        pct = d.get("percentage_of_total")
        row[col_idx].text = f"{pct*100:.1f}%" if isinstance(pct, (int, float)) else str(pct)


def _add_bullets(doc: Document, items: list[str]) -> None:
    for item in items:
        p = doc.add_paragraph(item)
        p.style = "List Bullet"


def _set_visible_page_footer(doc: Document, run_date: str) -> None:
    """Set the visible page-bottom footer text.

    The title and the date, for a client-facing audience. PRESENT-01 (D-4): an internal
    build stamp stood in the other branch, and the deliverable never took it.
    """
    text = f"{_project_title('report_header_title', 'Integrated Cost and Schedule Risk Analysis')} - {run_date}"
    for section in doc.sections:
        para = section.footer.paragraphs[0]
        para.text = text


def _set_doc_core_and_custom_properties(
    doc: Document,
    mode: str,
    engine_version: str,
    cv_status: str,
    recommendation_metric: str | None = None,
    beta_flag: bool = False,
) -> None:
    """Set core properties (Title, Subject) and custom properties.

    Custom properties: cross_validation_status, report_mode, engine_version,
    recommendation_metric (SR9 v3.5; "P80" or "Mean"),
    stage3_beta_present (Beta-08; "true" or "false").
    Title is the same in both modes; Subject names the mode for audit trail.
    """
    cp = doc.core_properties
    # RIDGELINE-01 P3: the product is named after the project's title, never in its place.
    cp.title = _project_title("report_core_title", "Integrated Cost and Schedule Risk Analysis - Executive Summary") + TITLE_SUFFIX
    cp.subject = f"SR9 v3.5 - {mode} mode"

    _set_custom_property(doc, CUSTOM_PROPERTY_NAME, cv_status)
    _set_custom_property(doc, CUSTOM_PROPERTY_REPORT_MODE, mode)
    _set_custom_property(doc, CUSTOM_PROPERTY_ENGINE_VERSION, engine_version)
    if recommendation_metric is not None:
        _set_custom_property(
            doc,
            CUSTOM_PROPERTY_RECOMMENDATION_METRIC,
            str(recommendation_metric),
        )
    # Beta-08: stage3_beta_present is always written so a programmatic
    # check can tell beta-flagged from non-beta runs unambiguously
    # (rather than the property being absent).
    _set_custom_property(
        doc, CUSTOM_PROPERTY_BETA_FLAG, "true" if beta_flag else "false",
    )


def _add_audit_trail_footer(doc: Document, audit_trail: dict[str, Any]) -> None:
    doc.add_heading("Audit trail", level=1)
    # SR9 v3.6.1 C6: prefer basename-only *_display keys; fall back to
    # the original full-path keys for backwards compat with v3.6 state
    # caches that pre-date C6.
    _register_display = audit_trail.get(
        "register_path_display", audit_trail.get("register_path", "")
    )
    _strawman_display = audit_trail.get(
        "strawman_path_display", audit_trail.get("strawman_path", "")
    )
    rows = [
        ("Risk register file", str(_register_display)),
        ("Strawman methodology workbook", str(_strawman_display)),
        ("Run date", str(audit_trail.get("run_date", ""))),
        ("Iterations", str(audit_trail.get("iterations", ""))),
        ("Random seed", str(audit_trail.get("random_seed", ""))),
        ("Day rate (sourced from Risk Register Variables sheet)",
         f"${float(audit_trail.get('day_rate_dollars_per_workday', 0.0)):,.0f}/wd"),
        ("Reporting P-level", f"P{audit_trail.get('reporting_p_level', '')}"),
    ]
    versions = audit_trail.get("engine_versions", {})
    # DELIVFIX-01 (R-3): render what was supplied. A fixed ("cost", "schedule", "integrated",
    # "final") loop would print four EMPTY rows the moment the keys changed - silently.
    _version_labels = {"package": "Package version", "engine": "Engine commit"}
    for layer, value in versions.items():
        rows.append((_version_labels.get(layer, f"Engine version - {layer}"), str(value)))

    table = doc.add_table(rows=len(rows), cols=2)
    table.style = "Light List Accent 1"
    for i, (k, v) in enumerate(rows):
        table.rows[i].cells[0].text = k
        table.rows[i].cells[1].text = v


# ----------------------------------------------------------------------------
# v3 helpers - callouts, charts, dataframe tables
# ----------------------------------------------------------------------------

CALLOUT_BG_HEX = "F2F4F7"   # very light grey-blue
CALLOUT_BORDER_HEX = "5B7C99"


def _set_cell_shading(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def _add_callout_box(doc: Document, title: str, body: str) -> None:
    """Render a static callout as a single-cell table with shaded background."""
    table = doc.add_table(rows=1, cols=1)
    table.autofit = False
    table.allow_autofit = False
    table.columns[0].width = Cm(PAGE_MARGIN_WIDTH_CM)
    cell = table.cell(0, 0)
    cell.width = Cm(PAGE_MARGIN_WIDTH_CM)
    _set_cell_border(cell, CALLOUT_BORDER_HEX, sz=6)
    _set_cell_shading(cell, CALLOUT_BG_HEX)
    cell.text = ""

    # Title paragraph
    p_title = cell.add_paragraph()
    run = p_title.add_run(title)
    run.bold = True
    run.font.name = BANNER_FONT_NAME
    run.font.size = Pt(12)

    # Body paragraphs (split on blank lines)
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        para = cell.add_paragraph()
        run = para.add_run(chunk)
        run.font.size = Pt(10)


def _add_picture_centered(doc: Document, png_path: str | Path, width_cm: float = 16.0) -> None:
    """Insert a PNG image centred on the page. Skips silently if missing."""
    if not png_path:
        return
    p = Path(png_path)
    if not p.exists():
        return
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run()
    run.add_picture(str(p), width=Cm(width_cm))


def _add_orienting(doc: Document, text: str) -> None:
    if not text:
        return
    para = doc.add_paragraph()
    run = para.add_run(text)
    run.font.size = Pt(11)


def _add_interpretation(doc: Document, text: str) -> None:
    if not text:
        return
    para = doc.add_paragraph()
    run = para.add_run(text)
    run.italic = True
    run.font.size = Pt(10)


def _add_dataframe_table(doc: Document, df: pd.DataFrame, style: str = "Light Grid Accent 1") -> None:
    """Render a pandas DataFrame as a Word table."""
    if df is None or len(df) == 0:
        return
    cols = list(df.columns)
    table = doc.add_table(rows=1, cols=len(cols))
    table.style = style
    for i, c in enumerate(cols):
        table.rows[0].cells[i].text = str(c)
    for _, row in df.iterrows():
        cells = table.add_row().cells
        for i, c in enumerate(cols):
            val = row[c]
            if pd.isna(val) or val is None:
                cells[i].text = "-"
            elif isinstance(val, float):
                cells[i].text = f"{val:.2f}"
            else:
                cells[i].text = str(val)


#: Reader labels for the keys a serialised DataFrame can carry into a table header (PUBLICFACE-01).
#: A key not listed is still never shown as code: see :func:`_header_label`.
_COLUMN_LABELS = {
    "risk_id": "Risk",
    "risk_title": "Title",
    "activity_id": "Activity ID",
    "activity_name": "Activity",
    "ci": "Criticality index",
    "on_deterministic_cp": "On deterministic critical path",
    "register_sha256": "Risk register",
    "strawman_sha256": "Strawman",
    "p6_sha256": "P6 schedule",
}


def _header_label(key: Any) -> str:
    """A column key as a reader should see it: its label, else a code name in words."""
    name = str(key)
    if name in _COLUMN_LABELS:
        return _COLUMN_LABELS[name]
    if "_" in name and name == name.lower():
        return name.replace("_", " ").capitalize()
    return name


def _add_dict_list_table(doc: Document, rows: list[dict[str, Any]], style: str = "Light Grid Accent 1") -> None:
    """Render a list-of-dicts (like a serialised DataFrame) as a Word table."""
    if not rows:
        return
    cols = list(rows[0].keys())
    table = doc.add_table(rows=1, cols=len(cols))
    table.style = style
    for i, c in enumerate(cols):
        table.rows[0].cells[i].text = _header_label(c)
    for row in rows:
        cells = table.add_row().cells
        for i, c in enumerate(cols):
            val = row.get(c)
            if val is None:
                cells[i].text = "-"
            elif isinstance(val, float):
                cells[i].text = f"{val:.2f}"
            else:
                cells[i].text = str(val)


def _add_model_validation_section(doc: Document, composed: dict[str, Any]) -> None:
    """REPORT01 F-B. No-op unless the Stage 3 composer set ``page_model_validation``.

    Same mechanism as the other Stage 3-only keys: the Stage 2.5 composer does not set
    this one, so the executive summary skips the section rather than needing a flag.
    """
    mv = composed.get("page_model_validation") or {}
    firing = mv.get("firing_table") or []
    magnitude = mv.get("cost_magnitude_table") or []
    if not (firing or magnitude):
        return

    doc.add_heading("Model validation", level=2)
    n_iter = mv.get("n_iterations") or 0
    doc.add_paragraph(
        f"Whether the simulation did what the register asked, over {n_iter:,} "
        f"iterations. This is a different question from cross-validation, which checks "
        f"that the two surfaces agree with each other."
    )
    for key in ("one_fire_draw_note", "firing_basis_note"):
        note = mv.get(key, "")
        if note:
            doc.add_paragraph(note)

    if firing:
        doc.add_heading("Realised firing against Probability", level=3)
        _add_dict_list_table(doc, firing)
    if magnitude:
        doc.add_heading("Sampled magnitude against the elicited estimate", level=3)
        note = mv.get("magnitude_note", "")
        if note:
            doc.add_paragraph(note)
        _add_dict_list_table(doc, magnitude)


def _add_correlation_sensitivity_section(doc: Document, composed: dict[str, Any]) -> None:
    """REPORT01 F-E. No-op unless the Stage 3 composer set the key."""
    cs = composed.get("page_correlation_sensitivity") or {}
    bounding = cs.get("bounding_table") or []
    shares = cs.get("variance_share_table") or []
    withheld = cs.get("withheld_reason", "")
    if not (bounding or shares or withheld):
        return

    doc.add_heading("What correlation contributes", level=2)
    if withheld:
        doc.add_paragraph(withheld)
    if bounding:
        doc.add_heading(
            "Correlation bounding: zero, elicited and full (GN3A section 4.1)", level=3)
        for key in ("scope_note", "uncovered_groups_note", "decision_rule"):
            note = cs.get(key, "")
            if note:
                doc.add_paragraph(note)
        _add_dict_list_table(doc, bounding)
    if shares:
        doc.add_heading("Share of portfolio variance by correlation group", level=3)
        note = cs.get("variance_share_note", "")
        if note:
            doc.add_paragraph(note)
        _add_dict_list_table(doc, shares)


def _add_six_approach_reconciliation_table(
    doc: Document, summary: dict[str, Any],
) -> None:
    """Render the §1 six-approach reconciliation table with bold headline row.

    Beta-15 Item 5. ``summary`` is the dict returned by
    ``composer.build_six_approach_reconciliation_table``: table
    (DataFrame), bold_row_index (int or None), orienting (paragraph
    text).
    """
    if not isinstance(summary, dict):
        return
    df = summary.get("table")
    if not isinstance(df, pd.DataFrame) or len(df) == 0:
        return

    orienting = summary.get("orienting", "")
    if orienting:
        _add_orienting(doc, orienting)

    cols = list(df.columns)
    table = doc.add_table(rows=1, cols=len(cols))
    table.style = "Light Grid Accent 1"
    for i, c in enumerate(cols):
        table.rows[0].cells[i].text = str(c)
    for _, row in df.iterrows():
        cells = table.add_row().cells
        for i, c in enumerate(cols):
            val = row[c]
            if pd.isna(val) or val is None:
                cells[i].text = "-"
            elif isinstance(val, float):
                cells[i].text = f"{val:.2f}"
            else:
                cells[i].text = str(val)

    bold_row_index = summary.get("bold_row_index")
    if isinstance(bold_row_index, int) and 0 <= bold_row_index < len(df):
        row_idx = bold_row_index + 1  # +1 for header
        for cell in table.rows[row_idx].cells:
            _set_cell_shading(cell, "FFF3CD")
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.bold = True


def _add_mode_sensitivity_summary_table(
    doc: Document, summary: dict[str, Any],
) -> None:
    """Render the §7 Mode-sensitivity 4-row summary with variant-aware bold.

    Beta-15 Item 3. ``summary`` is the dict returned by
    ``composer.build_mode_sensitivity_summary``: table (DataFrame),
    bold_row_index (int or None), orienting (paragraph text).
    """
    if not isinstance(summary, dict):
        return
    df = summary.get("table")
    if not isinstance(df, pd.DataFrame) or len(df) == 0:
        return

    orienting = summary.get("orienting", "")
    if orienting:
        _add_orienting(doc, orienting)

    cols = list(df.columns)
    table = doc.add_table(rows=1, cols=len(cols))
    table.style = "Light Grid Accent 1"
    for i, c in enumerate(cols):
        table.rows[0].cells[i].text = str(c)
    for _, row in df.iterrows():
        cells = table.add_row().cells
        for i, c in enumerate(cols):
            val = row[c]
            if pd.isna(val) or val is None:
                cells[i].text = "-"
            elif isinstance(val, float):
                cells[i].text = f"{val:.2f}"
            else:
                cells[i].text = str(val)

    bold_row_index = summary.get("bold_row_index")
    if isinstance(bold_row_index, int) and 0 <= bold_row_index < len(df):
        row_idx = bold_row_index + 1  # +1 for header
        for cell in table.rows[row_idx].cells:
            _set_cell_shading(cell, "FFF3CD")
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.bold = True


def _add_single_iteration_transparency_table(
    doc: Document,
    df: pd.DataFrame,
    *,
    deliverable_kind: str | None = None,
) -> None:
    """Render the per-risk transparency table for the §7 walkthrough.

    Beta-15 Item 6. Columns rendered: Risk ID, Probability, U_fire,
    Fired?, U_dur, Drawn duration (days), Mode, Mode multiplier,
    Contribution (days). 8 body rows for the canonical SRA Time=Yes
    set + a final TOTAL row summing the contribution column.

    SR15.1 Decision 2 = Option A: when ``deliverable_kind`` is
    ``"stage3_standalone"`` the ``Mode`` and ``Mode multiplier`` columns
    are dropped from the rendered table. Under the post-SR15 Stage 3
    full-CPM methodology the Mode multiplier is no longer applied to
    per-iteration impact magnitudes (the CPM kernel handles float
    consumption directly), so the columns would render as informational
    no-ops in the walkthrough context; the strawman Mode classification
    is still visible in the Table 6 schedule drivers section with the
    D4 footnote explaining its informational-only status. Stage 2.5
    walkthrough rendering is unchanged.
    """
    if df is None or len(df) == 0:
        return

    drop_mode_cols = str(deliverable_kind or "") == "stage3_standalone"

    # Display labels for the engine's column names. Engine adds u_fire_draw
    # / u_dur_draw under Beta-15 Item 6.
    columns: list[tuple[str, str]] = [
        ("risk_id", "Risk ID"),
        ("probability", "Probability"),
        ("u_fire_draw", "U_fire draw"),
        ("fired", "Fired?"),
        ("u_dur_draw", "U_dur draw"),
        ("drawn_duration_days", "Drawn duration (days)"),
        ("mode", "Mode"),
        ("mode_multiplier", "Mode multiplier"),
        ("contribution_days", "Contribution (days)"),
    ]
    if drop_mode_cols:
        columns = [
            (k, label) for k, label in columns
            if k not in ("mode", "mode_multiplier")
        ]
    cols_present = [(k, label) for k, label in columns if k in df.columns]

    table = doc.add_table(rows=1, cols=len(cols_present))
    table.style = "Light Grid Accent 1"
    for i, (_, label) in enumerate(cols_present):
        table.rows[0].cells[i].text = label

    for _, row in df.iterrows():
        cells = table.add_row().cells
        for i, (key, _) in enumerate(cols_present):
            val = row[key]
            if isinstance(val, bool):
                cells[i].text = "Yes" if val else "No"
            elif val == "" or val is None:
                cells[i].text = ""
            elif isinstance(val, float):
                if pd.isna(val):
                    cells[i].text = "-"
                elif key == "probability":
                    cells[i].text = f"{val:.3f}"
                elif key in ("u_fire_draw", "u_dur_draw"):
                    cells[i].text = f"{val:.4f}"
                else:
                    cells[i].text = f"{val:.2f}"
            else:
                cells[i].text = str(val)


def _add_walkthrough_sidebar(doc: Document, intro: str, walkthrough: str) -> None:
    """Render the single-iteration walkthrough as a shaded italic block."""
    if not walkthrough:
        return
    if intro:
        para = doc.add_paragraph()
        run = para.add_run(intro)
        run.font.size = Pt(11)

    table = doc.add_table(rows=1, cols=1)
    table.autofit = False
    table.allow_autofit = False
    table.columns[0].width = Cm(PAGE_MARGIN_WIDTH_CM)
    cell = table.cell(0, 0)
    cell.width = Cm(PAGE_MARGIN_WIDTH_CM)
    _set_cell_border(cell, CALLOUT_BORDER_HEX, sz=6)
    _set_cell_shading(cell, CALLOUT_BG_HEX)
    cell.text = ""

    for chunk in walkthrough.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        para = cell.add_paragraph()
        run = para.add_run(chunk)
        run.italic = True
        run.font.size = Pt(10)


def _highlight_high_leverage_rows(table, df: pd.DataFrame, threshold_days: float = 1.0) -> None:
    """Bold + shade rows where any 'delta' column exceeds threshold."""
    if df is None or len(df) == 0:
        return
    delta_col = next(
        (c for c in df.columns if "delta" in str(c).lower()), None,
    )
    if delta_col is None:
        return
    try:
        delta_vals = df[delta_col].astype(float).abs()
    except Exception:
        return
    for offset, (_, val) in enumerate(zip(delta_vals.index, delta_vals)):
        if val < threshold_days:
            continue
        row_idx = offset + 1  # +1 for header row
        if row_idx >= len(table.rows):
            continue
        for cell in table.rows[row_idx].cells:
            _set_cell_shading(cell, "FFF3CD")
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.bold = True


def _add_dataframe_table_with_highlight(
    doc: Document,
    df: pd.DataFrame,
    style: str = "Light Grid Accent 1",
    highlight_threshold_days: float = 1.0,
) -> None:
    """Render DataFrame and bold-highlight rows where delta exceeds threshold."""
    if df is None or len(df) == 0:
        return
    cols = list(df.columns)
    table = doc.add_table(rows=1, cols=len(cols))
    table.style = style
    for i, c in enumerate(cols):
        table.rows[0].cells[i].text = str(c)
    for _, row in df.iterrows():
        cells = table.add_row().cells
        for i, c in enumerate(cols):
            val = row[c]
            if pd.isna(val) or val is None:
                cells[i].text = "-"
            elif isinstance(val, float):
                cells[i].text = f"{val:.2f}"
            else:
                cells[i].text = str(val)
    _highlight_high_leverage_rows(table, df, threshold_days=highlight_threshold_days)


# ----------------------------------------------------------------------------
# v3.1 helpers - confidence curve, italic note line
# ----------------------------------------------------------------------------

def _add_italic_note(doc: Document, text: str, size_pt: int = 9) -> None:
    """Render a small italic note paragraph (D6, D9 inline annotations)."""
    if not text:
        return
    para = doc.add_paragraph()
    run = para.add_run(text)
    run.italic = True
    run.font.size = Pt(size_pt)


def _add_confidence_curve_table(
    doc: Document,
    rows: list[dict[str, Any]],
    style: str = "Light Grid Accent 1",
) -> None:
    """Render the Page 2 confidence curve table (Deliverable 11).

    The row flagged is_recommended is rendered with bold text and a light
    shaded background so the recommended row reads as the headline
    contingency level. Other rows are supporting context.

    SR9 v3.5: a Mean row is included; under the Mean-headline alt PROD
    output the Mean row carries is_recommended=True, otherwise the P80
    row does. Both PROD outputs render the same set of rows; only the
    highlight differs.
    """
    if not rows:
        return

    columns = [
        ("confidence_level",        "Confidence level"),
        ("integrated_contingency_m", "Integrated contingency ($M)"),
        ("schedule_slip_days",       "Schedule slip (days)"),
        ("above_naive_sum_m",        "Above naive sum ($M)"),
    ]
    table = doc.add_table(rows=1, cols=len(columns))
    table.style = style
    for i, (_, header) in enumerate(columns):
        table.rows[0].cells[i].text = header

    for row in rows:
        cells = table.add_row().cells
        is_recommended = bool(row.get("is_recommended", False))
        for i, (key, _) in enumerate(columns):
            val = row.get(key)
            if key == "confidence_level":
                text = str(val) + (" (recommended)" if is_recommended else "")
            elif key == "schedule_slip_days":
                text = f"{float(val):.1f}" if val is not None else "-"
            else:  # dollar columns
                text = f"${float(val):.2f}M" if val is not None else "-"
            cells[i].text = text
            if is_recommended:
                _set_cell_shading(cells[i], "FFF3CD")  # warm highlight
                for paragraph in cells[i].paragraphs:
                    for run in paragraph.runs:
                        run.bold = True


def _add_component_breakdown_table_v35(
    doc: Document,
    rows: list[dict[str, Any]],
    headline_col: str = "P80",
    style: str = "Light Grid Accent 1",
) -> None:
    """Render the Page 1 component breakdown with both P80 and Mean columns.

    Both PROD outputs render this same table (Component / P80 / Mean / Notes);
    `headline_col` ("P80" or "Mean") controls which column gets the warm
    highlight + bold styling. The "Value" key on each row is ignored here -
    it's a legacy alias that mirrors the P80 column.

    SR9 v3.5 brief §2 invariant: the cell text is identical between the two
    PROD outputs; only the column shading + bold differs.
    """
    if not rows:
        return

    headline_col = "P80" if str(headline_col).strip().upper() == "P80" else "Mean"

    columns = [
        ("Component", "Component"),
        ("P80", "P80 ($M)"),
        ("Mean", "Mean ($M)"),
        ("Notes", "Notes"),
    ]
    table = doc.add_table(rows=1, cols=len(columns))
    table.style = style
    for i, (_, header) in enumerate(columns):
        cells = table.rows[0].cells
        cells[i].text = header
        if header.startswith(headline_col):
            _set_cell_shading(cells[i], "FFF3CD")
            for paragraph in cells[i].paragraphs:
                for run in paragraph.runs:
                    run.bold = True

    for row in rows:
        body = table.add_row().cells
        for i, (key, _) in enumerate(columns):
            val = row.get(key, "")
            body[i].text = "" if val is None else str(val)
            if key == headline_col:
                _set_cell_shading(body[i], "FFF3CD")
                for paragraph in body[i].paragraphs:
                    for run in paragraph.runs:
                        run.bold = True


# ----------------------------------------------------------------------------
# v3 page renderers
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# Beta-12 — Activity-level criticality section (between Page 4 and Page 5)
# ----------------------------------------------------------------------------

def _add_criticality_section_v36(
    doc: Document,
    composed: dict[str, Any],
) -> None:
    """Render the activity-level criticality section into ``doc``.

    No-op when ``composed["page4b_criticality"]`` is empty / missing —
    the Stage 2.5 production path bypasses this section entirely
    (Beta-12 §3.5; Beta-00 §5 invariant: Stage 2.5 output unchanged
    when stage3_beta_result is None).

    Section structure (Beta-12 §3.5):
      - H1 heading "Activity-level criticality" (no BETA word — docx
        BETA banner from Beta-08 already covers the architectural flag)
      - Plain-language explainer paragraph (~250 words)
      - CI distribution chart image (banded bar PNG)
      - Distribution-shape interpretation paragraph (data-driven)
      - Near-critical activities table (CI 20-80% band)
      - Near-critical interpretation paragraph (data-driven)
      - H2 sub-heading "Risk-to-activity bridge"
      - Risk-bridge interpretation paragraph
      - Bridge table (top-3 schedule risks × auto-mapper expansion)
      - H2 sub-heading "Inputs that drive criticality accuracy"
      - Input-dependencies caveat block
      - Page break

    The caveat is the user-direction-driven editorial frame: positions
    the model as deterministic-given-inputs and the user as the
    controller of input quality. No dev/prod or workshop-pending
    phrasing in the section body (Beta-12 §3.3 caveat invariant).
    """
    p4b = composed.get("page4b_criticality") or {}
    if not p4b:
        return

    doc.add_heading("Activity-level criticality", level=1)

    # SR9 v3.6.1 A5: zero-expansion notice rendered as a banner-style
    # paragraph at the top of the criticality section. Caveats the
    # criticality content where any risk driver binds to zero activities
    # under the auto-mapper. Notice is None when all drivers are mapped.
    _zero_notice = composed.get("auto_mapper_zero_expansion_notice")
    if _zero_notice and _zero_notice.get("paragraph"):
        para = doc.add_paragraph()
        # Paragraph copy is markdown-style ("**bold opening.** body"); the
        # paragraph splits on the first ". " after the bold opener.
        text = str(_zero_notice["paragraph"]).strip()
        if text.startswith("**"):
            close = text.find("**", 2)
            if close != -1:
                bold_run = para.add_run(text[2:close])
                bold_run.bold = True
                rest = text[close + 2:].lstrip(" ")
                if rest:
                    para.add_run(" " + rest)
            else:
                para.add_run(text)
        else:
            para.add_run(text)

    # SR-S3-Beta-18 §1: auto-mapper interpretation paragraph. Frames
    # the over-bound risks (counterpart of the zero-expansion notice
    # above, which frames the zero-bound risks). Renders as a single
    # paragraph with the leading "**How to read..." marker promoted to
    # bold run, matching the zero-notice rendering pattern.
    _audit_interp = str(
        composed.get("auto_mapper_audit_interpretation", "") or ""
    ).strip()
    if _audit_interp:
        para = doc.add_paragraph()
        if _audit_interp.startswith("**"):
            close = _audit_interp.find("**", 2)
            if close != -1:
                bold_run = para.add_run(_audit_interp[2:close])
                bold_run.bold = True
                rest = _audit_interp[close + 2:].lstrip(" ")
                if rest:
                    para.add_run(" " + rest)
            else:
                para.add_run(_audit_interp)
        else:
            para.add_run(_audit_interp)

    # Beta-19 §3: main-report criticality section shrunk. Keeps the CI
    # explainer, a Chart-2 placeholder image-frame caption, a 5-row
    # near-critical summary, a risk-to-CP linkage prose paragraph
    # (replaces the full bridge table), the Inputs subsection, and a
    # forward-reference line to the sibling criticality note. Full
    # detail (10-row near-critical, bridge table, chart placeholders
    # for 1/3/4) sits in the sibling note rendered separately.

    # 1. Plain-language explainer.
    explainer = str(p4b.get("explainer", "")).strip()
    if explainer:
        for paragraph in explainer.split("\n\n"):
            cleaned = paragraph.strip()
            if cleaned:
                doc.add_paragraph(cleaned)

    # 2. Chart 2 — criticality density Gantt by phase. SR10.B embeds the
    #    rendered PNG when chart_output_dir was supplied to the composer;
    #    legacy / test paths fall back to the placeholder caption.
    chart2_main_path = str(p4b.get("chart2_density_gantt_path", "")).strip()
    if chart2_main_path and Path(chart2_main_path).exists():
        _add_picture_centered(doc, chart2_main_path)
        chart2_caption = str(
            p4b.get("chart2_placeholder_caption", "") or ""
        ).strip()
        if chart2_caption:
            _add_interpretation(doc, chart2_caption)
    else:
        chart2_caption = str(p4b.get("chart2_placeholder_caption", "")).strip()
        if chart2_caption:
            _add_interpretation(doc, chart2_caption)

    # 3. Near-critical activities — top-5 summary in the main report;
    #    the full 10-row table sits in the sibling criticality note.
    near_top_5 = p4b.get("near_critical_table_top_5") or []
    if near_top_5:
        doc.add_heading("Near-critical activities (top 5 by CI)", level=2)
        rendered_rows: list[dict[str, Any]] = []
        for row in near_top_5:
            r = dict(row)
            ci_val = r.get("ci")
            if isinstance(ci_val, (int, float)):
                r["ci"] = f"{ci_val:.0%}"
            for col in ("total_float_mean_hours", "total_float_std_hours"):
                v = r.get(col)
                if isinstance(v, (int, float)):
                    r[col] = f"{float(v):.1f}"
            rendered_rows.append(r)
        _add_dict_list_table(doc, rendered_rows)
        _near_caveat = str(p4b.get("near_critical_table_caveat", "") or "").strip()
        if _near_caveat:
            _add_interpretation(doc, _near_caveat)
    else:
        doc.add_paragraph(
            "No activities sit in the near-critical (CI 20-80%) band "
            "under the current inputs."
        )

    # 4. Risk-to-CP linkage prose — 2-3 sentence paragraph replacing
    #    the full risk-to-activity bridge table (which moves to the
    #    sibling criticality note).
    linkage_prose = str(p4b.get("risk_to_cp_linkage_prose", "")).strip()
    if linkage_prose:
        doc.add_paragraph(linkage_prose)

    # 5. Inputs that drive criticality accuracy.
    caveat = str(p4b.get("input_dependencies_caveat", "")).strip()
    if caveat:
        doc.add_heading(
            "Inputs that drive criticality accuracy", level=2,
        )
        for paragraph in caveat.split("\n\n"):
            cleaned = paragraph.strip()
            if cleaned:
                doc.add_paragraph(cleaned)

    # 6. Forward-reference to the sibling criticality note.
    fwd_ref = str(p4b.get("forward_reference_to_note", "")).strip()
    if fwd_ref:
        para = doc.add_paragraph()
        run = para.add_run(fwd_ref)
        run.italic = True
        run.font.size = Pt(10)

    doc.add_page_break()


def _add_criticality_appendix(
    doc: Document,
    composed: dict[str, Any],
) -> None:
    """Render the Stage 3 standalone docx's Criticality detail appendix.

    SR14b.1. Gated by ``deliverable_kind == "stage3_standalone"`` so the
    Stage 2.5 production deliverable is byte-identical (existence-guard
    invariant). The four chart PNG paths plus the full 10-row near-critical
    table and full risk-to-activity bridge table sit on
    ``composed["page4b_criticality"]`` per the SR14b.1 brief §3.1 extension;
    each shadow-key has the same source object as the corresponding
    deprecated ``composed["criticality_note"]`` field so the appendix and
    the (now-orphan) sibling note would render identical content if the
    sibling were re-enabled.

    Section structure (brief §3.2):
      - H1 "Criticality detail"
      - H2 1. Criticality index distribution (banded view) — Beta-12 CI
            distribution chart + data-driven interpretation paragraph
      - H2 2. Sorted Top-30 criticality (Chart 1) — SR10.B Chart 1
      - H2 3. Near-critical activities (CI 20-80%) - full detail —
            full 10-row table + calendar caveat
      - H2 4. Risk-to-activity bridge (top-3 schedule risk drivers) —
            interpretation paragraph ABOVE the full bridge table
      - H2 5. Float histogram with criticality overlay (Chart 4) —
            SR10.B Chart 4
      - H2 6. Risk-to-CP linkage (Chart 3) — SR10.B Chart 3

    The "Inputs that drive criticality accuracy" subsection (§7 in the
    deprecated sibling note) is intentionally omitted here — the same
    content already renders in the main-body criticality section via
    :func:`_add_criticality_section_v36`; the appendix does not repeat it.
    """
    # SR14b.1 AC8: no-op when the deliverable is not Stage 3 standalone.
    # Stage 2.5 path stays byte-identical by construction (the appendix
    # call site is the only place this helper is reachable).
    if str(composed.get("deliverable_kind") or "") != "stage3_standalone":
        return

    p4b = composed.get("page4b_criticality") or {}
    if not p4b:
        return

    # SR14b.1 §3.2 existence guard: the appendix renders only when the
    # new chart-path keys are present on page4b_criticality. Belt-and-
    # braces — the composer always populates them under SR14b.1, but the
    # guard documents the renderer-contract for legacy callers / tests
    # that build page4b_criticality without the SR14b.1 dict extension.
    _required_keys = (
        "chart1_sorted_top30_path",
        "chart3_risk_to_cp_linkage_path",
        "chart4_float_histogram_path",
        "ci_distribution_chart_path",
    )
    if not any(p4b.get(k) for k in _required_keys):
        return

    doc.add_heading("Criticality detail", level=1)

    # §1. Criticality index distribution (banded view).
    doc.add_heading(
        "Criticality index distribution (banded view)", level=2,
    )
    ci_dist_path = str(p4b.get("ci_distribution_chart_path", "") or "").strip()
    if ci_dist_path and Path(ci_dist_path).exists():
        _add_picture_centered(doc, ci_dist_path)
    dist_interp = str(p4b.get("distribution_interpretation", "")).strip()
    if dist_interp:
        for paragraph in dist_interp.split("\n\n"):
            cleaned = paragraph.strip()
            if cleaned:
                doc.add_paragraph(cleaned)
    ci_dist_caption = str(p4b.get("ci_distribution_caption", "")).strip()
    if ci_dist_caption:
        _add_interpretation(doc, ci_dist_caption)

    # §2. Sorted Top-30 criticality (Chart 1).
    doc.add_heading("Sorted Top-30 criticality (Chart 1)", level=2)
    chart1_path = str(p4b.get("chart1_sorted_top30_path", "") or "").strip()
    if chart1_path and Path(chart1_path).exists():
        _add_picture_centered(doc, chart1_path)
    chart1_caption = str(p4b.get("chart1_caption", "")).strip()
    if chart1_caption:
        _add_interpretation(doc, chart1_caption)

    # §3. Near-critical activities (CI 20-80%) - full detail. Renders the
    #     full 10-row table (vs the 5-row top-N summary in the main body)
    #     with the same column formatting _add_criticality_section_v36
    #     uses for near_critical_table_top_5: CI as percent, float
    #     mean/std as 1dp hours.
    doc.add_heading(
        "Near-critical activities (CI 20-80%) - full detail", level=2,
    )
    near_full = p4b.get("near_critical_table_full") or []
    if near_full:
        rendered_rows: list[dict[str, Any]] = []
        for row in near_full:
            r = dict(row)
            ci_val = r.get("ci")
            if isinstance(ci_val, (int, float)):
                r["ci"] = f"{ci_val:.0%}"
            for col in ("total_float_mean_hours", "total_float_std_hours"):
                v = r.get(col)
                if isinstance(v, (int, float)):
                    r[col] = f"{float(v):.1f}"
            rendered_rows.append(r)
        _add_dict_list_table(doc, rendered_rows)
        _near_caveat = str(p4b.get("near_critical_table_caveat", "") or "").strip()
        if _near_caveat:
            _add_interpretation(doc, _near_caveat)
    else:
        doc.add_paragraph(
            "No activities sit in the near-critical (CI 20-80%) band "
            "under the current inputs."
        )

    # §4. Risk-to-activity bridge (top-3 schedule risk drivers). Renders
    #     the interpretation paragraph ABOVE the full bridge table per
    #     §3.2 of the brief (matches the deprecated sibling-note flow at
    #     :func:`generate_criticality_note_docx` §6).
    doc.add_heading(
        "Risk-to-activity bridge (top-3 schedule risk drivers)", level=2,
    )
    bridge_interp = str(p4b.get("risk_bridge_interpretation", "")).strip()
    if bridge_interp:
        doc.add_paragraph(bridge_interp)
    bridge_full = p4b.get("risk_to_activity_bridge_full") or []
    if bridge_full:
        rendered_bridge: list[dict[str, Any]] = []
        for row in bridge_full:
            r = dict(row)
            ci_val = r.get("ci")
            if ci_val is None:
                r["ci"] = ""
            elif isinstance(ci_val, float) and ci_val != ci_val:
                # NaN guard (NaN != NaN).
                r["ci"] = ""
            elif isinstance(ci_val, (int, float)):
                r["ci"] = f"{ci_val:.0%}"
            r.pop("no_activity_bindings", None)
            rendered_bridge.append(r)
        _add_dict_list_table(doc, rendered_bridge)

    # §5. Float histogram with criticality overlay (Chart 4).
    doc.add_heading(
        "Float histogram with criticality overlay (Chart 4)", level=2,
    )
    chart4_path = str(p4b.get("chart4_float_histogram_path", "") or "").strip()
    if chart4_path and Path(chart4_path).exists():
        _add_picture_centered(doc, chart4_path)
    chart4_caption = str(p4b.get("chart4_caption", "")).strip()
    if chart4_caption:
        _add_interpretation(doc, chart4_caption)

    # §6. Risk-to-CP linkage (Chart 3).
    doc.add_heading("Risk-to-CP linkage (Chart 3)", level=2)
    chart3_path = str(p4b.get("chart3_risk_to_cp_linkage_path", "") or "").strip()
    if chart3_path and Path(chart3_path).exists():
        _add_picture_centered(doc, chart3_path)
    chart3_caption = str(p4b.get("chart3_caption", "")).strip()
    if chart3_caption:
        _add_interpretation(doc, chart3_caption)


def _render_v3_executive_summary(
    doc: Document,
    composed: dict[str, Any],
    audit_trail: dict[str, Any],
    disclaimer_paragraphs: list[str],
    cross_validation: dict[str, Any],
) -> None:
    """Render the 6-8 page v3 executive summary into doc."""

    # ---- Page 1: The answer (v3.1: integrated P80 lead) ----
    _add_title_page(doc, composed.get("executive_summary", {}), audit_trail)
    _maybe_render_preview_banner(doc, composed)
    doc.add_heading("Executive summary", level=1)

    # v3.1 D10: integrated P80 headline sentence (single recommended figure).
    headline_integrated = composed.get("page1_headline_integrated", "")
    if headline_integrated:
        para = doc.add_paragraph()
        run = para.add_run(headline_integrated)
        run.bold = True
        run.font.size = Pt(13)
    # STAGE3HEADLINE-01: the Stage 3 percentile block, when the composer supplied one.
    _stage3_headline = (composed.get("executive_summary") or {}).get("headline_stage3")
    if isinstance(_stage3_headline, dict):
        _add_stage3_headline(doc, _stage3_headline)

    # Beta-17 Item 3: Mean / median / buffer-choice framing paragraph.
    # Three sentences explaining (i) Mean as the portfolio answer, (ii) P80
    # as conservative buffer, (iii) the choice as risk-appetite not
    # arithmetic. Sits after the headline figure and BEFORE the
    # six-approach reconciliation table so the reader interprets the
    # headline before being shown alternative comparator approaches.
    portfolio_framing = composed.get("page1_portfolio_framing", "")
    if portfolio_framing:
        para = doc.add_paragraph()
        run = para.add_run(portfolio_framing)
        run.font.size = Pt(11)

    # Beta-15 Item 5: six-approach reconciliation table. Sits between
    # the headline figure and the component breakdown so the reader can
    # plant the Monte Carlo number against first-principles comparators
    # (10% / 20% rules of thumb, sum of pessimistic, EMV PERT, MC Mean,
    # MC P95) at first glance. Bold row marks the headline metric (MC
    # P80 by default; MC Mean when --headline Mean was passed).
    six_approach = composed.get("page1_six_approach_reconciliation")
    if isinstance(six_approach, dict):
        sa_table = six_approach.get("table")
        if isinstance(sa_table, pd.DataFrame) and len(sa_table) > 0:
            doc.add_heading(
                "Headline vs first-principles comparators", level=2,
            )
            _add_six_approach_reconciliation_table(doc, six_approach)

    # v3.1 D10 + v3.5: component breakdown table. Has both P80 and Mean
    # columns under v3.5; the headline column is highlighted per
    # composed["page1_component_breakdown_headline_col"].
    component_breakdown = composed.get("page1_component_breakdown", [])
    if component_breakdown:
        first_row = component_breakdown[0] if component_breakdown else {}
        if isinstance(first_row, dict) and "P80" in first_row and "Mean" in first_row:
            headline_col = composed.get(
                "page1_component_breakdown_headline_col", "P80",
            )
            _add_component_breakdown_table_v35(
                doc, component_breakdown, headline_col=headline_col,
            )
        else:
            # Backward-compat path for v3.1-shape rows (no P80/Mean keys).
            _add_dict_list_table(doc, component_breakdown)

    # SR9 v3.6.1 C2: mean-diversification interpretation note beneath the
    # component breakdown table (HTML / Word parity with the notebook).
    diversification_note = composed.get(
        "page1_component_breakdown_diversification_note", "",
    )
    if diversification_note:
        _add_italic_note(doc, diversification_note, size_pt=9)

    # SR9 v3.5: Page 1 Mean / P80 methodology footnote (rendered in both
    # PROD outputs and in dev so the methodology stance is always visible).
    mean_footnote = composed.get("page1_mean_footnote", "")
    if mean_footnote:
        _add_italic_note(doc, mean_footnote, size_pt=9)

    # v3.1 D10: schedule-in-days context (P80 leads, mean follows).
    schedule_context = composed.get("page1_schedule_context", "")
    if schedule_context:
        para = doc.add_paragraph()
        run = para.add_run(schedule_context)
        run.font.size = Pt(11)

    # v3.1 D10: Mode caveat (DP Review and All Series integrated P80 range).
    mode_caveat = composed.get("page1_mode_caveat", "")
    if mode_caveat:
        para = doc.add_paragraph()
        run = para.add_run(mode_caveat)
        run.italic = True
        run.font.size = Pt(10)

    # v3.1 D5: reading convention callout (visually framed).
    reading_convention = composed.get("page1_reading_convention", "")
    if reading_convention:
        doc.add_paragraph()
        _add_callout_box(
            doc,
            composed.get("page1_reading_convention_title", "Reading convention"),
            reading_convention,
        )

    # v3.1 D4: the top driver's dominance finding surfaced near headline.
    top_driver = composed.get("page1_top_schedule_driver", {}) or {}
    dominance_text = top_driver.get("dominance_text", "")
    if dominance_text:
        para = doc.add_paragraph()
        run = para.add_run(dominance_text)
        run.font.size = Pt(11)

    # v3 range table (Table 0) reframed as supporting detail.
    range_table = composed.get("page1_range_table", [])
    if range_table:
        doc.add_heading(
            ("Headline against the Stage 2.5 Mode-scenario comparators"
             if isinstance((composed.get("executive_summary") or {}).get("headline_stage3"), dict)
             else "Headline range across plausible Mode classifications"),
            level=2,
        )
        _add_dict_list_table(doc, range_table)
        # SR9 v3.6.1 B2a (surface 1): dedup footnote attached at composer
        # build time when two scenarios collapsed to identical numerics.
        # Empty/None when no dedup occurred. Mirrors the HTML render in
        # final_runner.ipynb Cell 14.
        _range_dedup_footnote = composed.get("page1_range_table_dedup_footnote")
        if _range_dedup_footnote:
            _add_italic_note(doc, _range_dedup_footnote, size_pt=10)

    # v3.1 D9: explanatory note immediately below Table 0.
    mean_cost_note = composed.get("page1_mean_cost_identical_note", "")
    if mean_cost_note:
        _add_italic_note(doc, mean_cost_note, size_pt=10)

    callouts = composed.get("callouts", {})
    if callouts.get("why_mc_matters"):
        doc.add_paragraph()
        _add_callout_box(
            doc,
            callouts.get("why_mc_matters_title", "Why MC matters here"),
            callouts.get("why_mc_matters", ""),
        )
    if callouts.get("how_ages_well"):
        doc.add_paragraph()
        _add_callout_box(
            doc,
            callouts.get("how_ages_well_title", "How this analysis ages well"),
            callouts.get("how_ages_well", ""),
        )

    doc.add_page_break()

    # ---- Page 2: Distribution shape (v3.1: confidence curve precedes) ----
    doc.add_heading("Distribution shape", level=1)

    # v3.1 D11: confidence curve table at top of Page 2.
    cc_preamble = composed.get("page2_confidence_curve_preamble", "")
    cc_rows = composed.get("page2_confidence_curve", [])
    cc_footnote = composed.get("page2_confidence_curve_footnote", "")
    if cc_rows:
        doc.add_heading("Confidence curve - integrated contingency by P-level", level=2)
        _add_orienting(doc, cc_preamble)
        _add_confidence_curve_table(doc, cc_rows)
        _add_italic_note(doc, cc_footnote, size_pt=9)
        # SR9 v3.5: diversification-flips-negative-at-P90+ footnote.
        diversification_tail_footnote = composed.get(
            "page2_diversification_tail_footnote", "",
        )
        if diversification_tail_footnote:
            _add_italic_note(doc, diversification_tail_footnote, size_pt=9)

    p2 = composed.get("page2_distribution", {})

    # Beta-15 Item 4: confidence-band waterfall image. Sits BETWEEN the
    # confidence-curve table (already rendered above) and the schedule
    # slip distribution sub-heading per brief Decision 4. Renders only
    # when the chart path is truthy.
    waterfall_path = p2.get("waterfall_path", "")
    if waterfall_path:
        doc.add_heading("Confidence-band waterfall", level=2)
        waterfall_caption = p2.get("waterfall_caption", "")
        if waterfall_caption:
            _add_orienting(doc, waterfall_caption)
        _add_picture_centered(doc, waterfall_path)

    # Beta-16 Item 2: cost outturn distribution subsection. Sits between
    # the confidence-curve / waterfall block above and the schedule slip
    # distribution below, restoring the cost-side graphical view dropped
    # in the SR9 v3 trim (brief Decision 3). Renders only when the
    # composer produced the chart pair (image-presence guard); empty
    # chart paths suppress the entire subsection so legacy callers that
    # bypass chart generation are unaffected.
    p2_cost = composed.get("page2_cost_distribution", {})
    cost_s_curve_path = p2_cost.get("s_curve_path", "")
    cost_density_path = p2_cost.get("density_path", "")
    if cost_s_curve_path or cost_density_path:
        doc.add_heading("Event-risk cost distribution", level=2)
        _add_orienting(doc, p2_cost.get("orienting", ""))
        if cost_s_curve_path:
            _add_picture_centered(doc, cost_s_curve_path)
        if cost_density_path:
            _add_picture_centered(doc, cost_density_path)

    doc.add_heading("Schedule slip distribution", level=2)
    _add_orienting(doc, p2.get("orienting", ""))
    _add_picture_centered(doc, p2.get("s_curve_path", ""))
    _add_picture_centered(doc, p2.get("density_path", ""))
    _add_interpretation(doc, p2.get("interpretation", ""))

    doc.add_page_break()

    # Beta-19 §1: Main report H1 marker. The Executive summary content
    # above (Pages 1-2) sits under the Executive summary H1; the Main
    # report H1 introduces the body sections (Pages 3-7 + Audit trail);
    # the Appendix H1 follows the single-iteration walkthrough.
    doc.add_heading("Main report", level=1)

    # ---- Page 3: Cost drivers (v3.1: D2 trimmed table, D6 mode-independence note) ----
    p3 = composed.get("page3_cost_drivers", {})
    doc.add_heading("Risk drivers - cost", level=1)
    _add_orienting(doc, p3.get("orienting", ""))
    _add_picture_centered(doc, p3.get("tornado_path", ""))
    _add_dict_list_table(doc, p3.get("drivers_table", []))
    # v3.1 D6: Mode-independence note immediately below the cost drivers table.
    _add_italic_note(doc, p3.get("mode_independence_note", ""), size_pt=10)
    _add_interpretation(doc, p3.get("interpretation", ""))

    # Beta-17 Item 4: RBS Level 1 cost category breakdown subsection.
    # Sits at the end of the Risk drivers - cost section, after the
    # driver-level tornado / table / interpretation. Heading is H2; the
    # orienting note is metric-aware (matches the Beta-16 headline metric).
    rbs_cost_heading = p3.get("rbs_l1_heading", "")
    rbs_cost_table = p3.get("rbs_l1_breakdown_table", [])
    if rbs_cost_heading and rbs_cost_table:
        doc.add_heading(rbs_cost_heading, level=2)
        _add_orienting(doc, p3.get("rbs_l1_orienting", ""))
        _add_dict_list_table(doc, rbs_cost_table)

    doc.add_page_break()

    # ---- Page 4: Schedule drivers and Mode sensitivity (v3.1: D7 explicit Mode basis) ----
    # PRESENT-01 (D-4): the heading had a second form naming an indicative Mode classification
    # and its mix string, and a Mode-sensitivity sub-block below it. Both were dev-only, and the
    # deliverable refuses dev.
    p4 = composed.get("page4_schedule_drivers", {})
    doc.add_heading("Risk drivers - schedule", level=1)
    _add_orienting(doc, p4.get("orienting_tornado", ""))
    _add_picture_centered(doc, p4.get("tornado_path", ""))
    _add_dict_list_table(doc, p4.get("drivers_table", []))
    # SR15 — Decision 4 (Director-locked 2026-05-16): Mode-column
    # footnote rendered immediately under the schedule drivers Table 6
    # in the Stage 3 standalone docx. Stage 2.5 composer does not set
    # ``mode_column_footnote_stage3`` so this branch is a no-op on the
    # Stage 2.5 path (lock preserved by omission). Footnote prose is
    # rendered italic at 9 pt to match the existing under-table caveat
    # convention (see ``criticality_reframe`` below).
    _sr15_mode_footnote = p4.get("mode_column_footnote_stage3", "")
    if _sr15_mode_footnote:
        _fn_para = doc.add_paragraph()
        _fn_run = _fn_para.add_run(_sr15_mode_footnote)
        _fn_run.italic = True
        _fn_run.font.size = Pt(9)
    _add_interpretation(doc, p4.get("interpretation_tornado", ""))

    reframe = p4.get("criticality_reframe", "")
    if reframe:
        para = doc.add_paragraph()
        run = para.add_run(reframe)
        run.italic = True
        run.font.size = Pt(9)

    # Beta-19 §2: forward-reference sentence; risk matrix block relocated to
    # the appendix (after the single-iteration walkthrough) as an
    # explanatory device. See "Risk matrix - traditional vs
    # probability-weighted (explanatory)" later in the doc.
    forward = p4.get("risk_matrix_forward_reference", "")
    if forward:
        para = doc.add_paragraph()
        run = para.add_run(forward)
        run.italic = True
        run.font.size = Pt(10)

    # Beta-17 Item 4: RBS Level 1 schedule category breakdown subsection.
    # Sits at the end of the Risk drivers - schedule section, after the
    # tornado / table / risk-matrix. Schedule metric is always
    # probability-weighted mean (days) per the schedule tornado convention.
    rbs_sched_heading = p4.get("rbs_l1_heading", "")
    rbs_sched_table = p4.get("rbs_l1_breakdown_table", [])
    if rbs_sched_heading and rbs_sched_table:
        doc.add_heading(rbs_sched_heading, level=2)
        _add_orienting(doc, p4.get("rbs_l1_orienting", ""))
        _add_dict_list_table(doc, rbs_sched_table)

    doc.add_page_break()

    # ---- Page 4b: Activity-level criticality (Beta-12) -----------------
    # Renders only when the Stage 3 Beta engine ran and populated the
    # criticality block; Stage 2.5 production path (no
    # stage3_beta_result) skips this section entirely. The docx-wide
    # BETA banner from Beta-08 already flags the architectural status;
    # this section's heading carries no BETA word per Beta-12 §3.5.
    _add_criticality_section_v36(doc, composed)

    # PRESENT-01 (D-4): a dev-only Page 5 stood here - reconciliation table,
    # confidence-band waterfall and a cross-validation status panel - behind
    # ``if mode == "dev"``. The deliverable refuses dev, so no reader has seen it; the
    # cross-validation verdict reaches the reader through the gate's own banner.

    # ---- Page 6: Action implications ----
    p6 = composed.get("page6_action_implications", {})
    doc.add_heading("Action implications", level=1)
    _add_orienting(doc, p6.get("orienting", ""))
    # SR-S3-Beta-18 §2: illustrative-only banner above the treatment ROI
    # table. The table cells themselves now read "Workshop input
    # required"; the banner makes the placeholder status visible to a
    # skim-reader. Bold opening run mirrors the auto-mapper notice
    # convention.
    _banner_text = str(p6.get("banner", "") or "").strip()
    if _banner_text:
        para = doc.add_paragraph()
        if _banner_text.startswith("**"):
            close = _banner_text.find("**", 2)
            if close != -1:
                bold_run = para.add_run(_banner_text[2:close])
                bold_run.bold = True
                rest = _banner_text[close + 2:].lstrip(" ")
                if rest:
                    para.add_run(" " + rest)
            else:
                para.add_run(_banner_text)
        else:
            para.add_run(_banner_text)
    roi_table = p6.get("treatment_roi_table")
    if isinstance(roi_table, pd.DataFrame) and len(roi_table) > 0:
        _add_dataframe_table(doc, roi_table)
    _add_interpretation(doc, p6.get("interpretation", ""))

    doc.add_heading("Recommendations", level=2)
    recs = p6.get("recommendations", [])
    if recs:
        _add_bullets(doc, recs)

    doc.add_page_break()

    # ---- Page 7: Methodology and caveats ----
    p7 = composed.get("page7_methodology", {})
    doc.add_heading("Methodology and caveats", level=1)

    doc.add_heading("Methodology summary", level=2)
    for paragraph in p7.get("summary_paragraphs", disclaimer_paragraphs[:4]):
        doc.add_paragraph(paragraph)

    # SR15 — Mode multipliers and the full-CPM approach (Decision 3,
    # Director-locked 2026-05-16). New H2 subsection inside the
    # "Methodology and caveats" H1; rendered only when the composer set
    # ``mode_multipliers_full_cpm_paragraphs`` (Stage 3 standalone
    # composer sets this; Stage 2.5 composer does not — Stage 2.5 lock
    # preserved by omission). Each paragraph string may carry a leading
    # ``**lead-phrase.**`` markdown marker; the renderer promotes the
    # marked text to a bold run and emits the remainder as plain prose,
    # matching the existing ``auto_mapper_audit_interpretation``
    # paragraph convention.
    _sr15_paragraphs = p7.get("mode_multipliers_full_cpm_paragraphs", [])
    if _sr15_paragraphs:
        _sr15_heading = p7.get(
            "mode_multipliers_full_cpm_heading",
            "Mode multipliers and the full-CPM approach",
        )
        doc.add_heading(_sr15_heading, level=2)
        for _p_text in _sr15_paragraphs:
            _p_text = str(_p_text).strip()
            if not _p_text:
                continue
            _para = doc.add_paragraph()
            if _p_text.startswith("**"):
                _close = _p_text.find("**", 2)
                if _close != -1:
                    _bold = _para.add_run(_p_text[2:_close])
                    _bold.bold = True
                    _rest = _p_text[_close + 2:].lstrip(" ")
                    if _rest:
                        _para.add_run(" " + _rest)
                    continue
            _para.add_run(_p_text)

    # Beta-17 Item 2: distribution-shape explainer (intro + 4 bullets).
    # Names PERT / Triangular / Lognormal / Binary with rationale per
    # shape. Sits immediately after the Methodology summary paragraphs
    # and BEFORE the Mode-sensitivity summary (Beta-15 Item 3) so the
    # distribution rationale lands before the Mode-classification one.
    dist_intro = p7.get("distribution_shape_explainer_intro", "")
    dist_bullets = p7.get("distribution_shape_explainer_bullets", [])
    if dist_intro:
        doc.add_paragraph(dist_intro)
    if dist_bullets:
        _add_bullets(doc, dist_bullets)

    # Beta-15 Item 3: Mode-sensitivity 4-row summary. Sits BEFORE Standards
    # references per brief Decision 3 (methodology-validation artefact
    # about whether the headline is a single-Mode-classification artefact).
    mode_sens_summary = p7.get("mode_sensitivity_summary")
    if isinstance(mode_sens_summary, dict):
        ms_table = mode_sens_summary.get("table")
        if isinstance(ms_table, pd.DataFrame) and len(ms_table) > 0:
            doc.add_heading("Mode-sensitivity summary", level=2)
            _add_mode_sensitivity_summary_table(doc, mode_sens_summary)

    doc.add_heading("Standards references", level=2)
    refs = p7.get("standards_references", "")
    if refs:
        doc.add_paragraph(refs)

    # Beta-15 Item 2: convergence diagnostic chart + caveat. Sits after
    # Standards references (methodology-validation artefact about
    # whether enough iterations have been run). Renders only when
    # chart_output_dir produced a path; otherwise the section is
    # silently skipped.
    convergence_path = p7.get("convergence_chart_path", "")
    if convergence_path:
        doc.add_heading("Convergence diagnostic", level=2)
        convergence_caption = p7.get("convergence_caption", "")
        if convergence_caption:
            _add_orienting(doc, convergence_caption)
        _add_picture_centered(doc, convergence_path)
        convergence_caveat = p7.get("convergence_caveat", "")
        if convergence_caveat:
            _add_italic_note(doc, convergence_caveat, size_pt=10)

    caveat = p7.get("dp_review_caveat", "")
    if caveat:
        # Heading is dev-only (it names "DP Review"); guarded by caveat body
        # so prod, which empties dp_review_caveat, drops both heading and body.
        doc.add_heading("DP Review classification caveat", level=2)
        para = doc.add_paragraph()
        sentences = caveat.split(". ", 1)
        lead = sentences[0] + ("." if not sentences[0].endswith(".") else "")
        rest = sentences[1] if len(sentences) > 1 else ""
        run_lead = para.add_run(lead + " ")
        run_lead.bold = True
        if rest:
            para.add_run(rest)

    # Beta-17 Item 5: Correlation Group (CG) drivers subsection. Sits
    # between Standards references (and the Beta-15 Convergence diagnostic
    # / DP Review caveat methodology blocks) and Limitations of current
    # analysis. Two orienting paragraphs + a CG ID / Driver / Member
    # risks / Coefficient table. Driver descriptions with REVIEW markers
    # need Director sign-off in smoke verification.
    cg_table = p7.get("cg_drivers_table", [])
    if cg_table:
        doc.add_heading("Correlation Group (CG) drivers", level=2)
        for paragraph in p7.get("cg_drivers_orienting_paragraphs", []):
            doc.add_paragraph(paragraph)
        cg_table_rows = [
            {
                "CG ID": row.get("cg_id", ""),
                "Driver description": row.get("driver_description", ""),
                "Member risks": ", ".join(row.get("member_risk_ids", [])),
                "Coefficient": (
                    f"{row['coefficient']:.2f}"
                    if isinstance(row.get("coefficient"), (int, float))
                    else "n/a"
                ),
            }
            for row in cg_table
        ]
        _add_dict_list_table(doc, cg_table_rows)

    _add_model_validation_section(doc, composed)
    _add_correlation_sensitivity_section(doc, composed)

    doc.add_heading("Limitations of current analysis", level=2)
    limits = p7.get("limitations_current", [])
    if limits:
        _add_bullets(doc, limits)
    closing = p7.get("limitations_closing", "")
    if closing:
        para = doc.add_paragraph()
        run = para.add_run(closing)
        run.italic = True

    doc.add_heading("Single-iteration walkthrough", level=2)
    _add_walkthrough_sidebar(
        doc,
        p7.get("single_iteration_intro", ""),
        p7.get("single_iteration_walkthrough", ""),
    )

    # Beta-15 Item 6: structured per-risk transparency table from
    # run_single_scenario_transparency (the run's seed). Renders 8 body rows
    # (one per Time=Yes risk) + a TOTAL summary row, with columns
    # showing the uniform draws so a reviewer can step through how
    # each fire/no-fire decision and each duration sample were made.
    single_iter_df = p7.get("single_iteration_table")
    if isinstance(single_iter_df, pd.DataFrame) and len(single_iter_df) > 0:
        # SR15.1 Decision 2 = Option A: Stage 3 standalone docx drops
        # the Mode + Mode-multiplier columns. Stage 2.5 docx unaffected.
        _add_single_iteration_transparency_table(
            doc,
            single_iter_df,
            deliverable_kind=composed.get("deliverable_kind"),
        )

    # Beta-19 §1: Appendix H1 marker. The Methodology / Standards /
    # Limitations / Single-iteration walkthrough content above belongs
    # to Main report per Decision 1; the relocated risk matrix is the
    # first true appendix entry. Audit trail (rendered after the page
    # break below) closes Main report, NOT Appendix — but the docx
    # currently renders the audit trail as the final section by
    # convention; the visual separation is sufficient for Beta-19.
    doc.add_page_break()
    doc.add_heading("Appendix", level=1)

    # SR14b.1: Criticality detail appendix section. Renders only when
    # ``composed["deliverable_kind"] == "stage3_standalone"`` so the
    # Stage 2.5 production docx is byte-identical to the SR14b
    # session-2 baseline (AC1/AC2 lock). Carries Charts 1, 3, 4 + the
    # Beta-12 CI distribution chart + full 10-row near-critical table
    # + full risk-to-activity bridge — the content the main-body
    # criticality section's forward-pointer line promises.
    _add_criticality_appendix(doc, composed)

    # Beta-19 §2: risk matrix block relocated here from the schedule
    # drivers section. Sits as an explanatory device alongside the
    # methodology / single-iteration walkthrough content in the appendix
    # area; the schedule drivers section carries a forward-reference
    # sentence pointing at this heading.
    p4 = composed.get("page4_schedule_drivers", {})
    if p4.get("risk_matrix_path"):
        doc.add_heading(
            "Risk matrix - traditional vs probability-weighted (explanatory)",
            level=2,
        )
        _add_orienting(doc, p4.get("orienting_matrix", ""))
        _add_picture_centered(doc, p4.get("risk_matrix_path", ""))
        _add_interpretation(doc, p4.get("interpretation_matrix", ""))

    doc.add_page_break()

    # ---- Page 8: Audit trail ----
    p8 = composed.get("page8_audit_trail", audit_trail)
    _add_audit_trail_footer(doc, p8)

    # Beta-15 Item 1: cross-validation one-liner at the top of the section
    # body (after the heading + audit table, before the reproducibility
    # paragraph). FAIL gates produce a FAIL sentence here in addition to
    # the existing top-of-doc FAIL banner.
    cv_sentence = p8.get("cross_validation_sentence", "")
    if cv_sentence:
        para = doc.add_paragraph()
        run = para.add_run(cv_sentence)
        run.font.size = Pt(10)

    repro = p8.get("reproducibility_paragraph", "")
    if repro:
        doc.add_paragraph()
        para = doc.add_paragraph()
        run = para.add_run(repro)
        run.italic = True

    hashes = p8.get("input_hashes", {})
    if hashes:
        doc.add_heading("Input file hashes (SHA-256)", level=2)
        rows = [(k, v) for k, v in hashes.items()]
        table = doc.add_table(rows=len(rows), cols=2)
        table.style = "Light List Accent 1"
        for i, (k, v) in enumerate(rows):
            table.rows[i].cells[0].text = _header_label(k)
            table.rows[i].cells[1].text = str(v)


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def generate_word_summary(
    summary_data: dict[str, Any],
    audit_trail_data: dict[str, Any],
    disclaimer_paragraphs: list[str],
    cross_validation: dict[str, Any],
    output_path: Path | str,
    composed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate the Word doc executive summary.

    Parameters
    ----------
    summary_data : dict
        The "executive_summary" slice from compose_final_report_data. Must
        contain: headline_contingency_range_p80, top_3_cost_drivers,
        top_3_schedule_drivers, schedule_basis_note, key_findings,
        methodology_caveats, recommendations.
    audit_trail_data : dict
        The "appendix_audit_trail" slice. Must contain register_path,
        strawman_path, run_date, engine_versions, etc.
    disclaimer_paragraphs : list[str]
        From disclaimer_text.get_paragraphs().
    cross_validation : dict
        From cross_validate_reports. Used to inject FAIL banner if
        all_pass is False, and to set custom property cross_validation_status.
    output_path : Path or str
        Where to write the .docx file.

    Returns
    -------
    dict:
      - output_path           : str (absolute path)
      - page_count_estimate   : int (target 3-5; not exact)
      - size_bytes            : int
      - fail_banner_present   : bool
    """
    # Beta-08: when composed.get("beta_flag") is True, this is a Stage 3
    # beta deliverable. We prefix the filename with BETA_ (idempotent),
    # inject the BETA banner above the title, and write the
    # stage3_beta_present custom property as "true". Per Beta-00 §5
    # architectural anchor: there is no path through this function that
    # produces a beta-flagged docx without the banner being applied.
    beta_flag = bool(composed.get("beta_flag")) if isinstance(composed, dict) else False
    beta_metadata: dict[str, Any] | None = None
    if beta_flag:
        beta_metadata = {
            "auto_mapper_audit_path": (
                composed.get("auto_mapper_audit_path") if composed else None
            ),
        }

    output_path = Path(_apply_beta_filename_prefix(Path(output_path), beta_flag))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fail_banner = not bool(cross_validation.get("all_pass", False))

    doc = Document()

    # FAIL banner (if any) goes in first; BETA banner detects FAIL via
    # body-scan and inserts below it. Order at code level: FAIL first,
    # BETA second; final body order: FAIL above, BETA below, title below.
    if fail_banner:
        _inject_fail_banner(doc)
    if beta_flag:
        _inject_beta_banner(doc, beta_metadata=beta_metadata)

    # SR9 v3 path: when composed dict supplied with v3 keys, render
    # the 6-8 page layout. Falls back to v2 layout otherwise.
    use_v3_layout = (
        composed is not None
        and isinstance(composed, dict)
        and "page1_headline" in composed
    )

    if use_v3_layout:
        _render_v3_executive_summary(
            doc=doc,
            composed=composed,
            audit_trail=audit_trail_data,
            disclaimer_paragraphs=disclaimer_paragraphs,
            cross_validation=cross_validation,
        )

        status_value = "FAILED" if fail_banner else "PASSED"
        # SR9 v3.2: mode-aware document properties + visible footer.
        mode = composed.get("report_mode", "dev") if composed else "dev"
        # DELIVFIX-01 (R-3): no "SP22" fallback - a sprint code in the document properties and
        # the visible footer. The package version, with the commit when the run supplied it.
        _versions = audit_trail_data.get("engine_versions", {}) or {}
        engine_version = str(_versions.get("package") or _versions.get("final") or "")
        if _versions.get("engine"):
            engine_version = f"{engine_version} ({str(_versions['engine'])[:9]})".strip()
        run_date = str(audit_trail_data.get("run_date", ""))
        # SR9 v3.5: recommendation_metric custom property (P80 or Mean).
        # Falls back to "P80" when composer didn't supply (legacy callers).
        recommendation_metric = (
            composed.get("recommendation_metric", "P80") if composed else "P80"
        )
        _set_doc_core_and_custom_properties(
            doc,
            mode=mode,
            engine_version=engine_version,
            cv_status=status_value,
            recommendation_metric=recommendation_metric,
            beta_flag=beta_flag,
        )
        _set_visible_page_footer(
            doc, run_date=run_date,
        )
        _apply_data_table_font(doc)
        doc.save(str(output_path))
        size = os.path.getsize(str(output_path))
        return {
            "output_path": str(output_path.resolve()),
            "page_count_estimate": 7,
            "size_bytes": int(size),
            "fail_banner_present": bool(fail_banner),
            "beta_banner_present": bool(beta_flag),
        }

    _add_title_page(doc, summary_data, audit_trail_data)

    doc.add_heading("Executive summary", level=1)
    stage3_headline = summary_data.get("headline_stage3")
    if isinstance(stage3_headline, dict):
        _add_stage3_headline(doc, stage3_headline)
    headline = summary_data.get("headline_contingency_range_p80", {})
    _add_headline_range(doc, headline)

    _add_top_n_table(
        doc,
        heading=f"Top 3 cost drivers ({summary_data.get('cost_drivers_basis', 'DP Review baseline')})",
        drivers=summary_data.get("top_3_cost_drivers", []),
        metric_label="P80 cost",
        units_label="dollars",
    )
    # SR9 v3.5: indicative-basis label derived from composed at format time.
    _indicative_basis = summary_data.get("indicative_basis_short", "Dummy Realistic")
    _sched_heading = summary_data.get("schedule_drivers_basis") or f"{_indicative_basis} basis"
    _add_top_n_table(
        doc,
        heading=f"Top 3 schedule drivers ({_sched_heading})",
        drivers=summary_data.get("top_3_schedule_drivers", []),
        metric_label="P80 schedule",
        units_label="days",
        extra_columns=[("Mode", "mode")],
    )
    note = summary_data.get("schedule_basis_note", "")
    if note:
        p = doc.add_paragraph()
        run = p.add_run(note)
        run.italic = True

    doc.add_heading("Key findings", level=2)
    _add_bullets(doc, summary_data.get("key_findings", []))

    div = summary_data.get("diversification_summary", {})
    if div.get("interpretation"):
        doc.add_heading("Diversification summary", level=2)
        doc.add_paragraph(div["interpretation"])

    doc.add_heading("Methodology summary", level=1)
    # Pick the first 4 paragraphs as the methodology summary; full disclaimer
    # appears in a later section
    for paragraph in disclaimer_paragraphs[:4]:
        doc.add_paragraph(paragraph)

    doc.add_heading("Caveats and limitations", level=1)
    _add_bullets(doc, summary_data.get("methodology_caveats", []))

    doc.add_heading("Recommendations", level=1)
    _add_bullets(doc, summary_data.get("recommendations", []))

    doc.add_heading("Disclaimer (full methodology)", level=1)
    for paragraph in disclaimer_paragraphs:
        doc.add_paragraph(paragraph)

    _add_audit_trail_footer(doc, audit_trail_data)

    # Custom property always set
    status_value = "FAILED" if fail_banner else "PASSED"
    _set_custom_property(doc, CUSTOM_PROPERTY_NAME, status_value)
    # Beta-08: stage3_beta_present is always written so v2-layout callers
    # behave the same as v3-layout callers w.r.t. the beta flag.
    _set_custom_property(
        doc, CUSTOM_PROPERTY_BETA_FLAG, "true" if beta_flag else "false",
    )

    _apply_data_table_font(doc)
    doc.save(str(output_path))
    size = os.path.getsize(str(output_path))

    return {
        "output_path": str(output_path.resolve()),
        "page_count_estimate": 5,
        "size_bytes": int(size),
        "fail_banner_present": bool(fail_banner),
        "beta_banner_present": bool(beta_flag),
    }


# ----------------------------------------------------------------------------
# SR-S3-Beta-19 §3 — Sibling criticality note docx
# ----------------------------------------------------------------------------

def generate_criticality_note_docx(
    composed: dict[str, Any],
    output_path: Path | str,
) -> dict[str, Any]:
    """Render the Beta-19 sibling criticality note docx.

    **DEPRECATED at SR14b.** The Stage 3 standalone report's appendix
    (SR14b session 2's new ``src/final/stage3_composer.py`` +
    criticality appendix-mode extension of
    ``src/final/sections/criticality.py``) carries equivalent content.
    Production runners stop emitting ``sra_criticality_note_PROD_*`` at
    SR14b merge per D4 Option A; this function stays on disk through
    one release cycle and is removed at SR14c. Do not call from new
    code; do not extend.

    Pulls content from ``composed["criticality_note"]`` populated by the
    composer. Scaffold-only — placeholder image-frame captions for the
    Top-30 / density-Gantt / risk-to-CP / float-histogram charts;
    SR10.B replaces these with actual images.

    Returns a dict with ``output_path``, ``size_bytes``, and
    ``sections_rendered`` (int).
    """
    cn = composed.get("criticality_note") or {}
    output_path = Path(output_path)

    doc = Document()
    # Beta-19 §3: sibling note shares the audit-trail run with the main
    # report (same engine run, same hashes), so we keep a minimal title
    # block here and defer the full audit table reference to the
    # text-line at the end of the document.
    doc.add_heading("Criticality and float visibility note", level=1)

    sections = 0

    purpose = str(cn.get("purpose_and_audience", "")).strip()
    if purpose:
        # Bold-marker handling: "**...**" leading run gets bold formatting.
        _add_markdown_paragraph(doc, purpose)
        sections += 1

    # §2 — CI explainer.
    doc.add_heading("CI explainer", level=2)
    explainer = str(cn.get("explainer", "")).strip()
    if explainer:
        for paragraph in explainer.split("\n\n"):
            cleaned = paragraph.strip()
            if cleaned:
                doc.add_paragraph(cleaned)
    sections += 1

    # §3 — Top-30 sorted criticality bar chart (Chart 1).
    doc.add_heading("Top-30 sorted criticality (Chart 1)", level=2)
    chart1_path = cn.get("chart1_path", "")
    if chart1_path and Path(str(chart1_path)).exists():
        _add_picture_centered(doc, chart1_path)
    else:
        _add_interpretation(doc, cn.get("chart1_caption", ""))
    sections += 1

    # §4 — Criticality density Gantt by phase (Chart 2). SR10.B embeds
    # the actual density Gantt; legacy paths (no chart_output_dir) fall
    # back to the Beta-12 CI distribution chart as a temporary stand-in,
    # then to the placeholder caption if no path is available at all.
    doc.add_heading("Criticality density Gantt by phase (Chart 2)", level=2)
    chart2_path = cn.get("chart2_path", "")
    if chart2_path and Path(str(chart2_path)).exists():
        _add_picture_centered(doc, chart2_path)
        chart2_caption = str(cn.get("chart2_caption", "")).strip()
        if chart2_caption:
            _add_interpretation(doc, chart2_caption)
    else:
        _add_interpretation(doc, cn.get("chart2_caption", ""))
    sections += 1

    # §5 — 10-row near-critical activities table.
    doc.add_heading("Near-critical activities (CI 20-80%) — 10-row detail", level=2)
    near = cn.get("near_critical_table_10row") or []
    if near:
        rendered_rows: list[dict[str, Any]] = []
        for row in near:
            r = dict(row)
            ci_val = r.get("ci")
            if isinstance(ci_val, (int, float)):
                r["ci"] = f"{ci_val:.0%}"
            for col in ("total_float_mean_hours", "total_float_std_hours"):
                v = r.get(col)
                if isinstance(v, (int, float)):
                    r[col] = f"{float(v):.1f}"
            rendered_rows.append(r)
        _add_dict_list_table(doc, rendered_rows)
        _near_caveat = str(cn.get("near_critical_table_caveat", "") or "").strip()
        if _near_caveat:
            _add_interpretation(doc, _near_caveat)
    else:
        doc.add_paragraph(
            "No activities sit in the near-critical (CI 20-80%) band "
            "under the current inputs."
        )
    near_interp = str(cn.get("near_critical_interpretation", "")).strip()
    if near_interp:
        _add_interpretation(doc, near_interp)
    sections += 1

    # §6 — Risk-to-activity bridge table.
    doc.add_heading(
        "Risk-to-activity bridge (top-3 schedule risk drivers)", level=2,
    )
    bridge_interp = str(cn.get("risk_bridge_interpretation", "")).strip()
    if bridge_interp:
        doc.add_paragraph(bridge_interp)
    bridge = cn.get("risk_to_activity_bridge") or []
    if bridge:
        rendered_bridge: list[dict[str, Any]] = []
        for row in bridge:
            r = dict(row)
            ci_val = r.get("ci")
            if ci_val is None:
                r["ci"] = ""
            elif isinstance(ci_val, float) and ci_val != ci_val:
                r["ci"] = ""
            elif isinstance(ci_val, (int, float)):
                r["ci"] = f"{ci_val:.0%}"
            r.pop("no_activity_bindings", None)
            rendered_bridge.append(r)
        _add_dict_list_table(doc, rendered_bridge)
        _bridge_caveat = str(
            cn.get("risk_to_activity_bridge_caveat", "") or ""
        ).strip()
        if _bridge_caveat:
            _add_interpretation(doc, _bridge_caveat)
    sections += 1

    # §7 — Float histogram with criticality overlay (Chart 4).
    doc.add_heading(
        "Float histogram with criticality overlay (Chart 4)", level=2,
    )
    chart4_path = cn.get("chart4_path", "")
    if chart4_path and Path(str(chart4_path)).exists():
        _add_picture_centered(doc, chart4_path)
    else:
        _add_interpretation(doc, cn.get("chart4_caption", ""))
    sections += 1

    # §8 — Risk-to-CP linkage (Chart 3).
    doc.add_heading("Risk-to-CP linkage (Chart 3)", level=2)
    chart3_path = cn.get("chart3_path", "")
    if chart3_path and Path(str(chart3_path)).exists():
        _add_picture_centered(doc, chart3_path)
    else:
        _add_interpretation(doc, cn.get("chart3_caption", ""))
    sections += 1

    # §9 — Inputs that drive criticality accuracy.
    caveat = str(cn.get("input_dependencies_caveat", "")).strip()
    if caveat:
        doc.add_heading(
            "Inputs that drive criticality accuracy", level=2,
        )
        for paragraph in caveat.split("\n\n"):
            cleaned = paragraph.strip()
            if cleaned:
                doc.add_paragraph(cleaned)
        sections += 1

    # §10 — Audit-trail reference.
    audit_ref = str(cn.get("audit_trail_reference", "")).strip()
    if audit_ref:
        para = doc.add_paragraph()
        run = para.add_run(audit_ref)
        run.italic = True
        run.font.size = Pt(9)
        sections += 1

    _apply_data_table_font(doc)
    doc.save(str(output_path))
    return {
        "output_path": str(output_path.resolve()),
        "size_bytes": int(os.path.getsize(str(output_path))),
        "sections_rendered": sections,
    }


def _add_markdown_paragraph(doc: Document, text: str) -> None:
    """Render a single markdown-light paragraph with **bold** support.

    Splits on "**" pairs and emits alternating regular / bold runs.
    No other markdown is interpreted (italic-asterisks pass through as
    literal asterisks since the only callers use bold).
    """
    para = doc.add_paragraph()
    chunks = text.split("**")
    # Even-indexed chunks are regular; odd-indexed chunks are bold.
    for i, chunk in enumerate(chunks):
        if not chunk:
            continue
        run = para.add_run(chunk)
        if i % 2 == 1:
            run.bold = True
