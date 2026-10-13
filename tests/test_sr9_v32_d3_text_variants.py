"""The five deliverable texts that once had a dev twin, and the limitations list.

Tests cover:
  - Each of the five carries no dev framing (the interim label, "Dummy Realistic",
    "Mode classification", "PM review")
  - LIMITATIONS_CURRENT has the exact PM-approved entry-3 text, and drops the LD/IDC entry

PRESENT-01 (D-4) retired the dev report. SR9 v3.2 had paired each of these with a ``_PROD``
twin and tested the pairing - that the twin existed, and that its placeholders were a subset of
the dev original's. The twin is now the only text, so the pairing tests have no subject; what
they were protecting - that the sentence a reader sees carries no indicative framing - is
asserted here directly, on the surviving constant.
"""
from __future__ import annotations

from src.final import commentary_text


# The five that carried a _PROD twin. The name now refers to the neutral text.
_NEUTRAL = [
    "HEADLINE_INTEGRATED_P80",
    "SCHEDULE_DAYS_CONTEXT",
    "DOMINANT_RISK_TEMPLATE",
    "DOMINANT_RISK_FALLBACK",
    "CONFIDENCE_CURVE_PREAMBLE",
]

_DEV_PHRASES = (
    "S" + "JP indicative",
    "Dummy Realistic",
    "Mode classification",
    "PM review",
    "indicative classification",
    "indicative Mode",
)


def test_the_neutral_texts_exist():
    for name in _NEUTRAL:
        assert hasattr(commentary_text, name), f"missing: {name}"


def test_the_neutral_texts_omit_dev_phrases():
    for name in _NEUTRAL:
        text = getattr(commentary_text, name)
        for phrase in _DEV_PHRASES:
            assert phrase not in text, f"{name} contains dev phrase {phrase!r}"


def test_limitations_current_exists():
    lst = commentary_text.LIMITATIONS_CURRENT
    assert isinstance(lst, list)
    assert 3 <= len(lst) <= 5  # PM-approved subset


def test_limitations_current_has_pm_approved_entry3_text():
    """PM addendum §1.4 supplies this phrasing verbatim."""
    expected = (
        "Criticality assessment uses the conservative starting-point "
        "classification informed by current schedule structure"
    )
    assert expected in commentary_text.LIMITATIONS_CURRENT


def test_limitations_current_omits_dev_phrases():
    for entry in commentary_text.LIMITATIONS_CURRENT:
        for phrase in _DEV_PHRASES:
            assert phrase not in entry, (
                f"LIMITATIONS_CURRENT entry contains {phrase!r}: {entry!r}"
            )


def test_limitations_current_drops_ld_idc_entry():
    """The dropped entry (LD/IDC layer deferred) stays dropped, per addendum §1.4."""
    for entry in commentary_text.LIMITATIONS_CURRENT:
        assert "LD" not in entry or "Liquidated" not in entry
        assert "IDC" not in entry


def test_headline_opening_v3_fallback_unchanged():
    """Per addendum §1.5: HEADLINE_OPENING (v3 fallback) leave untouched.

    This constant belongs to the Stage 2.5 route the deliverable no longer takes, and its
    indicative vocabulary is DUMMYSCOPE-01's to remove. Until then it is pinned as it stands.
    """
    assert "interim classification" in commentary_text.HEADLINE_OPENING
    assert "PM review" in commentary_text.HEADLINE_OPENING
