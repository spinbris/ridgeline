"""The client gate scans what git could commit - and nothing it could not.

GATESCOPE-01, Director ruling 03/09/2026: "gate respects gitignore". Before it,
`scripts/client_gate.py` walked the whole working tree, so a file under an
ignored path - an activated register workbook that Excel re-stamps with the
operator's machine path on every save, a regenerated showcase figure whose
compressed bytes coincide with a four-character term - redded the gate although
it could never be committed. A gate that reds on "the known one" stops being
read. SPEC_product.md §7a, R-9.

WHAT THIS ASSERTS
    Three properties of `client_gate.walk()`, on a repository this module builds
    once:
    1. A file under an ignored path is NOT scanned.
    2. An untracked file that is NOT ignored IS scanned - it is one `git add`
       from being committed, which is exactly what the gate protects.
    3. With no `.git` at the root the whole tree is walked, as the RS-A cut ran
       it on a copied tree before the repository existed.

    No confidential term is needed: `walk()` classifies paths, it does not
    match terms, so the plants are plain text and the assertion is about
    membership in what the gate would go on to scan.

WHY IT SHELLS OUT AND IS EXEMPTED, NOT MARKED SLOW
    `walk()` itself calls `git ls-files`; that is the mechanism under test and
    cannot be stubbed without testing something else. The repository is built
    once per module (two git calls) and walked twice (one call each); the
    no-git case makes no call. Measured total is in `_SHELLOUT_EXEMPT`. Marking
    this `slow` would move a gate-scope property off the per-stage gate, and a
    scope regression is precisely what that gate should catch first.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from client_gate import walk  # noqa: E402
from src.git_identity import git_env  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=git_env())


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("gatescope") / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (root / "ignored").mkdir()
    (root / "ignored" / "plant.txt").write_text("cannot be committed\n", encoding="utf-8")
    (root / "loose").mkdir()
    (root / "loose" / "plant.txt").write_text("one git add from committed\n", encoding="utf-8")
    (root / "tracked.txt").write_text("committed\n", encoding="utf-8")
    _git(root, "add", ".gitignore", "tracked.txt")
    return root


def _scanned(root: Path) -> set[str]:
    text, binary = walk(root, exclude=set())
    return {p.relative_to(root).as_posix() for p in text + binary}


def test_ignored_path_is_not_scanned(repo):
    assert "ignored/plant.txt" not in _scanned(repo), (
        "a file under a .gitignore'd path was scanned. It can never be committed, and "
        "GATESCOPE-01 rules the gate protects what can be - this is the red that made "
        "the gate stop being read."
    )


def test_untracked_but_not_ignored_is_scanned(repo):
    seen = _scanned(repo)
    assert "loose/plant.txt" in seen, (
        "an untracked, NOT-ignored file was skipped. It is one `git add` from committed; "
        "respecting .gitignore must not become 'only scan what is already tracked'."
    )
    assert "tracked.txt" in seen


def test_only_the_repositorys_gitignore_decides(repo):
    """`.git/info/exclude` (and by the same mechanism the operator's global
    excludes file) must NOT narrow the gate. The first draft used
    `--exclude-standard`, which honours both, so the scope of a governance
    control differed silently from machine to machine (review W1). A file
    excluded only by `.git/info/exclude` is untracked-not-ignored as far as
    the repository is concerned, and is scanned.
    """
    (repo / "local_only").mkdir(exist_ok=True)
    (repo / "local_only" / "plant.txt").write_text("excluded only locally\n", encoding="utf-8")
    info = repo / ".git" / "info"
    info.mkdir(exist_ok=True)
    (info / "exclude").write_text("local_only/\n", encoding="utf-8")
    assert "local_only/plant.txt" in _scanned(repo), (
        "a file excluded only by .git/info/exclude was skipped. That file is not ignored "
        "by the repository; the gate's scope must be readable from the tree, not from "
        "one machine's local configuration."
    )


def test_tree_without_git_is_walked_in_full(tmp_path):
    root = tmp_path / "copy"
    (root / "ignored").mkdir(parents=True)
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (root / "ignored" / "plant.txt").write_text("no repository here\n", encoding="utf-8")
    assert "ignored/plant.txt" in _scanned(root), (
        "with no .git at the root there is nothing to respect; the full walk is the mode the "
        "RS-A cut used on a copied tree before `git init`, and it must survive."
    )
