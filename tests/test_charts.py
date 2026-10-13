"""
Tests for chart generation.

Validates:
- All three chart types generate valid PNG files
- Charts handle edge cases (empty data, minimal data)
- File sizes are reasonable (not empty, not huge)
"""

from pathlib import Path
import pytest
import numpy as np

from src.config import SimConfig, ChainConfig, TornadoEntry
from src.simulation import MonteCarloEngine
from src.analysis import compute_tornado, compute_s_curve, compute_convergence
from src.charts import generate_s_curve, generate_tornado, generate_convergence


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path(__file__).parent.parent / "outputs" / "charts"


@pytest.fixture(autouse=True)
def _chart_output_dir():
    """``outputs/charts`` is where these tests WRITE, not an input they read.

    CHARTSDEP-01 lists it among the inputs, and on a fresh clone its absence made seven
    chart tests red with FileNotFoundError. Creating it is the tests-only fix (§11.5,
    Builder's choice recorded): skipping would keep the charts untested in CI, and there
    is nothing to skip FOR - no client data is involved and the directory costs nothing.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _run_sim():
    """Quick sim for chart test data."""
    from tests.test_simulation import make_config, make_buckets, make_sample_risks, make_corr_coefficients
    config = make_config(n_iter=10_000)
    risks = make_sample_risks()
    engine = MonteCarloEngine(
        config, make_buckets(), ChainConfig(), risks,
        make_corr_coefficients(), seed=42,
    )
    return engine.run(), config, risks


# ---------------------------------------------------------------------------
# S-Curve
# ---------------------------------------------------------------------------

class TestSCurveChart:

    def test_generates_png(self):
        raw, config, risks = _run_sim()
        sc = compute_s_curve(raw)
        path = OUTPUT_DIR / "test_s_curve.png"
        generate_s_curve(sc, config, path, view="All")
        assert path.exists()
        assert path.stat().st_size > 10_000  # should be a real image
        path.unlink()  # cleanup

    def test_with_tight_distribution(self):
        """Should handle case where L1 and total curves are close."""
        raw, config, risks = _run_sim()
        sc = compute_s_curve(raw)
        path = OUTPUT_DIR / "test_s_curve_tight.png"
        generate_s_curve(sc, config, path, view="BOP")
        assert path.exists()
        path.unlink()


# ---------------------------------------------------------------------------
# Tornado
# ---------------------------------------------------------------------------

class TestTornadoChart:

    def test_generates_png(self):
        raw, config, risks = _run_sim()
        tornado = compute_tornado(raw, risks)
        path = OUTPUT_DIR / "test_tornado.png"
        generate_tornado(tornado, path, view="All")
        assert path.exists()
        assert path.stat().st_size > 10_000
        path.unlink()

    def test_empty_tornado(self):
        """Should handle empty tornado gracefully."""
        path = OUTPUT_DIR / "test_tornado_empty.png"
        generate_tornado([], path, view="All")
        assert path.exists()
        path.unlink()

    def test_single_entry(self):
        """Should handle single tornado entry."""
        entry = TornadoEntry("R001", "Test risk", 1e12, 1e6, "BOP Contractor", "Layer 2")
        path = OUTPUT_DIR / "test_tornado_single.png"
        generate_tornado([entry], path)
        assert path.exists()
        path.unlink()


# ---------------------------------------------------------------------------
# Convergence
# ---------------------------------------------------------------------------

class TestConvergenceChart:

    def test_generates_png(self):
        raw, _, _ = _run_sim()
        conv = compute_convergence(raw, seed=42)
        path = OUTPUT_DIR / "test_convergence.png"
        generate_convergence(conv, path)
        assert path.exists()
        assert path.stat().st_size > 5_000
        path.unlink()

    def test_minimal_data(self):
        """Should handle convergence with only 2 points."""
        conv = {"conv_1000": 350e6, "conv_5000": 352e6}
        path = OUTPUT_DIR / "test_conv_minimal.png"
        generate_convergence(conv, path)
        assert path.exists()
        path.unlink()
