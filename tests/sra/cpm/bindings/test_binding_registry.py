"""Showcase-P2 WS2-A — project-binding registry + selection.

Covers the registry mechanics: register, lookup, duplicate, active-by-env, and the
refusal when nothing is selected.

REFRETIRE-01 (D-2) removed this file's other half. It asserted one project's declarative
surface - its filenames, party labels, report titles, risk prefix and chain ids - and the
workbook-equality gate for that project's ``LEGACY_CHAIN_IDS``, which needed a register that
is not in this repository and skipped everywhere. Both retired with the binding. Each shipped
project's own surface is asserted by its own test (``test_synthetic_wind_binding.py``).
"""
from __future__ import annotations

import pytest

from src.sra.cpm.bindings import (
    ACTIVE_PROJECT_ENV_VAR,
    NoProjectSelectedError,
    ProjectBinding,
    active_project_name,
    get_active_binding,
    get_binding,
    list_bindings,
    register_binding,
)


def test_no_default_project(monkeypatch):
    # QRAXL-01 generic decoupling: the "refproject" default was REMOVED. An unset
    # selection fails loud rather than silently resolving to RefProject.
    assert ACTIVE_PROJECT_ENV_VAR == "QRA_PROJECT"
    monkeypatch.delenv(ACTIVE_PROJECT_ENV_VAR, raising=False)
    with pytest.raises(NoProjectSelectedError):
        active_project_name()
    with pytest.raises(NoProjectSelectedError):
        get_active_binding()


def test_env_var_selects_active_binding(monkeypatch):
    sentinel = register_binding(
        ProjectBinding(name="test_proj_ws2a", project_name="TestProj"),
        overwrite=True,
    )
    monkeypatch.setenv(ACTIVE_PROJECT_ENV_VAR, "test_proj_ws2a")
    assert active_project_name() == "test_proj_ws2a"
    assert get_active_binding() is sentinel


def test_get_binding_unknown_raises_clear_keyerror():
    with pytest.raises(KeyError) as exc:
        get_binding("nonexistent_project_xyz")
    # The message names the missing project and lists what is registered.
    assert "nonexistent_project_xyz" in str(exc.value)


def test_register_duplicate_raises_without_overwrite():
    register_binding(ProjectBinding(name="dup_ws2a", project_name="Dup"), overwrite=True)
    with pytest.raises(ValueError):
        register_binding(ProjectBinding(name="dup_ws2a", project_name="Dup2"))


def test_register_non_binding_raises_typeerror():
    with pytest.raises(TypeError):
        register_binding({"name": "not_a_binding"})  # type: ignore[arg-type]


def test_binding_mappings_are_immutable():
    b = get_binding("synthetic_wind")
    with pytest.raises(TypeError):
        b.default_filenames["register"] = "x"  # type: ignore[index]
