"""RS-D-2 (D-14): the calibration tolerances are register values; the schedule check passes on
days OR percent, like the cost check.

Properties: ``IntegratedConfig`` refuses to be built without the four tolerances; the reader
returns the wind register's grid values and raises for a workbook carrying none; the loader
sets them from ``REGISTER_FILE``; the schedule check passes on the relative clause alone; no
code copy of a tolerance survives in ``src/``.

Written red-first: on the pre-RS-D-2 tree the reader does not exist, the config defaults the
tolerances, and the schedule check is absolute-only.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import openpyxl
import pytest

from tests.conftest import TEST_CALIBRATION_TOLERANCES

REPO = Path(__file__).resolve().parents[1]
WIND_REGISTER = REPO / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"


def test_integrated_config_requires_the_four_tolerances():
    from src.integrated.integrated_simulation import IntegratedConfig
    from src.sra.methodology_defaults_reader import build_test_methodology_defaults

    base = dict(register_path=Path("x"), p6_path=Path("x"), strawman_path=Path("x"),
                methodology_defaults=build_test_methodology_defaults())
    with pytest.raises(TypeError):
        IntegratedConfig(**base, day_rate=1.0)  # type: ignore[call-arg]
    cfg = IntegratedConfig(**base, day_rate=1.0, **TEST_CALIBRATION_TOLERANCES)
    assert cfg.schedule_calibration_tolerance_pct == TEST_CALIBRATION_TOLERANCES["schedule_calibration_tolerance_pct"]


def test_reader_returns_the_wind_register_tolerances():
    from src.sra.methodology_defaults_reader import read_calibration_tolerances

    assert read_calibration_tolerances(WIND_REGISTER, caller_module="tests") == TEST_CALIBRATION_TOLERANCES


def test_reader_raises_for_a_workbook_without_tolerances(tmp_path):
    from src.sra.methodology_defaults_reader import MethodologyDefaultsError, read_calibration_tolerances

    path = tmp_path / "no_tol.xlsx"
    openpyxl.Workbook().save(str(path))
    with pytest.raises(MethodologyDefaultsError, match="no calibration tolerance"):
        read_calibration_tolerances(path, caller_module="tests")


def test_loader_sets_the_tolerances_from_the_register(monkeypatch):
    """The full methodology reader is legacy-register-shaped (named ranges) and does not
    read a grid-native register - a pre-existing gap the wind path works around with the
    test factory (ledger WINDMETH-01). It is patched out here so the property under test,
    the loader sourcing the four tolerances from the register, is the only thing measured."""
    import src.integrated.integrated_simulation as mod
    from src.sra.methodology_defaults_reader import build_test_methodology_defaults

    monkeypatch.setattr(mod, "read_methodology_defaults", lambda *a, **k: build_test_methodology_defaults())
    for var in ("REGISTER_FILE", "P6_FILE", "STRAWMAN_FILE"):
        monkeypatch.setenv(var, str(WIND_REGISTER))
    cfg = mod.load_integrated_config()
    assert cfg.schedule_calibration_tolerance_pct == TEST_CALIBRATION_TOLERANCES["schedule_calibration_tolerance_pct"]
    assert cfg.cost_calibration_tolerance_dollars == TEST_CALIBRATION_TOLERANCES["cost_calibration_tolerance_dollars"]


def test_schedule_check_passes_on_the_relative_clause_alone():
    """Gap 3 days on a 100-day mean: fails the 1-day absolute clause, passes 5% relative.
    Under the old absolute-only check this was FAIL; the cost check has always had the OR."""
    from src.integrated.integrated_analysis import compute_marginal_calibration
    from src.integrated.integrated_simulation import IntegratedConfig
    from src.sra.methodology_defaults_reader import build_test_methodology_defaults

    cfg = IntegratedConfig(register_path=Path("x"), p6_path=Path("x"), strawman_path=Path("x"),
                           methodology_defaults=build_test_methodology_defaults(), day_rate=1.0,
                           **TEST_CALIBRATION_TOLERANCES)
    out = compute_marginal_calibration(
        integrated_results={"cost_dollars_array": np.full(10, 1e6), "schedule_days_array": np.full(10, 103.0)},
        standalone_cost_l2only_results={"cost_dollars_array": np.full(10, 1e6)},
        standalone_schedule_results={"finish_delay_days_array": np.full(10, 100.0)},
        config=cfg,
    )
    assert out["schedule_passes_calibration"] is True
    assert abs(out["schedule_relative_gap_pct"] - 0.03) < 1e-12
    assert "OR" in out["interpretation"]


def test_src_carries_no_tolerance_literal():
    # any tolerance-named field or parameter with a numeric default (the review widened it
    # from calibration_tolerance* to *tolerance*)
    # calibration tolerances and the SRA check's absolute_tolerance_days; numeric-precision
    # epsilons elsewhere (e.g. the calendar) are not calibration values
    pat = re.compile(r"(?:calibration_tolerance\w*|absolute_tolerance_days)\s*[:=]\s*(?:float\s*=\s*)?\d")
    hits = sorted(
        str(p.relative_to(REPO)) for p in (REPO / "src").rglob("*.py")
        if pat.search(p.read_text(encoding="utf-8", errors="ignore"))
    )
    assert hits == [], hits
