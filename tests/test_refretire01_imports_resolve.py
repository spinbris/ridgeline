"""REFRETIRE-01 P-6: nothing left in the tree imports what retired.

A retirement that deletes a module leaves importers behind, and an importer only fails when
someone runs it. Most of the scripts here are not run by any test, so a stale import would sit
undetected until a person reached for one - which is exactly when it is least welcome.

This walks every tracked Python file in ``src/``, ``scripts/``, ``tools/`` and ``tests/``,
reads its imports **statically** (nothing is executed - a script that runs an engine at import
must not run here), and for each first-party import checks two things:

1. the module it names exists;
2. the symbol it names exists in that module, at module scope.

Symbol resolution reads the target's AST for top-level ``def`` / ``class`` / assignment /
``import`` names. Star imports are skipped, and so is every symbol import from a module that
defines names conditionally (a top-level ``if`` / ``try`` / ``with``, including
``if TYPE_CHECKING:``) or re-exports through a module-level ``__getattr__`` (``src.defaults``
does this deliberately), because neither can be settled without running the code.

**What that leaves.** The symbol half is best-effort and skips those targets; the module half -
does the module exist at all - applies everywhere, and it is the half a retirement needs. The
walk globs the files present rather than the files git tracks, which fails safe: an untracked
file is checked too.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ROOTS = ("src", "scripts", "tools", "tests")
FIRST_PARTY = {"src", "scripts", "tools", "tests"}


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            files.append(path)
    return files


def _module_path(dotted: str) -> Path | None:
    """The file a first-party dotted module name resolves to, or None."""
    parts = dotted.split(".")
    base = REPO.joinpath(*parts)
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _module_level_names(path: Path) -> set[str] | None:
    """Names a module defines at module scope, or None when it cannot be read statically."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:  # pragma: no cover - a syntax error is another test's business
        return None
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            if node.name == "__getattr__":
                return None    # module-level __getattr__: names resolve at run time
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.If, ast.Try, ast.With)):
            return None      # conditional definitions: cannot settle statically
    return names


def _first_party_imports(path: Path) -> list[tuple[str, str | None, int]]:
    """``(module, symbol | None, lineno)`` for each first-party import in ``path``."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:  # pragma: no cover
        return []
    # An import a test deliberately expects to FAIL is not a stale import: it is the check
    # that a retirement stayed retired. Skip the body of a ``with pytest.raises(ImportError)``.
    expected_to_fail: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With) and any(
            isinstance(item.context_expr, ast.Call)
            and "raises" in ast.dump(item.context_expr.func)
            for item in node.items
        ):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    expected_to_fail.add(sub.lineno)

    out: list[tuple[str, str | None, int]] = []
    for node in ast.walk(tree):
        if getattr(node, "lineno", None) in expected_to_fail:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FIRST_PARTY:
                    out.append((alias.name, None, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue      # relative import: resolved against the package, skipped
            if node.module.split(".")[0] not in FIRST_PARTY:
                continue
            for alias in node.names:
                out.append((node.module, None if alias.name == "*" else alias.name, node.lineno))
    return out


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_every_first_party_import_resolves(path: Path) -> None:
    unresolved: list[str] = []
    for module, symbol, lineno in _first_party_imports(path):
        target = _module_path(module)
        if target is None:
            unresolved.append(f"line {lineno}: module {module!r} does not exist")
            continue
        if symbol is None:
            continue
        if _module_path(f"{module}.{symbol}") is not None:
            continue          # importing a submodule, not a name
        names = _module_level_names(target)
        if names is None:
            continue          # the target defines names conditionally; cannot settle statically
        if symbol not in names:
            unresolved.append(
                f"line {lineno}: {module!r} defines no {symbol!r} at module scope")
    assert not unresolved, (
        f"{path.relative_to(REPO)} imports what is not there:\n  " + "\n  ".join(unresolved)
    )
