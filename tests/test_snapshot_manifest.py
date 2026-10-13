"""SNAPSHOTCUT-01 S1: every tracked file is classified exactly once, and an unclassified file is red.

The manifest is ``scripts/release/snapshot_manifest.py``. Longest match decides, so a file is
classified once by construction; an entry named twice is refused when the module loads. What this
file pins is the allowlist direction: a tracked file no entry covers fails here, naming itself,
rather than shipping because nobody named it.
"""
from __future__ import annotations

import pytest

import scripts.release.snapshot_manifest as m


def test_every_tracked_file_is_classified():
    missing = m.unclassified(m.tracked_files())
    assert not missing, (
        f"{len(missing)} tracked file(s) not classified in scripts/release/snapshot_manifest.py "
        f"(add a ship or private entry): {missing}")


# --- the matcher, on paths that exercise each rule --------------------------------------------

@pytest.mark.parametrize("path, expected", [
    ("src/simulation.py", m.SHIP),
    ("scripts/client_gate.py", m.SHIP),
    ("scripts/flow.py", m.PRIVATE),                 # an exact entry beats the scripts/ folder
    ("scripts/hooks/pre-commit", m.PRIVATE),        # a deeper folder beats a shallower one
    ("CHANGELOG.md", m.PRIVATE),                    # only the root change log is private
    ("tests/golden/CHANGELOG.md", m.SHIP),
    ("CLAUDE.md", m.PRIVATE),
    ("dashboard/CLAUDE.md", m.PRIVATE),
    ("dashboard/package.json", m.SHIP),
    (".github/workflows/ci.yml", m.SHIP),
    (".github/workflows/client-gate.yml", m.PRIVATE),
    ("docs/am/03_JSON_Contract_Spec_v2_6.md", m.PRIVATE),
    ("docs/polish_handoff.md", m.SHIP),              # read at run time by a shipped tool
    ("tests/test_flow_guard.py", m.PRIVATE),         # an exact test entry beats tests/
    ("tests/tree_paths.py", m.PRIVATE),
    (".gitignore", m.PRIVATE),                       # the private rules; the public set ships there
    ("scripts/release/public.gitignore", m.PRIVATE), # an exact entry beats scripts/
])
def test_longest_match_decides(path, expected):
    assert m.classify(path) == expected


def test_a_file_shipped_in_anothers_place_is_published_at_its_path_and_its_source_is_private():
    published = m.shipped(["src/simulation.py", ".gitignore", "scripts/release/public.gitignore"])
    assert published == ["src/simulation.py", ".gitignore"]
    assert m.source(".gitignore") == "scripts/release/public.gitignore"
    assert m.source("src/simulation.py") == "src/simulation.py"
    for public, source in m.SHIPPED_AS.items():
        assert m.classify(public) == m.PRIVATE and m.classify(source) == m.PRIVATE, public
    assert m.shipped(["src/simulation.py"]) == ["src/simulation.py"]  # no source, nothing published


@pytest.mark.parametrize("path", [
    "NEW_ROOT_FILE.md",                 # no root catch-all; path-walker: plant
    "docs/a_new_document.md",           # no docs/ catch-all; path-walker: plant
    ".github/workflows/new.yml",        # a folder named only by its files; path-walker: plant
    "scripts",                          # a folder entry does not match the bare folder name
    "srcx/file.py",                     # a prefix of a folder is not under it; path-walker: plant
])
def test_an_unnamed_path_is_unclassified(path):
    assert m.classify(path) is None


def test_shipped_refuses_an_unclassified_file_by_name():
    with pytest.raises(ValueError, match="docs/a_new_document.md"):  # path-walker: plant
        m.shipped(["src/simulation.py", "docs/a_new_document.md"])  # path-walker: plant


#: Entries that name no tracked file, each with its reason. Any other such entry is a defect: a
#: misspelled or renamed private entry falls through to a shallower folder such as ``tests/`` and
#: the file it meant SHIPS (gate 3 round 1, W5).
NAMES_NOTHING: dict[str, str] = {
    "docs/STAGE4_step2_fill_prompt.md": "the link rule's recogniser for D-T's old path; the file moved at P1",  # path-walker: plant
}


def entries_naming_nothing(entries, tracked: list[str]) -> list[str]:
    """Entries no tracked file matches: an exact entry not tracked, a folder entry with nothing under it."""
    files = set(tracked)
    return [e for e in entries
            if (not any(p.startswith(e) for p in files) if e.endswith("/") else e not in files)]


def test_every_manifest_entry_names_a_tracked_file():
    tracked = m.tracked_files()
    # The public snapshot tracks no private file, so there only its ship entries can be checked.
    # (Its .gitignore is the public set, shipped in the private file's place: not a private file.)
    private_tracked = any(m.classify(p) == m.PRIVATE and p not in m.SHIPPED_AS for p in tracked)
    entries = [e for e, (cls, _) in m.MANIFEST.items() if private_tracked or cls == m.SHIP]
    expected = [e for e in NAMES_NOTHING if e in entries]
    assert entries_naming_nothing(entries, tracked) == expected


def test_red_a_misspelled_private_entry_is_named():
    planted = [*m.MANIFEST, "tests/test_flow_gaurd.py", "scripts/hookz/"]  # path-walker: plant
    found = entries_naming_nothing(planted, ["tests/test_flow_guard.py", "scripts/hooks/pre-commit"])
    assert {"tests/test_flow_gaurd.py", "scripts/hookz/"} <= set(found)  # path-walker: plant


def test_every_private_entry_has_a_reason_and_every_excluded_entry_is_private():
    for entry, (cls, reason) in m.MANIFEST.items():
        if cls == m.PRIVATE:
            assert reason.strip(), f"private entry {entry!r} has no reason"
        else:
            assert cls == m.SHIP, f"{entry!r} has classification {cls!r}"
    assert all(m.MANIFEST[e][0] == m.PRIVATE for e in m.EXCLUDED)
