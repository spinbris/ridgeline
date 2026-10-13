"""SEEDZERO-01 P2: no seed in ``src/`` or ``scripts/`` is a code default.

The Director, 11/10/2026: "we did not want any seed hardcoded". A seed declared as data - a binding,
the golden registry, a baseline's own record, a register cell - is a stated source. A seed that a
function, field, argparse option, module constant or ``or``/``else`` fallback supplies when its caller
gave none is not, and this guard finds the shapes that do it.

What it does not police, by the PM's ruling on result ``-1`` (D6(b)): a literal written at a call in
``scripts/`` (``seed=42`` in a one-off diagnostic) is the script author stating a seed, not a default.
In ``src/`` a literal seed at a call is still flagged, because engine code has no business choosing one.

A tripwire, not a proof: it reads the syntax, so a seed reached through an alias it does not know is
invisible to it. Each planted shape below shows that the shapes it claims are caught.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCANNED = ("src", "scripts")
#: A binding is declared data (the brief's §0): its literal seed is a stated source, as a script's is.
DECLARED_DATA = "src/sra/cpm/bindings/"
_SEED = re.compile(r"seed", re.IGNORECASE)


def _is_seed_name(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return bool(_SEED.search(node.id))
    if isinstance(node, ast.Attribute):
        return bool(_SEED.search(node.attr))
    return False


def _mentions_seed(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if _is_seed_name(sub):
            return True
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and _SEED.search(sub.value):
            return True
    return False


def _seed_value(node: ast.AST | None) -> bool:
    """A literal that would run as a seed: an int, or a string of digits."""
    if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
        return False
    if isinstance(node.value, int):
        return True
    return isinstance(node.value, str) and node.value.strip().isdigit()


def _defaults(fn: ast.FunctionDef | ast.AsyncFunctionDef):
    a = fn.args
    positional = a.posonlyargs + a.args
    pairs = list(zip(positional[len(positional) - len(a.defaults):], a.defaults))
    pairs += [(arg, d) for arg, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
    return pairs


def seed_defaults(source: str, *, in_src: bool) -> list[tuple[int, str]]:
    """Every seed default in ``source``, as (line, shape)."""
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg, default in _defaults(node):
                if _SEED.search(arg.arg) and (_seed_value(default) or _is_seed_name(default)):
                    found.append((default.lineno, f"parameter {arg.arg!r} defaults to a seed"))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _SEED.search(node.target.id) and _seed_value(node.value):
                found.append((node.lineno, f"field or constant {node.target.id!r} is a seed"))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names = target.elts if isinstance(target, ast.Tuple) else [target]
                values = (node.value.elts if isinstance(node.value, ast.Tuple)
                          and isinstance(target, ast.Tuple) else [node.value] * len(names))
                for name, value in zip(names, values):
                    # `config.random_seed = 42` in a script states a seed (D6(b)); in src/ it hard-codes one.
                    if isinstance(name, ast.Attribute) and not in_src:
                        continue
                    if _is_seed_name(name) and _seed_value(value):
                        label = name.id if isinstance(name, ast.Name) else name.attr
                        found.append((node.lineno, f"constant {label!r} is a seed"))
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            if _seed_value(node.values[-1]) and any(_mentions_seed(v) for v in node.values[:-1]):
                found.append((node.lineno, "'or' falls back to a seed"))
        elif isinstance(node, ast.IfExp):
            if _seed_value(node.orelse) and _mentions_seed(node.test):
                found.append((node.lineno, "'else' falls back to a seed"))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "add_argument":
                options = [a.value for a in node.args if isinstance(a, ast.Constant)
                           and isinstance(a.value, str)]
                if any(_SEED.search(o) for o in options):
                    for kw in node.keywords:
                        if kw.arg == "default" and _seed_value(kw.value):
                            found.append((node.lineno, "argparse option defaults to a seed"))
                continue
            # A lookup with a fallback: _named("Set_seed", 42), getattr(cfg, "bootstrap_seed", 42).
            positional_ints = [a for a in node.args if _seed_value(a)]
            others = [a for a in node.args if not _seed_value(a)]
            if positional_ints and any(_mentions_seed(a) for a in others):
                found.append((node.lineno, "a seed lookup falls back to a literal"))
            if in_src:
                for kw in node.keywords:
                    if kw.arg and _SEED.search(kw.arg) and _seed_value(kw.value):
                        found.append((node.lineno, f"a literal {kw.arg}= in engine code"))
    return sorted(set(found))


def scan(roots=SCANNED) -> list[str]:
    hits = []
    for root in roots:
        for path in sorted((REPO / root).rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            text = path.read_text(encoding="utf-8")
            in_src = rel.startswith("src/") and not rel.startswith(DECLARED_DATA)
            for line, shape in seed_defaults(text, in_src=in_src):
                hits.append(f"{rel}:{line}: {shape}")
    return hits


def test_no_seed_in_src_or_scripts_is_a_code_default():
    hits = scan()
    assert not hits, (
        "a seed is supplied by code when its caller gave none. Resolve it through the one "
        "convention (src.rng_streams.resolve_seed), refuse it by name (require_seed), or read it "
        "from the record it reproduces:\n  " + "\n  ".join(hits))


# --- the planted shapes: each must be caught, in src/ and in scripts/ ------------------------

PLANTED = {
    "parameter default": "def run(n, seed: int = 42):\n    pass\n",
    "constant default as parameter default": "def run(seed=DEFAULT_TRANSPARENCY_SEED):\n    pass\n",
    "dataclass field": "class C:\n    seed: int = 42\n",
    "module constant": "SEED = 42\n",
    "tuple constant": "N_ITER, SEED = 10_000, 42\n",
    "string constant": 'DELIVERABLE_SEED = "42"\n',
    "argparse default": 'p.add_argument("--seed", type=int, default=42)\n',
    "or fallback": "sd = seed or 42\n",
    "attribute or fallback": "sd = cfg.random_seed or 42\n",
    "else fallback": "s = seed if seed is not None else 0\n",
    "lookup fallback": 's = int(_named("Set_seed", 42) or 1)\n',
    "getattr fallback": 's = getattr(config, "bootstrap_seed", 42)\n',
}


@pytest.mark.parametrize("in_src", [True, False], ids=["src", "scripts"])
@pytest.mark.parametrize("shape", sorted(PLANTED))
def test_red_a_planted_seed_default_is_caught(shape, in_src):
    assert seed_defaults(PLANTED[shape], in_src=in_src), f"the guard missed a planted {shape}"


def test_red_a_literal_seed_at_an_engine_call_is_caught_in_src_only():
    """D6(b): a call-site literal is a stated seed in a script, and a hard-code in engine code."""
    src = "ci = bootstrap_percentile_ci(cost, percentile=80.0, seed=42)\n"
    assert seed_defaults(src, in_src=True)
    assert not seed_defaults(src, in_src=False)


def test_the_guard_passes_what_is_not_a_default():
    clean = (
        "def run(seed: int | None = None):\n    pass\n"
        "class C:\n    seed: int | None = None\n"
        'SEED_LABEL = "Random seed - legacy cost MC only"\n'
        "_DRAWN_SEED_MAX = 2**31 - 1\n"
        'p.add_argument("--seed", type=int, default=None)\n'
        "n = rng.integers(0, 10)\n"
    )
    assert seed_defaults(clean, in_src=True) == []
