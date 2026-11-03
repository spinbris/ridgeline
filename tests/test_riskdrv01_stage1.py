"""RISKDRV-01 stage 1: the build start comes from the schedule, and shared drivers are read and
checked. (Stage 1's refusal of declared drivers retired at stage 2, which simulates them.)

Fast: no engine run, no subprocess. Each refusal is a named red case.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import replace
from pathlib import Path

import openpyxl
import pytest

from src.am.run_period import resolve_project_start
from src.shared_drivers import (
    COLUMNS,
    SHEET,
    SharedDriver,
    SharedDriverError,
    parse_shared_drivers,
    read_shared_drivers,
    validate_shared_drivers,
)
from src.sra.cpm.xer_reader import parse_xer, xer_project_start

REPO = Path(__file__).resolve().parents[1]
WIND = REPO / "tests" / "fixtures" / "synthetic_wind"
ROAD = REPO / "tests" / "fixtures" / "synthetic_road"
WIND_REGISTER = WIND / "wind_register.xlsx"
WIND_XER = WIND / "wind_schedule.xer"


# --- PROJSTART-01 ------------------------------------------------------------------------

@pytest.mark.parametrize("xer, start", [
    (WIND_XER, _dt.date(2025, 4, 28)),
    (ROAD / "road_schedule.xer", _dt.date(2026, 7, 6)),
])
def test_build_start_is_the_schedules_earliest_start(xer: Path, start: _dt.date) -> None:
    assert xer_project_start(parse_xer(xer)) == start


def test_no_flag_takes_the_schedules_start() -> None:
    assert resolve_project_start(parse_xer(WIND_XER), None) == _dt.date(2025, 4, 28)


def test_an_agreeing_flag_is_accepted() -> None:
    assert resolve_project_start(parse_xer(WIND_XER), _dt.date(2025, 4, 28)) == _dt.date(2025, 4, 28)


def test_a_disagreeing_flag_is_refused() -> None:
    # The old default: a wind run dated from it printed every finish about 16 months early.
    with pytest.raises(ValueError, match="PROJSTART-01"):
        resolve_project_start(parse_xer(WIND_XER), _dt.date(2024, 1, 1))


def test_a_schedule_without_dates_is_refused() -> None:
    tables = parse_xer(WIND_XER)
    tables["TASK"] = tables["TASK"].drop(columns=["early_start_date", "target_start_date"])
    with pytest.raises(ValueError, match="PROJSTART-01"):
        xer_project_start(tables)


def test_the_old_default_is_gone() -> None:
    import src.am.run_period as rp
    assert not hasattr(rp, "DEFAULT_PROJECT_START")


# --- Shared drivers: reading ---------------------------------------------------------------

_P = {"Driver_ID": "D1", "Name": "Civil productivity", "Kind": "P", "Tag": "civil_productivity",
      "P10": -0.05, "Mode": 0.0, "P90": 0.20, "WBS_Codes": "10, 20", "Grid_Rows": "BOP civils",
      "Grid_Columns": "Labour, Plant", "Ruled_Risks": "WT-003", "Basis": "practitioner judgment"}
_Q = {"Driver_ID": "D3", "Name": "Electrical and grid quantity", "Kind": "Q",
      "Linked_Factors": "Q_Elec", "Elasticity": 1.0, "WBS_Codes": "40",
      "Ruled_Risks": "WT-025", "Basis": "quantity drives duration"}


def _rows(*drivers: dict) -> list[tuple]:
    rows = [("Shared drivers - RISKDRV-01",), tuple(COLUMNS)]
    rows += [tuple(d.get(c) for c in COLUMNS) for d in drivers]
    rows.append(tuple(None for _ in COLUMNS))  # a blank row is skipped
    return rows


def test_parse_reads_by_header_name() -> None:
    p, q = parse_shared_drivers(_rows(_P, _Q))
    assert (p.kind, p.wbs_codes, p.grid_columns, p.p90) == ("P", ("10", "20"), ("Labour", "Plant"), 0.2)
    assert (q.kind, q.linked_factors, q.elasticity, q.p10) == ("Q", ("Q_Elec",), 1.0, None)


def test_parse_survives_moved_columns() -> None:
    cols = list(reversed(COLUMNS))
    rows = [tuple(cols), tuple(_P.get(c) for c in cols)]
    assert parse_shared_drivers(rows)[0].tag == "civil_productivity"


def test_parse_refuses_a_missing_column() -> None:
    rows = [tuple(c for c in COLUMNS if c != "Basis")]
    with pytest.raises(SharedDriverError, match="Basis"):
        parse_shared_drivers(rows)


def test_parse_refuses_a_non_number() -> None:
    with pytest.raises(SharedDriverError, match="P90"):
        parse_shared_drivers(_rows({**_P, "P90": "twenty"}))


def test_shipped_road_register_declares_none() -> None:
    # Plan R4: road stays driver-free in RISKDRV-01, which proves the off path on a second project.
    assert read_shared_drivers(ROAD / "road_register.xlsx") == ()


# --- Shared drivers: the checks ------------------------------------------------------------

@pytest.fixture(scope="module")
def ctx() -> dict:
    from src.v5_register_reader import read_layer1_v5
    tables = parse_xer(WIND_XER)
    wbs = tuple(str(c) for c in tables["PROJWBS"]["wbs_short_name"])
    wb = openpyxl.load_workbook(WIND_REGISTER, read_only=True, data_only=True)
    ids = tuple(str(r[0]) for r in wb["Risk Register"].iter_rows(values_only=True)
                if r and r[0] and str(r[0]).startswith("WT-"))
    wb.close()
    return {"layer1": read_layer1_v5(WIND_REGISTER), "wbs_codes": wbs, "risk_ids": ids}


def _good() -> tuple[SharedDriver, SharedDriver]:
    return parse_shared_drivers(_rows(_P, _Q))


def test_the_planned_shape_passes(ctx: dict) -> None:
    validate_shared_drivers(_good(), **ctx)


@pytest.mark.parametrize("change, message", [
    ({"kind": "X"}, "Kind"),
    ({"wbs_codes": ("99",)}, "not in the schedule"),
    ({"wbs_codes": ()}, "no WBS_Codes"),
    ({"p90": None}, "needs P10, Mode and P90"),
    ({"p10": 0.3}, "P10 <= Mode <= P90"),
    ({"p10": -1.0}, "zero or negative"),
    ({"tag": "labour_rate"}, "already a Layer 1 factor"),
    ({"tag": ""}, "needs a Tag"),
    ({"grid_rows": ("Nowhere",)}, "not in Layer1_Base"),
    ({"grid_columns": ()}, "Grid_Rows and Grid_Columns"),
    ({"elasticity": 1.0}, "Q drivers only"),
    ({"ruled_risks": ("WT-999",)}, "not in the register"),
    ({"basis": ""}, "no Basis"),
])
def test_p_driver_refusals(ctx: dict, change: dict, message: str) -> None:
    p, q = _good()
    with pytest.raises(SharedDriverError, match=message):
        validate_shared_drivers((replace(p, **change), q), **ctx)


@pytest.mark.parametrize("change, message", [
    ({"linked_factors": ()}, "exactly one Layer 1 factor"),
    ({"linked_factors": ("Q_Elec", "Q_Grid")}, "exactly one Layer 1 factor"),
    ({"linked_factors": ("Q_Nothing",)}, "not a Layer 1 factor"),
    ({"linked_factors": ("Duration",)}, "prices project time"),
    ({"elasticity": None}, "positive Elasticity"),
    ({"elasticity": 0.0}, "positive Elasticity"),
    ({"p90": 0.1}, "leave P10, Mode and P90 blank"),
    ({"grid_rows": ("BOP civils",)}, "adds no cost"),
])
def test_q_driver_refusals(ctx: dict, change: dict, message: str) -> None:
    p, q = _good()
    with pytest.raises(SharedDriverError, match=message):
        validate_shared_drivers((p, replace(q, **change)), **ctx)


def test_two_drivers_on_one_wbs_code_are_refused(ctx: dict) -> None:
    p, q = _good()
    with pytest.raises(SharedDriverError, match="already driven by D1"):
        validate_shared_drivers((p, replace(q, wbs_codes=("20",))), **ctx)


def test_duplicate_ids_are_refused(ctx: dict) -> None:
    p, q = _good()
    with pytest.raises(SharedDriverError, match="duplicate"):
        validate_shared_drivers((p, replace(q, driver_id="D1")), **ctx)


def test_drivers_need_layer1(ctx: dict) -> None:
    with pytest.raises(SharedDriverError, match="Layer 1 is off"):
        validate_shared_drivers(_good(), **{**ctx, "layer1": None})


def test_every_problem_is_named_at_once(ctx: dict) -> None:
    p, q = _good()
    with pytest.raises(SharedDriverError) as exc:
        validate_shared_drivers((replace(p, basis=""), replace(q, elasticity=None)), **ctx)
    assert "no Basis" in str(exc.value) and "positive Elasticity" in str(exc.value)
