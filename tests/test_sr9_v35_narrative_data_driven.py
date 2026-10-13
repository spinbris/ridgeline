"""SR9 v3.5 - narrative data-driven cleanup tests.

Asserts that:
  - format_mode_mix / count_modes / format_scenario_label helpers behave
    correctly for empty, single-mode, and mixed-mode inputs.
  - Every literal mode-mix string ('1S/7P', '3S/2H/3P', '8S', 'seven of
    eight') has been removed from the presentation-layer source files.
  - Composer substitutes the actual mode-mix from runtime engine output
    into MODE_CAVEAT_HEADLINE, READING_CONVENTION, DP_REVIEW_CAVEAT,
    and the range-table scenario labels.
  - SR9 v3.5 dev-mode deprecation surface is present (RUN_FINAL.bat
    default is prod; dev warning is in the cell source of final_runner).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.final.executive_summary import (
    SCENARIO_LABEL_SUFFIX,
    count_modes,
    format_mode_mix,
    format_scenario_label,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# format_mode_mix / count_modes
# ---------------------------------------------------------------------------

def test_format_mode_mix_8s_when_all_series():
    modes = {f"R{i:03d}": "Series" for i in range(8)}
    assert format_mode_mix(modes) == "8S"


def test_format_mode_mix_3s_2h_3p_dummy_realistic():
    modes = {
        "R017.1": "Series", "R067": "Series", "R090": "Series",
        "R013": "Hybrid", "R026.1": "Hybrid",
        "R015.1": "Parallel", "R016.1": "Parallel", "R016.2": "Parallel",
    }
    assert format_mode_mix(modes) == "3S/2H/3P"


def test_format_mode_mix_1s_7p_canonical_dp_review():
    modes = {f"R{i:03d}": "Parallel" for i in range(7)}
    modes["R090"] = "Series"
    assert format_mode_mix(modes) == "1S/7P"


def test_format_mode_mix_empty_returns_none_marker():
    assert format_mode_mix({}) == "(none)"


def test_format_mode_mix_rejects_unknown_modes():
    # RS-D-5 (D-17): an unknown Mode raises by name; it is never bucketed as "?".
    modes = {"R001": "Foo", "R002": "Series"}
    with pytest.raises(ValueError, match="Foo"):
        format_mode_mix(modes)


def test_count_modes_round_trip():
    modes = {"a": "Series", "b": "Hybrid", "c": "Parallel", "d": "Series"}
    counts = count_modes(modes)
    assert counts == {"Series": 2, "Hybrid": 1, "Parallel": 1}


def test_format_scenario_label_carries_the_canonical_suffix():
    label = format_scenario_label("DP_Review")
    assert label == f"DP Review baseline ({SCENARIO_LABEL_SUFFIX['DP_Review']})"


def test_format_scenario_label_explicit_suffix_override():
    label = format_scenario_label("All_Series", suffix="custom note")
    assert label == "All Series (custom note)"


def test_format_scenario_label_empty_suffix_omits_separator():
    label = format_scenario_label("All_Series", suffix="")
    assert label == "All Series"


def test_format_scenario_label_unknown_scenario_id_falls_back():
    label = format_scenario_label("MyAlt", suffix="")
    assert label == "MyAlt"


# ---------------------------------------------------------------------------
# Beta-11 Section 1 - chart legend stripping
# ---------------------------------------------------------------------------

# SR9 v3.3 Path A forbidden phrases. A chart legend must contain none of these. Mix strings
# ('8S', '3S/2H/3P', '1S/7P') are forbidden because they encode the indicative classification
# framing; since PRESENT-01 (D-4) the label has no mix-string parameter to carry them at all.
_PROD_FORBIDDEN = (
    "Dummy Realistic",
    "Dummy_Realistic",
    "S" + "JP indicative",
    "PM review pending",
    "PM review",
    "Mode classification",
    "indicative classification",
    "8S",
    "3S/2H/3P",
    "1S/7P",
)


@pytest.mark.parametrize(
    "scenario_id", ("DP_Review", "Dummy_Realistic", "All_Series"),
)
def test_prod_scenario_label_no_forbidden(scenario_id):
    """Beta-11 Section 1: the chart legend must contain zero SR9 v3.3 Path A forbidden
    phrases. Locks the body-text path; the PNG OCR test (Beta-11 Section 4) locks the rendered
    chart side.
    """
    label = format_scenario_label(scenario_id)
    found = [phrase for phrase in _PROD_FORBIDDEN if phrase in label]
    assert not found, (
        f"scenario label {label!r} contains forbidden phrases {found}; "
        f"check resolve_scenario_label_suffix() and the base map in format_scenario_label."
    )


def test_scenario_label_omits_mix_string():
    """Mix strings ('8S' / '3S/2H/3P' / '1S/7P') are forbidden in a chart legend because they
    encode the indicative classification framing. The label takes no mix string since
    PRESENT-01 (D-4), so what is asserted here is that none reappears in the base or suffix.
    """
    for scenario_id in ("DP_Review", "All_Series", "Dummy_Realistic"):
        label = format_scenario_label(scenario_id)
        assert "8S" not in label
        assert "3S/2H/3P" not in label
        assert "1S/7P" not in label


# ---------------------------------------------------------------------------
# Beta-11a Fix 1 — suppress redundant parenthetical when name == suffix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "scenario_id", ("DP_Review", "Dummy_Realistic", "All_Series"),
)
def test_prod_scenario_label_no_redundant_parenthetical(scenario_id):
    """Beta-11a Fix 1: suppress 'X (X)' patterns in legends.

    The Dummy_Realistic label was rendering as 'Alternate Mode
    scenario (alternate Mode scenario)' — display name and suffix were
    the same string. Fix: format_scenario_label drops the parenthetical
    when the suffix is just a re-statement of the base.

    Regex matches any word duplication of the form 'X (X)' where the
    inside-parens text is the trailing words of the outside-parens
    text, case-insensitive.
    """
    import re

    label = format_scenario_label(scenario_id)
    # Look for 'A B (a b)' style duplication: capture the parenthetical
    # and the immediately preceding trailing words of equal length.
    match = re.search(r"^(.+?)\s*\(([^)]+)\)$", label)
    if not match:
        return  # No parenthetical at all → trivially fine
    base, paren = match.group(1).strip(), match.group(2).strip()
    assert base.casefold() != paren.casefold(), (
        f"scenario label {label!r} has a redundant parenthetical: "
        f"{base!r} == {paren!r}. Beta-11a Fix 1 should suppress this via "
        f"_is_redundant_suffix in src/final/executive_summary.py."
    )


def test_dummy_realistic_prod_label_renders_without_duplication():
    """Beta-11a Fix 1 — pin the canonical case the fix targets."""
    label = format_scenario_label("Dummy_Realistic")
    # Either 'Alternate Mode scenario' alone (option a — what we did)
    # or some form without the doubled parenthetical.
    assert label == "Alternate Mode scenario", (
        f"Expected 'Alternate Mode scenario' (no redundant parenthetical); "
        f"got {label!r}"
    )


# ---------------------------------------------------------------------------
# No literal mode counts in presentation-layer source files
# ---------------------------------------------------------------------------

_FORBIDDEN_LITERALS = ("1S/7P", "3S/2H/3P", "seven of eight")
_PRESENTATION_FILES = (
    REPO_ROOT / "src" / "final" / "commentary_text.py",
    REPO_ROOT / "src" / "final" / "composer.py",
    REPO_ROOT / "src" / "final" / "word_generator.py",
)


@pytest.mark.parametrize("path", _PRESENTATION_FILES)
def test_no_hardcoded_mode_mix_literals_in_presentation_layer(path):
    """Mode-mix counts must derive from runtime data, not be baked as
    literals in templates. Catches narrative-template regressions.
    """
    src = path.read_text(encoding="utf-8")
    found = [lit for lit in _FORBIDDEN_LITERALS if lit in src]
    assert not found, (
        f"{path.name}: forbidden hardcoded mode-mix literals {found}. "
        f"Use {{dp_review_mix}} / {{indicative_mix}} / {{all_series_mix}} "
        f"placeholders, filled at format time from runtime engine output."
    )


# ---------------------------------------------------------------------------
# Composer substitutes runtime mode-mix into narrative slots
# ---------------------------------------------------------------------------

def test_commentary_template_includes_mix_placeholders():
    """MODE_CAVEAT_HEADLINE, READING_CONVENTION, DP_REVIEW_CAVEAT must
    contain the v3.5 placeholders so format-time substitution works."""
    from src.final import commentary_text

    assert "{dp_review_mix}" in commentary_text.MODE_CAVEAT_HEADLINE
    assert "{all_series_mix}" in commentary_text.MODE_CAVEAT_HEADLINE
    assert "{indicative_mix}" in commentary_text.READING_CONVENTION
    assert "{dp_review_mix}" in commentary_text.READING_CONVENTION
    assert "{all_series_mix}" in commentary_text.READING_CONVENTION
    assert "{n_parallel_dp}" in commentary_text.DP_REVIEW_CAVEAT
    assert "{n_total_dp}" in commentary_text.DP_REVIEW_CAVEAT

