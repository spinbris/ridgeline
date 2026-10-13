"""Showcase-P2 WS2-C — static portability regression guards.

Asserts that engine code in ``src/`` carries no project-specific identifiers, so the framework
stays project-agnostic and future code cannot reintroduce hardcoding. Two bans:

1. No bare legacy chain IDs (``R076``/``R015``/``R017``/``R018``/``R019``) outside
   ``bindings/``. Dotted production risk IDs (``R015.1``, ``R017.1``, …) are legitimate
   register data and are allowed (brief §4A.3). AST-based: string *literals* only.
2. **No mention of the retired reference project anywhere in ``src/``** - not as a literal, an
   identifier, a module name, a docstring or a comment, and with no ``bindings/`` exemption.

Ban 2 widened at REFRETIRE-01, in two directions at once. It was scoped to string literals
outside ``bindings/``, which left the project's name in 109 comments and docstrings and in the
binding module itself - and a name in a comment is what tells the next reader that a retired
project is still live. The history belongs in ``docs/``, where it is dated and can be read in
order; the code says what it does now.

Exemptions:
- Ban 1 only: ``src/sra/cpm/bindings/`` — a binding is the home for its own project's values.
- A line carrying a ``# portability-ok`` pragma (escape hatch for a deliberate, reviewed
  exception; none currently used).

If this test fails, move the offending value into the active project binding, or write the
sentence without the project's name — do not suppress the guard.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
BINDINGS_DIR = SRC_ROOT / "sra" / "cpm" / "bindings"

# Bare legacy chain IDs, NOT followed by a dot (so dotted production IDs
# like R015.1 / R017.1 are not matched — they are legitimate data).
_BARE_LEGACY_ID = re.compile(r"\bR0(?:76|15|17|18|19)\b(?!\.)")
_PRAGMA = "# portability-ok"


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    """ids() of the Constant nodes that are module/class/function docstrings."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
    return out


def _string_literal_violations(pattern_check) -> list[str]:
    """Return ``"path:line: <snippet>"`` for non-docstring string literals
    in ``src/`` (excluding ``bindings/``) whose value trips ``pattern_check``.
    """
    violations: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if BINDINGS_DIR in path.parents:
            continue
        source = path.read_text(encoding="utf-8")
        source_lines = source.splitlines()
        tree = ast.parse(source, filename=str(path))
        doc_ids = _docstring_node_ids(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in doc_ids:
                continue
            line_idx = getattr(node, "lineno", 1) - 1
            if 0 <= line_idx < len(source_lines) and _PRAGMA in source_lines[line_idx]:
                continue
            if pattern_check(node.value):
                snippet = node.value[:60].replace("\n", " ")
                violations.append(f"{path.relative_to(SRC_ROOT.parent)}:{node.lineno}: {snippet!r}")
    return violations


def test_no_bare_legacy_chain_ids_in_engine_src():
    """No bare legacy chain IDs in engine code outside bindings/."""
    violations = _string_literal_violations(lambda v: bool(_BARE_LEGACY_ID.search(v)))
    assert not violations, (
        "Bare legacy chain IDs (R076/R015/R017/R018/R019) found in src/ "
        "outside bindings/. Move them to the active binding's "
        "LEGACY_CHAIN_IDS:\n  " + "\n  ".join(violations)
    )


#: The retired reference project, spelt as it appeared: module name, symbol prefix, prose.
_RETIRED_PROJECT = re.compile(r"refproject", re.IGNORECASE)


def _text_violations(pattern, root: Path = SRC_ROOT, *, skip_bindings: bool = False):
    """``"path:line: <line>"`` for every line under ``root`` matching ``pattern``.

    Whole-text, not AST: a comment and a docstring are exactly what these bans are about, and
    they are invisible to a literal scan. ``bindings/`` is included by default - REFRETIRE-01
    retired the binding that was the one legitimate home for the retired project's name - and
    ``skip_bindings`` excludes it for a ban whose legitimate home it still is.
    """
    violations = []
    for path in sorted(root.rglob("*.py")):
        if skip_bindings and BINDINGS_DIR in path.parents:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _PRAGMA in line:
                continue
            if pattern.search(line):
                violations.append(
                    f"{path.relative_to(SRC_ROOT.parent)}:{lineno}: {line.strip()[:80]!r}")
    return violations


def test_the_retired_project_is_not_named_anywhere_in_src():
    """REFRETIRE-01 P-3: no module, symbol, default, import, string, docstring or comment in
    ``src/`` names the retired reference project."""
    violations = _text_violations(_RETIRED_PROJECT)
    assert not violations, (
        "the retired reference project is named in src/. Its binding retired at REFRETIRE-01: "
        "move the value into the active project's binding, or write the sentence without the "
        "name - the history is in docs/, dated:\n  " + "\n  ".join(violations)
    )


#: Any register risk id, dotted or not. A risk id is a fact about one project's register;
#: PRESENT-01 (P-3) is that no text the deliverable is built from states one.
_ANY_RISK_ID = re.compile(r"\bR\d{3}(?:\.\d)?\b")

FINAL_ROOT = SRC_ROOT / "final"


def test_no_risk_id_literal_in_the_deliverables_text_layer():
    """PRESENT-01 P-3: nothing under ``src/final/`` names a risk by id.

    Every string the deliverable renders, and every comment explaining one, belongs to the
    product rather than to a project. A run knows its own risk ids; a constant does not. The
    scan is whole-text because the sites this brief removed were comments and docstrings as
    often as they were rendered strings, and a literal-only scan would have missed most of them.

    The ban is ``src/final/`` because that is where P-3 draws it. The engine and reader modules
    still carry roughly seventy such literals, almost all in explanatory comments; widening the
    ban to all of ``src/`` is PROJFACT-01.
    """
    violations = _text_violations(_ANY_RISK_ID, FINAL_ROOT)
    assert not violations, (
        "a risk id is named in src/final/. Derive it from the run (the drivers carry their own "
        "ids), resolve it from the active binding, or write the sentence without it - a "
        f"deliberate, reviewed exception carries a {_PRAGMA!r} pragma on the line:\n  "
        + "\n  ".join(violations)
    )


def test_the_risk_id_guard_would_catch_what_it_bans():
    """Guard sanity: the pattern matches the shapes this ban exists for, in either form."""
    for banned in ("R067", "R090", "R017.1", "R026.1", "R001"):
        assert _ANY_RISK_ID.search(banned), f"guard missed {banned}"
    for legit in ("WT01", "KH12", "CG05", "R67", "20.C.95.EI.466"):
        assert not _ANY_RISK_ID.search(legit), f"guard wrongly matched {legit}"


def test_dotted_production_ids_are_allowed():
    """Guard sanity: dotted production IDs must NOT trip the legacy-id ban
    (else the guard would false-positive on legitimate register data)."""
    for legit in ("R015.1", "R017.1", "R016.2", "R026.1"):
        assert not _BARE_LEGACY_ID.search(legit), f"guard wrongly matched {legit}"
    for banned in ("R076", "R015", "R017", "R018", "R019"):
        assert _BARE_LEGACY_ID.search(banned), f"guard missed {banned}"
