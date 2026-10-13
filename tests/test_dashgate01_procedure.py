"""DASHGATE-01 P6: the release procedure names what is now automatic, and it all exists.

A procedure that names a command nobody can run - or still tells the operator to do by hand what
the code now does - is a check on the wrong artefact. Each named command is resolved here.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROCEDURE = REPO / "docs" / "RELEASE_PROCEDURE_dashboard.md"

NAMED = {
    "scripts/release/route_smoke_check.py": "step 5",
    "scripts/release/served_vs_promoted_check.py": "step 8",
    "scripts/release/write_publish_list.py": "step 0",
    "scripts/release/build_guard.py": "step 3",
}
STALE = (
    r"script owed",
    r"until the script lands",
    r"do not use `--deploy`\*\*",
    r"A filter in code is owed",
    r"Tooling owed",
)


def test_the_procedure_names_each_check_and_each_exists():
    text = PROCEDURE.read_text(encoding="utf-8")
    for script, step in NAMED.items():
        assert script in text, f"the procedure no longer names {script} ({step})"
        assert (REPO / script).is_file(), f"the procedure names {script}, which does not exist"
    assert "guard_build_output" in text, "the procedure no longer names the build-output guard"
    from src.am.publish_period import guard_build_output  # noqa: F401  - it resolves


def test_the_procedure_no_longer_says_the_checks_are_owed():
    text = PROCEDURE.read_text(encoding="utf-8")
    found = [p for p in STALE if re.search(p, text)]
    assert not found, f"the procedure still describes as owed what DASHGATE-01 built: {found}"


def test_step_3_states_the_rule_the_guard_enforces():
    """The doc and the guard must not state different properties (PM R-1; round 1 W5). The rule is
    behaviour-tested in `test_dashgate01_deploy_guard.py`; this holds the text to it."""
    text = PROCEDURE.read_text(encoding="utf-8")
    step3 = text[text.index("### 3. Guard"):text.index("### 4. ")]
    assert "every string in `config.json`" in step3, "step 3 no longer states the all-strings rule"
    assert "except the\nvalue of `routes[].src`" in step3 or "except the value of `routes[].src`" in step3
    assert "fails closed" in step3, "step 3 no longer says the guard refuses an unknown shape"
    assert "this build did not produce" in step3, "step 3 no longer states the stale-output rule"
    for step in ("build_guard.py clear", "vercel build", "build_guard.py check", "vercel deploy --prebuilt"):
        assert step in step3, f"step 3's by-hand sequence no longer names {step!r}"


def test_the_by_hand_sequence_is_the_printed_sequence():
    """Step 3's four by-hand commands are `deploy_steps`' four, in order (N6: and where they run)."""
    from src.am import publish_period

    steps = publish_period.deploy_steps(production=False)
    assert [s.action for s in steps] == ["clear", "vercel", "guard", "vercel"]
    assert [s.where for s in steps] == ["repository root", "dashboard", "repository root", "dashboard"]


def test_step_5_claims_only_what_the_script_proves_and_step_6_carries_the_rest():
    """PM R-8: check 1 proves 200-as-HTML; the rendered elements are step 6's, by hand."""
    text = PROCEDURE.read_text(encoding="utf-8")
    step5 = text[text.index("### 5. Smoke"):text.index("### 6. ")]
    step6 = text[text.index("### 6. "):text.index("### 7. ")]
    assert "`text/html`" in step5 and "404s" in step5 and "byte-match" in step5
    assert "What it does not prove: the rendered elements" in step5
    assert "checked by hand, on every route, in step 6" in step5
    assert "renders each\npathname-dependent element" not in step5, "step 5 still claims rendering"
    for element in ("nav tab is highlighted", "page-title suffix", "guidance strip is present"):
        assert element in step6, f"step 6 no longer lists: {element}"



def _by_hand_block() -> list[str]:
    text = PROCEDURE.read_text(encoding="utf-8")
    step3 = text[text.index("### 3. Guard"):text.index("### 4. ")]
    block = step3[step3.index("```powershell"):]
    block = block[len("```powershell"):block.index("```", 3)]
    return [" ".join(ln.split("#", 1)[0].split()) for ln in block.strip().splitlines()]


def test_the_by_hand_commands_are_the_printed_commands_word_for_word():
    """Round 2, NOTE-1: the printed clear and guard name the venv interpreter, as the by-hand
    block does; the texts, not only the actions, are equal."""
    from src.am import publish_period

    printed = [" ".join(s.argv) for s in publish_period.deploy_steps(production=False)]
    assert _by_hand_block() == printed, (_by_hand_block(), printed)


def test_the_opening_says_a_build_ships_only_named_projects():
    """Round 2, breaker WARN-1: the procedure's opening agrees with step 0."""
    text = PROCEDURE.read_text(encoding="utf-8")
    opening = " ".join(text[:text.index("## ")].split())
    assert "ships every project in" not in opening, "the opening says every project ships"
    assert "named for publication" in opening, "the opening no longer says only named projects ship"
