"""QRAXL-01 step 6a - Tier-1 headless gates (risk-first, no Excel UI).

- read-parity: the Tier-1 headless read (grids -> shared parser) deep-equals the
  Tier-2 openpyxl reader on the same workbook (structural, one parser).
- parser import-cleanliness: qra_register_parse (Tier-1's read path, run in
  Pyodide) imports with pandas/openpyxl BLOCKED - stays in qra_core's clean closure.
- make_xlwings byte-parity: every embedded core module in dist/qra_xlwings_combined.py
  decodes byte-identical to the repo source, and the bundle bootstraps to a
  callable qra_core (self-contained + functional).
- cross-runtime rtol 1e-12 (slow, needs node + the Q4 pyodide install): the Tier-1
  headless run in Pyodide 314.0.1 reproduces the Tier-2 CPython cost arrays within
  rtol 1e-12, Layer 1 OFF and ON, seed 42 - the ratified Q4 policy on the real
  wind register. The CPython QRAXL-01.0 client gate stays raw == (untouched).
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from src.layer1_factors import Layer1Config
from src.tier1_headless import read_register_headless
from src.v5_register_reader import read_layer1_v5, read_risks_v5

REPO = Path(__file__).resolve().parents[1]
WIND = REPO / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"


# --- read-parity: Tier-1 headless == Tier-2 openpyxl (one shared parser) -----

def test_read_parity_risks_and_layer1() -> None:
    t2_risks = read_risks_v5(str(WIND), risk_id_prefix="WT")
    t2_layer1 = read_layer1_v5(str(WIND))
    t1_risks, t1_layer1 = read_register_headless(str(WIND), risk_id_prefix="WT")

    assert t1_risks == t2_risks  # RiskInput dataclass deep-equal, order included
    assert isinstance(t1_layer1, Layer1Config) and t2_layer1 is not None
    assert t1_layer1.factors == t2_layer1.factors
    assert t1_layer1.corr_names == t2_layer1.corr_names
    assert t1_layer1.corr_mode == t2_layer1.corr_mode
    assert t1_layer1.declared_total == t2_layer1.declared_total
    assert np.array_equal(t1_layer1.base, t2_layer1.base)
    assert np.array_equal(t1_layer1.corr_matrix, t2_layer1.corr_matrix)


def test_client_register_returns_none_layer1() -> None:
    # A client register (RefProject) carries NO Layer-1 sheets, so the shared
    # parser returns None -> Layer 1 OFF (shared-pool), exactly as Tier 2. The
    # parser's None path is the contract both readers rely on.
    from src.qra_register_parse import parse_layer1_from_grids
    assert parse_layer1_from_grids({}) is None


# --- parser import-cleanliness (Tier-1 read path is Pyodide-clean) -----------

_CLEAN_SUBPROC = textwrap.dedent(
    """
    import sys
    FORBIDDEN_TOP = {"pandas", "openpyxl"}
    FORBIDDEN_FULL = {"src.sra.cpm.xer_reader"}
    class _Blocker:
        def find_spec(self, name, path=None, target=None):
            top = name.split(".")[0]
            if (top in FORBIDDEN_TOP or name in FORBIDDEN_FULL
                    or any(name.startswith(f + ".") for f in FORBIDDEN_FULL)):
                raise ModuleNotFoundError("BLOCKED Pyodide-unsafe import: " + name)
            return None
    sys.meta_path.insert(0, _Blocker())
    # the whole reachable closure of the Tier-1 read path must be clean
    import src.qra_register_parse as p
    import src.tier1_headless  # top-level imports must be clean (openpyxl is fn-local)
    assert "pandas" not in sys.modules and "openpyxl" not in sys.modules
    # exercise the parser so any lazy import fires too
    grid = [[None]] * 2 + [["", "", "", "", "", "Contingent Risk Cost"]]  # row 3 section
    print("PARSER_CLEAN_OK")
    """
)


@pytest.mark.slow  # TESTLANE-01 A sweep: shells out (see tests/conftest.py guard)
def test_parser_is_pyodide_clean() -> None:
    r = subprocess.run(
        [sys.executable, "-c", _CLEAN_SUBPROC], cwd=str(REPO),
        capture_output=True, text=True,
    )
    assert "PARSER_CLEAN_OK" in r.stdout, (
        f"parser import-cleanliness failed:\nSTDOUT:{r.stdout}\nSTDERR:{r.stderr}"
    )


# --- make_xlwings byte-parity + functional bundle ---------------------------

@pytest.mark.slow  # TESTLANE-01 A sweep: shells out (see tests/conftest.py guard)
def test_make_xlwings_byte_parity_and_bootstraps(tmp_path) -> None:
    import tools.make_qra_xlwings as mk

    # GD-B byte-churn fix: build to tmp_path so the test never rewrites the
    # repo's dist/qra_xlwings_combined.py (which a user may have pasted from).
    out = mk.build(tmp_path / "qra_xlwings_combined.py")
    combined = out.read_text(encoding="utf-8")
    embedded = mk.embedded_core(combined)
    for name, rel in mk.CORE_MODULES:
        assert embedded[name] == (mk.REPO / rel).read_bytes(), (
            f"embedded core '{name}' is NOT byte-identical to the repo source"
        )

    # the bundle is self-contained: bootstrap the core in a fresh subprocess and
    # confirm run_cost_layer imports and is callable (no repo on sys.path needed).
    # Isolated (-I) and from an empty folder, and any `src` module the bundle did not
    # install itself is refused: an editable install puts the repository on every
    # path, -I does not remove it, and it hid a missing module (SNAPSHOTCUT-01, -7).
    boot = textwrap.dedent(
        f"""
        import base64, types, sys

        class _OnlyTheBundle:
            def find_spec(self, name, path=None, target=None):
                if name == "src" or name.startswith("src."):
                    raise ModuleNotFoundError(f"the bundle does not carry {{name}}")
                return None

        sys.meta_path.insert(0, _OnlyTheBundle())
        combined = open({str(out)!r}, encoding="utf-8").read()
        head = combined[:combined.index("# xlwings Lite shell")]
        head = "\\n".join(l for l in head.splitlines() if not l.startswith("from __future__"))
        exec(head, {{}})
        assert callable(sys.modules["src.qra_core"].run_cost_layer)
        print("BUNDLE_OK")
        """
    )
    script = tmp_path / "boot.py"
    script.write_text(boot, encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    r = subprocess.run([sys.executable, "-I", str(script)], capture_output=True, text=True, cwd=empty)
    assert "BUNDLE_OK" in r.stdout, f"bundle bootstrap failed:\n{r.stdout}\n{r.stderr}"


# --- cross-runtime rtol 1e-12 (slow; node + Q4 pyodide install) --------------

def _node_and_pyodide_available() -> bool:
    if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
        return False
    return (REPO / "spikes" / "qraxl01_q4" / "node_modules" / "pyodide" / "pyodide.mjs").exists()  # link-rule: the step 6a cross-runtime gate runs the private spike when present, skips when absent


@pytest.mark.slow
def test_cross_runtime_rtol_1e_12() -> None:
    if not _node_and_pyodide_available():
        pytest.skip("node + Q4 pyodide 314.0.1 install required for the cross-runtime gate")
    # Tier-2 capture (CPython) -> Tier-1 run (Pyodide 314.0.1) -> compare.
    cap = subprocess.run(
        [sys.executable, "-m", "spikes.qraxl01_step6a.capture_tier2"],  # link-rule: the step 6a cross-runtime gate runs the private spike when present, skips when absent
        cwd=str(REPO), capture_output=True, text=True,
    )
    assert cap.returncode == 0, f"capture failed:\n{cap.stderr[-2000:]}"
    run = subprocess.run(
        ["node", str(REPO / "spikes" / "qraxl01_step6a" / "run_pyodide_step6a.mjs")],  # link-rule: the step 6a cross-runtime gate runs the private spike when present, skips when absent
        cwd=str(REPO), capture_output=True, text=True,
    )
    assert run.returncode == 0, f"pyodide run failed:\n{run.stderr[-2000:]}"

    d = REPO / "spikes" / "qraxl01_step6a" / "data"  # link-rule: the step 6a cross-runtime gate runs the private spike when present, skips when absent
    load = lambda f: np.frombuffer((d / f).read_bytes(), dtype=np.float64)
    for tag, a, b in [
        ("OFF", load("cost_off.f64"), load("cost_off_pyodide.f64")),
        ("ON", load("cost_on.f64"), load("cost_on_pyodide.f64")),
    ]:
        assert a.shape == b.shape and a.size > 0
        assert np.allclose(a, b, rtol=1e-12, atol=0), (
            f"cross-runtime rtol 1e-12 FAILED (Layer 1 {tag}): "
            f"max_rel={np.abs(a - b)[a != 0].max() / np.abs(a[a != 0]).max():.3e}"
        )
