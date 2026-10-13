"""3c Part A A-5: one Stage 3 config construction, and it reads the project's own register.

Director decision 04/09/2026, option A. A-5 requires the deliverable on the wind binding to
reproduce the showcase headline **exactly**. Two hand-built configs that coincide today satisfy
that on the day they are written and silently stop the first time either is edited; one shared
construction satisfies it structurally. These tests hold the structure, not a number - the
number itself is held by the wind golden, which exercises this same path
(``tests/golden/golden_harness._adapter_wind`` calls ``run_wind_showcase.run_integrated``).

The showcase previously built its config by hand with a flat 0.5 CG map and the reference
project's ``build_test_methodology_defaults()``. Both were measured inert on the integrated
array before removal (record §3.1); the golden is what proves they stayed inert.
"""
from __future__ import annotations

import ast
from pathlib import Path

from src.integrated.stage3_config import (
    STAGE3_APPLY_MODE_MULTIPLIERS,
    STAGE3_CRITICALITY_MODE,
    build_stage3_config,
    stage3_config_summary,
)
from src.sra.methodology_defaults_reader import (
    read_calibration_tolerances,
    read_cg_coefficients,
    read_mode_multipliers,
)

REPO = Path(__file__).resolve().parents[1]
WIND_DIR = REPO / "tests" / "fixtures" / "synthetic_wind"
WIND_REGISTER = WIND_DIR / "wind_register.xlsx"
WIND_XER = WIND_DIR / "wind_schedule.xer"


def _wind_config(**kw):
    return build_stage3_config(
        register_path=WIND_REGISTER, xer_path=WIND_XER, strawman_path=WIND_REGISTER,
        caller_module="tests/test_3c_a_shared_stage3_config.py", **kw,
    )


def test_every_methodology_value_comes_from_the_register():
    """Not a code constant, and not another project's binding - this register's own values."""
    cfg = _wind_config(iterations=1000, seed=42)
    ic = cfg.integrated_config

    assert dict(cfg.schedule_mc_config.mode_multipliers) == read_mode_multipliers(WIND_REGISTER)
    assert dict(ic.cg_correlation_coefficients) == read_cg_coefficients(WIND_REGISTER)
    assert dict(ic.methodology_defaults.mode_multipliers) == read_mode_multipliers(WIND_REGISTER)
    assert dict(ic.methodology_defaults.cg_coefficients) == read_cg_coefficients(WIND_REGISTER)

    tolerances = read_calibration_tolerances(WIND_REGISTER)
    assert ic.cost_calibration_tolerance_dollars == tolerances["cost_calibration_tolerance_dollars"]
    assert ic.cost_calibration_tolerance_pct == tolerances["cost_calibration_tolerance_pct"]
    assert ic.schedule_calibration_tolerance_days == tolerances["schedule_calibration_tolerance_days"]
    assert ic.schedule_calibration_tolerance_pct == tolerances["schedule_calibration_tolerance_pct"]

    # the wind register's own run-config block, not a code default
    assert ic.day_rate == 35000.0
    assert ic.reporting_p_level == 80


def test_the_flat_cg_map_is_gone_and_the_registers_own_shape_is_used():
    """The showcase's hand-built config used {CG01..CG13: 0.5}; the register is not flat."""
    cfg = _wind_config(iterations=1000, seed=42)
    cg = dict(cfg.integrated_config.cg_correlation_coefficients)
    assert len(set(cg.values())) > 1, f"CG map is flat, so it is not the register's: {cg}"


def test_both_arms_share_iteration_count_and_seed():
    cfg = _wind_config(iterations=1234, seed=7)
    assert cfg.integrated_config.iterations == 1234
    assert cfg.schedule_mc_config.n_iter == 1234
    assert cfg.integrated_config.random_seed == 7
    assert cfg.schedule_mc_config.seed == 7


def test_the_stage3_production_basis_is_pinned_not_inherited():
    """WIND-01's defect was relying on ScheduleMCConfig's default, which is True."""
    cfg = _wind_config(iterations=1000, seed=42)
    assert STAGE3_APPLY_MODE_MULTIPLIERS is False
    assert cfg.schedule_mc_config.apply_mode_multipliers is False
    assert cfg.binding_config.apply_mode_multipliers is False
    assert cfg.criticality_measurement_mode == STAGE3_CRITICALITY_MODE == "mode_independent"


def test_iterations_and_day_rate_fall_back_to_the_register_when_not_overridden():
    cfg = _wind_config(seed=42)
    assert cfg.integrated_config.iterations == 50000  # wind MC_Params
    assert cfg.integrated_config.day_rate == 35000.0


def test_config_summary_carries_what_the_provenance_manifest_needs():
    summary = stage3_config_summary(_wind_config(iterations=1000, seed=42))
    for key in ("register_path", "xer_path", "iterations", "seed", "day_rate",
                "mode_multipliers", "cg_coefficients", "apply_mode_multipliers"):
        assert key in summary, key
    assert summary["iterations"] == 1000
    assert summary["seed"] == 42


def test_the_showcase_builds_its_config_here_and_nowhere_else():
    """A-5 structurally: the showcase must not hand-build an IntegratedConfigStage3 again.

    Parsed, not grepped, so a mention in a comment or docstring does not satisfy it.
    """
    source = (REPO / "scripts" / "run_wind_showcase.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "build_stage3_config" in called, (
        "the showcase no longer calls build_stage3_config; A-5's exact reproduction then "
        "rests on two configs coinciding rather than on one construction"
    )
    assert "IntegratedConfigStage3" not in called, (
        "the showcase hand-builds IntegratedConfigStage3 again - that is the second source "
        "for one number that option A exists to remove"
    )
