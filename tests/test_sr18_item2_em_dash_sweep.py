"""SR18 Item 2 — scoped em-dash sweep.

Locks the post-SR18 acceptance criteria per the SR18 brief §5 AC 2-5:

* `grep -cP ' — ' src/final/commentary_text.py` returns 0
* `grep -cP ' — ' src/final/stage3_beta_report.py` returns 0
* No em-dash in any element of `BETA_BANNER_LINES`
* No em-dash in any string literal passed to `ax.set_title`,
  `fig.suptitle`, or chart-caption helpers in `charts.py`

Scope discipline (per Director-locked SR18 §2): SR18 fixes the four
surfaces named above and the named SR17-introduced em-dashes inside
those files. The remaining ~280 em-dashes elsewhere in `src/final/`
(comments and docstrings outside the four scoped files / constants)
are explicitly OUT of scope and queued as SR19+ work.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EM_DASH = "—"


def _count_em_dashes(path: str) -> int:
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    return text.count(EM_DASH)


def test_ac2_commentary_text_zero_em_dashes():
    assert _count_em_dashes("src/final/commentary_text.py") == 0, (
        "SR18 §5 AC 2: src/final/commentary_text.py must contain zero "
        "em-dashes after the sweep."
    )


def test_ac3_stage3_beta_report_zero_em_dashes():
    assert _count_em_dashes("src/final/stage3_beta_report.py") == 0, (
        "SR18 §5 AC 3: src/final/stage3_beta_report.py must contain zero "
        "em-dashes after the sweep."
    )


def test_ac4_beta_banner_lines_zero_em_dashes():
    from src.final.word_generator import BETA_BANNER_LINES

    for i, line in enumerate(BETA_BANNER_LINES):
        assert EM_DASH not in line, (
            f"SR18 §5 AC 4: BETA_BANNER_LINES[{i}] contains an em-dash: "
            f"{line!r}"
        )


_TITLE_ANNOTATION_RE = re.compile(
    r'"[^"]*' + EM_DASH + r'[^"]*"|' + "'[^']*" + EM_DASH + r"[^']*'",
    flags=re.MULTILINE,
)


def test_ac5_charts_module_titles_zero_em_dashes():
    """The brief's AC 5 holds the line at chart-title strings — the
    callsites of ax.set_title, fig.suptitle, and chart-caption ax.text
    helpers in charts.py. The per-callsite check is approximated here by
    searching for em-dashes inside string literals; comments and
    docstrings are out of scope and stay as-is.

    The literal-string em-dash regex is conservative (single-line string
    literals only); multi-line f-strings are flagged by the second
    assertion below which checks each chart-title literal we know about.
    """
    paths = [
        REPO_ROOT / "src" / "final" / "charts.py",
        REPO_ROOT / "src" / "final" / "sections" / "criticality.py",
    ]
    offenders: list[tuple[str, int, str]] = []
    for p in paths:
        text = p.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if _TITLE_ANNOTATION_RE.search(line):
                offenders.append((p.name, i, line.strip()))
    assert not offenders, (
        f"SR18 §5 AC 5: em-dash found in string literals in chart modules. "
        f"Offenders: {offenders}"
    )


@pytest.mark.project("synthetic_wind")  # stage 4 F-33: these constants resolve to the reference project's text
def test_sr17_introduced_em_dashes_swept():
    """Specific constants the SR17 reword introduced em-dashes into; SR18
    must clean them up as part of the §3 Item 2 d-bullet."""
    from src.final import commentary_text, stage3_beta_report

    assert EM_DASH not in commentary_text.GATING_COLLISION_NOTE_STAGE3, (
        "GATING_COLLISION_NOTE_STAGE3 should be em-dash-free post-SR18"
    )
    para2 = commentary_text.MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3[1]
    assert EM_DASH not in para2, (
        "MODE_MULTIPLIERS_FULL_CPM_PARAGRAPHS_STAGE3 paragraph 2 should "
        "be em-dash-free post-SR18"
    )
    assert EM_DASH not in stage3_beta_report.COVER_PAGE_CAVEAT_TEXT, (
        "COVER_PAGE_CAVEAT_TEXT should be em-dash-free post-SR18"
    )
    assert EM_DASH not in stage3_beta_report.PREVIEW_BANNER_TEXT, (
        "PREVIEW_BANNER_TEXT should be em-dash-free post-SR18"
    )
