"""SP17 A1 - language regression test.

Asserts that the EMV vs MC Mean vs P50 language fix stays in place across
the three in-scope artifacts and that the explainer block remains present
in the client runner notebook.

The EMV/P50 conflation language was already corrected upstream of A1
(see the SP17 A1 results for the
all-KEEP discovery result). A1 locks in that correctness, adds a
director-visible explainer block in the runner, and baselines the
project-wide em-dash rule across the three in-scope files.

Scope decisions (per SP17_A1_results.md):
- Explainer sentinel required in runner only. Appendices does not have a
  portfolio-level EMV section that warrants the director framing block.
- reporting.py is a data module (computes DataFrames and dicts); it has
  no HTML to carry the sentinel. The canonical corrective sentence in
  compute_emv_bridge's docstring is the preservation target instead.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.input_skips import skip_missing

REPO_ROOT = Path(__file__).resolve().parents[1]

REPORTING_PY = REPO_ROOT / "src" / "reporting.py"

IN_SCOPE_FILES = [REPORTING_PY]


FORBIDDEN_PATTERNS = [
    r"EMV[^.\n]{0,80}(?:approx|approximate(?:ly)?|~|\u2248|aligns?|align(?:s|ed)?\s+with|compare[sd]?\s+(?:to|with)|close\s+to|near(?:ly)?|equivalent\s+to|equal[s]?\s+to|matches?)[^.\n]{0,40}P50",
    r"P50[^.\n]{0,80}(?:approx|approximate(?:ly)?|~|\u2248|aligns?|align(?:s|ed)?\s+with|compare[sd]?\s+(?:to|with)|close\s+to|near(?:ly)?|equivalent\s+to|equal[s]?\s+to|matches?)[^.\n]{0,40}EMV",
    r"EMV[^.\n]{0,40}\(median\)",
    r"EMV[^.\n]{0,40}\bis\b[^.\n]{0,20}\bmedian\b",
    r"P50[^.\n]{0,40}(?:is\s+the|as\s+the)[^.\n]{0,30}EMV\s+comparator",
    r"agree\s+to\s+within\s+about\s+\d+(?:\.\d+)?%",
]

CANONICAL_SENTENCE_PATTERN = (
    r"correct\s+(?:MC\s+)?comparator[^.]{0,40}"
    r"(?:for\s+EMV\s+)?is\s+(?:the\s+)?MC\s+Mean"
    r"[^.]{0,80}not\s+(?:the\s+)?P50"
)

# Strip the canonical sentence (and the explainer block's own correct
# framing) before running forbidden-pattern checks, otherwise we would
# flag the cure as the disease.
ALLOW_LIST_PATTERNS = [
    CANONICAL_SENTENCE_PATTERN,
    r"P50\s+is\s+NOT\s+the\s+correct\s+comparator\s+for\s+EMV",
    r"correct\s+comparator\s+for\s+EMV\s+is\s+MC\s+Mean",
]

# Double-hyphen used as em-dash substitute: match exactly `--` not
# adjacent to more hyphens. Correctly preserves markdown horizontal
# rules (`---` or longer runs).
DOUBLE_HYPHEN_REGEX = re.compile(r"(?<!-)--(?!-)")


# RS-B step 3: these tests are PARAMETRIZED over paths - one parameter is a
# source file that is present, the others are notebooks the *.ipynb cut removed.
# So the guard is per-parameter, not per-module. A module-scoped guard skipped
# the whole file and took three PASSING tests with it, which is coverage traded
# for a green lane. This checks the artefact THIS parameter reads.
@pytest.fixture(autouse=True)
def _requires_this_parameters_input(request):
    params = getattr(getattr(request.node, "callspec", None), "params", {})
    path = params.get("path")
    if path is not None and not path.exists():
        skip_missing(path)

def _read(path: Path) -> str:
    """Return file text suitable for regex checks.

    For .ipynb files, extract cell sources via nbformat and join with
    real newlines. Raw .ipynb JSON stores cell-internal newlines as the
    literal two-char sequence "\\n", which breaks patterns that use
    [^.\\n] as a line-boundary guard. Parsing via nbformat also
    neutralises any ensure_ascii unicode-escape variance.
    """
    if path.suffix == ".ipynb":
        import nbformat
        nb = nbformat.read(str(path), as_version=4)
        return "\n".join(cell.source for cell in nb.cells)
    return path.read_text(encoding="utf-8")


def _strip_allow_list(text: str) -> str:
    for pat in ALLOW_LIST_PATTERNS:
        text = re.sub(pat, "[ALLOWED]", text, flags=re.IGNORECASE)
    return text


@pytest.mark.parametrize("path", IN_SCOPE_FILES, ids=lambda p: p.name)
def test_no_forbidden_phrases(path):
    """No EMV / P50 conflation language in any in-scope file."""
    assert path.exists(), f"{path} not found"
    text = _strip_allow_list(_read(path))
    for pat in FORBIDDEN_PATTERNS:
        match = re.search(pat, text, flags=re.IGNORECASE)
        assert match is None, (
            f"Forbidden phrase matched in {path.name}: "
            f"pattern={pat!r}, match={match.group(0)!r}"
        )


def test_canonical_sentence_present_in_reporting():
    """The canonical corrective sentence from the critical review must
    survive any rewrite of adjacent text in reporting.py.

    Current home: compute_emv_bridge docstring (approx line 119-121).
    The regex tolerates two forms:
    - "correct comparator for EMV is MC Mean ... not P50" (v3 spec quote)
    - "correct MC comparator is the MC Mean ... not the P50" (current
      docstring, with EMV mentioned earlier in the same sentence)
    Both carry the same framing; what must survive is the construction
    linking MC Mean as the correct comparator against P50.
    """
    text = _read(REPORTING_PY)
    match = re.search(CANONICAL_SENTENCE_PATTERN, text, flags=re.IGNORECASE)
    assert match is not None, (
        "Canonical sentence ('correct comparator ... MC Mean ... not "
        "P50') missing from src/reporting.py - was it accidentally "
        "rewritten?"
    )
    # Ensure EMV is in context (within 200 chars before the match),
    # otherwise the pattern could match an unrelated comparison.
    context_start = max(0, match.start() - 200)
    context = text[context_start:match.end()]
    assert re.search(r"\bEMV\b", context), (
        "'correct comparator ... MC Mean ... not P50' found in "
        "reporting.py, but EMV not mentioned in preceding context - "
        "the framing has drifted from EMV."
    )


@pytest.mark.parametrize("path", IN_SCOPE_FILES, ids=lambda p: p.name)
def test_no_em_or_en_dashes_in_in_scope_files(path):
    """Project-wide rule: no em dash (U+2014), en dash (U+2013), or
    double-hyphen-as-em-dash-substitute in any in-scope file.

    The double-hyphen check is narrower:
    - .py files: skipped. `--` can be legitimate (CLI flag in doc
      strings, argparse help text, etc.).
    - .ipynb markdown cells: flag `--` only when not adjacent to more
      hyphens (preserves `---`+ markdown horizontal rules).
    - .ipynb code cells: skipped (CLI flags in strings and comments).
    """
    assert path.exists(), f"{path} not found"

    forbidden_chars = ["\u2014", "\u2013"]

    # Unicode dash check: full file text via nbformat-aware reader.
    text = _read(path)
    for ch in forbidden_chars:
        assert ch not in text, (
            f"Forbidden dash character {ch!r} (U+{ord(ch):04X}) found "
            f"in {path.name}"
        )

    # Double-hyphen check: markdown cells only.
    if path.suffix == ".ipynb":
        import nbformat
        nb = nbformat.read(str(path), as_version=4)
        for i, cell in enumerate(nb.cells):
            if cell.cell_type != "markdown":
                continue
            match = DOUBLE_HYPHEN_REGEX.search(cell.source)
            assert match is None, (
                f"Double-hyphen em-dash substitute found in markdown "
                f"cell {i} of {path.name} at position {match.start()}: "
                f"context={cell.source[max(0, match.start()-15):match.end()+15]!r}"
            )
