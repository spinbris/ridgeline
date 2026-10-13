"""SRA-02 S-C2 - Mapping.Gating_Activity_ID gets a reader.

Before this stage the column was written by the scaffolder
(``tools/register_scaffold.py:182-183``) and read by nothing:
``strawman_reader._MAPPING_HEADERS`` declared four fields and excluded it, so
``_read_mapping_sheet`` never returned it and the join never set it. The engine
looked for gating on the ``Risk Register`` sheet instead
(``_SCOPE_HEADERS:307``), where the scaffolder emits no such header, so every
risk on a consolidated register resolved ``gating_activity_id`` to ``None``.

These tests pin the reader half only. Scope is ``strawman_reader.py``'s Mapping
path; whether any consumer acts on the value is a separate question and is
reported in the S-C2 close-out rather than changed here.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import openpyxl
import pytest

from src.sra.strawman_reader import (
    _MAPPING_HEADERS,
    _read_mapping_sheet,
    read_risk_scope,
)

REPO = Path(__file__).resolve().parents[1]
WIND_REGISTER = REPO / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"

#: A4.4's blast-radius table, re-measured from the fixture at S-C2 start rather
#: than carried from the brief. Risk -> (Prefix_List, Gating_Activity_ID).
#: These five carry a gate that differs from their prefix; the other five mapped
#: risks name a gate identical to their prefix and are inert by construction.
_DIVERGENT = {
    "WT-001": ("20.A", "20.G.001"),
    "WT-008": ("30.A", "30.G.001"),
    "WT-020": ("40.C", "40.G.001"),
    "WT-031": ("60.A", "60.G.001"),
    "WT-032": ("60.B", "60.G.002"),
}

#: All ten risks carrying a Mapping row. The five above plus the five whose
#: gate equals their prefix - both groups are "mapped" for the fabrication check.
_MAPPED_IDS = frozenset(_DIVERGENT) | {
    "WT-002", "WT-009", "WT-021", "WT-026", "WT-027",
}


@pytest.fixture(autouse=True)
def _wind_binding(monkeypatch):
    """Select the synthetic_wind binding for every test in this module.

    Function-scoped and monkeypatch-based deliberately, following the convention
    tests/conftest.py:33 names: conftest installs a FUNCTION-scoped autouse
    fixture that forces QRA_PROJECT="refproject" before each test, so a
    module-scoped fixture is overridden by it and has no effect. My first attempt
    used module scope and the consolidated frame came back EMPTY - every row
    filtered out by active_risk_id_prefix() resolving to "R" instead of "WT".

    Worth recording rather than quietly fixing: a gating assertion evaluated over
    an empty frame is a vacuous pass. The only reason this surfaced as a failure
    instead of a green run is the ``len(unmapped) > 0`` guard below, which exists
    for exactly that reason.
    """
    spec = importlib.util.spec_from_file_location(
        "wind_binding_sc2", WIND_REGISTER.parent / "wind_binding.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # self-registers 'synthetic_wind'
    monkeypatch.setenv("QRA_PROJECT", "synthetic_wind")


@pytest.fixture(scope="module")
def mapping_raw() -> dict:
    wb = openpyxl.load_workbook(str(WIND_REGISTER), data_only=True)
    try:
        return _read_mapping_sheet(wb)
    finally:
        wb.close()


def test_gating_is_a_declared_mapping_field():
    """The contract-level statement. Without this the column has no reader at
    all, which was the S-A finding."""
    assert "gating_activity_id" in _MAPPING_HEADERS
    # Underscored spelling first, matching the scaffolder's emitted header.
    assert _MAPPING_HEADERS["gating_activity_id"][0] == "Gating_Activity_ID"


def test_read_mapping_sheet_surfaces_gating(mapping_raw):
    """``_read_mapping_sheet`` returns the value rather than dropping it."""
    assert mapping_raw, "no mapped risks read from the fixture"
    for rid in _DIVERGENT:
        assert rid in mapping_raw, rid
        assert "gating_activity_id" in mapping_raw[rid], rid


def test_gating_values_match_the_fixture(mapping_raw):
    """Read faithfully, not fabricated: every divergent risk's gate is the one
    the workbook carries."""
    for rid, (prefix, gate) in _DIVERGENT.items():
        assert mapping_raw[rid]["prefix_list"] == prefix, rid
        assert mapping_raw[rid]["gating_activity_id"] == gate, rid


def test_gating_reaches_the_scope_frame_on_the_consolidated_path():
    """The join, end to end. ``read_risk_scope`` takes the consolidated branch
    for this register (no ``Risk_Scope`` sheet) and must carry gating through to
    the frame the engine reads."""
    df = read_risk_scope(str(WIND_REGISTER))
    assert "gating_activity_id" in df.columns
    by_id = df.set_index("risk_id")["gating_activity_id"].to_dict()
    for rid, (_prefix, gate) in _DIVERGENT.items():
        assert by_id.get(rid) == gate, (
            f"{rid}: scope frame carries {by_id.get(rid)!r}, fixture says {gate!r}"
        )


def test_reader_discriminates_mapped_from_unmapped_rather_than_fabricating():
    """Fail-closed direction check, made falsifiable in BOTH directions.

    Two properties in one assertion pair, because either alone is a weak gate:

    * a risk WITH a Mapping row carries its gate - fails before the reader change
      (everything is None), and
    * a risk WITHOUT one reads None, never an empty string and never a guessed
      value derived from its prefix - fails against an implementation that
      defaults unmapped rows instead of leaving them absent.

    Written this way after the first draft asserted only the second limb and
    therefore passed before the change as well as after: it could not fail on the
    property it was cited for, which is the shape this programme keeps finding.
    """
    df = read_risk_scope(str(WIND_REGISTER))
    by_id = df.set_index("risk_id")["gating_activity_id"].to_dict()

    mapped = {rid: by_id.get(rid) for rid in _DIVERGENT}
    assert all(v is not None for v in mapped.values()), (
        f"mapped risks lost their gate: {mapped}"
    )

    unmapped_ids = [r for r in by_id if r not in _MAPPED_IDS]
    assert unmapped_ids, "fixture has no unmapped risks to check"
    for rid in unmapped_ids:
        assert by_id[rid] is None, (
            f"{rid} has no Mapping row but reads gating {by_id[rid]!r} - "
            "the reader is fabricating a value rather than leaving it absent"
        )
