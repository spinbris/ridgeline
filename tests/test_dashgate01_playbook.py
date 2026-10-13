"""DASHGATE-01 PM ruling R-6: the PLAYBOOK's Kestrel publish expects the refusal.

Kestrel is `synthetic_road`, which is not named for publication, so `PUBLISH_PERIOD` refuses it:
that is the gate working. `test_stage5_playbook_tripwire` checks that the PLAYBOOK's commands name
files and flags that exist, not what they print; this pins the outcome the walkthrough promises.

The Kestrel reference-value pins, which hold the insider copy byte for byte, are in
a private test, which does not ship (SNAPSHOTCUT-01).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
#: The Kestrel walkthrough these pins hold: the insider copy since READABILITY-01 P1.
PLAYBOOK = REPO / "docs" / "programme" / "manuals_insider" / "PLAYBOOK.md"  # link-rule: the insider playbook's dashboard checks run when it is present, skip when absent
#: The public walkthrough promises the same refusal (READABILITY-01 gate 3 round 1, N5).
PUBLIC_PLAYBOOK = REPO / "docs" / "PLAYBOOK.md"
#: The insider copy is checked wherever it is present and skips, naming itself, in the public snapshot.
BOTH = pytest.mark.parametrize("copy", [
    pytest.param(PUBLIC_PLAYBOOK, id="public"),
    pytest.param(PLAYBOOK, id="insider", marks=pytest.mark.needs_input("docs/programme/manuals_insider/PLAYBOOK.md")),  # link-rule: the insider playbook's dashboard checks run when it is present, skip when absent
])
REFUSAL = "PUBLISH REFUSED: project 'synthetic_road' may not be published: it is not named for publication"


def _after(text: str, marker: str, span: int = 2500) -> str:
    i = text.index(marker)
    return text[i:i + span]


@BOTH
def test_the_period_step_expects_the_road_publish_to_be_refused(copy: Path):
    text = copy.read_text(encoding="utf-8")
    section = _after(text, ".\\PUBLISH_PERIOD.bat <json-path-printed-above> --project $binding")
    expect = section[section.index("**Expect.**"):]
    assert REFUSAL in expect.split("**If not.**")[0], "the Kestrel publish still expects a build"
    assert "synthetic_wind" in section, "the walkthrough no longer points at the named showcase"


@BOTH
def test_step_b5_expects_the_refusal_for_a_project_not_named(copy: Path):
    text = copy.read_text(encoding="utf-8")
    b5 = text[text.index("### Step B.5 - Publish"):text.index("### Step B.6")]
    assert REFUSAL in b5, "step B.5 still promises a build for a project that is refused"


def test_the_quoted_refusal_is_what_the_code_prints():
    """The PLAYBOOK quotes the real message, not a paraphrase."""
    import pytest

    from src.am.publish_period import PublishError, refuse_unpublishable

    with pytest.raises(PublishError) as exc:
        refuse_unpublishable("synthetic_road")
    assert f"PUBLISH REFUSED: {exc.value}".startswith(REFUSAL)
