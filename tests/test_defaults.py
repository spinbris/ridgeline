"""
Tests for src/defaults.py — centralised default values.

Validates:
- Module is importable
- Headless bucket count and TIC sum match SP8b
- Chain risk ID structure
- Chart positions structure
"""

import pytest

# RS-B step 2: this module reads the reference project's register shape, RBS map
# or chain identifiers, so it selects that binding explicitly rather than
# inheriting the suite default. Visible here, greppable, and departing from a
# default that tests/test_project_selection.py pins.
pytestmark = pytest.mark.project("synthetic_wind")


def test_defaults_importable():
    """src.defaults must import without error."""
    import src.defaults  # noqa: F401


def test_headless_buckets_are_the_active_bindings_own():
    """REFRETIRE-01: these asserted one project's bucket count and TIC sum through the generic
    reader, so they measured that project's data rather than the resolution. What ``defaults``
    owes is the ACTIVE binding's buckets, whatever they are."""
    from src.defaults import HEADLESS_BUCKETS
    from src.sra.cpm.bindings import get_active_binding

    declared = get_active_binding().headless_config["wbs_buckets"]
    assert len(HEADLESS_BUCKETS) == len(declared)
    assert sum(b.base_cost for b in HEADLESS_BUCKETS) == sum(b.base_cost for b in declared)


def test_chain_risk_ids_structure():
    """CHAIN_RISK_IDS must have the correct keys and c2_targets must be a list. A project that
    declares no legacy chain gets the all-None fallback, which is a no-op, not an error."""
    from src.defaults import CHAIN_RISK_IDS
    required_keys = {"c1_trigger", "c1_target", "c2_trigger", "c2_targets"}
    assert required_keys == set(CHAIN_RISK_IDS.keys())
    assert isinstance(CHAIN_RISK_IDS["c2_targets"], list)


def test_chart_positions_all_present():
    """CHART_POSITIONS must have all 7 chart keys with correct tuple structure."""
    from src.defaults import CHART_POSITIONS
    expected_keys = {"s_curve", "tornado", "convergence", "output_hist",
                     "input_dist", "gain_pain", "wbs_dist"}
    assert expected_keys == set(CHART_POSITIONS.keys())
    for key, val in CHART_POSITIONS.items():
        assert isinstance(val, tuple), f"{key} is not a tuple"
        assert len(val) == 4, f"{key} tuple has {len(val)} elements, expected 4"
        sheet, cell, w, h = val
        assert isinstance(sheet, str), f"{key} sheet is not str"
        assert isinstance(cell, str), f"{key} cell is not str"
        assert isinstance(w, (int, float)), f"{key} width is not numeric"
        assert isinstance(h, (int, float)), f"{key} height is not numeric"
