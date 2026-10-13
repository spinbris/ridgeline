"""PROCDIET-01 A5: compute a change's track from what it does, not from the Builder's say-so.

Track N if any of these holds, otherwise Track L:
- a ``src/`` Python file whose AST differs once docstrings, and the wording of messages (strings
  inside ``raise``, ``print``, ``warnings.warn`` and logger calls), are set aside;
- a ``src/`` file added, deleted, or not Python;
- a change to inputs, goldens or methodology text (``N_PATHS`` below);
- a change to the gate's own files (``GATE_PATHS`` below, GATEHOLD-01 P3).

A headline that moves is Track N too, and the audit lane's output pack reds it; this script does
not repeat that check.

Usage:
    python scripts/track.py <base-ref> [<head-ref>]   # prints "track=L" or "track=N", then reasons
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.git_identity import git_env  # noqa: E402

#: Prefixes that are Track N by path: inputs, goldens and methodology text.
N_PATHS = (
    "tests/fixtures/",
    "tests/golden/",
    "status_periods/",
    "METHODOLOGY.md",
)

#: The gate's own files: the audit list, the scripts the audit lane and ``ci.yml`` run, and the
#: workflows. An edit that drops a line from the list, or defangs the pack, is Track N. The flow
#: guard's escalation 1 names every one of them, and the guard's own tests hold that.
GATE_PATHS = (
    "tests/audit_lane.txt",
    "scripts/track.py",
    "scripts/audit_lane.py",
    "scripts/output_pack.py",
    "scripts/ws4a_repro_gate.py",
    ".github/workflows/",
)

_MESSAGE_CALLS = {"print", "warn", "debug", "info", "warning", "error", "exception", "critical"}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          check=True, env=git_env()).stdout


class _SetAside(ast.NodeTransformer):
    """Drops docstrings, and blanks string literals that are message wording."""

    def _strip_docstring(self, node):
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
        return node

    def visit_Module(self, node):
        return self.generic_visit(self._strip_docstring(node))

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = visit_Module

    def _blank(self, node):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                sub.value = ""
        return node

    def visit_Raise(self, node):
        return self._blank(node)

    def visit_Call(self, node):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in _MESSAGE_CALLS:
            for arg in [*node.args, *(k.value for k in node.keywords)]:
                self._blank(arg)
        return self.generic_visit(node)


def logic(source: str) -> str:
    return ast.dump(_SetAside().visit(ast.parse(source)), include_attributes=False)


def classify(base: str, head: str = "HEAD") -> tuple[str, list[str]]:
    reasons: list[str] = []
    changes = _git("diff", "--name-status", "--no-renames", f"{base}...{head}").splitlines()
    for line in changes:
        status, path = line.split("\t", 1)
        if path.startswith(N_PATHS):
            reasons.append(f"{path}: inputs, goldens or methodology text")
        elif path.startswith(GATE_PATHS):
            reasons.append(f"{path}: the gate's own files")
        elif path.startswith("src/"):
            if status != "M" or not path.endswith(".py"):
                reasons.append(f"{path}: {status} in src/")
                continue
            merge_base = _git("merge-base", base, head).strip()
            before = _git("show", f"{merge_base}:{path}")
            after = _git("show", f"{head}:{path}")
            if logic(before) != logic(after):
                reasons.append(f"{path}: logic changed")
    return ("N" if reasons else "L"), reasons


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    track, reasons = classify(*argv[1:])
    print(f"track={track}")
    for r in reasons:
        print(f"  {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
