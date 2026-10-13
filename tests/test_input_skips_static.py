"""No skip reason under ``tests/`` may interpolate a path (TESTLANE-01 B, P-B7).

The close check for ``tests/input_skips.py``. That module removes the class; this
one keeps it removed, because the failure mode is not "someone reverts the helper",
it is "someone adds the seventy-third call site by copying the seventy-second".

At G0, 17 of 21 distinct skip reasons on a fresh clone carried an absolute
``<drive>:\\Users\\<name>\\...`` path. A reason is built from a label and a register row
now, so a reason that formats a value into itself is the shape this stage removed
and it fails here naming its own line.

Static rather than runtime, for the same reason ``test_shellout_routes_static.py``
is: a skip only fires on a machine that lacks the input, so a runtime check would
be green on every machine that has the data and would never catch the regression on
the machine that matters.

**What this check does not catch, ruled rather than widened (TESTLANE-01 B).** It
looks for a reason built from a runtime value, because that is how a path reaches a
log. A *constant* reason that names no input at all - the ten
``"Required inputs missing"`` lines found by the AC-B4 fresh clone - is invisible to
it, and those were fixed at the call site instead. Widening the rule to "every
constant reason must name a register row" was rejected: it would fail the tesseract
line, which carries install instructions for three platforms and is more useful than
a label, and the two non-input fixture-state reasons. The limit is therefore real and
recorded here; the fresh-clone ``-rs`` sweep, not this file, is what finds the next
anonymous constant.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent

#: The helper is allowed to format a reason - that is its job.
_EXEMPT_FILES = frozenset({"input_skips.py"})

#: Reasons that interpolate something which is provably not a path. Each carries the
#: reason it is safe, in the file, rather than in a commit message nobody re-reads.
#:
#: Keyed on (file, enclosing function, the reason's leading text) - never on a line
#: number. A line key moves with every unrelated edit above the site: on 11/09/2026 an
#: import added for ARM64ULP-01 shifted one of these by a line and redded the stage lane
#: (EXEMPTKEY-01). The leading text keeps the key from widening to every formatted
#: reason in the same function.
_EXEMPT_SITES: frozenset[tuple[str, str, str]] = frozenset({
    # Interpolates the project name and the env var's own name, never a path. The
    # reason has to say which project and which variable to set, and both are
    # repo-level identifiers a CI log should carry.
    ("tests/golden/test_golden.py", "test_golden", "confidential golden "),
    # The path was removed from these two in TESTLANE-01 B. What is left is the
    # input's key in the fixture, the guard variable's own name, and the register
    # pointer - the three things the reader needs and none of them a path.
    ("tests/test_qraxl01_0_bit_identity.py", "_require_inputs", "confidential-tier input '"),
    ("tests/test_qraxl01_0_bit_identity_10k.py", "_require_inputs", "confidential-tier input '"),
})


class _Finding:
    __slots__ = ("path", "line", "shape")

    def __init__(self, path: str, line: int, shape: str) -> None:
        self.path, self.line, self.shape = path, line, shape

    def __repr__(self) -> str:  # pragma: no cover - only shown on failure
        return f"{self.path}:{self.line}  {self.shape}"


def _is_formatted(node: ast.expr | None) -> bool:
    """True if the expression builds a string from a runtime value.

    Covers the two shapes that carried paths: an f-string (``ast.JoinedStr`` with a
    ``FormattedValue`` part) and explicit ``"...".format(...)`` / ``"..." % x``.
    A plain constant string is fine - it cannot carry this machine's path.
    """
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(p, ast.FormattedValue) for p in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return isinstance(node.left, ast.Constant)
    if isinstance(node, ast.Call):
        func = node.func
        return isinstance(func, ast.Attribute) and func.attr == "format"
    return False


def _skip_reason_nodes(tree: ast.Module):
    """Yield ``(node, reason_expr)`` for every skip site that states a reason."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")

        # pytest.skip("reason") / pytest.skip(reason="...")
        if name == "skip":
            if node.args:
                yield node, node.args[0]
            for kw in node.keywords:
                if kw.arg in (None, "reason", "msg"):
                    yield node, kw.value

        # pytest.mark.skipif(cond, reason="..."), and xfail, which is read the same way
        elif name in ("skipif", "xfail"):
            for kw in node.keywords:
                if kw.arg == "reason":
                    yield node, kw.value


def _leading_text(reason: ast.expr) -> str:
    """The constant a formatted reason starts with - the part of it that identifies it."""
    if isinstance(reason, ast.JoinedStr) and reason.values and isinstance(reason.values[0], ast.Constant):
        return str(reason.values[0].value)
    if isinstance(reason, ast.BinOp) and isinstance(reason.left, ast.Constant):
        return str(reason.left.value)
    if isinstance(reason, ast.Call) and isinstance(getattr(reason.func, "value", None), ast.Constant):
        return str(reason.func.value.value)
    return ""


def _function_at(tree: ast.Module, line: int) -> str:
    """The innermost function enclosing a line, or "" at module level."""
    best = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.lineno <= line <= n.end_lineno:
            if best is None or n.lineno > best.lineno:
                best = n
    return best.name if best else ""


def scan_source(src: str, rel: str) -> list[_Finding]:
    tree = ast.parse(src, filename=rel)
    out: list[_Finding] = []
    for node, reason in _skip_reason_nodes(tree):
        if not _is_formatted(reason):
            continue
        if (rel, _function_at(tree, node.lineno), _leading_text(reason)) in _EXEMPT_SITES:
            continue
        out.append(_Finding(rel, node.lineno, ast.dump(reason)[:60]))
    return out


def scan(path: Path) -> list[_Finding]:
    return scan_source(path.read_text(encoding="utf-8"), path.relative_to(TESTS_ROOT.parent).as_posix())


_HELPERS = frozenset({
    "skip_reason", "skip_reason_all", "skip_missing", "skip_missing_all", "skip_locked",
})

#: Attribute calls that return a bool, so passing one where a path belongs is the typo.
_PREDICATES = frozenset({"exists", "is_file", "is_dir"})


def _looks_boolean(node: ast.expr) -> bool:
    if isinstance(node, (ast.Compare, ast.BoolOp, ast.UnaryOp)):
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _PREDICATES
    )


def scan_helper_args(path: Path) -> list[_Finding]:
    """Find helper calls handed a guard expression instead of the thing it guarded.

    A second class, added after review found one live instance (P-B7 close). The check
    above cannot see it: the reason is not formatted at the call site, it is built by
    the helper, which this file exempts because that is the helper's job. But
    ``skip_reason(p.exists())`` describes ``True`` as the label "True" and renders
    "True not available" - a reason naming nothing, reintroduced *through* the module
    that exists to prevent it.

    ``describe()`` also raises ``TypeError`` on a bool, which is the loud version. This
    is the early version: the runtime guard only fires on a machine that lacks the
    input, which is precisely the machine nobody is watching.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(TESTS_ROOT.parent).as_posix()
    out: list[_Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in _HELPERS:
            continue
        args = list(node.args) + [
            kw.value for kw in node.keywords if kw.arg in ("label", "register", "detail")
        ]
        for a in args:
            if _looks_boolean(a):
                out.append(_Finding(rel, node.lineno, f"{name}(<boolean>)"))
                break
    return out


def _modules() -> list[Path]:
    return sorted(
        p
        for p in TESTS_ROOT.rglob("*.py")
        if "__pycache__" not in p.parts and p.name not in _EXEMPT_FILES
    )


def test_no_skip_reason_interpolates_a_value() -> None:
    findings = [f for path in _modules() for f in scan(path)]
    assert not findings, (
        "These skip reasons build themselves from a runtime value, which is how an "
        "absolute path carrying a username reaches a CI log (P-B7; 17 of 21 distinct "
        "reasons did at G0):\n"
        + "\n".join(f"  {f!r}" for f in findings)
        + "\n\nUse tests/input_skips.py - skip_missing(path) / skip_locked(path), or "
        "skip_reason(path, ...) for a skipif - which names the input by label and the "
        "register row. If a reason genuinely must interpolate something that is not a "
        "path, add it to _EXEMPT_SITES with the reason it is safe."
    )


def test_no_helper_call_is_handed_a_guard_expression() -> None:
    findings = [f for path in _modules() for f in scan_helper_args(path)]
    assert not findings, (
        "These call sites pass a boolean - almost always `p.exists()` where `p` "
        "belongs - so the reason renders as 'True not available' and names no input:\n"
        + "\n".join(f"  {f!r}" for f in findings)
        + "\n\nPass the path itself: skip_reason(p), not skip_reason(p.exists())."
    )


def test_the_boolean_check_can_actually_fail() -> None:
    """Positive control for the second class, in the shape review actually found."""
    src = (
        "from tests.input_skips import skip_reason\n"
        "import pytest\n"
        "pytest.skip(skip_reason(cfg.xer_path.exists(), "
        "label=cfg.register_path.exists()))\n"
    )
    tree = ast.parse(src)
    hits = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", getattr(n.func, "attr", "")) in _HELPERS
        and any(
            _looks_boolean(a)
            for a in list(n.args)
            + [kw.value for kw in n.keywords if kw.arg in ("label", "register", "detail")]
        )
    ]
    assert hits, (
        "the boolean-argument scanner no longer matches the shape it was written for, "
        "so test_no_helper_call_is_handed_a_guard_expression cannot fail"
    )


def test_the_check_can_actually_fail() -> None:
    """The positive control, run every time rather than remembered.

    A static scan that has never been shown failing is indistinguishable from one
    whose matcher stopped matching - which is exactly what a refactor of
    ``_skip_reason_nodes`` would do silently.
    """
    src = 'import pytest\np = "/x"\npytest.skip(f"missing: {p}")\n'
    tree = ast.parse(src)
    assert [r for _, r in _skip_reason_nodes(tree) if _is_formatted(r)], (
        "the scanner no longer recognises an f-string skip reason, so "
        "test_no_skip_reason_interpolates_a_value cannot fail and is not evidence"
    )


def test_an_exempt_site_survives_a_line_added_above_it() -> None:
    """EXEMPTKEY-01. The exemption was keyed on a line number, so an unrelated import added
    above the site (ARM64ULP-01, 11/09/2026) moved it and redded the stage lane. Keyed on the
    function and the reason's own text, a moved site is not a finding."""
    rel = "tests/test_qraxl01_0_bit_identity_10k.py"
    src = (TESTS_ROOT.parent / rel).read_text(encoding="utf-8")
    assert not scan_source(src, rel)
    assert not scan_source("# a line added above everything\n\n" + src, rel)


def test_an_exempt_function_does_not_exempt_a_different_reason() -> None:
    """The key is not the function alone: a new formatted reason inside an exempt function
    is still a finding."""
    rel = "tests/test_qraxl01_0_bit_identity_10k.py"
    src = "import pytest\ndef _require_inputs(p):\n    pytest.skip(f'missing: {p}')\n"
    assert [f.line for f in scan_source(src, rel)] == [3]
