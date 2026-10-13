"""
Tests for view override logic.

Verifies that:
- view=None in overrides does NOT override config.view
- view="Shared" in overrides DOES override config.view
- SimConfig retains its view when overrides has view=None
"""

from src.config import SimConfig


def _apply_overrides(config, overrides):
    """Replicate the override logic from main.py run_simulation()."""
    if overrides.get("iterations"):
        config.n_iter = overrides["iterations"]
    if overrides.get("seed") is not None:
        config.seed = overrides["seed"]
    if overrides.get("view"):
        config.view = overrides["view"]


def test_view_not_overridden_when_none():
    """overrides={"view": None} should not change config.view."""
    config = SimConfig(view="Shared")
    _apply_overrides(config, {"view": None})
    assert config.view == "Shared"


def test_view_overridden_when_explicit():
    """overrides={"view": "Shared"} should set config.view to Shared."""
    config = SimConfig(view="All")
    _apply_overrides(config, {"view": "Shared"})
    assert config.view == "Shared"


def test_view_default_from_config():
    """Config with view="Shared" stays Shared when overrides has no view key."""
    config = SimConfig(view="Shared")
    _apply_overrides(config, {})
    assert config.view == "Shared"
