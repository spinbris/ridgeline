"""PROVCRLF01 - the golden gate's input digests must be machine-independent.

The gate hashes every registry-listed input and asserts it against the
manifest. While that digest is a byte-hash of the WORKING COPY, it records how
git happened to materialise a text file on this machine, not what git stores:
the repo declares ``* text=auto eol=lf`` while a Windows checkout with
``core.autocrlf=true`` holds CRLF. Same commit, same blob, two digests - so the
gate is green on the XPS and red on any compliant checkout.

These tests assert the property the gate was always meant to have.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import tests.golden.golden_harness as gh
from src.git_identity import git_env

pytestmark = pytest.mark.unit

WIND_XER = "tests/fixtures/synthetic_wind/wind_schedule.xer"


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd or gh.REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=git_env(),
    ).stdout.strip()


def test_wind_xer_working_copy_really_does_disagree_with_the_index() -> None:
    """Guard the premise. If this repo ever stops reproducing the disagreement,
    the tests below would pass for the wrong reason."""
    eol = _git("ls-files", "--eol", WIND_XER)
    assert "attr/text=auto eol=lf" in eol, f"unexpected attributes: {eol}"


def test_input_digest_ignores_working_copy_line_endings(tmp_path: Path) -> None:
    """The defect, stated as an assertion, in a hermetic repo.

    Built with `* text=auto eol=lf` and core.autocrlf=true - the exact
    configuration that produces PROV-CRLF-01 - so the LF and CRLF working
    copies are the same input at the same commit and must digest identically.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "test@example.invalid", cwd=repo)
    _git("config", "user.name", "test", cwd=repo)
    _git("config", "core.autocrlf", "true", cwd=repo)
    (repo / ".gitattributes").write_bytes(b"* text=auto eol=lf\n")
    path = repo / "schedule.xer"
    path.write_bytes(b"a\tb\nc\td\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "input", cwd=repo)

    lf_digest = gh.input_digest(path)
    path.write_bytes(b"a\tb\r\nc\td\r\n")
    crlf_digest = gh.input_digest(path)

    assert crlf_digest == lf_digest, (
        "the golden gate's input digest depends on this machine's line endings"
    )
    assert lf_digest["method"] == "git_blob_oid"


def test_wind_xer_is_identified_by_its_stored_content_not_this_checkout() -> None:
    """The same property, asserted on the REAL gate input rather than a fixture.

    This tree holds the xer as CRLF (see the premise guard above) while git
    stores it as LF. If the digest equals the OID git records at HEAD, then the
    CRLF working copy made no difference to it - which is the whole claim.
    """
    path = gh.resolve_input(WIND_XER)
    stored_oid = _git("rev-parse", f"HEAD:{WIND_XER}")
    entry = gh.input_digest(path)
    assert entry == {"method": "git_blob_oid", "value": stored_oid}


def test_input_digest_records_its_method() -> None:
    entry = gh.input_digest(gh.resolve_input(WIND_XER))
    assert set(entry) == {"method", "value"}
    assert entry["method"] == "git_blob_oid"


def test_input_hashes_are_method_tagged_records() -> None:
    row = gh.get_row("wind_synth")
    hashes = gh.input_hashes(row)
    assert set(hashes) == set(row.inputs)
    for rel, entry in hashes.items():
        assert set(entry) == {"method", "value"}, f"{rel} is not a method/value record"
        assert entry["method"] in {"git_blob_oid", "sha256_bytes"}


def test_input_digest_of_a_tracked_file_given_as_a_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PROVCRLF01 G5 defect (Mac witness section 3), mc half of the same bug.

    ``_git_blob_oid`` ran git with ``-C <path.parent>`` while passing the full
    ``str(path)`` as the pathspec, so a relative path was re-resolved against
    the new working directory, matched nothing, and the tracked input silently
    took the byte-hash fallback. ``resolve_input`` happens to hand this harness
    absolute paths today, which is exactly why nothing here caught it - the
    existing tests checked the fallback's output shape, never its trigger.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "test@example.invalid", cwd=repo)
    _git("config", "user.name", "test", cwd=repo)
    (repo / ".gitattributes").write_bytes(b"* text=auto eol=lf\n")
    (repo / "fixtures").mkdir()
    path = repo / "fixtures" / "schedule.xer"
    path.write_bytes(b"a\tb\nc\td\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "input", cwd=repo)

    absolute = gh.input_digest(path)
    assert absolute["method"] == "git_blob_oid", "premise broken: the file is tracked"

    monkeypatch.chdir(repo)
    relative = gh.input_digest(Path("fixtures/schedule.xer"))

    assert relative["method"] == "git_blob_oid", (
        "a tracked input took the untracked fallback because it was passed as a "
        "relative path - the recorded method is false"
    )
    assert relative == absolute


def test_untracked_input_falls_back_to_byte_hashing(tmp_path: Path) -> None:
    """The fallback is not optional: an input can be untracked, or sit outside
    any repository entirely."""
    import hashlib

    path = tmp_path / "loose.xlsx"
    path.write_bytes(b"not-in-any-repo")
    entry = gh.input_digest(path)
    assert entry["method"] == "sha256_bytes"
    assert entry["value"] == hashlib.sha256(b"not-in-any-repo").hexdigest()


def test_input_digest_still_moves_on_a_genuine_content_change(tmp_path: Path) -> None:
    """Machine-independence must not be bought with a false negative: a digest
    that read the committed blob regardless of the working copy would pass the
    tests above while missing a real input change, and the gate would stop
    reporting INPUT CHANGED."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "test@example.invalid", cwd=repo)
    _git("config", "user.name", "test", cwd=repo)
    (repo / ".gitattributes").write_bytes(b"* text=auto eol=lf\n")
    path = repo / "schedule.xer"
    path.write_bytes(b"a\tb\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "input", cwd=repo)

    before = gh.input_digest(path)
    path.write_bytes(b"a\tb\nEXTRA\n")
    after = gh.input_digest(path)

    assert after["method"] == "git_blob_oid"
    assert after["value"] != before["value"], (
        "a real content change in the working copy went undetected"
    )


def _worktree_with_input(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A repository, a linked worktree of it, and a tracked input inside the worktree."""
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", "-b", "master", cwd=main)
    _git("config", "user.email", "test@example.invalid", cwd=main)
    _git("config", "user.name", "test", cwd=main)
    (main / ".gitattributes").write_bytes(b"* text=auto eol=lf\n")
    (main / "fixtures").mkdir()
    (main / "fixtures" / "schedule.xer").write_bytes(b"a\tb\nc\td\n")
    _git("add", "-A", cwd=main)
    _git("commit", "-q", "-m", "input", cwd=main)
    lane = tmp_path / "lane"
    _git("worktree", "add", "-q", "-b", "feature/LANE-01", str(lane), cwd=main)
    return main, lane, lane / "fixtures" / "schedule.xer"


def test_input_digest_holds_in_a_worktree_hook_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FLOW-01 Step 3 escalation, ruled (a) by the Director 24/09/2026.

    Inside a linked worktree git exports GIT_DIR (and an absolute GIT_INDEX_FILE) to its
    hooks, without GIT_WORK_TREE. The pre-commit golden gate inherits them, so the harness's
    `git -C <input folder> ls-files` took that folder for the work-tree root, matched nothing,
    and every tracked input fell back to `sha256_bytes`: both goldens red on untouched inputs,
    and no lane could commit. The environment below is the one captured from a real hook.
    """
    main, lane, path = _worktree_with_input(tmp_path)
    expected = gh.input_digest(path)
    assert expected["method"] == "git_blob_oid", "premise broken: the file is tracked"

    gitdir = main / ".git" / "worktrees" / "lane"
    monkeypatch.setenv("GIT_DIR", gitdir.as_posix())
    monkeypatch.setenv("GIT_INDEX_FILE", (gitdir / "index").as_posix())
    monkeypatch.chdir(lane)

    assert gh.input_digest(path) == expected


def test_the_harness_git_calls_carry_no_local_git_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every variable `git rev-parse --local-env-vars` names is cleared for the harness's own
    git calls - not only GIT_DIR (Director, 24/09/2026). Asserted on what is passed, so a
    variable that happens to be harmless in this test is still proven cleared."""
    local = _git("rev-parse", "--local-env-vars").split()
    assert "GIT_DIR" in local and "GIT_INDEX_FILE" in local, "premise: the list names them"
    _, _, path = _worktree_with_input(tmp_path)  # built before the environment is poisoned
    for name in local:
        monkeypatch.setenv(name, "poisoned")

    seen: list[dict | None] = []
    real_run = subprocess.run

    def spy(args, *a, **k):
        if args and args[0] == "git" and "--local-env-vars" not in args:
            seen.append(k.get("env"))
        return real_run(args, *a, **k)

    monkeypatch.setattr(gh.subprocess, "run", spy)
    gh.input_digest(path)
    gh.engine_ref()

    assert seen, "the spy saw no harness git call"
    for env in seen:
        assert env is not None, "a harness git call inherited the whole environment"
        leaked = sorted(set(local) & set(env))
        assert not leaked, f"local git variables reached a harness git call: {leaked}"
