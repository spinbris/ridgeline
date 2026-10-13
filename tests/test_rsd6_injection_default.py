"""RS-D-6 (D-18): the default injection method is a register value; no code default survives.

Properties: the two code defaults are gone (the binding constant and the auto-mapper config
field); the register's Methodology sheet carries ``Default_Injection_Method`` and the reader
returns it; a binding that pins nothing resolves to the register's value; the Mapping sheet's
``Injection_Method`` column reaches the scope frame; the grid parser refuses a duplicate row
and ignores an unknown label instead of absorbing it (GRIDPARSE-01).

Written red-first: on the pre-RS-D-6 tree the constant and the field exist and the reader
does not.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

REPO = Path(__file__).resolve().parents[1]
WIND_REGISTER = REPO / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"


def test_no_code_default_for_the_injection_method():
    import src.integrated.stage3_inputs as stage3_inputs
    from src.sra.cpm.risk_driver_schema import AutoMapperConfig

    assert "default_injection_method" not in AutoMapperConfig.__dataclass_fields__
    field = stage3_inputs.Stage3BindingConfig.__dataclass_fields__["default_injection_method"]
    assert field.default is None


def test_reader_returns_the_wind_register_default():
    from src.sra.methodology_defaults_reader import read_default_injection_method

    assert read_default_injection_method(WIND_REGISTER, caller_module="tests") == "discrete_event_additive_days"


def test_reader_raises_for_a_workbook_without_a_default(tmp_path):
    from src.sra.methodology_defaults_reader import MethodologyDefaultsError, read_default_injection_method

    path = tmp_path / "no_default.xlsx"
    openpyxl.Workbook().save(str(path))
    with pytest.raises(MethodologyDefaultsError, match="no default injection method"):
        read_default_injection_method(path, caller_module="tests")


def test_the_config_resolves_to_the_register_unless_pinned():
    from src.integrated.stage3_inputs import (
        Stage3BindingConfig,
        resolve_default_injection_method,
    )

    def _cfg(**kwargs):
        return Stage3BindingConfig(
            register_path=WIND_REGISTER, xer_path=WIND_REGISTER, strawman_path=WIND_REGISTER,
            float_threshold_hours=480.0, **kwargs)

    assert resolve_default_injection_method(_cfg()) == "discrete_event_additive_days"
    pinned = _cfg(default_injection_method="additive_pert_days")
    assert resolve_default_injection_method(pinned) == "additive_pert_days"


def test_mapping_sheet_injection_method_reaches_the_scope_frame():
    from src.sra.strawman_reader import _MAPPING_HEADERS, read_risk_scope

    assert "injection_method" in _MAPPING_HEADERS
    scope = read_risk_scope(str(WIND_REGISTER))
    assert "injection_method" in scope.columns  # blank on every wind row: the register's default applies


def test_grid_parser_refuses_duplicates_and_ignores_unknown_labels():
    from src.qra_register_parse import RegisterReadError, resolve_methodology_from_grid

    base = [["CG01", 0.5], ["Series", 1.0], ["Hybrid", 0.5], ["Parallel", 0.0]]
    out = resolve_methodology_from_grid(base + [["Some_Other_Number", 42.0]], source="t")
    assert "Some_Other_Number" not in out["mode_multipliers"] and "Some_Other_Number" not in out["cg_coefficients"]
    with pytest.raises(RegisterReadError, match="more than once"):
        resolve_methodology_from_grid(base + [["Hybrid", 0.9]], source="t")
    full = resolve_methodology_from_grid(
        base + [["Schedule_Calibration_Tolerance_Days", 1.0], ["Schedule_Calibration_Tolerance_Pct", 0.05],
                ["Cost_Calibration_Tolerance_Dollars", 50000.0], ["Cost_Calibration_Tolerance_Pct", 0.001],
                ["Default_Injection_Method", "discrete_event_additive_days"]], source="t")
    assert full["calibration_tolerances"]["schedule_calibration_tolerance_pct"] == 0.05
    assert full["default_injection_method"] == "discrete_event_additive_days"
    with pytest.raises(RegisterReadError, match="not one of"):
        resolve_methodology_from_grid(base + [["Default_Injection_Method", "broadcast"]], source="t")


def test_parser_and_schema_agree_on_the_method_names():
    """The shared core keeps its own copy of the three names for Pyodide-cleanliness; this
    pins the two copies to each other (review NOTE)."""
    from src.qra_register_parse import _INJECTION_METHOD_NAMES
    from src.sra.cpm.risk_driver_schema import INJECTION_METHODS

    assert tuple(_INJECTION_METHOD_NAMES) == tuple(INJECTION_METHODS)
