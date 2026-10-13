"""PRESENT-01 (P-2): the renderers emit what the presentation contract says they emit.

A renderer that reorders a section, drops one, or renames a heading fails here **naming what
moved** - the point of the contract is that the failure message tells you which section, not that
some string comparison went red.

The Word check renders a real document through the same helper the word-generator tests use, and
reads the heading sequence back out of the .docx. The HTML check reads the ``PAGES`` list out of
the committed notebook, because that list *is* the HTML body's order.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.final import presentation_contract as contract

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = REPO_ROOT / "final_runner.ipynb"


def _first_divergence(expected: list[str], actual: list[str]) -> str:
    """A message naming the first place the two sequences part company."""
    for i, (e, a) in enumerate(zip(expected, actual)):
        if e != a:
            return (
                f"section {i + 1} differs: the contract says {e!r}, the renderer emitted {a!r}"
            )
    if len(expected) != len(actual):
        longer, shorter = (expected, actual) if len(expected) > len(actual) else (actual, expected)
        side = "the contract has" if len(expected) > len(actual) else "the renderer emitted"
        return f"{side} {longer[len(shorter):]!r} that the other does not"
    return "sequences agree"


# ---------------------------------------------------------------------------
# The contract itself
# ---------------------------------------------------------------------------

def test_the_contract_is_versioned():
    assert contract.CONTRACT_VERSION
    assert contract.CONTRACT_VERSION.count(".") == 1, "version reads major.minor"


def test_section_names_are_unique_within_each_renderer():
    for sections in (contract.WORD_SECTIONS, contract.STAGE3_STANDALONE_SECTIONS,
                     contract.HTML_SECTIONS):
        names = [s.name for s in sections]
        assert len(names) == len(set(names)), f"duplicate section name in {names}"


def test_the_stage3_standalone_differs_from_the_summary_by_one_named_section():
    summary = {s.name for s in contract.WORD_SECTIONS}
    standalone = {s.name for s in contract.STAGE3_STANDALONE_SECTIONS}
    assert standalone - summary == {"criticality_detail"}
    assert not summary - standalone


def test_every_required_disclosure_says_where_it_lives_and_why():
    assert contract.REQUIRED_DISCLOSURES
    for d in contract.REQUIRED_DISCLOSURES:
        assert d.where.strip(), f"{d.name} does not say where it appears"
        assert len(d.why.split()) >= 10, f"{d.name}'s reason is too thin to act on"


# ---------------------------------------------------------------------------
# The HTML body - the notebook's PAGES list is its order
# ---------------------------------------------------------------------------

def _notebook_pages() -> list[tuple[str, str]]:
    """The ``PAGES`` list as the committed notebook declares it."""
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    for cell in cells:
        source = "".join(cell.get("source", []))
        if "PAGES = [" not in source:
            continue
        start = source.index("PAGES = [") + len("PAGES = ")
        depth, end = 0, None
        for i, ch in enumerate(source[start:], start=start):
            depth += (ch == "[") - (ch == "]")
            if depth == 0:
                end = i + 1
                break
        assert end is not None, "PAGES list is not closed in the notebook cell"
        return [tuple(pair) for pair in ast.literal_eval(source[start:end])]
    raise AssertionError("no cell in final_runner.ipynb declares PAGES")


def test_the_notebook_renders_the_contract_sections_in_order():
    expected = [(s.composed_keys[0], s.heading) for s in contract.HTML_SECTIONS]
    actual = _notebook_pages()
    assert actual == expected, _first_divergence(
        [f"{k} -> {h}" for k, h in expected], [f"{k} -> {h}" for k, h in actual],
    )


def test_the_notebook_reports_an_absent_section_by_name():
    """The absence rule is the contract's, and the notebook is where it is enforced."""
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    source = "\n".join("".join(c.get("source", [])) for c in cells)
    assert "Sections not produced by this run" in source, (
        "the HTML body no longer names the sections a run did not produce; a section lost to a "
        "renamed composer key would vanish without the reader being told"
    )


# ---------------------------------------------------------------------------
# The user guide - the same list, checked by the same test (P-7)
# ---------------------------------------------------------------------------

GUIDE = REPO_ROOT / "docs" / "SOFTWARE_USER_GUIDE.md"


def _guide_section_list() -> list[str]:
    """The bolded section names from the guide's numbered list in 8.1."""
    import re

    text = GUIDE.read_text(encoding="utf-8")
    start = text.index("### 8.1 ")
    body = text[start:text.index("### 8.2 ", start)]
    return re.findall(r"^\d+\. \*\*(.+?)\*\*", body, flags=re.MULTILINE)


def test_the_user_guide_lists_the_contract_sections_in_order():
    """P-7: 8.1 and the contract are one list. If either moves alone, this names which."""
    expected = [contract.resolve_heading(s) for s in contract.WORD_SECTIONS]
    actual = _guide_section_list()
    assert actual == expected, _first_divergence(expected, actual)


def test_the_user_guide_quotes_the_contract_version():
    version = contract.CONTRACT_VERSION
    assert f"**{version}**" in GUIDE.read_text(encoding="utf-8"), (
        f"the guide does not quote contract version {version}; a version bump must reach the "
        "document that claims to describe the same list"
    )


# ---------------------------------------------------------------------------
# The Word document
# ---------------------------------------------------------------------------

def _rendered_heading_sequence(path: Path) -> list[str]:
    from docx import Document

    doc = Document(str(path))
    return [p.text.strip() for p in doc.paragraphs if p.style.name == "Heading 1"]


@pytest.fixture(scope="module")
def rendered_word_doc(tmp_path_factory):
    """One rendered document, reused by the checks below."""
    from tests.test_sr9_v3_word_generator import _generate_v3_doc

    return _generate_v3_doc(tmp_path_factory.mktemp("contract"))


def test_the_word_document_renders_the_contract_sections_in_order(rendered_word_doc):
    path, composed = rendered_word_doc
    metric = str(composed.get("headline_metric", "P80"))
    # This fixture composes without a Stage 3 result, so the two Stage 3-only sections are
    # legitimately absent; a shipped deliverable cannot take that path (STAGE3HEADLINE-01 P1).
    stage3 = composed.get("executive_summary", {}).get("headline_stage3") is not None
    expected = [
        contract.resolve_heading(s, metric=metric)
        for s in contract.word_sections(stage3=stage3)
    ]
    actual = _rendered_heading_sequence(path)
    assert actual == expected, _first_divergence(expected, actual)


def test_the_word_sections_name_keys_a_real_compose_produces(rendered_word_doc):
    """Every composed key a section declares is one a real compose call actually returns."""
    _, composed = rendered_word_doc
    for section in contract.WORD_SECTIONS:
        for key in section.composed_keys:
            if section.requires_stage3:
                continue  # this fixture does not compose them
            assert key in composed, (
                f"section {section.name!r} declares composed key {key!r}, which a compose call "
                "does not produce - the section would render empty, or not at all"
            )


@pytest.mark.parametrize("sections", [contract.WORD_SECTIONS, contract.HTML_SECTIONS])
def test_every_section_declares_a_heading(sections):
    for s in sections:
        assert s.heading.strip(), f"section {s.name!r} has no heading"
