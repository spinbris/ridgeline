"""The manuals name no symbol that the module no longer defines.

PUBLIC-01 D-4(a), signed 20/09/2026.

WHY THIS IS A SECOND GUARD AND NOT A WIDER FIRST ONE
    DOCPOINT-01 built `tests/test_manual_pointers.py`, which asks whether a document names a
    **file** absent from the tree. It says nothing about symbols, and the gap has bitten
    twice: `METHODOLOGY.md` cited `sra_simulation.EXPECTED_TIME_YES_RISK_IDS` for months
    after REFRETIRE-01 retired it, and `ARCHITECTURE.md` named `read_xer(path)` as the xer
    reader's public surface when the function is `parse_xer` - found by hand during
    SHOWCASE-02, because nothing was looking.

    D-4 ruled this **narrow on purpose**: only backticked names carrying a **dotted symbol
    suffix**, and only where the module part resolves to a real file under `src/`. The
    tempting wider version - resolve every backticked identifier - is the shape DOCPOINT-01
    measured producing sixteen false findings on `ARCHITECTURE.md` alone, every one of them
    prose working as intended.

WHAT IS AND IS NOT COVERED, STATED SO THE GAP IS KNOWN
    Covered: ``src.pkg.mod.NAME``, ``src/pkg/mod.NAME``, and ``mod.NAME`` where ``mod``
    matches exactly one module basename under `src/`.

    **Not covered: a bare call like ``read_xer(path)``**, where nothing in the token says
    which module should define it. Resolving those needs context a regex does not have, and
    guessing is how a guard starts producing findings that are prose. That instance is
    corrected by hand at PUBLIC-01 and the class stays open - if it recurs, the answer is a
    convention (always cite ``module.symbol``), not a cleverer regex.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from tests.input_skips import private_and_absent, private_documents_skip

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"

DOCUMENTS = (
    "README.md",
    "CLAUDE.md",  # link-rule: the agent manual's symbols are resolved when it is present, skipped when absent
    "METHODOLOGY.md",
    "ARCHITECTURE.md",
    "SCALABILITY.md",
)

#: A backticked token whose last dotted part looks like a symbol. The module part may use
#: slashes or dots; a trailing "()" is tolerated and stripped.
_TOKEN = re.compile(r"`([A-Za-z_][A-Za-z0-9_./]*\.[A-Za-z_][A-Za-z0-9_]*)(?:\(\))?`")

#: Extensions that make a token a filename rather than a symbol reference - those are
#: test_manual_pointers.py's job, not this one's.
_FILE_SUFFIXES = (
    ".md", ".py", ".json", ".csv", ".xlsx", ".xlsm", ".xer", ".bat", ".toml",
    ".ipynb", ".txt", ".yml", ".yaml", ".cfg", ".ini", ".parquet", ".docx", ".html",
)


def _src_modules() -> dict[str, str]:
    """``{basename: dotted.module.path}`` for every module under src/, basenames unique."""
    out: dict[str, list[str]] = {}
    for p in SRC.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        dotted = ".".join(p.relative_to(REPO_ROOT).with_suffix("").parts)
        out.setdefault(p.stem, []).append(dotted)
    # A basename that is not unique cannot be resolved from a bare `mod.NAME`, so it is
    # dropped rather than guessed at.
    return {k: v[0] for k, v in out.items() if len(v) == 1}


def _resolve(token: str, modules: dict[str, str]) -> tuple[str, str] | None:
    """``(dotted_module, symbol)`` if this token names a src symbol, else None."""
    if token.lower().endswith(_FILE_SUFFIXES):
        return None
    head, _, symbol = token.rpartition(".")
    if not head or not symbol:
        return None
    normalised = head.replace("/", ".").strip(".")
    if normalised.startswith("src."):
        candidate = normalised
    elif normalised in modules:                      # bare basename, e.g. `cpm_kernel`
        candidate = modules[normalised]
    elif normalised.rpartition(".")[2] in modules:   # e.g. `sra.cpm.cpm_kernel`
        candidate = modules[normalised.rpartition(".")[2]]
    else:
        return None                                  # not ours - np.mean, pytest.approx
    return candidate, symbol


@pytest.fixture(scope="module")
def modules() -> dict[str, str]:
    return _src_modules()


def test_the_walker_finds_symbols_to_check(modules):
    """A walker that resolved nothing would report no rot and look identical to health."""
    total = 0
    present = [d for d in DOCUMENTS if not private_and_absent(d)]  # the public snapshot lacks the private ones
    for doc in present:
        text = (REPO_ROOT / doc).read_text(encoding="utf-8")
        total += sum(1 for t in _TOKEN.findall(text) if _resolve(t, modules))
    assert total >= 10, (
        f"only {total} src symbol references resolved across {len(present)} documents - "
        f"the pattern or the module map has stopped matching, and the check below is "
        f"passing on nothing")


@pytest.mark.parametrize("document", private_documents_skip(DOCUMENTS))
def test_the_manual_names_no_symbol_its_module_lacks(document: str, modules):
    text = (REPO_ROOT / document).read_text(encoding="utf-8")
    missing: list[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        for token in _TOKEN.findall(line):
            resolved = _resolve(token, modules)
            if resolved is None:
                continue
            dotted, symbol = resolved
            try:
                module = importlib.import_module(dotted)
            except Exception as exc:                 # noqa: BLE001 - reported, not raised
                missing.append(f"line {i}: `{token}` - {dotted} will not import ({exc})")
                continue
            if hasattr(module, symbol):
                continue
            # A submodule is not an attribute of its package until something imports it,
            # so `src.final.deliverable` would read as rot on a hasattr check alone. Try
            # it as a module before reporting - found by this guard's own first run.
            try:
                importlib.import_module(f"{dotted}.{symbol}")
            except Exception:                        # noqa: BLE001 - genuinely absent
                missing.append(f"line {i}: `{token}` - {dotted} defines no {symbol!r}")
    assert not missing, (
        f"{document} names symbols their modules do not define:\n  " + "\n  ".join(missing)
        + "\n\nEither the symbol was renamed or retired - say what replaced it - or the "
          "citation names the wrong module. This is the class that let "
          "EXPECTED_TIME_YES_RISK_IDS outlive REFRETIRE-01 by weeks."
    )
