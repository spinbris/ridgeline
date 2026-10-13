"""SNAPSHOTCUT-01 S1: which tracked files ship in the public snapshot, and which stay private.

One file, as data. Every tracked path is classified exactly once, by the LONGEST matching entry:
an entry ending in ``/`` covers everything under that folder, any other entry is one exact path. A
tracked file that no entry matches is **unclassified, and unclassified is red** - never shipped by
default. This is an allowlist: the failure to fear is a file that ships because nobody named it.

Python rather than TOML because the brief requires the exclusion list to be imported, not
restated: ``EXCLUDED`` (READABILITY-01's link-rule list) lives here, and
``tests/test_readability01_public_docs.py`` imports it from here. A TOML file cannot import it.

Every ``private`` entry carries a one-line reason; ``ship`` entries need none.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SHIP = "ship"
PRIVATE = "private"

#: What does not ship, and the reason for each. RELEASE-01 plan D-2 and D-T, as read by PM ruling
#: R-3 (READABILITY-01, 01/10/2026): the conservative reading, under which fewer files ship, never
#: more. Only the ROOT CHANGELOG.md is excluded - tests/golden/CHANGELOG.md ships with the goldens.
#: Moved here from tests/test_readability01_public_docs.py at SNAPSHOTCUT-01; order and membership
#: unchanged, so the link rule's behaviour is unchanged.
_EXCLUDED_REASONS: dict[str, str] = {
    "CLAUDE.md": "the agent operating manual; process, not product",
    ".claude/": "agent hooks, commands and settings; process tooling",
    "scripts/flow.py": "the PM/Builder bus and lane tool; process tooling",
    "scripts/flow_evidence.py": "the bus's evidence recorder; process tooling",
    "docs/stage_briefs/": "stage briefs and the stage log; the record of the work",
    "docs/running_records/": "running records; the record of the work",
    "docs/OPEN_THREADS.md": "the register of open rows; the record of the work",
    "docs/programme/": "the product spec, roadmap and insider manuals",
    "docs/VAULT_WIKI.md": "points into a private knowledge base",
    "CHANGELOG.md": "the root change log; the record of the work",
    "docs/Aust_GLines/": "an internal gap analysis; left out by plan D-2",
    "docs/STAGE4_step2_fill_prompt.md": "a working prompt; D-T names it by its old path",  # path-walker: plant - moved at P1
    # "the operating-model documents" (D-2), listed by R-3
    "docs/OPERATING_MODEL_v2.md": "the operating model; process",
    "docs/PROCESS_DISCIPLINE.md": "process doctrine",
    "docs/GIT_AND_TEST_NOTES.md": "git and test process notes",
    "docs/PITFALLS.md": "internal pitfalls notes",
    "docs/ARCH_DEBT.md": "internal architectural-debt notes",
    "docs/STYLE.md": "internal style notes",
    "docs/INPUTS_REFERENCE.md": "internal input reference",
    "docs/procedures/": "internal procedures",
    # METHDUP-01's stale copies (plan D-2 leaves them out; gate 3 round 1, W3)
    "docs/system_description/": "stale copies of the method documents",
}

#: The link rule's list: no public document may reference one of these. Imported by
#: tests/test_readability01_public_docs.py; do not copy it.
EXCLUDED: tuple[str, ...] = tuple(_EXCLUDED_REASONS)

#: Everything else that is private, with its reason. Not in EXCLUDED, so the link rule does not
#: police references to these (that is the link-rule step's question, not this list's).
_OTHER_PRIVATE: dict[str, str] = {
    "dashboard/CLAUDE.md": "the dashboard's agent operating manual; process, not product",
    ".github/workflows/client-gate.yml": "needs the private term list as a secret",
    "docs/OPEN_THREADS_archive.md": "the register's archived rows; the record of the work",
    "gate_allow.txt": "the client gate's own allowlist state",
    "terms.sha256": "the client gate's term-list digest",
    "scripts/hooks/": "pre-commit and pre-push hooks; process tooling",
    "spikes/": "exploratory spikes, not product",
    "docs/am/": "internal design specs; private by the Director's ruling",
    "docs/reference/aust_cegn/": "a published government text; held until its licence is read",
    "docs/GUARD_CONVENTION.md": "internal convention note; default private for unnamed docs",
    "docs/REGUX01_cie_review_prompt.md": "a working review prompt",
    "docs/REGUX01_cie_verify_part2a_prompt.md": "a working review prompt",
    "docs/Tropic_Ridge_CEGN_Critical_Review.md": "an internal critical review",
    "docs/archived_references.toml": "internal manifest of archived references",
    "docs/cie/": "an internal finishing brief",
    "docs/openpyxl_excel_repair_playbook.md": "an internal repair playbook",
    # gate 3 round 1, B1: the private ignore rules name private paths; a public set ships instead
    ".gitignore": "names private paths; the snapshot ships scripts/release/public.gitignore in its place",
    "scripts/release/public.gitignore": "shipped as .gitignore, not at its own path",
    # gate 3 round 1, N8
    "scripts/release/machine_names.txt": "the build machines' names, which the cut searches every shipped file for",
    # gate 3 round 1, W3: each needs a private file at run time
    "scripts/release/cut_snapshot.py": "the release tool: reads the private repository (its tags, terms.sha256 "
                                       "and machine list) at run time",
    "scripts/measure_playbook_kestrel.py": "opens the private insider playbook at run time",
    "scripts/extract_cegn_text.py": "writes into the held government reference text; it goes with the held reference",
}

#: Tests that do not ship: each tests a private file or tool, or needs input that stays private.
#: A test that only mentions a private file, or checks a product surface and reads one private file
#: among several, is not here; it skips cleanly or iterates what ships instead.
_PRIVATE_TESTS: dict[str, str] = {
    # the process tooling: the bus, the lanes, the guard and the hooks
    "tests/test_flow_02c.py": "tests the private process tooling (flow.py, hooks)",
    "tests/test_flow_bus_watch.py": "tests the private process tooling (flow.py)",
    "tests/test_flow_close.py": "tests the private process tooling (flow.py, hooks)",
    "tests/test_flow_conditional.py": "tests the private process tooling (flow.py, hooks)",
    "tests/test_flow_evidence.py": "tests the private process tooling (flow_evidence.py)",
    "tests/test_flow_gate3_r1.py": "tests the private process tooling (flow.py, guard)",
    "tests/test_flow_gate3_r2.py": "tests the private process tooling (guard)",
    "tests/test_flow_guard.py": "tests the private agent guard (.claude/hooks)",
    "tests/test_flow_guard_git.py": "tests the private agent guard (.claude/hooks)",
    "tests/test_flow_lock_text.py": "tests the private process tooling (flow.py)",
    "tests/test_flow_prepush.py": "tests the private pre-push hook",
    "tests/test_flow_session_sync.py": "tests the private session hook (.claude/hooks)",
    "tests/test_flow_tool.py": "tests the private process tooling (flow.py)",
    "tests/test_flow_tool_units.py": "tests the private process tooling (flow.py)",
    # the record of the work
    "tests/test_stage_log.py": "tests the private stage log and its guard",
    "tests/test_governance_agreement.py": "tests the private roadmap and register against git tags",
    "tests/test_spec_versions.py": "tests the private product spec",
    "tests/test_docs_budget.py": "tests the private agent manual's word ceiling",
    # the insider playbook and the reference values that exist to back it
    "tests/test_dashgate01_playbook_insider.py": "pins the private insider playbook byte for byte",
    "tests/test_5b_playbook_reference.py": "tests the private insider playbook and the reference behind it",
    # need input that stays private
    "tests/test_reference_currency.py": "reads the held government reference text",
    "tests/tree_paths.py": "the tree-path walker; reads the private archived-references list",
    "tests/test_tree_paths.py": "the tree-path walker's tests; read the private archived-references list",
    # the release tool's tests, which cut from the private repository (gate 3 round 1, W3)
    "tests/test_snapshot_cut.py": "tests the private release tool against the private repository's files",
    # gate 3 round 2, finding 3
    "tests/private_shellout_exempt.py": "the private tests' shell-out exemptions, merged by tests/conftest.py",
}

#: The engagement-era one-off scripts (Director, 09/10/2026): each read inputs the snapshot does not
#: carry, for one sprint's check or one workbook's repair. One of the same era ships, because a
#: shipped test or document runs it: sr9_v34_migrate_fixture.py. Two more did, until SNAPSHOTCUT-01
#: retired the dead tests that ran them, and them (Director, 11/10/2026).
_PHASE2 = "an engagement-era one-off: strawman phase-2 build, repair or probe"
_SP17 = "an engagement-era one-off: an earlier strawman pre-flight, gate or bisect"
_BETA = "an engagement-era one-off: an earlier sprint's smoke evidence"
_SPRINT = "an engagement-era one-off: an earlier sprint's diagnostic or applier"
_ENGAGEMENT_SCRIPTS: dict[str, str] = {
    "scripts/_apply_beta08_stage_log_entry.py": _BETA,
    "scripts/_sr15_compare_baselines.py": _SPRINT,
    "scripts/beta14_smoke.py": _BETA,
    "scripts/beta15_smoke.py": _BETA,
    "scripts/beta16_smoke.py": _BETA,
    "scripts/beta17_smoke.py": _BETA,
    "scripts/sp18a_bootstrap_arrays.py": _SPRINT,
    "scripts/sr15_engine_determinism_check.py": _SPRINT,
    "scripts/sr17_diagnostic.py": _SPRINT,
    "scripts/sr19_diagnostic.py": _SPRINT,
    "scripts/sr1_diagnostic.py": _SPRINT,
    "scripts/sr2_diagnostic.py": _SPRINT,
    "scripts/sr5_diagnostic.py": _SPRINT,
    "scripts/sr8_diagnostic.py": _SPRINT,
    "scripts/sr9_v36_cross_val_diagnostic.py": _SPRINT,
    "scripts/sr9_v3_6_1_01_apply.py": _SPRINT,
    "scripts/sr9_v3_6_1_01_cell17_smoke.py": _SPRINT,
    "scripts/sr9_v3_6_1_02_apply_notebook.py": _SPRINT,
    "scripts/sr9_v3_6_1_02_html_check.py": _SPRINT,
    "scripts/sr9_v3_6_1_02_path_leak_inspect.py": _SPRINT,
    "scripts/sr9_v3_6_1_03_apply_notebook.py": _SPRINT,
    "scripts/sr9_v3_6_1_03_c6_apply.py": _SPRINT,
    "scripts/sr9_v3_6_1_03_c6_validate.py": _SPRINT,
    "scripts/sr9_v3_6_1_04_gate5_check.py": _SPRINT,
    "scripts/sra_bisect_xlsx.py": _SP17,
    "scripts/sra_gate1_diagnostic.py": _SP17,
    "scripts/sra_gate2_diagnostic.py": _SP17,
    "scripts/sra_gate3_diagnostic.py": _SP17,
    "scripts/sra_phase2_a1_a2.py": _PHASE2,
    "scripts/sra_phase2_b.py": _PHASE2,
    "scripts/sra_phase2_c.py": _PHASE2,
    "scripts/sra_phase2_c4.py": _PHASE2,
    "scripts/sra_phase2_d.py": _PHASE2,
    "scripts/sra_phase2_d_preview.py": _PHASE2,
    "scripts/sra_phase2_diagnose_formulas.py": _PHASE2,
    "scripts/sra_phase2_diagnose_open.py": _PHASE2,
    "scripts/sra_phase2_e.py": _PHASE2,
    "scripts/sra_phase2_e_readback.py": _PHASE2,
    "scripts/sra_phase2_f.py": _PHASE2,
    "scripts/sra_phase2_fix_p6_table.py": _PHASE2,
    "scripts/sra_phase2_fix_risk_scope_spare.py": _PHASE2,
    "scripts/sra_phase2_force_recalc.py": _PHASE2,
    "scripts/sra_phase2_inspect_row6.py": _PHASE2,
    "scripts/sra_phase2_isolate_formula.py": _PHASE2,
    "scripts/sra_phase2_mode_count_check.py": _PHASE2,
    "scripts/sra_phase2_patch_p13.py": _PHASE2,
    "scripts/sra_phase2_preflight.py": _PHASE2,
    "scripts/sra_phase2_probe.py": _PHASE2,
    "scripts/sra_phase2_probe_c.py": _PHASE2,
    "scripts/sra_phase2_spotcheck.py": _PHASE2,
    "scripts/sra_phase2_test_formula.py": _PHASE2,
    "scripts/sra_phase2_test_xlookup.py": _PHASE2,
    "scripts/sra_phase2_verify_post_fix.py": _PHASE2,
    "scripts/sra_preflight.py": _SP17,
}

_SHIPPED: tuple[str, ...] = (
    # the product
    "src/", "dashboard/", "templates/", "tools/", "config/", "data/",
    # tests ship (Director, 09/10/2026); which ones read private files is measured at the cut
    "tests/",
    # scripts ship, minus the process tooling named above
    "scripts/",
    # synthetic, public
    "examples/", "status_periods/",
    "docs/showcase/", "docs/diagrams/", "docs/architecture_diagram.png",
    # user documents (D-T)
    "docs/SOFTWARE_USER_GUIDE.md", "docs/PLAYBOOK.md", "docs/RELEASE_PROCEDURE_dashboard.md",
    "docs/run-recipes.md",
    # read at run time by tools/register_polish.py (Director, 09/10/2026)
    "docs/polish_handoff.md",
    # CI: the audit lane, and the weekly full suite (inert without a self-hosted runner);
    # the client-gate workflow stays private
    ".github/workflows/ci.yml", ".github/workflows/nightly.yml", ".github/workflows/cycle-time.yml",
    # root: the product's entry points and repository plumbing
    "README.md", "ARCHITECTURE.md", "METHODOLOGY.md", "SCALABILITY.md", "LICENSE", "PROVENANCE.md",
    "pyproject.toml", "pytest.ini", "requirements.txt", "requirements-dev.txt",
    "requirements_client.txt", "requirements-lock-20260901-py312.txt",
    "RUN_FINAL.bat", "RUN_PERIOD.bat", "PUBLISH_PERIOD.bat",
    "report_html.j2", "final_runner.ipynb", ".gitattributes",
)

#: A file the snapshot carries at a path whose private file stays private: the published path, and
#: the tracked file whose bytes ship there. Each source is itself a private entry.
SHIPPED_AS: dict[str, str] = {
    ".gitignore": "scripts/release/public.gitignore",
}


def _entries() -> dict[str, tuple[str, str]]:
    """Every entry, as path -> (classification, reason). An entry named twice is a defect."""
    out: dict[str, tuple[str, str]] = {}
    sources = (
        [(p, (PRIVATE, r)) for p, r in _EXCLUDED_REASONS.items()]
        + [(p, (PRIVATE, r)) for p, r in _OTHER_PRIVATE.items()]
        + [(p, (PRIVATE, r)) for p, r in _PRIVATE_TESTS.items()]
        + [(p, (PRIVATE, r)) for p, r in _ENGAGEMENT_SCRIPTS.items()]
        + [(p, (SHIP, "")) for p in _SHIPPED]
    )
    for path, value in sources:
        if path in out:
            raise ValueError(f"manifest names {path!r} twice")
        out[path] = value
    return out


MANIFEST: dict[str, tuple[str, str]] = _entries()


def match(path: str) -> str | None:
    """The longest manifest entry covering ``path`` (a repo-relative, forward-slash path), or None."""
    best = None
    for entry in MANIFEST:
        hit = path.startswith(entry) if entry.endswith("/") else path == entry
        if hit and (best is None or len(entry) > len(best)):
            best = entry
    return best


def classify(path: str) -> str | None:
    """``ship``, ``private``, or None when no entry covers the path (unclassified: red)."""
    entry = match(path)
    return None if entry is None else MANIFEST[entry][0]


def tracked_files(root: Path = REPO, ref: str | None = None) -> list[str]:
    """The tracked files: the index when ``ref`` is None, else the tree at ``ref``."""
    cmd = ["git", "-C", str(root)]
    cmd += ["ls-files", "-z"] if ref is None else ["ls-tree", "-r", "-z", "--name-only", ref]
    out = subprocess.run(cmd, check=True, capture_output=True, env=_git_env()).stdout.decode("utf-8")
    return [p for p in out.split("\0") if p]


def _git_env() -> dict[str, str]:
    """The repository's clean git environment (no GIT_DIR a hook exported)."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from src.git_identity import git_env

    return git_env()


def unclassified(paths: list[str]) -> list[str]:
    return [p for p in paths if classify(p) is None]


def shipped(paths: list[str]) -> list[str]:
    """The published paths: each shipped path, and each ``SHIPPED_AS`` path whose source is tracked.
    Refuses when any path is unclassified, naming them."""
    missing = unclassified(paths)
    if missing:
        raise ValueError("unclassified tracked files (classify each in "
                         "scripts/release/snapshot_manifest.py): " + ", ".join(missing))
    tracked = set(paths)
    return [p for p in paths if classify(p) == SHIP] + [
        public for public, source in SHIPPED_AS.items() if source in tracked]


def source(path: str) -> str:
    """The tracked file whose bytes ship at the published ``path``."""
    return SHIPPED_AS.get(path, path)
