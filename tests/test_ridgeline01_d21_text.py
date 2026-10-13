"""RIDGELINE-01 P5: nothing says the product does not compute base plus contingency (D-21).

D-21 (22/09/2026) ruled that the base estimate is an input, that the owner view's distribution of
base plus contingency is a product output, and that this deliverable presents the event-risk
contingency. Five texts denied the second half. Each is checked here for the denial wording, and
for the positive statement, so a rewording that drops the ruling fails as well as one that
restores the denial.

SPEC §9 quotes the v1.0 wording verbatim as its change record; only §1 is checked.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.input_skips import skip_if_private_and_absent

REPO = Path(__file__).resolve().parents[1]

DENIALS = (
    r"never outputs?",
    r"does not compute (the )?base",
    r"not modelled in this analysis",
    r"does not grow to cover",
    r"base estimate and escalation are inputs",
    # Gate 3 round 1, W4: the shapes a later rewording could take.
    r"is not modell?ed",
    r"outside the product",
    r"not an? (\w+ )?output",
)
AFFIRMATION = r"base plus contingency"
#: A clause is where a negation governs; its end is punctuation followed by a space or the end.
CLAUSE_END = re.compile(r"[.;:](?=\s|$)")
#: Round 3 (gate 3 WARN 2): the curly apostrophe too, as typographic quotes render "isn’t".
NEGATION = re.compile(r"\b(not|never|no|none|nor|without)\b|n['’]t\b", re.I)


def _between(path: str, start: str, end: str) -> str:
    skip_if_private_and_absent(path)  # the private documents are not in the public snapshot
    text = (REPO / path).read_text(encoding="utf-8")
    i = text.index(start)
    return text[i:text.index(end, i + len(start))]


def _limitations_bullet() -> str:
    from src.final import commentary_text

    return commentary_text.L1_SYSTEMIC_CAVEAT_BULLET


PLACES = {
    "L1_SYSTEMIC_CAVEAT_BULLET": _limitations_bullet,
    "CLAUDE.md opening": lambda: _between("CLAUDE.md", "## What this repo does", "\n## "),  # link-rule: the D-21 sentence is read from the private document when present, skipped when absent
    "SPEC §1": lambda: _between("docs/programme/SPEC_product.md", "\n## 1. ", "\n## 2. "),  # link-rule: the D-21 sentence is read from the private document when present, skipped when absent
    "README.md opening": lambda: _between("README.md", "# ", "\n## "),
    "METHODOLOGY.md scope": lambda: _between("METHODOLOGY.md", "**Scope, stated once", "\n---"),
}


def denials_in(text: str) -> list[str]:
    return [p for p in DENIALS if re.search(p, text, re.I)]


def _clauses(text: str) -> list[str]:
    return [c.strip() for c in CLAUSE_END.split(" ".join(text.split()))]


def negated_affirmations(text: str) -> list[str]:
    """Clauses naming base plus contingency as an output under a negation (round 3, WARN 2).

    Each is a denial in its own right: one affirming clause elsewhere must not hide it.
    """
    return [c for c in _clauses(text)
            if re.search(AFFIRMATION, c, re.I) and re.search(r"output", c, re.I)
            and NEGATION.search(c)]


def affirms(text: str) -> bool:
    """A clause states base plus contingency as an output, with no negation anywhere in it.

    Round 1, W4: the first version only looked for the phrase, so "does not output base plus
    contingency" passed as an affirmation.
    """
    clauses = CLAUSE_END.split(" ".join(text.split()))
    return any(re.search(AFFIRMATION, c, re.I) and re.search(r"output", c, re.I)
               and not NEGATION.search(c) for c in clauses)


@pytest.mark.parametrize("place", sorted(PLACES))
def test_no_place_denies_that_base_plus_contingency_is_an_output(place: str) -> None:
    text = PLACES[place]()
    assert not denials_in(text), f"{place} still denies D-21: {denials_in(text)}"
    assert not negated_affirmations(text), f"{place} denies D-21 in: {negated_affirmations(text)}"
    assert affirms(text), f"{place} no longer states D-21's output affirmatively"


def test_the_check_reds_on_the_text_it_replaced() -> None:
    """The v1.0 sentence, as the agent manual and README carried it until RIDGELINE-01."""
    old = ("It computes the contingency term - base estimate and escalation are inputs and "
           "hand-offs, never outputs (SPEC §1, R-5/D-1).")
    assert denials_in(old)


@pytest.mark.parametrize("doctored", [
    "Systemic uncertainty on the base (Layer 1) is not modelled.",
    "Base plus contingency is outside the product.",
    "Base plus contingency is not an output.",
    "Base plus contingency is not a product output of this system.",
])
def test_the_denial_list_catches_each_new_shape(doctored: str) -> None:
    assert denials_in(doctored), doctored


@pytest.mark.parametrize("doctored", [
    "The product does not output base plus contingency.",
    "Base plus contingency is never an output here.",
    "No view reports base plus contingency as an output.",
    "The owner view's base plus contingency isn't an output.",
])
def test_a_negated_affirmation_is_not_an_affirmation(doctored: str) -> None:
    assert not affirms(doctored), doctored


def test_an_affirmation_survives_a_negation_in_another_clause() -> None:
    text = "The base is not estimated here. The owner view's base plus contingency is an output."
    assert affirms(text)


VALID = "The owner view's distribution of base plus contingency is an output."


@pytest.mark.parametrize("negated", [
    "Base plus contingency is never an output.",
    "Base plus contingency isn't an output.",
    "Base plus contingency isn\u2019t an output.",
])
def test_a_negated_clause_reds_even_beside_a_valid_affirmation(negated: str) -> None:
    text = f"{VALID} {negated}"
    assert affirms(text), "the valid clause should still affirm"
    assert negated_affirmations(text) == [negated.rstrip(".")], text
