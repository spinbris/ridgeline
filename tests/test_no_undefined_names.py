"""No function reads a name that cannot exist. Fast, whole-tree, static.

SHOWCASE-RENDER-01. `scripts/run_wind_showcase.py` referenced `sb` from
`render()`, where it is a local of `_render_sra_schedule_md()` — a refactor
extracted the helper and left the use behind. The script therefore could not
finish, in this repository or the one it was cut from, and had not been able to
for an unknown length of time.

WHY THIS TEST AND NOT ONLY A SMOKE TEST
    The smoke test in `test_showcase_smoke.py` runs the entry point and would
    have caught that one instance. This catches the CLASS, across every module
    in `src/`, `scripts/` and `tools/`, in well under a second and without
    executing anything. Most of those modules have no end-to-end test and never
    will — a script that is run by hand twice a year cannot justify a slow test,
    but it can justify this one.

HOW IT WORKS, AND WHAT IT CANNOT SEE
    `symtable` classifies each name in each scope. A name that a function READS,
    that it never assigns, that is not a module-level binding and not a builtin,
    can only resolve at runtime by luck. That is exactly the shape of the defect.

    It cannot see names created dynamically — `globals()[...] = x`, star-imports,
    or attributes. Star-imports would produce false positives rather than misses,
    and there are none in the scanned trees today. If one is added, this test
    will say so, and the fix is to name the imports rather than to weaken this.
"""
from __future__ import annotations

import builtins
import symtable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("src", "scripts", "tools")

#: Module-level dunders exist at runtime but are not symtable module symbols.
_MODULE_DUNDERS = {
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__debug__",
}
_ALWAYS_DEFINED = set(dir(builtins)) | _MODULE_DUNDERS


def _undefined_names_in(path: Path) -> list[tuple[str, str]]:
    """[(qualified scope, name)] for names read but never bound."""
    try:
        source = path.read_text(encoding="utf-8")
        table = symtable.symtable(source, path.name, "exec")
    except (SyntaxError, UnicodeDecodeError):
        return []
    module_level = {s.get_name() for s in table.get_symbols()}
    found: list[tuple[str, str]] = []

    def walk(scope: symtable.SymbolTable, prefix: str = "") -> None:
        for child in scope.get_children():
            for sym in child.get_symbols():
                name = sym.get_name()
                if (
                    sym.is_global()
                    and not sym.is_assigned()
                    and name not in module_level
                    and name not in _ALWAYS_DEFINED
                ):
                    found.append((f"{prefix}{child.get_name()}", name))
            walk(child, f"{prefix}{child.get_name()}.")

    walk(table)
    return found


def _scan() -> list[str]:
    out = []
    for root in SCANNED:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            out += [f"{rel}::{scope}() reads {name!r}" for scope, name in _undefined_names_in(path)]
    return out


def test_scan_actually_reaches_the_modules():
    """The check must not pass by scanning nothing.

    A whole-tree scan that silently matches no files reports zero problems and
    looks identical to a clean tree, which is the failure mode this suite has
    been bitten by more than once.
    """
    scanned = [
        p for root in SCANNED
        for p in (REPO_ROOT / root).rglob("*.py")
        if "__pycache__" not in p.parts
    ]
    assert len(scanned) > 100, (
        f"only {len(scanned)} modules scanned across {SCANNED}; the scan is not "
        "reaching the tree, so a clean result would mean nothing."
    )


def test_no_function_reads_an_undefined_name():
    problems = _scan()
    assert not problems, (
        "A function reads a name that cannot resolve — it will raise NameError "
        "the moment that line runs:\n  " + "\n  ".join(problems)
    )
