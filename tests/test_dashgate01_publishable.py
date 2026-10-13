"""DASHGATE-01 P1: each project declares whether it may be published, and the default is no.

RELEASE-01 D-5 as amended: an explicit ``publish = true``, and a project marked
``confidential = true`` is refused even with the flag set (two locks). The default is nothing
(PM ruling D-A: an undeclared project is confidential). The golden registry's ``confidential`` is
not the publish gate, but the binding must agree with it, because one fact is not held two ways.
The registry is read here, never edited.
"""
from __future__ import annotations

import ast
import dataclasses
import tomllib
from pathlib import Path

import pytest

from src.sra.cpm.bindings import ProjectBinding, get_binding, is_publishable

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "tests" / "golden" / "projects.toml"
SHIPPED = sorted(p.stem for p in (REPO / "src" / "sra" / "cpm" / "bindings").glob("*.py")
                 if p.stem not in ("__init__", "registry"))


def _bare(**fields) -> ProjectBinding:
    return ProjectBinding(name="probe_key", project_name="Probe", **fields)


def test_a_binding_that_declares_nothing_is_not_publishable():
    bare = _bare()
    assert bare.publish is False and bare.confidential is True
    assert not is_publishable(bare)


def test_publish_without_clearing_confidential_is_not_publishable():
    assert not is_publishable(_bare(publish=True))
    assert not is_publishable(_bare(publish=True, confidential=True))


def test_clearing_confidential_without_publish_is_not_publishable():
    assert not is_publishable(_bare(confidential=False))


def test_only_both_locks_open_publish():
    assert is_publishable(_bare(publish=True, confidential=False))


def test_for_this_release_only_the_wind_showcase_is_publishable():
    """D-5: only `synthetic_wind` (Tropic Ridge) sets it; `synthetic_road` stays unpublished."""
    assert {n: is_publishable(get_binding(n)) for n in SHIPPED} == {
        "synthetic_road": False, "synthetic_wind": True}
    assert get_binding("synthetic_road").confidential is False


def _binding_for_row(row: dict) -> ProjectBinding | None:
    """The shipped binding whose declared register is one of the row's inputs - by data, not name."""
    inputs = {Path(p).as_posix() for p in row.get("inputs", [])}
    for name in SHIPPED:
        b = get_binding(name)
        register = f"{b.data_dirs.get('register', '')}/{b.default_filenames.get('register', '')}"
        if register in inputs:
            return b
    return None


def test_every_binding_agrees_with_the_golden_registry_on_confidential():
    rows = tomllib.loads(REGISTRY.read_text(encoding="utf-8"))["projects"]
    matched = {}
    for key, row in rows.items():
        b = _binding_for_row(row)
        assert b is not None, f"registry row {key} matches no shipped binding by its inputs"
        matched[b.name] = key
        assert b.confidential == row["confidential"], (
            f"{b.name}.confidential = {b.confidential} but the golden registry's {key} says "
            f"{row['confidential']}: one fact, held two ways")
    assert sorted(matched) == SHIPPED, f"a shipped binding has no registry row: {matched}"


def test_the_agreement_check_reds_on_a_disagreement(monkeypatch):
    import src.sra.cpm.bindings.registry as registry

    road = get_binding("synthetic_road")
    monkeypatch.setitem(registry._REGISTRY, "synthetic_road",
                        dataclasses.replace(road, confidential=True))
    with pytest.raises(AssertionError, match="one fact, held two ways"):
        test_every_binding_agrees_with_the_golden_registry_on_confidential()


def test_the_publish_answer_names_no_project():
    """Attributes, not names (GOLDEN01 rule 1): `is_publishable` compares no string."""
    import inspect

    import src.sra.cpm.bindings.registry as registry

    tree = ast.parse(inspect.getsource(registry.is_publishable))
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Compare)
               for n in [*n.comparators, n.left]
               if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not strings, f"is_publishable compares against names: {strings}"


# --- Round 1, N7: only real booleans open the locks ---------------------------------------------

@pytest.mark.parametrize("fields", [
    {"publish": "yes", "confidential": False},
    {"publish": 1, "confidential": False},
    {"publish": True, "confidential": 0},
    {"publish": True, "confidential": None},
])
def test_a_non_boolean_lock_is_refused_at_declaration(fields):
    with pytest.raises(TypeError, match="bool"):
        _bare(**fields)


def test_a_look_alike_binding_never_truthy_publishes():
    """Anything reaching `is_publishable` without the dataclass's check still needs True/False."""
    from types import SimpleNamespace

    assert not is_publishable(SimpleNamespace(publish="True", confidential=False))
    assert not is_publishable(SimpleNamespace(publish=True, confidential=0))
    assert is_publishable(SimpleNamespace(publish=True, confidential=False))
