"""PUBLICFACE-01 P4: public copy carries no internal reference.

Two surfaces: the app's source strings (comments are not rendered, so they are stripped first) and
the strings in a period JSON a real run writes (values only; a contract field's NAME is not copy).
``queued_for_v1_1`` is a contract field and keeps its name; its value and its rendering are copy.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DASH = REPO / "dashboard"

#: What a public reader must not meet: a document number, a version plan, a sprint tag, an
#: internal sheet name, a queue.
INTERNAL = {
    "Doc <n>": re.compile(r"\bDoc \d"),
    "version <n>": re.compile(r"\bv\d+(?:\.\d+)*\b"),
    "SR<n>": re.compile(r"\bSR\d+"),
    "AM_ sheet": re.compile(r"\bAM_[A-Za-z]"),
    "queued": re.compile(r"queued", re.I),
    # The class, not the instance (gate 3 round 1, W1): a build or spec tag, a section sign, a
    # brief, a ticket id. A field NAME such as stage_brief is an identifier, not copy: the pattern
    # wants a space.
    "AM<nn> tag": re.compile(r"\bAM\d{2}"),
    "section sign": re.compile("§"),
    "stage brief": re.compile(r"stage brief", re.I),
    "ticket id": re.compile(r"\b(?:WIND|ROAD|MIT|RSK)-\d"),
}
CONTRACT_FIELD = "queued_for_v1_1"

_COMMENTS = re.compile(r"/\*.*?\*/|(?<![:\"'])//[^\n]*", re.S)


def internal_marks(text: str) -> dict[str, list[str]]:
    text = text.replace(CONTRACT_FIELD, "")
    hits = {name: rx.findall(text) for name, rx in INTERNAL.items()}
    return {name: found for name, found in hits.items() if found}


def _app_sources() -> list[Path]:
    roots = [DASH / "app", DASH / "components"]
    files = [p for r in roots for p in sorted(r.rglob("*.tsx"))]
    return files + sorted((DASH / "lib").glob("*.ts*"))


def test_the_scan_can_fail():
    """Plant each reference; the scan must name each, and must ignore the contract field."""
    planted = "Doc 3 v2.3 SR10.C AM_Milestones queued AM02.1 §4.B.2 stage brief WIND-1"
    assert set(internal_marks(planted)) == set(INTERNAL)
    assert internal_marks("audit.stage_brief") == {}
    assert internal_marks(f"{CONTRACT_FIELD}: z.string()") == {}
    assert internal_marks(_COMMENTS.sub("", "x {/* Doc 3 v2.3 */} // v1.1\ny")) == {}


@pytest.mark.parametrize("path", _app_sources(), ids=lambda p: p.relative_to(DASH).as_posix())
def test_no_app_string_names_an_internal_document_or_plan(path):
    found = internal_marks(_COMMENTS.sub("", path.read_text(encoding="utf-8")))
    assert found == {}, f"{path.relative_to(REPO).as_posix()} shows the public: {found}"


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


@pytest.mark.slow
def test_no_engine_string_in_a_period_json_names_an_internal_document_or_plan(tmp_path):
    from src.am.run_period import run_period

    workbook = REPO / "status_periods" / "wind_period_01.xlsx"
    if not workbook.is_file():
        pytest.skip("status_periods/wind_period_01.xlsx is not in this tree")
    out = run_period(
        workbook_path=workbook, output_dir=tmp_path, allow_dirty=True, project="synthetic_wind",
        main_iterations=300, days_at_risk_iterations=100, counterfactual_iterations=100,
        seed=42, criticality_measurement_mode="both", project_start=_dt.date(2024, 1, 1))
    doc = json.loads(Path(out).read_text(encoding="utf-8"))
    found = {s[:80]: m for s in _strings(doc) if (m := internal_marks(s))}
    assert found == {}, f"the period JSON a reader sees carries: {found}"
    assert doc["audit"]["methodology_notes"], "the scan read no notes"
    assert any(CONTRACT_FIELD in n for n in doc["audit"]["methodology_notes"]), (
        "the contract field the app reads is gone")
