"""Tests for SingleRun Shared view alignment."""
import numpy as np
import pytest

from src.config import (
    SimConfig, WBSBucket, ChainConfig, RiskInput,
    SingleRunResult, SingleRunEvent,
)
from src.single_run import run_single
from src.writer import _build_shared_single_run, _build_standard_single_run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> SimConfig:
    defaults = dict(
        n_iter=1000, tic=300_000_000, contingency=30_000_000,
        bop_contract=300_000_000,
        bop_contingency=5_000_000, cse_contingency=5_000_000,
    )
    defaults.update(overrides)
    return SimConfig(**defaults)


def _make_buckets() -> list[WBSBucket]:
    return [
        WBSBucket("Concrete/Civil", 55_000_000, -0.10, 0.20, "Triangular"),
        WBSBucket("Structural Steel", 30_000_000, -0.05, 0.25, "Triangular"),
    ]


def _make_chains() -> ChainConfig:
    return ChainConfig()


def _make_shared_risks() -> list[RiskInput]:
    """Risks with Shared owner for pool view testing."""
    return [
        RiskInput("R019", "GTG civil foundations delay", "Shared",
                  "Triangular", "CG05", 0.30,
                  1_000_000, 3_000_000, 8_000_000),
        RiskInput("R044", "Civil subcontractor pricing", "Shared",
                  "PERT", "CG01", 0.50,
                  500_000, 2_000_000, 5_000_000),
        RiskInput("R062", "Transformer installation delay", "Shared",
                  "Binary/PERT", "CG03", 0.25,
                  200_000, 1_000_000, 3_000_000),
    ]


def _make_mixed_risks() -> list[RiskInput]:
    """Mixed-owner risks for All view testing."""
    return [
        RiskInput("R015", "Inclement weather overrun", "BOP Contractor",
                  "Triangular", "CG06", 0.175,
                  350_000, 1_000_000, 2_000_000),
        RiskInput("R019", "GTG civil foundations delay", "Shared",
                  "Triangular", "CG05", 0.30,
                  1_000_000, 3_000_000, 8_000_000),
        RiskInput("R076", "Regulatory/planning delay", "Owner",
                  "Triangular", "CG07", 0.175,
                  875_000, 2_100_000, 5_000_000),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSingleRunShared:

    def test_single_run_shared_no_l1(self):
        """Shared view single run should have zero L1 variation."""
        config = _make_config(view="Shared")
        result = run_single(config, _make_buckets(), _make_chains(),
                            _make_shared_risks())
        assert result.l1_total_variation == 0.0
        assert len(result.buckets) == 0  # no L1 buckets

    def test_single_run_shared_pool_metrics(self):
        """Shared view should populate pool_budget, pool_headroom, n_fired."""
        config = _make_config(view="Shared")
        result = run_single(config, _make_buckets(), _make_chains(),
                            _make_shared_risks(), pool_budget=15_000_000)
        assert result.pool_budget == 15_000_000
        assert result.n_risks > 0
        assert result.view == "Shared"
        # pool_headroom = pool_budget - l2_total
        assert abs(result.pool_headroom - (15_000_000 - result.l2_total)) < 1.0

    def test_single_run_shared_total_is_pool_cost(self):
        """In Shared view, total_outturn should equal l2_total (not TIC+L2)."""
        config = _make_config(view="Shared")
        result = run_single(config, _make_buckets(), _make_chains(),
                            _make_shared_risks())
        assert result.total_outturn == result.l2_total

    def test_single_run_all_has_l1(self):
        """All view should still run L1 (regression)."""
        config = _make_config(view="All")
        result = run_single(config, _make_buckets(), _make_chains(),
                            _make_mixed_risks())
        assert len(result.buckets) > 0
        assert result.l1_outturn > 0

    def test_single_run_event_has_probability(self):
        """Every event should have probability populated."""
        config = _make_config(view="Shared")
        result = run_single(config, _make_buckets(), _make_chains(),
                            _make_shared_risks())
        for ev in result.events:
            assert 0 < ev.probability <= 1.0

    def test_single_run_view_stored(self):
        """SingleRunResult should store the view used."""
        config = _make_config(view="Shared")
        result = run_single(config, _make_buckets(), _make_chains(),
                            _make_shared_risks())
        assert result.view == "Shared"

    def test_single_run_all_view_stored(self):
        """All view result should store 'All'."""
        config = _make_config(view="All")
        result = run_single(config, _make_buckets(), _make_chains(),
                            _make_mixed_risks())
        assert result.view == "All"


class TestWriterFormats:

    def test_writer_shared_output_format(self):
        """Writer should produce pool summary for Shared view."""
        result = SingleRunResult(
            view="Shared",
            events=[
                SingleRunEvent("R019", "Test risk fired", "Shared",
                               0.30, True, 3_000_000, 10.0),
                SingleRunEvent("R044", "Test risk not fired", "Shared",
                               0.50, False, 0.0, 0.0),
            ],
            l2_total=3_000_000,
            total_outturn=3_000_000,
            shared_l2=3_000_000,
            pool_budget=15_000_000,
            pool_headroom=12_000_000,
            n_fired=1,
            n_risks=2,
        )
        rows = []
        _build_shared_single_run(rows, result)

        # Check header
        assert "SHARED RISK POOL" in rows[0][0]
        # Check pool summary exists
        pool_rows = [r for r in rows if isinstance(r[0], str) and "Pool" in r[0]]
        assert len(pool_rows) >= 2  # pool cost + pool budget + headroom
        # Check WITHIN BUDGET status
        headroom_row = [r for r in rows if isinstance(r[0], str) and "headroom" in r[0].lower()]
        assert len(headroom_row) == 1
        assert "WITHIN BUDGET" in headroom_row[0][5]

    def test_writer_all_output_format(self):
        """Writer should produce standard outturn summary for All view (regression)."""
        from src.config import SingleRunBucket
        result = SingleRunResult(
            view="All",
            buckets=[
                SingleRunBucket("Test Bucket", 50_000_000, 0.05, 2_500_000, "Triangular"),
            ],
            events=[
                SingleRunEvent("R015", "Test risk", "BOP Contractor",
                               0.175, True, 1_000_000, 5.0),
            ],
            l1_total_variation=2_500_000,
            l1_outturn=302_500_000,
            l2_total=1_000_000,
            total_outturn=303_500_000,
            bop_l2=1_000_000,
            bop_outturn=303_500_000,
            n_fired=1,
            n_risks=1,
        )
        rows = []
        _build_standard_single_run(rows, result)

        # Check L1 header present
        assert "LAYER 1" in rows[0][0]
        # Check cost summary present
        summary_rows = [r for r in rows if isinstance(r[0], str) and "COST SUMMARY" in r[0]]
        assert len(summary_rows) == 1
        # Check probability is numeric
        l2_header_idx = next(i for i, r in enumerate(rows) if "LAYER 2" in str(r[0]))
        event_row = rows[l2_header_idx + 1]
        assert event_row[3] == 0.175  # numeric probability (col shifted by Dist column)


class TestNumericOutput:

    def test_single_run_output_numeric_cost(self):
        """Event cost_impact in SingleRunResult should be float, not string."""
        config = _make_config(view="Shared")
        result = run_single(config, _make_buckets(), _make_chains(),
                            _make_shared_risks())
        for ev in result.events:
            assert isinstance(ev.cost_impact, (int, float))

    def test_single_run_output_numeric_probability(self):
        """Event probability in SingleRunResult should be float, not string."""
        config = _make_config(view="Shared")
        result = run_single(config, _make_buckets(), _make_chains(),
                            _make_shared_risks())
        for ev in result.events:
            assert isinstance(ev.probability, float)

    def test_single_run_pool_summary_numeric(self):
        """Shared view l2_total, pool_budget, pool_headroom should be numeric."""
        config = _make_config(view="Shared")
        result = run_single(config, _make_buckets(), _make_chains(),
                            _make_shared_risks(), pool_budget=15_000_000.0)
        assert isinstance(result.l2_total, (int, float))
        assert isinstance(result.pool_budget, (int, float))
        assert isinstance(result.pool_headroom, (int, float))
