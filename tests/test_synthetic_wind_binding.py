"""Showcase-P2 WS2-C — synthetic-wind binding selection + RefProject-free surface.

Proves a *second* binding registers and is selectable by env var (the
project-agnostic extension point works for more than just RefProject), and
that its declarative surface shares no RefProject identifiers. The full
end-to-end run (cost + Stage 2.5 + Stage 3 against the synthetic register /
strawman / .xer) lives in tests/test_synthetic_wind.py once those fixtures
are generated.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from src.sra.cpm.bindings import (
    ACTIVE_PROJECT_ENV_VAR,
    get_active_binding,
    get_binding,
)

_WIND_BINDING_PATH = (
    Path(__file__).resolve().parent
    / "fixtures" / "synthetic_wind" / "wind_binding.py"
)

# "contractor" is deliberately NOT here. The scrub rewrote the client company
# name to the neutral token "Contractor", which is ordinary domain vocabulary -
# synthetic_wind.py:26 legitimately carries party_labels["contractor"]. A
# detector that forbids a word the product uses is a false positive, not a gate.
_FORBIDDEN = ("refproject", "r076", "r015", "r017", "r018", "r019")


def _load_wind_binding():
    """Import the path-based fixture binding (self-registers on import)."""
    spec = importlib.util.spec_from_file_location(
        "wind_binding_fixture", _WIND_BINDING_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wind_binding_registers_and_is_selectable(monkeypatch):
    _load_wind_binding()
    b = get_binding("synthetic_wind")
    assert b.project_name == "SyntheticWind"
    # Selectable by env var, exactly like refproject.
    monkeypatch.setenv(ACTIVE_PROJECT_ENV_VAR, "synthetic_wind")
    assert get_active_binding().name == "synthetic_wind"


def test_wind_binding_surface_has_no_refproject_identifiers():
    _load_wind_binding()
    b = get_binding("synthetic_wind")
    blob = " ".join(
        [b.project_name]
        + list(b.default_filenames.values())
        + list(b.party_labels.values())
        + list(b.narrative_templates.values())
        + list(b.wbs_labels.values())
    ).lower()
    for token in _FORBIDDEN:
        assert token not in blob, f"wind binding surface leaks {token!r}"


def test_wind_binding_default_filenames_point_at_fixtures():
    _load_wind_binding()
    b = get_binding("synthetic_wind")
    assert b.default_filenames["register"] == "wind_register.xlsx"
    # REG-01: strawman dissolved into the consolidated register; both roles
    # resolve to the one workbook.
    assert b.default_filenames["strawman"] == "wind_register.xlsx"
    assert b.default_filenames["schedule"].endswith("wind_schedule.xer")


def test_wind_binding_risk_id_prefix_is_wt():
    _load_wind_binding()
    assert get_binding("synthetic_wind").risk_id_prefix == "WT"
