"""QRAXL-01 step 3 - qra_core is Pyodide-safe and runs standalone.

Two guarantees for the Tier-1 (xlwings Lite / Pyodide) goal:

1. TRANSITIVE-CLOSURE CLEANLINESS (the important one): the WHOLE reachable import
   set of ``src.qra_core`` - not just qra_core.py - must load without pulling any
   Pyodide-unsafe module (pandas, openpyxl, the XER reader). A clean qra_core that
   imports something which in turn imports pandas/XER is NOT clean. This is proven
   in a FRESH subprocess with an import hook that raises on the forbidden set, then
   imports qra_core AND runs run_cost_layer (so the function-local cascade import is
   exercised too).

2. STANDALONE ON PLAIN TYPES: run_cost_layer works on plain-python + numpy inputs
   constructed directly (SimpleNamespace risks, plain dict dual_lookup) - never
   routed through the pandas shell. This proves it runs standalone AND that the
   dual_lookup boundary hands across plain types, not pandas objects that happen to
   work in CPython but would die in Pyodide.

Both tests are fast (<=1000 iters) - fast-lane regression cover for the Tier-1 goal.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.config import ChainConfig
import src.qra_core as qra_core

REPO_ROOT = Path(__file__).resolve().parents[1]

# Runs in a fresh interpreter: install a meta-path finder that raises on any
# Pyodide-unsafe module BEFORE importing qra_core, then import + run it. If the
# closure needs pandas / openpyxl / the XER reader, the import raises and the
# subprocess exits non-zero without printing the sentinel.
_SUBPROCESS = textwrap.dedent(
    '''
    import sys

    FORBIDDEN_TOP = {"pandas", "openpyxl"}
    FORBIDDEN_FULL = {"src.sra.cpm.xer_reader"}

    class _Blocker:
        def find_spec(self, name, path=None, target=None):
            top = name.split(".")[0]
            if (top in FORBIDDEN_TOP
                    or name in FORBIDDEN_FULL
                    or any(name.startswith(f + ".") for f in FORBIDDEN_FULL)):
                raise ModuleNotFoundError(
                    "BLOCKED Pyodide-unsafe import in qra_core closure: " + name
                )
            return None  # defer to the real finders

    sys.meta_path.insert(0, _Blocker())

    import numpy as np
    from types import SimpleNamespace
    from src.config import ChainConfig
    import src.qra_core as q  # must not trigger any blocked import

    risks = [
        SimpleNamespace(
            risk_id="R%d" % i, probability=0.5, opt_cost=100.0, ml_cost=200.0,
            pess_cost=300.0, distribution="PERT",
            correlation_group="CG0%d" % (i + 1), planned_day=0,
        )
        for i in range(3)
    ]
    # one dual-coded risk exercises the schedule branch + the plain-dict boundary
    dual_lookup = {
        "R1": {"mode_multiplier": 1.0, "mode": "Series",
               "opt_d": 1.0, "ml_d": 2.0, "pess_d": 3.0},
    }
    res = q.run_cost_layer(
        n_iter=500, risks=risks, cg_coefficients={"CG02": 0.5},
        dual_lookup=dual_lookup, chain_risk_ids={}, chain_config=ChainConfig(),
        seed=42,
    )
    assert res["cost_dollars_array"].shape == (500,), res["cost_dollars_array"].shape
    assert res["schedule_days_array"].shape == (500,)
    # Belt-and-suspenders: nothing forbidden slipped into the closure.
    assert "pandas" not in sys.modules, "pandas leaked into qra_core closure"
    assert "openpyxl" not in sys.modules, "openpyxl leaked into qra_core closure"
    print("PYODIDE_CLEAN_OK")
    '''
)


@pytest.mark.slow  # TESTLANE-01 A sweep: shells out (see tests/conftest.py guard)
def test_qra_core_transitive_closure_is_pyodide_clean():
    """The whole reachable import set of qra_core loads with pandas/openpyxl/XER
    blocked - so it will load under xlwings Lite (Pyodide)."""
    r = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert "PYODIDE_CLEAN_OK" in r.stdout, (
        "qra_core's transitive import closure pulled a Pyodide-unsafe module "
        "(pandas / openpyxl / xer_reader).\n"
        f"--- STDOUT ---\n{r.stdout}\n--- STDERR ---\n{r.stderr}"
    )
    assert r.returncode == 0, r.stderr


def _plain_risks(n: int = 4) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            risk_id=f"R{i}", probability=0.4 + 0.1 * i, opt_cost=100.0 * (i + 1),
            ml_cost=250.0 * (i + 1), pess_cost=600.0 * (i + 1), distribution="PERT",
            correlation_group=f"CG{i % 2 + 1:02d}", planned_day=0,
        )
        for i in range(n)
    ]


def test_qra_core_runs_standalone_on_plain_types():
    """run_cost_layer on directly-constructed plain objects + dicts (no pandas)."""
    risks = _plain_risks(4)
    dual_lookup = {
        "R2": {"mode_multiplier": 1.0, "mode": "Series",
               "opt_d": 2.0, "ml_d": 5.0, "pess_d": 12.0},
    }
    kwargs = dict(
        n_iter=1000, risks=risks, cg_coefficients={"CG01": 0.5, "CG02": 0.5},
        dual_lookup=dual_lookup, chain_risk_ids={}, chain_config=ChainConfig(),
        seed=42,
    )
    res = qra_core.run_cost_layer(**kwargs)

    assert res["cost_dollars_array"].shape == (1000,)
    assert res["schedule_days_array"].shape == (1000,)
    assert res["cost_dollars_array"].dtype == np.float64
    assert res["risk_ids_dual"] == ["R2"]  # dual_lookup key handed across as plain type
    assert np.all(res["cost_dollars_array"] >= 0.0)

    # Determinism: same seed -> byte-identical (the bit-identity contract in miniature)
    res2 = qra_core.run_cost_layer(**kwargs)
    assert np.array_equal(res["cost_dollars_array"], res2["cost_dollars_array"])
    assert np.array_equal(res["schedule_days_array"], res2["schedule_days_array"])
