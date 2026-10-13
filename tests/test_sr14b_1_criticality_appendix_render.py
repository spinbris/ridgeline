"""SR14b.1 AC4 / AC5 / AC6 / AC8 / AC9 — renderer tests.

Asserts ``_add_criticality_appendix`` (the new helper in
``src/final/word_generator.py``) emits the expected Stage 3 standalone
docx appendix section:

* AC4 — Four embedded PNG picture elements (the four chart paths from
  ``composed["page4b_criticality"]``).
* AC5 — One H1 ``"Criticality detail"`` followed by six H2 sub-headings
  in the order specified at brief §3.2.
* AC6 — 10-row near-critical table + full-length risk-to-activity
  bridge table rendered as Word tables.
* AC8 — No-op when ``composed["deliverable_kind"] != "stage3_standalone"``
  (Stage 2.5 byte-identity by construction at the new call-site).
* AC9 — Zero "Stage 2.5" substring anywhere in the rendered appendix
  text.

Uses synthetic ``page4b_criticality`` data plus four tiny test-only
PNG fixtures (written via :mod:`struct` so we don't depend on
matplotlib here). The rendered docx is inspected via python-docx's
``inline_shapes`` count, paragraph/style-name iteration, and table-cell
text extraction.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

docx = pytest.importorskip("docx")
Document = docx.Document

from src.final import commentary_text  # noqa: E402
from src.final.word_generator import (  # noqa: E402
    _add_criticality_appendix,
)


# ---------------------------------------------------------------------------
# Synthetic PNG fixture — 1x1 grey-pixel valid PNG, written from scratch
# so the test doesn't depend on PIL/matplotlib being importable.
# ---------------------------------------------------------------------------


def _write_tiny_png(target: Path) -> None:
    """Write a valid 1x1 grayscale PNG to ``target``."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00")
    target.write_bytes(
        sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    )


@pytest.fixture
def chart_pngs(tmp_path: Path) -> dict[str, str]:
    paths = {
        "ci_distribution_chart_path": tmp_path / "page4b_ci_distribution.png",
        "chart1_sorted_top30_path": tmp_path / "sr10b_chart1.png",
        "chart3_risk_to_cp_linkage_path": tmp_path / "sr10b_chart3.png",
        "chart4_float_histogram_path": tmp_path / "sr10b_chart4.png",
    }
    for p in paths.values():
        _write_tiny_png(p)
    return {k: str(v) for k, v in paths.items()}


# ---------------------------------------------------------------------------
# Composed-dict factories
# ---------------------------------------------------------------------------


NEAR_CRITICAL_ROW_COUNT = 10
BRIDGE_ROW_COUNT = 7  # multi-row bridge (one per activity binding)


def _make_near_critical_rows() -> list[dict]:
    return [
        {
            "activity_id": f"ACT{i:03d}",
            "activity_name": f"Activity {i}",
            "ci": 0.35 + i * 0.04,
            "ci_band": "near (30-70%)",
            "total_float_mean_hours": 20.0 + i * 5.0,
            "total_float_std_hours": 4.0 + i * 0.5,
            "on_deterministic_cp": False,
        }
        for i in range(1, NEAR_CRITICAL_ROW_COUNT + 1)
    ]


def _make_bridge_rows() -> list[dict]:
    return [
        {
            "risk_id": f"R{i:03d}",
            "risk_title": f"Risk {i} title",
            "activity_id": f"ACT{i:03d}",
            "activity_name": f"Activity {i}",
            "ci": 0.4 + i * 0.05,
            "on_deterministic_cp": False,
            "no_activity_bindings": False,
        }
        for i in range(1, BRIDGE_ROW_COUNT + 1)
    ]


def _make_stage3_composed(chart_pngs: dict[str, str]) -> dict:
    """Composed dict matching the SR14b.1-extended ``page4b_criticality``
    shape on the Stage 3 standalone path."""
    return {
        "deliverable_kind": "stage3_standalone",
        "page4b_criticality": {
            # Existing keys the appendix reads.
            "distribution_interpretation": (
                "Distribution-shape interpretation. The CI mass concentrates "
                "in the rarely band."
            ),
            "near_critical_table_caveat": "_Calendar caveat note._",
            "risk_bridge_interpretation": (
                "Bridge connects top-3 schedule drivers to activities."
            ),
            # SR14b.1 additive keys.
            "ci_distribution_chart_path": chart_pngs["ci_distribution_chart_path"],
            "chart1_sorted_top30_path": chart_pngs["chart1_sorted_top30_path"],
            "chart3_risk_to_cp_linkage_path": chart_pngs[
                "chart3_risk_to_cp_linkage_path"
            ],
            "chart4_float_histogram_path": chart_pngs[
                "chart4_float_histogram_path"
            ],
            "near_critical_table_full": _make_near_critical_rows(),
            "risk_to_activity_bridge_full": _make_bridge_rows(),
            "chart1_caption": (
                commentary_text.CRITICALITY_CHART_1_PLACEHOLDER_CAPTION
            ),
            "chart3_caption": (
                commentary_text.CRITICALITY_CHART_3_PLACEHOLDER_CAPTION
            ),
            "chart4_caption": (
                commentary_text.CRITICALITY_CHART_4_PLACEHOLDER_CAPTION
            ),
            "ci_distribution_caption": (
                commentary_text.CRITICALITY_CI_DISTRIBUTION_CAPTION_STAGE3
            ),
        },
    }


# ---------------------------------------------------------------------------
# AC5 — H1 + six H2 sub-headings in spec order.
# ---------------------------------------------------------------------------


EXPECTED_H1 = "Criticality detail"

EXPECTED_H2_ORDER = (
    "Criticality index distribution (banded view)",
    "Sorted Top-30 criticality (Chart 1)",
    "Near-critical activities (CI 20-80%) - full detail",
    "Risk-to-activity bridge (top-3 schedule risk drivers)",
    "Float histogram with criticality overlay (Chart 4)",
    "Risk-to-CP linkage (Chart 3)",
)


def _extract_headings(doc) -> list[tuple[str, str]]:
    """Return [(style_name, text), ...] for paragraphs whose style is a
    Heading style (Heading 1 / Heading 2 / ...)."""
    out: list[tuple[str, str]] = []
    for p in doc.paragraphs:
        sn = getattr(p.style, "name", "") or ""
        if sn.startswith("Heading "):
            out.append((sn, p.text))
    return out


def test_ac5_h1_and_six_h2_sub_headings_in_order(chart_pngs) -> None:
    composed = _make_stage3_composed(chart_pngs)
    doc = Document()
    _add_criticality_appendix(doc, composed)

    headings = _extract_headings(doc)
    # The appendix produces exactly one H1 ("Criticality detail") and
    # six H2 sub-headings in spec order. No other heading levels emitted.
    h1s = [t for s, t in headings if s == "Heading 1"]
    h2s = [t for s, t in headings if s == "Heading 2"]
    assert h1s == [EXPECTED_H1], f"Expected exactly one H1 {EXPECTED_H1!r}; got {h1s}"
    assert tuple(h2s) == EXPECTED_H2_ORDER, (
        f"H2 sub-headings out of order or missing.\n"
        f"  Expected: {EXPECTED_H2_ORDER}\n"
        f"  Got:      {tuple(h2s)}"
    )


# ---------------------------------------------------------------------------
# AC6 — full 10-row near-critical + full risk-to-activity bridge.
# ---------------------------------------------------------------------------


def test_ac6_near_critical_full_table_renders_10_rows(chart_pngs) -> None:
    composed = _make_stage3_composed(chart_pngs)
    doc = Document()
    _add_criticality_appendix(doc, composed)
    # Find the near-critical table by searching for ACT001 / ACT010 in
    # the same table's cells. python-docx counts header row as a row, so
    # 10 data rows + 1 header = 11 total rows.
    near_tables = [
        t for t in doc.tables
        if any("ACT001" in cell.text for row in t.rows for cell in row.cells)
        and any("ACT010" in cell.text for row in t.rows for cell in row.cells)
    ]
    assert near_tables, "Near-critical table (with ACT001..ACT010) missing"
    assert len(near_tables[0].rows) == NEAR_CRITICAL_ROW_COUNT + 1, (
        f"Expected {NEAR_CRITICAL_ROW_COUNT + 1} rows (10 data + 1 header); "
        f"got {len(near_tables[0].rows)}"
    )


def test_ac6_risk_bridge_full_table_renders_all_rows(chart_pngs) -> None:
    composed = _make_stage3_composed(chart_pngs)
    doc = Document()
    _add_criticality_appendix(doc, composed)
    bridge_tables = [
        t for t in doc.tables
        if any("R001" in cell.text for row in t.rows for cell in row.cells)
        and any(
            f"R{BRIDGE_ROW_COUNT:03d}" in cell.text
            for row in t.rows for cell in row.cells
        )
    ]
    assert bridge_tables, (
        f"Risk-to-activity bridge table (with R001..R{BRIDGE_ROW_COUNT:03d}) missing"
    )
    assert len(bridge_tables[0].rows) == BRIDGE_ROW_COUNT + 1, (
        f"Expected {BRIDGE_ROW_COUNT + 1} bridge rows (data + 1 header); "
        f"got {len(bridge_tables[0].rows)}"
    )


# ---------------------------------------------------------------------------
# AC4 — four embedded PNG picture elements.
# ---------------------------------------------------------------------------


def test_ac4_four_chart_pngs_embedded(chart_pngs) -> None:
    composed = _make_stage3_composed(chart_pngs)
    doc = Document()
    _add_criticality_appendix(doc, composed)
    # Each _add_picture_centered call produces one inline shape. The
    # appendix embeds CI distribution + Chart 1 + Chart 3 + Chart 4 = 4.
    assert len(doc.inline_shapes) == 4, (
        f"Expected 4 embedded charts (CI distribution + Charts 1, 3, 4); "
        f"got {len(doc.inline_shapes)}"
    )


# ---------------------------------------------------------------------------
# AC8 — no-op when deliverable_kind != "stage3_standalone".
# ---------------------------------------------------------------------------


def test_ac8_no_op_when_deliverable_kind_is_stage25(chart_pngs) -> None:
    """Stage 2.5 byte-identity invariant. The new helper sits in the
    Stage 3 appendix slot; on the Stage 2.5 path ``composed`` has
    ``deliverable_kind=None`` (or absent), so the helper short-circuits
    before adding any content."""
    composed = _make_stage3_composed(chart_pngs)
    # Flip the gate to the Stage 2.5 default (None / absent).
    composed.pop("deliverable_kind")

    doc_blank = Document()
    blank_paragraph_count = len(doc_blank.paragraphs)
    blank_table_count = len(doc_blank.tables)
    blank_inline_count = len(doc_blank.inline_shapes)

    doc = Document()
    _add_criticality_appendix(doc, composed)

    assert len(doc.paragraphs) == blank_paragraph_count
    assert len(doc.tables) == blank_table_count
    assert len(doc.inline_shapes) == blank_inline_count


def test_ac8_no_op_when_deliverable_kind_explicit_stage25(chart_pngs) -> None:
    """Defensive coverage for callers that explicitly set
    ``deliverable_kind="stage25_final_report"`` rather than relying on
    the absence-default. Same byte-identity outcome."""
    composed = _make_stage3_composed(chart_pngs)
    composed["deliverable_kind"] = "stage25_final_report"

    doc = Document()
    _add_criticality_appendix(doc, composed)

    headings = _extract_headings(doc)
    assert headings == [], (
        f"Expected no headings on Stage 2.5 path; got {headings}"
    )
    assert len(doc.inline_shapes) == 0


def test_ac8_no_op_when_chart_paths_all_empty(chart_pngs) -> None:
    """Existence-guard belt-and-braces: even when deliverable_kind is
    ``stage3_standalone``, if all four chart paths are empty strings
    the appendix short-circuits (callers that build the dict without
    chart rendering shouldn't emit a section with empty image frames)."""
    composed = _make_stage3_composed(chart_pngs)
    p4b = composed["page4b_criticality"]
    for k in (
        "ci_distribution_chart_path",
        "chart1_sorted_top30_path",
        "chart3_risk_to_cp_linkage_path",
        "chart4_float_histogram_path",
    ):
        p4b[k] = ""

    doc = Document()
    _add_criticality_appendix(doc, composed)
    headings = _extract_headings(doc)
    assert headings == [], (
        f"Expected no headings with all chart paths empty; got {headings}"
    )


# ---------------------------------------------------------------------------
# AC9 — zero "Stage 2.5" references in rendered text.
# ---------------------------------------------------------------------------


def test_ac9_zero_stage25_references_in_appendix_text(chart_pngs) -> None:
    composed = _make_stage3_composed(chart_pngs)
    doc = Document()
    _add_criticality_appendix(doc, composed)
    body_text = "\n".join(p.text for p in doc.paragraphs)
    table_text = "\n".join(
        cell.text for t in doc.tables for row in t.rows for cell in row.cells
    )
    full = (body_text + "\n" + table_text).lower()
    assert "stage 2.5" not in full
    assert "stage2.5" not in full
    # Defensive: also no orphan references to the deprecated sibling
    # deliverable filename pattern (which would suggest the appendix
    # was wired to the deprecated note).
    assert "sra_criticality_note_prod" not in full


# ---------------------------------------------------------------------------
# Smoke — appendix renders together with the rest of an executive
# summary docx (downstream wiring sanity).
# ---------------------------------------------------------------------------


def test_appendix_call_site_does_not_break_downstream(chart_pngs) -> None:
    """The new call site inside ``_render_v3_executive_summary`` sits
    immediately before the existing risk-matrix appendix block. This
    test confirms the helper doesn't leak page-break state or otherwise
    interact badly with a follow-on heading; it adds an H2 right after
    the appendix and confirms the H2 lands in the same document."""
    composed = _make_stage3_composed(chart_pngs)
    doc = Document()
    _add_criticality_appendix(doc, composed)
    # Simulate the risk-matrix heading that follows in the real call site.
    doc.add_heading(
        "Risk matrix - traditional vs probability-weighted (explanatory)",
        level=2,
    )
    h2s = [
        p.text for p in doc.paragraphs
        if getattr(p.style, "name", "") == "Heading 2"
    ]
    # Six H2 sub-headings from the appendix + one risk-matrix H2.
    assert len(h2s) == len(EXPECTED_H2_ORDER) + 1
    assert h2s[-1].startswith("Risk matrix")
