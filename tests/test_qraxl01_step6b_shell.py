"""QRAXL-01 step 6b - xlwings Tier-1 shell gates (aux resolution + headless run).

- extended read-parity: the shared resolver's cg_coefficients / dual_lookup /
  chain_risk_ids / chain_config deep-equal Tier-2's on the wind register (dual_lookup
  vs the authoritative `_resolve_modes`; cg vs methodology_defaults; constants locked).
- headless run == engine: run_headless (all inputs resolved from grids) reproduces
  the Tier-2 run_integrated_simulation cost arrays raw == in CPython, Layer 1 OFF and
  ON (write-back verification: the output arrays match the engine).
- convergence note: the 25k default carries a P80 CI half-width (bootstrap).
- rho-triple monotone; cores stay import-clean; full-input cross-runtime rtol 1e-12
  (slow, node + Pyodide 314.0.1).

The CPython QRAXL-01.0 client gate stays raw == (untouched); the fixture regenerates
bit-safe (covered by the existing bit-identity + step-5 lossless gates).
"""
from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES
from tests.conftest import TEST_MODE_MULTIPLIERS

import subprocess
import sys
import textwrap
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from src.config import ChainConfig
from src.qra_register_parse import (
    resolve_aux_from_grid,
    resolve_methodology_from_grid,
)
from src.tier1_headless import extract_grids_openpyxl, run_headless_from_workbook

from tests._fixture_values import FIXTURE_DAY_RATE
REPO = Path(__file__).resolve().parents[1]
WIND = REPO / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"


# ---------------------------------------------------------------------------
# xlwings Lite used_range fix (step 6b defect): the Tier-1 shell reads each grid
# sheet via a Grid_* NAMED RANGE (Lite does not implement sheet.used_range). The
# shell's xlwings read cannot be exercised headless, so this is the CI proxy:
# every Grid_* range must cover EXACTLY the openpyxl row-1 grid the parser
# consumes (row-1-aligned, no truncation at the V5 layout's interior blanks).
# ---------------------------------------------------------------------------

def _read_named_grid(wb, name: str) -> list:
    grid: list = []
    dn = wb.defined_names[name]
    for title, coord in dn.destinations:
        for row in wb[title][coord]:
            grid.append([c.value for c in row])
    return grid


def test_grid_named_ranges_cover_exact_openpyxl_grid() -> None:
    import openpyxl
    grids = extract_grids_openpyxl(WIND)
    wb = openpyxl.load_workbook(WIND, data_only=True)
    try:
        assert "Grid_RiskRegister" in wb.defined_names, (
            "wind register missing Grid_* named ranges - regenerate the fixture "
            "(scripts/build_synthetic_wind_fixture.py) after the used_range fix"
        )
        assert _read_named_grid(wb, "Grid_RiskRegister") == grids["risk_register"]
        for sheet in ("Layer1_Base", "Layer1_Factors", "Layer1_Allocation", "Layer1_Correlation"):
            assert _read_named_grid(wb, f"Grid_{sheet}") == grids["layer1"][sheet], sheet
        # GD-B: the methodology grid is exposed via Grid_Methodology, row-1-aligned.
        assert "Grid_Methodology" in wb.defined_names
        assert _read_named_grid(wb, "Grid_Methodology") == grids["methodology"]
    finally:
        wb.close()


def test_shell_has_no_forbidden_lite_api() -> None:
    # Guard: the Tier-1 shell must not use Lite-unsupported Sheet APIs (this
    # class of defect only surfaces in Excel, never headless).
    shell = (REPO / "src" / "tier1_xlwings_shell.py").read_text(encoding="utf-8")
    # strip the FORBIDDEN doc block so we only scan live code
    live = shell.split("FORBIDDEN in Lite")[0] + shell.split("_GRID_NAMES: dict")[-1]
    assert ".used_range" not in live
    assert ".api" not in live
    assert ".copy()" not in live


@pytest.fixture
def _wind_binding():
    # FUNCTION-scoped so it runs AFTER the conftest refproject autouse (GD-0) and
    # overrides it for this module's tests. Activating the wind binding sets
    # QRA_PROJECT=synthetic_wind (risk-id prefix "WT"); save/restore so it
    # never leaks to a later test. _activate_wind_binding re-exec's the binding
    # module, which registers with overwrite=True (idempotent per call).
    import os
    import scripts.run_wind_showcase as wind
    saved = os.environ.get("QRA_PROJECT")
    wind._activate_wind_binding()
    try:
        yield wind
    finally:
        if saved is None:
            os.environ.pop("QRA_PROJECT", None)
        else:
            os.environ["QRA_PROJECT"] = saved


# --- GD-B: methodology READ FROM THE REGISTER GRID, parity vs the engine ----

def test_methodology_grid_parity(_wind_binding) -> None:
    # GD-B / Decision 1: the register's own "Methodology" grid must deep-equal the
    # methodology the Tier-2 integrated cost arm uses - CG coefficients from
    # build_test_methodology_defaults() and mode multipliers from the engine's
    # sra_config. This is what makes the grid read (no hardcoded constant) safe:
    # if the fixture's methodology block drifts from the engine, this fails.
    from tests._fixture_values import FIXTURE_DAY_RATE
    from tests.conftest import TEST_MODE_MULTIPLIERS as ENG_MM
    from src.sra.methodology_defaults_reader import build_test_methodology_defaults

    meth = resolve_methodology_from_grid(extract_grids_openpyxl(WIND)["methodology"])
    assert meth["cg_coefficients"] == build_test_methodology_defaults().cg_coefficients
    assert meth["mode_multipliers"] == ENG_MM


def test_methodology_grid_absent_fails_loud() -> None:
    # No fallback to a cross-project constant: an absent/empty methodology grid
    # raises rather than silently applying RefProject's CG dict (the no-defaults
    # directive, Coupling B).
    from src.qra_register_parse import RegisterReadError
    with pytest.raises(RegisterReadError):
        resolve_methodology_from_grid([])


# --- extended read-parity: resolver aux == Tier-2's ------------------------

def test_extended_read_parity_aux(_wind_binding) -> None:
    from src.integrated.integrated_simulation import _resolve_modes, _default_chain_risk_ids
    from src.sra.strawman_reader import read_risk_scope

    grids = extract_grids_openpyxl(WIND)
    aux = resolve_aux_from_grid(grids["risk_register"], grids["methodology"], "WT")
    # dual_lookup vs the authoritative Tier-2 resolver (_resolve_modes)
    assert aux["dual_lookup"] == _resolve_modes(read_risk_scope(str(WIND)), None, mode_multipliers=TEST_MODE_MULTIPLIERS)
    # cg (now read from the register grid) vs the dict the integrated engine uses
    from src.sra.methodology_defaults_reader import build_test_methodology_defaults
    assert aux["cg_coefficients"] == build_test_methodology_defaults().cg_coefficients
    # chain_config default + chain_risk_ids from the binding
    assert asdict(aux["chain_config"]) == asdict(ChainConfig())
    assert aux["chain_risk_ids"] == _default_chain_risk_ids()


# --- headless run outputs (P-curve etc.) + convergence note + triple --------

def test_convergence_note_and_triple(_wind_binding) -> None:
    out = run_headless_from_workbook(WIND, "WT", n_iter=25_000, seed=42, view="owner")
    conv = out["convergence_note"]
    assert conv["p80_ci95_half_width"] > 0 and conv["p80_ci95_half_width_pct"] > 0
    assert conv["n_iter"] == 25_000
    # correlation-sensitivity triple monotone at P80 (systemic tail widens)
    t = {m: dict((int(p), v) for p, v in out["triple"][m]) for m in out["triple"]}
    assert t["zero"][80] <= t["elicited"][80] <= t["one"][80]
    assert out["corr_flag"].startswith("valid")
    # P-curve is 19 rows (P5..P95); S-curve 101 points
    assert len(out["p_table"]) == 19 and len(out["s_curve"]["value"]) == 101


# --- cores import-clean (resolver + headless run are Pyodide-clean) ---------

_CLEAN = textwrap.dedent(
    """
    import sys
    FORBIDDEN = {"pandas", "openpyxl"}
    class _B:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in FORBIDDEN:
                raise ModuleNotFoundError("BLOCKED: " + name)
            return None
    sys.meta_path.insert(0, _B())
    import src.qra_register_parse            # resolver + parser
    import src.tier1_headless                # headless run core (openpyxl is fn-local)
    from src.tier1_headless import run_headless
    assert "pandas" not in sys.modules and "openpyxl" not in sys.modules
    print("CORES_CLEAN_OK")
    """
)


@pytest.mark.slow  # TESTLANE-01 A sweep: shells out (see tests/conftest.py guard)
def test_cores_import_clean() -> None:
    r = subprocess.run([sys.executable, "-c", _CLEAN], cwd=str(REPO),
                       capture_output=True, text=True)
    assert "CORES_CLEAN_OK" in r.stdout, f"{r.stdout}\n{r.stderr}"


# --- slow: headless run == engine (full-input parity + write-back), CPython -

@pytest.mark.slow
def test_headless_run_matches_engine_cpython(_wind_binding) -> None:
    import src.integrated.integrated_simulation as integ
    from src.integrated.integrated_simulation import IntegratedConfig
    from src.sra.methodology_defaults_reader import build_test_methodology_defaults
    from src.sra.strawman_reader import read_risk_scope
    from src.v5_register_reader import read_layer1_v5, read_risks_v5

    risks = read_risks_v5(str(WIND), risk_id_prefix="WT")
    rs = read_risk_scope(str(WIND))

    def _cfg(layer1):
        return IntegratedConfig(
            register_path=WIND, p6_path=WIND, strawman_path=WIND,
            methodology_defaults=build_test_methodology_defaults(),
            iterations=25_000, random_seed=42, layer1_config=layer1,
            day_rate=FIXTURE_DAY_RATE,
        **TEST_CALIBRATION_TOLERANCES)

    eng_off = np.asarray(
        integ.run_integrated_simulation(_cfg(None), risks, rs)["cost_dollars_array"], float)
    eng_on = np.asarray(
        integ.run_integrated_simulation(_cfg(read_layer1_v5(str(WIND))), risks, rs)["cost_dollars_array"], float)

    hl_off = run_headless_from_workbook(WIND, "WT", 25_000, 42, "shared-pool")
    hl_on = run_headless_from_workbook(WIND, "WT", 25_000, 42, "owner")
    # the headless P-curve is built from the SAME cost array as the engine -> raw ==
    for p, v in hl_off["p_table"]:
        assert v == float(np.percentile(eng_off, p))
    for p, v in hl_on["p_table"]:
        assert v == float(np.percentile(eng_on, p))


# --- slow: full-input cross-runtime rtol 1e-12 (node + Pyodide 314.0.1) ------

def _node_and_pyodide() -> bool:
    if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
        return False
    return (REPO / "spikes" / "qraxl01_q4" / "node_modules" / "pyodide" / "pyodide.mjs").exists()  # link-rule: the step 6b full-input gate runs the private spike when present, skips when absent


@pytest.mark.slow
def test_full_input_cross_runtime_rtol_1e_12() -> None:
    if not _node_and_pyodide():
        pytest.skip("node + Q4 pyodide 314.0.1 install required")
    cap = subprocess.run([sys.executable, "-m", "spikes.qraxl01_step6a.capture_tier2"],  # link-rule: the step 6b full-input gate runs the private spike when present, skips when absent
                         cwd=str(REPO), capture_output=True, text=True)
    assert cap.returncode == 0, cap.stderr[-2000:]
    run = subprocess.run(["node", str(REPO / "spikes/qraxl01_step6b/run_pyodide_step6b.mjs")],  # link-rule: the step 6b full-input gate runs the private spike when present, skips when absent
                         cwd=str(REPO), capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-2000:]
    t2 = REPO / "spikes/qraxl01_step6a/data"  # link-rule: the step 6b full-input gate runs the private spike when present, skips when absent
    t1 = REPO / "spikes/qraxl01_step6b/data"  # link-rule: the step 6b full-input gate runs the private spike when present, skips when absent
    load = lambda p: np.frombuffer(p.read_bytes(), dtype=np.float64)
    for tag, a, b in [
        ("OFF", load(t2 / "cost_off.f64"), load(t1 / "cost_off_pyodide.f64")),
        ("ON", load(t2 / "cost_on.f64"), load(t1 / "cost_on_pyodide.f64")),
    ]:
        assert a.size > 0 and a.shape == b.shape
        assert np.allclose(a, b, rtol=1e-12, atol=0), f"full-input rtol 1e-12 FAILED (L1 {tag})"
