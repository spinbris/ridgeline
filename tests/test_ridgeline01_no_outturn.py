"""RIDGELINE-01 P6: the published figure is never called an outturn (R-12).

GN4 Appendix C reserves "outturn" for the post-escalation nominal figure, and this product
publishes the real-terms event-risk contingency. Every string literal that can reach a
deliverable - the deliverable layer, the shipped bindings' narrative, and the report notebook - is
scanned. Comments and docstrings are not rendered and are not scanned.

Three allowances, each named by the assignment that holds it, never by line number:
  - ``MEAN_FOOTNOTE_TEXT`` names a contract type, "target outturn cost";
  - ``_ESCALATION_HANDOFF`` is the GN4 disclaimer, which uses the word to disown it;
  - ``contract_terms._TERMS`` renders only for a ``target_outturn_cost`` binding, and none ships.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORD = re.compile(r"outturn", re.I)

SCANNED = sorted(
    [*(REPO / "src" / "final").rglob("*.py"),
     *(p for p in (REPO / "src" / "sra" / "cpm" / "bindings").glob("*.py")
       if p.stem not in ("__init__", "registry"))])
ALLOWED = {
    ("src/final/commentary_text.py", "MEAN_FOOTNOTE_TEXT"),
    ("src/final/stage3_beta_report.py", "_ESCALATION_HANDOFF"),
    ("src/final/contract_terms.py", "_TERMS"),
}


def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _owner(stmt: ast.stmt) -> str | None:
    """The name a top-level statement assigns, if it is an assignment."""
    targets = stmt.targets if isinstance(stmt, ast.Assign) else (
        [stmt.target] if isinstance(stmt, ast.AnnAssign) else [])
    names = [t.id for t in targets if isinstance(t, ast.Name)]
    return names[0] if names else None


def outturn_strings(source: str, rel: str) -> list[str]:
    tree = ast.parse(source)
    skip = _docstrings(tree)
    hits = []
    for stmt in tree.body:
        if (rel, _owner(stmt)) in ALLOWED:
            continue
        for node in ast.walk(stmt):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in skip and WORD.search(node.value)):
                hits.append(f"{rel}:{node.lineno}: {node.value!r}")
    return hits


def test_the_scan_covers_the_deliverable_layer_and_the_shipped_bindings():
    rels = {p.relative_to(REPO).as_posix() for p in SCANNED}
    assert "src/final/composer.py" in rels and "src/final/word_generator.py" in rels
    assert "src/sra/cpm/bindings/synthetic_wind.py" in rels
    for rel, _ in ALLOWED:
        assert rel in rels, f"an allowance names a file the scan no longer reads: {rel}"


def test_no_rendered_string_calls_the_figure_an_outturn():
    hits = []
    for path in SCANNED:
        rel = path.relative_to(REPO).as_posix()
        hits += outturn_strings(path.read_text(encoding="utf-8"), rel)
    assert not hits, "R-12: the published figure is not an outturn:\n  " + "\n  ".join(hits)


def test_the_report_notebook_does_not_call_it_an_outturn():
    nb = json.loads((REPO / "final_runner.ipynb").read_text(encoding="utf-8"))
    sources = ["".join(c["source"]) for c in nb["cells"]]
    sources.append(json.dumps(nb["metadata"]))
    assert not [s for s in sources if WORD.search(s)]


#: The app's rendered surface (ruling R-7): routes, components and the strings they import from
#: lib/ (round 1, W5). Not tests.
APP_DIRS = ("dashboard/app", "dashboard/components", "dashboard/lib")
#: Identifiers, which nothing renders and D-4 keeps (round 1, W5: only where they ARE identifiers,
#: so "outturns" in a rendered string still reds): import statements, JSX tag names, and the name
#: a declaration introduces.
_IMPORT = re.compile(r"""^\s*import\b[^;]*?["'][^"'\n]*["'];?""", re.M | re.S)
_TAG_NAME = re.compile(r"(</?)\s*[A-Za-z_][\w.]*")
_DECLARED = re.compile(r"\b(function|const|let|var|class|interface|type|enum)\s+[A-Za-z_$][\w$]*")


def strip_ts_comments(source: str) -> str:
    """Remove comments, and nothing inside a string (round 1, W5).

    A regex cannot tell ``//`` in ``"a // b"`` or ``https://`` from a comment, and ate the rest of
    the line. An apostrophe after a letter is JSX text ("What's"), not a string opening.
    """
    out, i, n, quote = [], 0, len(source), None
    while i < n:
        c = source[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(source[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"`" or (c == "'" and not (i and source[i - 1].isalnum())):
            quote = c
            out.append(c)
            i += 1
            continue
        if source.startswith("/*", i):
            j = source.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if source.startswith("//", i) and not (i and source[i - 1] == ":"):
            j = source.find("\n", i)
            i = n if j < 0 else j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def app_outturn_lines(source: str) -> list[str]:
    text = strip_ts_comments(source)
    text = _DECLARED.sub(r"\1", _TAG_NAME.sub(r"\1", _IMPORT.sub("", text)))
    return [ln.strip() for ln in text.splitlines() if re.search(r"outturn", ln, re.I)]


def test_the_app_does_not_call_it_an_outturn():
    hits = []
    for d in APP_DIRS:
        for path in sorted((REPO / d).rglob("*.tsx")) + sorted((REPO / d).rglob("*.ts")):
            rel = path.relative_to(REPO).as_posix()
            hits += [f"{rel}: {ln}" for ln in app_outturn_lines(path.read_text(encoding="utf-8"))]
    assert not hits, "R-12: the app calls the figure an outturn:\n  " + "\n  ".join(hits)


def test_the_app_scan_covers_lib():
    assert "dashboard/lib" in APP_DIRS


@pytest.mark.parametrize("rendered", [
    '<Card title="Integrated outturn (cost + schedule)">',
    "<p>Two outturns, compared</p>",
    '<Card title="cost // schedule outturn">',
    "<p>See https://example.org for the outturn</p>",
    "const LABEL = `P80 outturn`;",
])
def test_the_app_scan_reds_on_each_rendered_shape(rendered):
    assert app_outturn_lines(rendered), rendered


def test_the_app_scan_passes_identifiers_and_comments():
    assert not app_outturn_lines(
        'import { IntegratedOutturnCard } from "@/components/IntegratedOutturnCard";\n'
        "/** The integrated outturn. */\n{/* Integrated outturn (contract 1.4) */}\n"
        "export function IntegratedOutturnCard({ a }: Props) {\n"
        "  return <IntegratedOutturnCard a={a} />; // outturn in a comment\n"
        "}\n<p>What's here</p>\n")


def test_no_shipped_binding_declares_the_target_outturn_cost_contract():
    """Round 1, N1: the ``_TERMS`` allowance is safe only while no shipped binding selects it."""
    from src.sra.cpm.bindings import get_binding

    shipped = sorted(p.stem for p in (REPO / "src" / "sra" / "cpm" / "bindings").glob("*.py")
                     if p.stem not in ("__init__", "registry"))
    assert shipped
    declared = {n: get_binding(n).contract_type for n in shipped}
    assert "target_outturn_cost" not in declared.values(), declared


def test_each_allowance_still_holds_the_word_it_is_allowed():
    """An allowance that no longer matches anything is a hole waiting for a new string."""
    for rel, name in ALLOWED:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        stmt = next(s for s in tree.body if _owner(s) == name)
        assert WORD.search(ast.unparse(stmt)), f"{rel}:{name} no longer uses the word"


def test_the_scan_reds_on_the_strings_it_replaced():
    doctored = 'LABEL = "Cost outturn (integrated cost arm)"\n'
    assert outturn_strings(doctored, "src/final/composer.py")
    assert not outturn_strings('"""A docstring about outturn."""\n# outturn\n', "example")
