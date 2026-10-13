"""SR14b D2 Option A — renderer banner-hook tests.

Two contracts:

1. Banner-absent case (Stage 2.5 path): ``_maybe_render_preview_banner``
   is a no-op when ``composed["preview_banner"]`` is missing or
   falsy. This is the load-bearing test for the Stage 2.5 lock
   continuity — the hook must not perturb the docx byte stream when
   Stage 2.5's composed dict doesn't carry the key.

2. Banner-present case (Stage 3 path): the hook renders the banner
   string into the docx as an italicised 10-point paragraph and the
   HTML accessor returns the string verbatim.
"""

from __future__ import annotations

from docx import Document

from src.final.final_reporting import get_preview_banner
from src.final.word_generator import _maybe_render_preview_banner


# ---------------------------------------------------------------------------
# docx hook (word_generator)
# ---------------------------------------------------------------------------


def test_maybe_render_preview_banner_no_op_when_key_absent() -> None:
    """Stage 2.5 path — ``composed`` does not carry ``preview_banner``;
    the hook adds nothing to the document."""
    doc = Document()
    _add = doc.paragraphs.__len__
    n_before = _add()
    _maybe_render_preview_banner(doc, {"some": "other key"})
    assert _add() == n_before


def test_maybe_render_preview_banner_no_op_when_empty_string() -> None:
    """Empty string is treated as absent (same no-op behaviour)."""
    doc = Document()
    n_before = len(doc.paragraphs)
    _maybe_render_preview_banner(doc, {"preview_banner": ""})
    assert len(doc.paragraphs) == n_before


def test_maybe_render_preview_banner_renders_when_key_present() -> None:
    """Stage 3 path — banner string lands as an italic 10pt paragraph."""
    doc = Document()
    n_before = len(doc.paragraphs)
    banner_text = "Stage 3 Beta preview — methodology-bearing draft."
    _maybe_render_preview_banner(doc, {"preview_banner": banner_text})
    assert len(doc.paragraphs) == n_before + 1
    p = doc.paragraphs[n_before]
    assert banner_text in p.text
    # Run carries italic + 10pt font.
    run = p.runs[0]
    assert run.italic is True
    assert run.font.size.pt == 10


# ---------------------------------------------------------------------------
# HTML accessor (final_reporting)
# ---------------------------------------------------------------------------


def test_get_preview_banner_returns_empty_string_when_absent() -> None:
    """Stage 2.5 path — accessor returns ``""`` so notebook render
    loops skip cleanly."""
    assert get_preview_banner({}) == ""
    assert get_preview_banner({"some": "other key"}) == ""


def test_get_preview_banner_returns_string_when_present() -> None:
    """Stage 3 path — accessor returns the banner verbatim."""
    banner_text = "Stage 3 Beta preview — methodology-bearing draft."
    assert get_preview_banner({"preview_banner": banner_text}) == banner_text


def test_get_preview_banner_coerces_none_to_empty() -> None:
    """A ``None`` value (programmer error) is coerced to ``""`` rather
    than raised — the accessor is designed as a safe getter."""
    assert get_preview_banner({"preview_banner": None}) == ""
