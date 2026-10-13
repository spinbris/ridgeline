"""REG03 S2 - EMV as live Excel formulas (the deterministic cross-check).

Two layers:
- a formula-STRING assertion (always runs, no dependency): the generated formulas
  encode the intended distribution-aware arithmetic;
- a numeric RECONCILIATION (skipif `formulas` absent): the generated Excel formulas,
  evaluated headless via the `formulas` lib, reproduce the retired Python EMV literals
  to floating tolerance - and blank input rows evaluate to 0/blank, not an error.

`formulas` is a dev-only optional dep (requirements-dev.txt); the reconciliation is
skipped when it is not importable, so it never blocks the main suite. Steve's in-Excel
load test is the real-Excel confirmation.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import openpyxl
import pytest

import scripts.build_synthetic_wind_fixture as fixture_builder
from scripts.build_synthetic_wind_fixture import (
    WIND_DAY_RATE, _cost_distribution_mean, _pert_mean,
)
from tests.conftest import TEST_MODE_MULTIPLIERS
from tools.register_scaffold import (
    DATA_START_ROW, build_template, emv_formula_strings,
)

REPO = Path(__file__).resolve().parents[1]


def test_emv_formula_strings_encode_the_dispatch():
    """The formula strings encode the distribution-aware mean, the Grid_Methodology
    mode lookup, the day_rate reference and the blank guards."""
    cost, days, dollars = emv_formula_strings(5)
    # EMV_cost: probability x distribution-mean dispatch, blank-guarded
    assert cost.startswith('=IF(O5="","",O5*')
    assert '(P5+4*Q5+R5)/6' in cost           # PERT mean
    assert '(P5+Q5+R5)/3' in cost             # Triangular mean
    assert '1.2816' in cost and 'EXP(' in cost and 'LN(' in cost  # Lognormal
    assert 'LOWER(H5)="lognormal"' in cost
    # EMV_sched_days: PERT days x mode multiplier looked up from Methodology
    assert days.startswith('=IF(OR(T5<>"Yes",U5="")')
    assert '(V5+4*W5+X5)/6' in days
    assert 'INDEX(Methodology!$B$2:$B$20,MATCH(Z5,Methodology!$A$2:$A$20,0))' in days
    assert 'IFERROR(' in days                 # blank/unmatched Mode -> 0
    # EMV_sched_dollars: days x the named day_rate
    assert dollars == '=AC5*MC_day_rate'


def _evaluate(path: Path) -> dict:
    """Evaluate a workbook's Risk Register EMV cells headless via `formulas`.
    Returns {addr: value} for the AB/AC/AD columns."""
    formulas = pytest.importorskip("formulas")
    import warnings
    warnings.filterwarnings("ignore")
    xl = formulas.ExcelModel().loads(str(path)).finish()
    sol = xl.calculate()
    out = {}
    for k, v in sol.items():
        ku = k.upper()
        if "RISK REGISTER'!" in ku:
            addr = ku.split("RISK REGISTER'!")[-1]
            if addr[:2] in ("AB", "AC", "AD"):
                try:
                    out[addr] = v.value[0, 0]
                except Exception:
                    out[addr] = v.value
    return out


def test_emv_formulas_reconcile_to_retired_python_literals():
    """Each EMV formula, evaluated headless, reproduces the pre-S2 Python literal."""
    pytest.importorskip("formulas")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "wind.xlsx"
        fixture_builder.build_register(path)
        cells = _evaluate(path)
        max_err = 0.0
        for i, r in enumerate(fixture_builder.WIND_RISKS):
            (rid, _st, _de, _ow, _r1, _r2, dist, _cg, _rc, pc, oc, mc, pcst,
             timp, mode, pt, od, md, pd, _ca, _pf) = r
            row = DATA_START_ROW + i
            exp_cost = pc * _cost_distribution_mean(dist, oc, mc, pcst)
            exp_days = (pt * _pert_mean(od, md, pd) * TEST_MODE_MULTIPLIERS[mode]
                        if timp == "Yes" else 0.0)
            exp_dollars = exp_days * WIND_DAY_RATE
            for col, exp in (("AB", exp_cost), ("AC", exp_days), ("AD", exp_dollars)):
                got = cells.get(f"{col}{row}")
                got = 0.0 if got in ("", None) else float(got)
                max_err = max(max_err, abs(got - exp))
        assert max_err < 1e-6, f"EMV reconciliation drift {max_err:.3e}"


def test_emv_formulas_zero_on_blank_rows_no_error():
    """Empty-template gate: EMV on blank input rows evaluates to 0/blank, never
    #DIV/0! or #N/A."""
    pytest.importorskip("formulas")
    with tempfile.TemporaryDirectory() as d:
        path = build_template(Path(d) / "tmpl.xlsx")
        cells = _evaluate(path)
        for addr, val in cells.items():
            assert not (isinstance(val, str) and val.startswith("#")), (addr, val)
        # a representative blank row: days + dollars are 0, cost is blank/0
        assert (cells.get("AC5") or 0) == 0
        assert (cells.get("AD5") or 0) == 0
        assert cells.get("AB5") in ("", None, 0)
