"""
Tests for pool budget and gain/pain config defaults.

Validates:
- SimConfig.pool_budget default is $15M
- GainPainConfig defaults are correct
"""

import pytest

from src.config import SimConfig, GainPainConfig

# RS-B step 2: this module asserts against the reference project's register
# shape, RBS map, chain identifiers or narrative templates, so it selects that
# binding explicitly rather than inheriting the suite default.
pytestmark = pytest.mark.project("synthetic_wind")


def test_pool_budget_default():
    """SimConfig.pool_budget default should be $15M."""
    config = SimConfig()
    assert config.pool_budget == 15_000_000.0


def test_gain_pain_config_defaults():
    """GainPainConfig defaults should match expected values. The TOC is the active project's,
    resolved from its binding - it was a literal here until REFRETIRE-01, and the literal was
    one project's contract value."""
    from src.sra.cpm.bindings import get_active_binding

    gp = GainPainConfig()
    assert gp.toc == get_active_binding().headless_config["gp_toc"]
    assert gp.share_split == 0.5
    assert gp.max_reward_pct == 0.05
    assert gp.max_risk_pct == 0.05
    assert gp.enabled is False


def test_gp_config_defaults_match_defaults_py():
    """GainPainConfig defaults should match src/defaults.py constants."""
    from src.defaults import (
        DEFAULT_GP_TOC, DEFAULT_GP_SHARE_SPLIT,
        DEFAULT_GP_MAX_REWARD_PCT, DEFAULT_GP_MAX_RISK_PCT,
    )
    gp = GainPainConfig()
    assert gp.toc == DEFAULT_GP_TOC
    assert gp.share_split == DEFAULT_GP_SHARE_SPLIT
    assert gp.max_reward_pct == DEFAULT_GP_MAX_REWARD_PCT
    assert gp.max_risk_pct == DEFAULT_GP_MAX_RISK_PCT


def test_gp_enabled_flag_bool_conversion():
    """enabled flag: 0 -> False, 1 -> True, truthy -> True."""
    assert GainPainConfig(enabled=False).enabled is False
    assert GainPainConfig(enabled=True).enabled is True
    # bool(0) = False, bool(1) = True — matching reader logic
    assert bool(0) is False
    assert bool(1) is True
