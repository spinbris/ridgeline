"""QRAXL-01 generic decoupling — the no-defaults property test (GD-A).

Enforces the Director directive: there is NO default project. An unset selection
fails loud with a located error; nothing silently falls back to RefProject's V9
register or constants. RefProject is retained as the worked example, selected
explicitly (it must still resolve).

These tests UNSET ``QRA_PROJECT`` via ``monkeypatch`` (function-scoped, so
it runs after and overrides the ``tests/conftest.py`` refproject autouse) to
exercise the fail-loud path — the one place the harness selection is removed.
"""
from __future__ import annotations

import pytest

from src.sra.cpm.bindings import (
    NoProjectSelectedError,
    active_project_name,
    active_risk_id_prefix,
    get_active_binding,
    get_binding,
)

_ENV = "QRA_PROJECT"


# --- no project selected -> fail loud, never RefProject -----------------------

def test_get_active_binding_fails_loud_when_unset(monkeypatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    with pytest.raises(NoProjectSelectedError) as ei:
        get_active_binding()
    msg = str(ei.value)
    assert _ENV in msg and "no default" in msg.lower()
    # the located error must NOT silently name/point at RefProject's V9 register
    assert "V9" not in msg and "refproject master" not in msg.lower()


def test_active_project_name_fails_loud_when_unset(monkeypatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    with pytest.raises(NoProjectSelectedError):
        active_project_name()


def test_active_risk_id_prefix_fails_loud_when_unset(monkeypatch) -> None:
    # No cross-project "R" default: the reader's prefix resolution now raises
    # rather than silently reading RefProject's prefix.
    monkeypatch.delenv(_ENV, raising=False)
    with pytest.raises(NoProjectSelectedError):
        active_risk_id_prefix()


def test_default_register_filename_fails_loud_when_unset(monkeypatch) -> None:
    from src.defaults import get_default_register_filename
    monkeypatch.delenv(_ENV, raising=False)
    with pytest.raises(NoProjectSelectedError):
        get_default_register_filename()


def test_no_default_project_constant_survives() -> None:
    # The default was removed, not renamed. DEFAULT_PROJECT must no longer be a
    # public export of the registry (a reintroduced default would fail this).
    import src.sra.cpm.bindings.registry as reg
    assert not hasattr(reg, "DEFAULT_PROJECT")


# --- An explicitly-selected project resolves ---------------------------------

def test_synthetic_road_selected_explicitly_resolves(monkeypatch) -> None:
    monkeypatch.setenv(_ENV, "synthetic_road")
    b = get_active_binding()
    assert b.name == "synthetic_road"
    assert active_risk_id_prefix() == "KH"


def test_synthetic_wind_is_first_class_binding(monkeypatch) -> None:
    # promoted out of the test fixture into src/sra/cpm/bindings/ -> auto-imports
    # by name with no fixture exec.
    monkeypatch.setenv(_ENV, "synthetic_wind")
    assert get_binding("synthetic_wind").name == "synthetic_wind"
    assert active_risk_id_prefix() == "WT"


# --- Coupling C: headless_config sourced from the binding, fail-loud ---------

_HEADLESS_GETTERS = (
    "get_default_workbook_filename",
    "get_default_gp_toc",
    "get_headless_buckets",
    "get_headless_cg_coefficients",
    "get_wbs_cross_bucket_rho",
    "get_default_programme_seasons",
)


def test_headless_values_resolve_from_the_selected_binding(monkeypatch) -> None:
    # A binding that supplies headless_config -> every getter returns ITS values, so the legacy
    # cost-MC / --no-excel path runs on the project that was selected and on no other. Asserted
    # against the binding's own declaration rather than one project's literals, which is what
    # this test measured until REFRETIRE-01 retired that project.
    import src.defaults as d
    from src.sra.cpm.bindings import get_active_binding
    monkeypatch.setenv(_ENV, "synthetic_wind")
    declared = get_active_binding().headless_config
    assert d.get_wbs_cross_bucket_rho() == declared["wbs_cross_bucket_rho"]
    assert d.get_headless_cg_coefficients() == declared["cg_coefficients"]
    assert d.get_default_gp_toc() == declared["gp_toc"]
    assert len(d.get_headless_buckets()) == len(declared["wbs_buckets"])


def test_headless_values_fail_loud_for_binding_without_headless_config(monkeypatch) -> None:
    # A binding that supplies NO headless_config -> every headless getter fails
    # loud rather than falling back to RefProject's value (no cross-project fallback).
    import src.defaults as d
    from src.sra.cpm.bindings import ProjectBinding, register_binding
    register_binding(
        ProjectBinding(name="bare_no_headless_gd", project_name="Bare"),
        overwrite=True,
    )
    monkeypatch.setenv(_ENV, "bare_no_headless_gd")
    for getter_name in _HEADLESS_GETTERS:
        with pytest.raises(ValueError, match="headless_config"):
            getattr(d, getter_name)()


def test_headless_partial_config_fails_loud_on_absent_key(monkeypatch) -> None:
    # synthetic_wind supplies four keys and withholds two. The supplied ones
    # resolve; the withheld ones fail loud. Partial config is honoured
    # key-by-key, which is the property - not any particular key's membership.
    #
    # RS-B RE-POINTED THIS TEST, and the reason is the point of it. Step 1 gave
    # the wind binding gp_toc and wbs_buckets, so this test still passed its
    # assertions while no longer testing anything: its two remaining examples
    # were the only absent keys left, and had step 1 supplied all four this
    # would have become an empty loop that greens forever. Step 1 deliberately
    # left workbook_filename and programme_seasons absent so fail-loud kept
    # something to catch, and this is where that decision is cashed.
    import src.defaults as d
    monkeypatch.setenv(_ENV, "synthetic_wind")
    assert d.get_wbs_cross_bucket_rho() == 0.4
    assert d.get_headless_cg_coefficients()["CG06"] == 0.4  # wind's own map (not 0.5)
    assert d.get_default_gp_toc() == 50_000_000.0           # supplied at RS-B step 1
    assert len(d.get_headless_buckets()) == 6               # supplied at RS-B step 1

    withheld = ("get_default_workbook_filename", "get_default_programme_seasons")
    assert withheld, "the fail-loud half of this test must never become an empty loop"
    for getter_name in withheld:
        with pytest.raises(ValueError, match="headless_config"):
            getattr(d, getter_name)()


def test_headless_module_attrs_fail_loud_when_unset(monkeypatch) -> None:
    # The legacy `from src.defaults import HEADLESS_BUCKETS`-style access resolves
    # via __getattr__ -> the binding. With no project selected it fails loud
    # (NoProjectSelectedError), never a cross-project RefProject constant.
    import src.defaults as d
    monkeypatch.delenv(_ENV, raising=False)
    for attr in ("HEADLESS_BUCKETS", "HEADLESS_CG_COEFFICIENTS",
                 "WBS_CROSS_BUCKET_RHO", "DEFAULT_PROGRAMME_SEASONS",
                 "DEFAULT_GP_TOC", "DEFAULT_WORKBOOK_FILENAME"):
        with pytest.raises((NoProjectSelectedError, ValueError)):
            getattr(d, attr)
