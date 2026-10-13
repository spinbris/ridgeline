"""The guide, the spec and the playbook name only paths that exist (REPORTDOC-01 P-6 to P-9).

The walker is ``tests/doc_paths.py``; its docstring says what resolves and why. This module holds
the three documents to it, holds each document's exemptions, and proves the walker can fail on
the shapes it exists for - the two found live on 13/09/2026 among them.

The guide's two path limbs lived in ``tests/test_guide_tripwire.py`` until this brief and moved
here unchanged in coverage: the same twenty distinct spans are candidates under both, measured
before the move. Resolution is now against the tracked tree rather than the disk, which is the
stricter of the two.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.doc_paths import (
    Exemption,
    Tree,
    candidate_count,
    describe,
    spans,
    stale_exemptions,
    unresolved,
)
from tests.input_skips import private_documents_skip

REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE = "docs/SOFTWARE_USER_GUIDE.md"
SPEC = "docs/programme/SPEC_product.md"  # link-rule: the private spec's or insider playbook's paths are walked when present, skipped when absent
PLAYBOOK = "docs/PLAYBOOK.md"
INSIDER_PLAYBOOK = "docs/programme/manuals_insider/PLAYBOOK.md"  # link-rule: the private spec's or insider playbook's paths are walked when present, skipped when absent

_S0 = "0. Why this document exists"
_S2 = "2. Surfaces - what a user can pick up"
_S2A = "2a. Entry points - what is supported, what is retired"
_S6A = "6a. Deliverable contract (from the notebook review §2-3, §7)"
_S8 = "8. Decisions"
_S9 = "9. Lock"

_ARCHIVED_AM = "in the archived active-management repository, frozen at 6c071ff (SPEC bases)"
_ARCHIVED_ENG = "in the archived engagement repository, frozen at 4f62147 (SPEC bases)"
_RETIRED = "retired at stage 3c; §2a exists to say so (R-4)"
_RETIRED_REFRETIRE = "retired at REFRETIRE-01; §2a exists to say so"
_XLWINGS_TAB = "a tab in the xlwings Lite editor, not a repository file"

#: The Kestrel walkthrough's exemptions. Its full text lives in the insider copy since
#: READABILITY-01 P1; the public copy carries the same list until its own rewrite.
_PLAYBOOK_EXEMPTIONS = [
    Exemption("Step 1 - Create the project's register from the template", "register_v1.xlsx",
              "the file the reader creates, under outputs\\<project>\\"),
    Exemption("Step 3 - Cost QRA in the workbook (Tier 1; activation is the specialist's)",
              "sample.nb.py", _XLWINGS_TAB),
    Exemption("Step 3 - Cost QRA in the workbook (Tier 1; activation is the specialist's)",
              "main.py", _XLWINGS_TAB),
    Exemption("Step 5 - Run the schedule arm and the integrated result (Tier 2)",
              "ERROR: .venv\\Scripts\\python.exe not found", "quoted error text"),
    Exemption("Step 7 - Produce a period and serve it in the app",
              "ERROR: .venv\\Scripts\\python.exe not found", "quoted error text"),
]

#: Every exemption names the heading it is scoped to and why the span is meant not to resolve.
EXEMPTIONS: dict[str, list[Exemption]] = {
    GUIDE: [
        Exemption("5.1 Activation, once per machine and workbook", "main.py", _XLWINGS_TAB),
    ],
    SPEC: [
        Exemption(_S0, "docs/stage_briefs/SRA-01_design_brief.md:113", _ARCHIVED_ENG),  # link-rule: a walker exemption for a line of the private spec, used only when the spec is present
        Exemption(_S0, "docs/programme/PRODUCT_PATH_inventory.md", _ARCHIVED_AM),  # link-rule: a walker exemption for a line of the private spec, used only when the spec is present
        *(Exemption(_S2A, name, _RETIRED) for name in (
            "RUN_SRA.bat", "RUN_INTEGRATED.bat", "RUN_REPORT.bat", "_build_final_runner_*.py",
            "run_report.py", "export_report.py", "report_template.ipynb", "run_from_excel.py",
            "run_single_only.py", "run_assumptions_from_excel.py", "setup_vba.py",
            "check_dist.py", "run_toc_sensitivity.py", "diagnose_reader_diff.py",
        )),
        Exemption(_S6A, "run_report.py:31-32", _RETIRED + "; cited for the PDF it alone produced (D-12)"),
        Exemption(_S8, "run_report.py", "R-4 and D-5 name the retired report path"),
        Exemption(_S8, "export_report.py", "R-4 names the retired report path"),
        Exemption(_S2A, "main.py", _RETIRED_REFRETIRE),
        Exemption(_S9, "main.py", _RETIRED_REFRETIRE + "; v1.12 records the retirement"),
        Exemption(_S9, "scripts/sr9_diagnostic.py",
                  "v1.8's change record names the script REPORT01 F-G retired"),
    ],
    PLAYBOOK: _PLAYBOOK_EXEMPTIONS,
    INSIDER_PLAYBOOK: _PLAYBOOK_EXEMPTIONS,
}

#: Guard the guard (P-9). Measured 13/09/2026 at 45 / 101 / 38; floors sit below with room.
CANDIDATE_FLOOR = {GUIDE: 35, SPEC: 80, PLAYBOOK: 30, INSIDER_PLAYBOOK: 30}

DOCUMENTS = (GUIDE, SPEC, PLAYBOOK, INSIDER_PLAYBOOK)


@pytest.fixture(scope="module")
def tree() -> Tree:
    return Tree.from_git(REPO_ROOT)


def _read(doc: str) -> str:
    path = REPO_ROOT / doc
    assert path.exists(), f"missing: {doc}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("doc", private_documents_skip(DOCUMENTS))
def test_the_document_names_paths_to_check(doc: str) -> None:
    """A walker that silently matched nothing would pass every limb below."""
    count = candidate_count(_read(doc))
    assert count >= CANDIDATE_FLOOR[doc], f"{doc}: only {count} path candidates found"


@pytest.mark.parametrize("doc", private_documents_skip(DOCUMENTS))
def test_every_path_the_document_names_resolves(doc: str, tree: Tree) -> None:
    missing = unresolved(_read(doc), tree, EXEMPTIONS[doc])
    assert not missing, f"{doc} names paths that do not exist:\n  " + describe(missing)


@pytest.mark.parametrize("doc", private_documents_skip(DOCUMENTS))
def test_no_exemption_outlives_its_reason(doc: str, tree: Tree) -> None:
    stale = stale_exemptions(_read(doc), tree, EXEMPTIONS[doc])
    assert not stale, f"{doc} carries stale exemptions:\n  " + "\n  ".join(
        f"`{e.span}` under '{e.section}': {why}" for e, why in stale)


# --- the walker can fail ---------------------------------------------------------------------

_SMALL = Tree(["src/a.py", "tests/conftest.py", "tools/conftest.py", "RUN_FINAL.bat",
               "scripts/client_gate.py", "docs/design/01_Workflow_Design.md"])  # path-walker: plant


def _texts(doc: str, tree: Tree = _SMALL, exemptions: list[Exemption] | None = None) -> list[str]:
    return [s.text for s in unresolved(doc, tree, exemptions or [])]


def test_a_line_suffix_is_stripped_and_the_file_still_has_to_exist() -> None:
    assert _texts("`src/a.py:12` and `src/a.py:3-9,14`") == []
    assert _texts("`src/gone.py:12`") == ["src/gone.py:12"]


def test_a_line_suffix_does_not_hide_a_bare_filename_from_the_walker() -> None:
    """``run_report.py:31-32`` was not a candidate at all before this brief."""
    assert _texts("`gone.py:31-32`") == ["gone.py:31-32"]


def test_a_bare_filename_resolves_only_when_one_tracked_file_carries_it() -> None:
    assert _texts("`client_gate.py`") == []
    assert _texts("`conftest.py`") == ["conftest.py"], "two carriers is ambiguous, not resolved"
    assert _texts("`nowhere.py`") == ["nowhere.py"]


def test_a_glob_resolves_only_when_it_matches_something() -> None:
    assert _texts("`RUN_*.bat`") == []
    assert _texts("`RETIRED_*.bat`") == ["RETIRED_*.bat"]


def test_a_glob_with_no_directory_matches_root_files_only() -> None:
    """Review WARN 1: a retired root launcher must not stay green on a fixture elsewhere."""
    assert _texts("`RUN_*.bat`", Tree(["RUN_FINAL.bat", "RUN_PERIOD.bat"])) == []
    assert _texts("`RUN_*.bat`", Tree(["tests/fixtures/RUN_OLD.bat"])) == ["RUN_*.bat"]


def test_a_glob_star_does_not_cross_a_directory() -> None:
    assert _texts("`docs/*.md`", Tree(["docs/sub/x.md"])) == ["docs/*.md"]
    assert _texts("`docs/*.md`", Tree(["docs/x.md"])) == []


def test_runtime_paths_and_placeholders_are_not_checked_but_near_misses_are() -> None:
    assert _texts("`outputs\\runs\\x.json` `inputs/` `outputs\\<project>\\r.xlsx`") == []
    assert _texts("`outputsx/a.py`") == ["outputsx/a.py"]


def test_spans_inside_fenced_blocks_are_not_prose_and_a_fenced_hash_is_not_a_heading() -> None:
    doc = "## Real\n```powershell\n# not a heading\n`gone.py`\n```\n`also_gone.py`\n"
    found = spans(doc)
    assert [(s.section, s.text) for s in found] == [("Real", "also_gone.py")]


def test_an_exempted_glob_whose_family_returns_anywhere_is_stale() -> None:
    """Re-review WARN, 13/09/2026: the root-only glob rule is right for resolving a pointer and
    wrong for staleness, which must notice a retired family arriving wherever it lands."""
    doc = "## Entry points\n`_build_final_runner_*.py`\n"
    exempt = [Exemption("Entry points", "_build_final_runner_*.py", "retired at 3c")]
    assert stale_exemptions(doc, Tree(["src/a.py"]), exempt) == []
    stale = stale_exemptions(doc, Tree(["scripts/_build_final_runner_html.py"]), exempt)
    assert [why for _, why in stale] == ["its span now resolves in this repository"]


def test_an_unclosed_fence_fails_rather_than_skipping_the_rest() -> None:
    """Review WARN 2: a bare toggle, left open, swallowed every span to the end of the document."""
    with pytest.raises(ValueError, match="line 2"):
        spans("## A\n```\n`gone.py`\n")


@pytest.mark.parametrize("doc", [
    "## A\n~~~\n`in_fence.py`\n~~~\n`after.py`\n",
    "## A\n````\n```\n`in_fence.py`\n```\n````\n`after.py`\n",
    "## A\n```powershell\n`in_fence.py`\n```\n`after.py`\n",
])
def test_a_fence_closes_only_on_its_own_marker(doc: str) -> None:
    assert [s.text for s in spans(doc)] == ["after.py"]


def test_an_exemption_under_a_repeated_heading_is_stale() -> None:
    """Review WARN 3: two headings with one text would share an exemption, which is the
    span-alone hole P-7 closes, one level up."""
    doc = "## History\n`gone.py`\n## History\n`gone.py`\n"
    stale = stale_exemptions(doc, _SMALL, [Exemption("History", "gone.py", "change record")])
    assert [why for _, why in stale] == ["its heading is not unique in the document"]


def test_an_exemption_covers_its_own_section_only() -> None:
    doc = "## History\n`gone.py`\n## Contract\n`gone.py`\n"
    exempt = [Exemption("History", "gone.py", "named in the change record")]
    missing = unresolved(doc, _SMALL, exempt)
    assert [(s.section, s.text) for s in missing] == [("Contract", "gone.py")]


def test_an_exemption_whose_span_has_left_its_section_is_stale() -> None:
    doc = "## History\nnothing here now\n"
    stale = stale_exemptions(doc, _SMALL, [Exemption("History", "gone.py", "was named")])
    assert [why for _, why in stale] == ["its span no longer appears under its heading"]


def test_an_exemption_whose_file_has_arrived_is_stale_even_at_another_path() -> None:
    doc = "## Rhythms\n`docs/01_Workflow_Design.md`\n"
    exempt = [Exemption("Rhythms", "docs/01_Workflow_Design.md", "archived repository")]
    assert unresolved(doc, _SMALL, exempt) == []
    stale = stale_exemptions(doc, _SMALL, exempt)
    assert [why for _, why in stale] == ["its span now resolves in this repository"]


# --- the two live instances, on the real documents -------------------------------------------

@pytest.mark.needs_input(SPEC)  # the control is built on the private spec
def test_sr9_diagnostic_back_in_the_outputs_row_reds_despite_its_history_exemption(tree: Tree) -> None:
    """SPECCONTRACT-01's second instance. §9 names the retired script legitimately; putting it
    back into §6a's Outputs row - where it stood until v1.8 - must still red."""
    spec = _read(SPEC)
    live = "re-rendered by `scripts/run_diagnostic.py`"
    assert spec.count(live) == 1, "the §6a Outputs row no longer reads as this test expects"
    doctored = spec.replace(live, "re-rendered by `scripts/sr9_diagnostic.py`")
    missing = unresolved(doctored, tree, EXEMPTIONS[SPEC])
    assert [(s.section, s.text) for s in missing] == [(_S6A, "scripts/sr9_diagnostic.py")]


@pytest.mark.needs_input(SPEC)  # the control is built on the private spec
def test_the_pre_v1_9_workflow_design_pointer_reds_even_if_exempted(tree: Tree) -> None:
    """SPECCONTRACT-01's third instance, found by this walker on 13/09/2026. §5 cited the May
    workflow design in the archived repository after RS-A2 had moved it into this one."""
    spec = _read(SPEC)
    live = "(`docs/am/01_Workflow_Design.md`, moved into this repository by RS-A2)"  # link-rule: this test reads the private spec when present (needs_input above) and checks this text in it
    assert spec.count(live) == 1, "§5 no longer cites the workflow design as this test expects"
    doctored = spec.replace(live, "(archived AM repo, `docs/01_Workflow_Design.md`)")
    missing = unresolved(doctored, tree, EXEMPTIONS[SPEC])
    assert [s.text for s in missing] == ["docs/01_Workflow_Design.md"]
    exempted = EXEMPTIONS[SPEC] + [
        Exemption("5. The two rhythms", "docs/01_Workflow_Design.md", "archived AM repo")]
    stale = stale_exemptions(doctored, tree, exempted)
    assert [(e.span, why) for e, why in stale] == [
        ("docs/01_Workflow_Design.md", "its span now resolves in this repository")]


def test_the_tree_refuses_a_directory_git_does_not_know(tmp_path: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        Tree.from_git(tmp_path)
