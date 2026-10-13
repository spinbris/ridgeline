"""CONFIGTRUTH-01 P3 (register item 2): a zero is refused as a zero, and the pre-flight tests presence.

The pre-flight tested ``bool(run_cfg.get(key))``, so a zero iteration count or P-level was reported as
"absent from the run config", and the register's count was checked even when ``SR9_ITERATIONS``
overrides it. ``build_stage3_config`` tested ``is not None``, so a zero reached the engines.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import openpyxl
import pytest

from src.final.deliverable_preflight import check_register_settings, run_preflight
from src.integrated.stage3_config import build_stage3_config
from src.sra.methodology_defaults_reader import MethodologyDefaultsError

REPO = Path(__file__).resolve().parents[1]
WIND_DIR = REPO / "tests" / "fixtures" / "synthetic_wind"
WIND_REGISTER = WIND_DIR / "wind_register.xlsx"
WIND_XER = WIND_DIR / "wind_schedule.xer"

ITERATIONS_ROW = "Iterations (n)"
P_LEVEL_ROW = "Reporting P-Level (pct)"
CHECK = {ITERATIONS_ROW: "iterations", P_LEVEL_ROW: "reporting P-level"}


def _register_with(tmp_path: Path, label: str, value) -> Path:
    register = tmp_path / "wind_register.xlsx"
    shutil.copy(WIND_REGISTER, register)
    wb = openpyxl.load_workbook(register)
    for row in wb["MC_Params"].iter_rows():
        if row[1].value == label:
            row[2].value = value
            break
    else:
        raise AssertionError(f"the wind fixture no longer carries a {label!r} row - update this test")
    wb.save(register)
    wb.close()
    return register


# --- P3a: the deliverable's pre-flight (does not reach the period run) ---------------------------

@pytest.mark.parametrize("label", [ITERATIONS_ROW, P_LEVEL_ROW])
@pytest.mark.parametrize("value, word", [(0, "zero"), (-5, "negative")])
def test_the_preflight_names_a_zero_or_negative_as_such_not_as_absent(label, value, word, tmp_path):
    register = _register_with(tmp_path, label, value)
    result = {r.label: r for r in check_register_settings(register, register)}[CHECK[label]]
    assert not result.ok, result
    assert word in result.detail and "absent" not in result.detail, result.detail


@pytest.mark.parametrize("value", [0, None])
def test_the_registers_iteration_count_is_not_checked_when_sr9_iterations_overrides_it(value, tmp_path):
    register = _register_with(tmp_path, ITERATIONS_ROW, value)
    env = {"QRA_PROJECT": "synthetic_wind", "REGISTER_FILE": str(register),
           "P6_FILE": str(WIND_XER), "STRAWMAN_FILE": str(register), "SR9_ITERATIONS": "5000"}
    import src.sra.cpm.bindings.synthetic_wind  # noqa: F401  self-registers
    result = {r.label: r for r in run_preflight(env)}["iterations"]
    assert result.ok and "SR9_ITERATIONS" in result.detail, result


# --- P3b: the shared builder, which the period run also reaches (held with point A) --------------

@pytest.mark.parametrize("label", [ITERATIONS_ROW, P_LEVEL_ROW])
def test_the_builder_refuses_a_zero_saying_it_is_zero(label, tmp_path):
    register = _register_with(tmp_path, label, 0)
    with pytest.raises(MethodologyDefaultsError, match="zero"):
        build_stage3_config(register_path=register, xer_path=WIND_XER, strawman_path=register,
                            project="synthetic_wind", caller_module="test_configtruth01")


# --- gate 3 round 1: the caller's override, and a cell that is not a whole number ----------------

@pytest.mark.parametrize("value, word", [(0, "zero"), (-500, "negative")])
def test_the_builder_refuses_a_zero_or_negative_iteration_override(value, word):
    """WARN 4: the period run passes ``iterations=`` straight into the builder, past any pre-flight."""
    with pytest.raises(MethodologyDefaultsError, match=word):
        build_stage3_config(register_path=WIND_REGISTER, xer_path=WIND_XER, strawman_path=WIND_REGISTER,
                            project="synthetic_wind", iterations=value, caller_module="test_configtruth01")


@pytest.mark.parametrize("label", [ITERATIONS_ROW, P_LEVEL_ROW])
@pytest.mark.parametrize("value", ["abc", 2.5, 80.5, 49999.9, True])
def test_a_cell_that_is_not_a_whole_number_is_refused_by_name(label, value, tmp_path):
    """WARN 5 and the numerics WARN: a non-numeric cell surfaced as a bare ValueError, a fraction was
    truncated without a word, and a TRUE cell counted as 1."""
    register = _register_with(tmp_path, label, value)
    with pytest.raises(MethodologyDefaultsError) as exc:
        build_stage3_config(register_path=register, xer_path=WIND_XER, strawman_path=register,
                            project="synthetic_wind", caller_module="test_configtruth01")
    message = str(exc.value)
    assert label in message and "MC_Params" in message and repr(value) in message, message
    result = {r.label: r for r in check_register_settings(register, register)}[CHECK[label]]
    assert not result.ok and repr(value) in result.detail, result


# --- gate 3 round 2, WARN-6: the positive control for the whole-number refusal ------------------

@pytest.mark.parametrize("key, raw, expected", [
    ("iterations", 50000.0, 50000), ("iterations", "50000", 50000),
    ("p_level_reporting", 80.0, 80), ("p_level_reporting", " 80 ", 80),
])
def test_an_integral_float_or_a_digit_string_resolves_to_the_whole_number(key, raw, expected):
    """A refusal that also refused every float would pass the tests above and break a real register.

    Called on the contract with the exact types, not through a saved workbook: openpyxl writes 50000.0
    as "50000" and reads it back as an int, so a workbook round trip never reaches the float branch.
    """
    from pathlib import Path as _Path

    from src.integrated.run_config_contract import SOURCE_REGISTER, resolve_run_setting

    value, source = resolve_run_setting({key: raw, "run_config_sheet": "MC_Params"}, key,
                                        strawman_path=_Path("register.xlsx"), project="synthetic_wind")
    assert (value, type(value), source) == (expected, int, SOURCE_REGISTER)
