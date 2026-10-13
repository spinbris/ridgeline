"""The guide's §7 artefact table and the files a run writes agree (REPORTDOC-01 P-5).

Here, in the stage lane: the table parses, its HTML row is the one ``RUN_FINAL.bat`` writes, the
executive-summary rows hold under each headline setting against the deliverable's own naming, and
the matcher is proven able to fail in each direction. The comparison of every row against a real
run lives beside the run that already exists for §6a's outputs -
``tests/test_3c_a_deliverable.py::test_the_sequence_produces_the_outputs_of_6a_and_no_pdf`` -
which is ``slow``, so **drift in the rest of the table is caught by the increment lane**, not the
stage lane.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.guide_artefacts import (
    HEADLINE_SETTINGS,
    Row,
    artefact_rows,
    disagreement,
    html_row_from_runner,
    pattern,
    written_files,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# Read in fixtures, never at import: a module-level read of docs/ kills collection of the whole
# session on a tree without docs/, which is what tests/test_goldcoll01_collection_guard.py
# builds - and it caught exactly that on this module's first increment lane (13/09/2026).
@pytest.fixture(scope="module")
def guide() -> str:
    return (REPO_ROOT / "docs" / "SOFTWARE_USER_GUIDE.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def bat() -> str:
    return (REPO_ROOT / "RUN_FINAL.bat").read_text(encoding="utf-8", errors="ignore")


def test_the_table_parses_into_one_row_per_artefact(guide: str) -> None:
    paths = [r.path for r in artefact_rows(guide)]
    assert len(paths) >= 10, f"§7's artefact table parsed to {len(paths)} rows: {paths}"
    assert len(set(paths)) == len(paths), "a row is listed twice"


def test_the_html_row_is_the_file_run_final_writes(guide: str, bat: str) -> None:
    assert html_row_from_runner(bat) in [r.path for r in artefact_rows(guide)]


def test_a_row_the_parser_cannot_read_fails_rather_than_dropping_out(guide: str) -> None:
    """Review WARN 5: a row rewritten with ``/`` separators used to leave the comparison silently."""
    live = "| `outputs\\runs\\<date>_<binding key>\\engine_log.txt` |"
    assert guide.count(live) == 1, "§7's engine log row no longer reads as this test expects"
    doctored = guide.replace(live, "| `outputs/runs/<date>_<binding key>/engine_log.txt` |")
    with pytest.raises(ValueError, match="engine_log"):
        artefact_rows(doctored)


@pytest.mark.parametrize("setting", HEADLINE_SETTINGS)
def test_the_executive_summary_rows_hold_under_each_headline_setting(setting, guide, tmp_path, monkeypatch):
    """Review WARN 4: the P80 row was stated unconditionally, a Mean-only run does not write it,
    and the real-run comparison only ever runs under ``both``.

    The naming here is the deliverable's own - ``resolve_inputs`` turns the setting into metrics
    and ``write_artefacts`` names one document per metric - with the engines, the Word renderer's
    body, the Stage 3 emitter and the cache stubbed out. The ``BETA_`` prefix is applied by the
    real helper; whether a production run carries it is the real-run comparison's to show.
    """
    import src.final.deliverable as deliverable
    import src.final.stage3_composer as stage3_composer
    import src.final.state_cache as state_cache
    import src.final.word_generator as word_generator
    import src.sra.cpm.bindings as bindings

    monkeypatch.setattr(deliverable, "assert_ready", lambda env: [])
    monkeypatch.setattr(bindings, "get_active_binding", lambda: SimpleNamespace(
        name="p", project_name="P", narrative=lambda key: None))
    inputs = deliverable.resolve_inputs(
        {"REGISTER_FILE": "r.xlsx", "P6_FILE": "s.xer", "STRAWMAN_FILE": "r.xlsx",
         "FINAL_REPORT_HEADLINE_METRIC": setting},
        output_dir=tmp_path)

    def word(*, output_path, **_):
        path = Path(word_generator._apply_beta_filename_prefix(output_path, True))
        path.write_bytes(b"")
        return {"output_path": str(path)}

    def no_stage3(**_):
        raise RuntimeError("the Stage 3 pair is not under test here")

    monkeypatch.setattr(word_generator, "generate_word_summary", word)
    monkeypatch.setattr(stage3_composer, "emit_stage3_standalone_artefacts", no_stage3)
    monkeypatch.setattr(state_cache, "write_state_cache", lambda *a, **k: None)
    monkeypatch.setattr(deliverable, "stage3_config_summary", lambda config: {})

    composed = {"run_date": "2026-09-13", "executive_summary": {},
                "appendix_audit_trail": {"engine_versions": {}}, "disclaimer_paragraphs": []}
    deliverable.write_artefacts(inputs, MagicMock(), composed, {"all_pass": True})

    rows = [r for r in artefact_rows(guide) if "executive_summary" in r.path]
    assert len(rows) == 2, rows
    found = disagreement(rows, written_files(tmp_path), set(), headline=setting)
    assert found == {"unnamed": [], "unwritten": [], "ambiguous": []}, (
        f"under --headline {setting}, §7's executive summary rows and the deliverable disagree: {found}")


# --- the matcher can fail, in each direction -------------------------------------------------

_ROWS = [
    Row("outputs\\BETA_executive_summary_<date>.docx", frozenset({"P80", "both"})),
    Row("outputs\\BETA_executive_summary_MEAN_<date>.docx", frozenset({"Mean", "both"})),
    Row("outputs\\runs\\<date>_<binding key>\\engine_log.txt", frozenset()),
    Row("outputs\\runs\\<date>_<binding key>\\<array>.parquet", frozenset()),
]
_FILES = [
    "BETA_executive_summary_2026-09-13.docx",
    "BETA_executive_summary_MEAN_2026-09-13.docx",
    "runs/2026-09-13_synthetic_wind/engine_log.txt",
    "runs/2026-09-13_synthetic_wind/composed.cost.parquet",
]
_CLEAN = {"unnamed": [], "unwritten": [], "ambiguous": []}


def test_the_matcher_agrees_with_itself_on_a_consistent_pair() -> None:
    assert disagreement(_ROWS, _FILES, set(), headline="both") == _CLEAN


def test_a_written_file_the_table_does_not_name_is_reported() -> None:
    rows = [r for r in _ROWS if "engine_log" not in r.path]
    assert disagreement(rows, _FILES, set(), headline="both")["unnamed"] == [
        "runs/2026-09-13_synthetic_wind/engine_log.txt"]


def test_a_row_no_run_writes_is_reported() -> None:
    invented = "outputs\\runs\\<date>_<binding key>\\invented.txt"
    rows = _ROWS + [Row(invented, frozenset())]
    assert disagreement(rows, _FILES, set(), headline="both")["unwritten"] == [invented]


def test_a_new_file_the_deliverable_starts_writing_is_reported() -> None:
    files = _FILES + ["runs/2026-09-13_synthetic_wind/new_artefact.txt"]
    assert disagreement(_ROWS, files, set(), headline="both")["unnamed"] == [
        "runs/2026-09-13_synthetic_wind/new_artefact.txt"]


def test_the_p80_row_is_not_satisfied_by_the_mean_file() -> None:
    """A wildcard ``<date>`` would match ``MEAN_2026-09-13`` and hide a missing P80 document."""
    assert not pattern("outputs\\BETA_executive_summary_<date>.docx").fullmatch(
        "BETA_executive_summary_MEAN_2026-09-13.docx")
    files = [f for f in _FILES if f != "BETA_executive_summary_2026-09-13.docx"]
    assert disagreement(_ROWS, files, set(), headline="both")["unwritten"] == [
        "outputs\\BETA_executive_summary_<date>.docx"]


def test_a_file_two_rows_both_match_is_reported() -> None:
    rows = _ROWS + [Row("outputs\\runs\\<date>_<binding key>\\<anything>.txt", frozenset())]
    assert disagreement(rows, _FILES, set(), headline="both")["ambiguous"]


def test_an_excluded_row_is_not_required_to_be_written() -> None:
    html = "outputs\\<project>_deliverable_<date>.html"
    rows = _ROWS + [Row(html, frozenset())]
    assert disagreement(rows, _FILES, {html}, headline="both")["unwritten"] == []


def test_a_conditional_row_is_required_only_under_its_settings() -> None:
    p80_only = [f for f in _FILES if "MEAN" not in f]
    assert disagreement(_ROWS, p80_only, set(), headline="P80") == _CLEAN
    assert disagreement(_ROWS, p80_only, set(), headline="Mean")["unwritten"] == [
        "outputs\\BETA_executive_summary_MEAN_<date>.docx"]
    assert disagreement(_ROWS, p80_only, set(), headline="Mean")["unnamed"] == [
        "BETA_executive_summary_2026-09-13.docx"]


def test_an_unconditional_row_is_required_under_every_setting() -> None:
    """The shape the review found: the P80 row with no condition, checked under Mean."""
    rows = [Row("outputs\\BETA_executive_summary_<date>.docx", frozenset()), _ROWS[1]]
    mean_only = ["BETA_executive_summary_MEAN_2026-09-13.docx"]
    assert disagreement(rows, mean_only, set(), headline="Mean")["unwritten"] == [
        "outputs\\BETA_executive_summary_<date>.docx"]


def test_an_unknown_headline_setting_is_refused() -> None:
    with pytest.raises(ValueError, match="headline setting"):
        disagreement(_ROWS, _FILES, set(), headline="p80")
