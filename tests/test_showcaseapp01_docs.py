"""SHOWCASEAPP-01 P7 and P8: the operator docs say what E3 measured, and what the publish command does.

P7 - the release procedure, measured on the first real `vercel build` of this tree (P4) and the first
preview deploy (P5): no "not re-measured here"; step 0 says how a link is made, and what it does
besides; step 5 sets the bypass secret without putting it on a command line; step 6 lists the
integrated card (D-K) and the brand line. `dashboard/README.md` says the showcase is linked from
here and how it is protected, and names no URL.

P8 - PUBLISHGUIDE-01 and PUBLISHBAT-01: the guide and the batch file say what `PUBLISH_PERIOD` prints
(the four-step preview sequence, not "two commands"), and the guide lists the two refusals DASHGATE-01
added.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROCEDURE = REPO / "docs" / "RELEASE_PROCEDURE_dashboard.md"
README = REPO / "dashboard" / "README.md"
GUIDE = REPO / "docs" / "SOFTWARE_USER_GUIDE.md"
BAT = REPO / "PUBLISH_PERIOD.bat"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin:text.index(end, begin + len(start))]


# --- P7: the release procedure --------------------------------------------------------------------

def test_the_procedure_no_longer_says_the_build_was_not_measured_here():
    assert "not re-measured here" not in _read(PROCEDURE)


def test_step_0_says_how_the_link_is_made_and_what_it_does_besides():
    step0 = _section(_read(PROCEDURE), "### 0. ", "### 1. ")
    assert "answer **No**" in step0, "step 0 does not say to decline the Git connection"
    assert "dashboard\\.gitignore" in step0, "step 0 does not name the .gitignore lines link appends"
    assert "vercel pull --environment=preview" in step0, "step 0 does not name the settings pull"
    assert "project_settings_required" in step0, "step 0 does not say what an unsettled build does"


def test_step_3_records_the_measured_config():
    step3 = " ".join(_section(_read(PROCEDURE), "### 3. Guard", "### 4. ").split())
    assert "CLI 59.1.3" in step3 and "no `overrides`" in step3


def test_step_5_never_puts_the_secret_on_a_command_line():
    step5 = _section(_read(PROCEDURE), "### 5. Smoke", "### 6. ")
    assert not re.search(r'VERCEL_AUTOMATION_BYPASS_SECRET\s*=\s*"', step5), \
        "step 5 still sets the secret as a literal, which puts it in the shell's history"
    assert "Read-Host -AsSecureString" in step5


def test_step_6_lists_the_integrated_card_and_the_brand_line():
    step6 = _section(_read(PROCEDURE), "### 6. ", "### 7. ")
    assert "integrated" in step6, "step 6 does not list the integrated card on / (D-K)"
    assert "A CBL Analytics product." in step6, "step 6 does not list the brand line"


def test_the_readme_says_the_showcase_is_linked_here_and_how_it_is_protected():
    deployments = _section(_read(README), "## Deployments", "\n## ")
    assert "no Vercel project is linked to\nthis directory" not in deployments
    assert "tropic-ridge-qsra" in deployments
    assert "Vercel Authentication" in deployments
    assert "https://" not in deployments, "the README records a URL before R"


# --- P8: PUBLISHGUIDE-01 and PUBLISHBAT-01 --------------------------------------------------------

def test_the_guide_says_what_publish_period_prints():
    s103 = _section(_read(GUIDE), "### 10.3 ", "## 11. ")
    assert "two commands" not in s103, "PUBLISHGUIDE-01: the guide still says two commands"
    for step in ("build_guard.py clear", "vercel build", "build_guard.py check",
                 "vercel deploy --prebuilt"):
        assert step in s103, f"the guide does not name the printed step {step!r}"


def test_the_guide_lists_the_two_dashgate_refusals():
    s103 = _section(_read(GUIDE), "### 10.3 ", "## 11. ")
    assert "not named for publication" in s103 and "confidential" in s103
    assert "meta.project_key" in s103


def test_the_batch_file_says_what_it_prints():
    header = _read(BAT).split("if ")[0]
    assert "two commands" not in header, "PUBLISHBAT-01: the header still says two commands"
    assert "four" in header
