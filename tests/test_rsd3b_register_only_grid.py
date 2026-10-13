"""RS-D-3b (D-15, shape A): the register is the only source of the Mode multiplier grid.

Properties: ``src/`` names no multiplier constant; both engine configs require a grid and
refuse to be built without one; the schedule MC refuses to run without a config; the one
reader returns the register's grid for a grid-native register and raises for a workbook that
carries none; the test harness's fixture grid equals the wind register's grid and the
documented test factory's, so the three cannot drift apart silently.
"""
from __future__ import annotations

import re
from pathlib import Path

import openpyxl
import pytest

from tests.conftest import TEST_MODE_MULTIPLIERS

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
WIND_REGISTER = REPO / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"
OLD_NAME = re.compile(r"\bMODE_" + r"MULTIPLIERS\b")  # split so this file is not a hit


def test_src_names_no_multiplier_constant():
    hits = sorted(
        str(p.relative_to(REPO)) for p in SRC.rglob("*.py")
        if OLD_NAME.search(p.read_text(encoding="utf-8", errors="ignore"))
    )
    assert hits == [], hits


def test_sra_config_requires_a_grid():
    from src.sra.sra_config import SRAConfig

    with pytest.raises(TypeError):
        SRAConfig(register_path=Path("x"), p6_path=Path("x"), strawman_path=Path("x"), day_rate=1.0)  # type: ignore[call-arg]
    cfg = SRAConfig(register_path=Path("x"), p6_path=Path("x"), strawman_path=Path("x"),
                    day_rate=1.0, mode_multipliers=TEST_MODE_MULTIPLIERS)
    assert cfg.mode_multipliers == TEST_MODE_MULTIPLIERS


def test_schedule_mc_config_requires_a_grid_and_run_requires_a_config():
    from src.sra.cpm.cpm_simulation import ScheduleMCConfig, run_schedule_mc

    with pytest.raises(TypeError):
        ScheduleMCConfig()  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="non-empty"):
        ScheduleMCConfig(mode_multipliers={})
    with pytest.raises(ValueError, match="no default configuration"):
        run_schedule_mc(graph=None, risk_drivers={"x": object()}, config=None)  # type: ignore[arg-type]


def test_reader_returns_the_wind_register_grid_and_the_fixtures_agree():
    from src.sra.methodology_defaults_reader import (
        build_test_methodology_defaults,
        read_mode_multipliers,
    )

    from_register = read_mode_multipliers(WIND_REGISTER, caller_module="tests")
    assert from_register == TEST_MODE_MULTIPLIERS
    assert dict(build_test_methodology_defaults().mode_multipliers) == TEST_MODE_MULTIPLIERS


def test_reader_raises_for_a_workbook_without_a_grid(tmp_path):
    from src.sra.methodology_defaults_reader import MethodologyDefaultsError, read_mode_multipliers

    path = tmp_path / "no_grid.xlsx"
    openpyxl.Workbook().save(str(path))
    with pytest.raises(MethodologyDefaultsError, match="no Mode multiplier grid"):
        read_mode_multipliers(path, caller_module="tests")


def test_sra_loader_takes_the_grid_from_the_register(monkeypatch):
    """The production SRA loader reads the grid from REGISTER_FILE, not from code. The wind
    register serves as register and strawman here (it carries a run-config surface)."""
    from src.sra.sra_config import load_sra_config

    for var in ("REGISTER_FILE", "P6_FILE", "STRAWMAN_FILE"):
        monkeypatch.setenv(var, str(WIND_REGISTER))
    cfg = load_sra_config()
    assert cfg.mode_multipliers == TEST_MODE_MULTIPLIERS
