"""TESTLANE-01 A, Q1: the process-starting routes the runtime guard cannot see.

**What the runtime guard covers, and what it cannot.** The autouse fixture in
``tests/conftest.py`` patches ``subprocess.{run,Popen,call,check_call,
check_output}`` for the duration of an unmarked test, so an unmarked test that
calls ``subprocess.run(...)`` fails naming itself. That is the only shape present
in this suite today, and for it the guard works.

It cannot see five others, each demonstrated by the Reviewer (26/08) starting a
real process from a wholly unmarked test with the guard installed:

* ``os.system`` - not a ``subprocess`` attribute at all, so nothing is patched on
  that path;
* ``os.popen`` - caught today, but only by accident and only sometimes: the
  guard's repo-code test resolves the frozen pseudo-filename ``<frozen os>``
  against the *process working directory*, so the same call classifies as repo
  code when pytest is launched from the repo and as third-party code when it is
  not;
* ``asyncio.create_subprocess_exec`` - on Windows this goes through
  ``asyncio.windows_utils.Popen``, which subclasses whatever ``subprocess.Popen``
  was bound at asyncio-import time. Import asyncio before the patch and the
  subclass holds the real class; import it after and the guard sees a stdlib
  caller frame and delegates. Either order bypasses it;
* a module-level ``from subprocess import run`` - the attribute is read during
  collection, before any fixture exists to patch it;
* a module-level alias (``_RUN = subprocess.run``) or a module-level
  ``class X(subprocess.Popen)`` - same import-time binding, same result.

The last three are absent from the suite today. The guard's own docstring says so
and calls the grep worth repeating - which is a note asking a person to remember.
This file is that grep, run by the lane.

**Why static, and why the guard is left alone.** These routes bind at import
time, so nothing running inside a test can intercept them; the check has to
happen before execution or not at all. It is deliberately a *second* instrument
rather than an extension of the runtime guard: the guard answers "is this test
shelling out right now", this answers "could this module shell out at all", and
merging them would make the fast lane depend on the slow one's mechanism.

**Structural, not textual.** The check parses each module and looks at nodes, so
prose is never a finding. That matters concretely: ``tests/conftest.py`` quotes
``from subprocess import run`` in its own docstring, and a grep-shaped
implementation of this check would have to carry an exemption for that line - a
known false positive is how a check earns a blanket suppression and then guards
nothing. It is also why this file needs no exemption for itself: it names the
shapes as strings in a table, and a string is not an import.

The limit of a structural check, stated so it is not mistaken for a total one:
it reads what the module declares, so ``exec("import subprocess")`` or
``__import__`` defeats it. It is a drift check, not an adversary.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

TESTS_ROOT = Path(__file__).resolve().parent

#: The ``subprocess`` callables the runtime guard patches. A module-level
#: reference to any of them is bound before the guard can replace it.
_SUBPROCESS_CALLABLES = frozenset(
    {"run", "Popen", "call", "check_call", "check_output"}
)

#: Process starters that never touch ``subprocess``, so the guard never sees
#: them wherever they appear - not only at module level.
_PROCESS_STARTERS: dict[str, frozenset[str]] = {
    "os": frozenset({"system", "popen"}),
    "asyncio": frozenset({"create_subprocess_exec", "create_subprocess_shell"}),
}

_WATCHED_MODULES = frozenset({"subprocess", *_PROCESS_STARTERS})


class Finding(NamedTuple):
    path: str
    line: int
    shape: str


def _module_is_slow(tree: ast.Module) -> bool:
    """True if the module carries ``pytestmark = pytest.mark.slow``.

    Module-level, because these bindings happen at import: a per-test marker
    arrives too late to say anything about what the module did on the way in.
    """
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            continue
        marks = node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) else [node.value]
        for mark in marks:
            if isinstance(mark, ast.Attribute) and mark.attr == "slow":
                return True
    return False


def _module_aliases(tree: ast.Module) -> dict[str, str]:
    """Local name -> watched stdlib module, following ``import x as y``."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in _WATCHED_MODULES:
                    aliases[a.asname or a.name] = a.name
    return aliases


def _module_level_nodes(tree: ast.Module):
    """Yield nodes that execute at import time.

    Descends through module-level ``if``/``try``/``with`` bodies - an import
    guarded by a conditional still runs during collection - but stops at any
    function or class body, which does not.
    """
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for field in ("body", "orelse", "finalbody", "handlers"):
            stack.extend(getattr(node, field, []) or [])


def _base_is_popen(base: ast.expr, aliases: dict[str, str], imported: set[str]) -> bool:
    if isinstance(base, ast.Attribute) and base.attr == "Popen":
        return isinstance(base.value, ast.Name) and aliases.get(base.value.id) == "subprocess"
    return isinstance(base, ast.Name) and base.id in imported


def scan(path: Path) -> list[Finding]:
    """Every import-time process-starting shape in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), str(path))
    if _module_is_slow(tree):
        return []

    rel = path.relative_to(TESTS_ROOT.parent).as_posix()
    aliases = _module_aliases(tree)
    findings: list[Finding] = []
    popen_imported: set[str] = set()

    # First pass, imports only. The loop below both fills this set (on ImportFrom)
    # and reads it (on ClassDef), and _module_level_nodes pops a stack, so nodes
    # arrive in reverse source order: `class X(Popen)` written after
    # `from subprocess import Popen` was inspected before the import was recorded,
    # and the class went unnamed (deviation 11). Collecting first makes the verdict
    # independent of traversal order rather than merely correct for the common
    # source ordering.
    for node in _module_level_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for a in node.names:
                if a.name == "Popen":
                    popen_imported.add(a.asname or a.name)

    # Anywhere in the module: a starter that bypasses `subprocess` entirely.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
            continue
        module = aliases.get(node.value.id)
        if module in _PROCESS_STARTERS and node.attr in _PROCESS_STARTERS[module]:
            findings.append(Finding(rel, node.lineno, f"{module}.{node.attr}"))

    # Import time only: bindings taken before the runtime guard exists.
    for node in _module_level_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module in _WATCHED_MODULES:
            watched = (
                _SUBPROCESS_CALLABLES
                if node.module == "subprocess"
                else _PROCESS_STARTERS[node.module]
            )
            for a in node.names:
                if a.name in watched:
                    findings.append(
                        Finding(rel, node.lineno, f"from {node.module} import {a.name}")
                    )
                    if node.module == "subprocess" and a.name == "Popen":
                        popen_imported.add(a.asname or a.name)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute):
            v = node.value
            if (
                isinstance(v.value, ast.Name)
                and aliases.get(v.value.id) == "subprocess"
                and v.attr in _SUBPROCESS_CALLABLES
            ):
                findings.append(
                    Finding(rel, node.lineno, f"module-level alias of subprocess.{v.attr}")
                )
        elif isinstance(node, ast.ClassDef):
            for base in node.bases:
                if _base_is_popen(base, aliases, popen_imported):
                    findings.append(
                        Finding(rel, node.lineno, f"class {node.name}(subprocess.Popen)")
                    )
    return sorted(set(findings))


def _modules() -> list[Path]:
    return sorted(
        p for p in TESTS_ROOT.rglob("*.py") if "__pycache__" not in p.parts
    )


def test_no_unmarked_module_can_start_a_process_at_import() -> None:
    """No module under tests/ takes a process-starting route the guard cannot see.

    A module that legitimately needs one carries ``pytestmark = pytest.mark.slow``,
    which is the same bargain the runtime guard offers: shell out if you must, but
    then say so, and stay out of the per-stage lane.
    """
    findings = [f for path in _modules() for f in scan(path)]
    assert not findings, (
        "These modules can start a process by a route the runtime guard in "
        "tests/conftest.py cannot intercept, and are not marked slow:\n"
        + "\n".join(f"  {f.path}:{f.line}  {f.shape}" for f in findings)
        + "\n\nEither add `pytestmark = pytest.mark.slow` to the module - the "
        "marker is what keeps it out of the per-stage gate - or use "
        "subprocess.<attr> directly, which the runtime guard does see."
    )
