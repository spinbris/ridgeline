"""CONFIGTRUTH-01 gate 3 round 1 BLOCKER: the report's own reproducibility text must not promise seed 42.

The audit page told a reader to "execute RUN_FINAL.bat with random seed 42". Since the Director's seed ruling
(08/10/2026) an unset ``SR9_SEED`` draws a seed, so that instruction re-runs a different run with no pointer to
the one recorded. The text must say a re-run reproduces when given the seed recorded in the run's provenance,
set as ``SR9_SEED``, and must not say 42.
"""
from __future__ import annotations

import re

import pytest

from src.final import commentary_text

_FORTY_TWO = re.compile(r"\b42\b")
_PARAGRAPH_OPENING = "To regenerate this deliverable"
#: The paragraph's own last words. The window ends here, so a "42" elsewhere on the page cannot fail a
#: correct paragraph (gate 3 round 2, WARN-5).
_PARAGRAPH_CLOSING = "produces an updated deliverable."


def _holds(text: str) -> list[str]:
    problems = []
    if "SR9_SEED" not in text:
        problems.append("does not name SR9_SEED")
    if "provenance" not in text:
        problems.append("does not point to the seed recorded in the provenance")
    if _FORTY_TWO.search(text):
        problems.append("still says 42")
    return problems


def test_the_reproducibility_paragraph_points_to_the_recorded_seed():
    assert _holds(commentary_text.REPRODUCIBILITY) == []


@pytest.mark.slow
def test_the_rendered_deliverable_carries_that_paragraph(tmp_path):
    """Read from the artefacts a run writes, not from the constant: the paragraph must reach the
    report, and the report's copy must hold the property."""
    from tests import publicface01_render as pf

    rendered = pf.render("synthetic_wind", tmp_path)
    carriers = {}
    for artefact in rendered.artefacts():
        text = " ".join(re.sub(r"<[^>]+>", " ", pf.text_of(artefact)).split())
        if _PARAGRAPH_OPENING in text:
            start = text.index(_PARAGRAPH_OPENING)
            end = text.find(_PARAGRAPH_CLOSING, start)
            assert end != -1, f"{artefact.name}: the paragraph's last sentence is not where it should be"
            carriers[artefact.name] = text[start:end + len(_PARAGRAPH_CLOSING)]
    assert carriers, "no artefact carries the reproducibility paragraph - the check cannot fail"
    problems = {name: _holds(text) for name, text in carriers.items() if _holds(text)}
    assert not problems, problems
