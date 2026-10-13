"""AM09 - engine provenance stamp: builder + dirty-tree guard.

Covers the run_period-layer pieces of AM09 (the writer-layer meta shape lives
in test_json_writer.py):
  - _build_engine_provenance: engine_sha vs pin (True / False / None soft-fail)
    and per-file input digests;
  - _sha256_file: stable for identical bytes, flips on a one-byte change;
  - the dirty-tree guard: REFUSES a dirty the engine tree unless --allow-dirty,
    both branches demonstrated (brief section 4, non-negotiable Director cond.).

Marked unit; the guard tests short-circuit before any engine work via mocks, so
no MC run happens.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

import src.am.run_period as rp
from src.am.run_period import _build_engine_provenance, _sha256_file
from src.git_identity import git_env

# A SHA-shaped value for tests that need *an* engine SHA; nothing pins to it (RS-A2 P-3).
ENGINE_SHA_AT_HEAD = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"

pytestmark = pytest.mark.unit


def _touch(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def _git(cwd: Path, *args: str) -> str:
    """Run git in ``cwd`` with identity/config forced, so the test is hermetic."""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
        env=git_env(),
    ).stdout.strip()


def _git_repo(tmp_path: Path) -> Path:
    """A repo declaring ``eol=lf`` with ``core.autocrlf=true`` - i.e. the exact
    configuration that produces the PROV-CRLF-01 disagreement on Windows."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "core.autocrlf", "true")
    (repo / ".gitattributes").write_bytes(b"* text=auto eol=lf\n")
    return repo


# ---------------------------------------------------------------------------
# _build_engine_provenance: SHA vs pin
# ---------------------------------------------------------------------------

def _provenance(tmp_path: Path, engine_sha, engine_tree_dirty=False):
    reg = _touch(tmp_path / "reg.xlsx", b"register-bytes")
    xer = _touch(tmp_path / "p.xer", b"xer-bytes")
    wb = _touch(tmp_path / "wb.xlsx", b"workbook-bytes")
    return _build_engine_provenance(
        engine_sha=engine_sha,
        engine_tree_dirty=engine_tree_dirty,
        register_path=reg,
        xer_path=xer,
        workbook_path=wb,
    )


# test_matches_pin_true_when_sha_equals_pin, test_matches_pin_false_when_sha_differs and
# test_matches_pin_none_when_sha_unresolved were RETIRED at RS-A2: the pin fields they
# asserted were dropped from the contract (P-3, Director 03/09/2026). The property that
# survives - engine_sha is this repository's HEAD and engine_tree_dirty is measured - is
# asserted below and by test_am_run_period_e2e.


@pytest.mark.slow  # git plumbing per input; measured 806 ms for 8 digests - over the exemption line (Director 25/08), so slow, per test not per module
def test_dirty_flag_passed_through(tmp_path: Path) -> None:
    assert _provenance(tmp_path, ENGINE_SHA_AT_HEAD, engine_tree_dirty=True)[
        "engine_tree_dirty"
    ] is True


# ---------------------------------------------------------------------------
# input_sha256: per-file, stable, one-byte-sensitive
# ---------------------------------------------------------------------------

@pytest.mark.slow  # git plumbing per input; measured 806 ms for 8 digests - over the exemption line (Director 25/08), so slow, per test not per module
def test_input_sha256_records_method_per_input(tmp_path: Path) -> None:
    """PROVCRLF01: every digest carries the method that produced it.

    A provenance field that silently switches method is the same defect one
    layer up, so the method is recorded per input, never inferred from context.
    """
    prov = _provenance(tmp_path, ENGINE_SHA_AT_HEAD)
    digests = prov["input_sha256"]
    assert set(digests) == {"register", "xer", "workbook"}
    for key, entry in digests.items():
        assert set(entry) == {"method", "value"}, f"{key} is not a method/value record"
        assert entry["method"] in {"git_blob_oid", "sha256_bytes"}
    # tmp_path is not a repository, so these fall back to byte-hashing - and the
    # record must SAY so rather than leaving the method to be guessed.
    assert digests["register"]["method"] == "sha256_bytes"
    assert digests["register"]["value"] == hashlib.sha256(b"register-bytes").hexdigest()
    # per-file, not concatenated: the three differ
    assert len({e["value"] for e in digests.values()}) == 3


@pytest.mark.slow  # git plumbing per input; measured 806 ms for 8 digests - over the exemption line (Director 25/08), so slow, per test not per module
def test_input_digest_is_machine_independent_for_a_tracked_text_input(
    tmp_path: Path,
) -> None:
    """PROVCRLF01 - the assertion the old byte-equality test should always have made.

    A text input tracked in a repo that declares ``eol=lf`` must digest
    identically whether this machine materialised it LF or CRLF. Byte-hashing
    the working copy fails this: that IS the defect. Hashing the git blob OID
    passes it, because git normalises line endings before computing identity.
    """
    repo = _git_repo(tmp_path)
    path = repo / "schedule.xer"
    path.write_bytes(b"a\tb\nc\td\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "input")

    lf_digest = rp._input_digest(path)
    assert lf_digest["method"] == "git_blob_oid"

    # Simulate what core.autocrlf=true does to this file on a Windows checkout.
    path.write_bytes(b"a\tb\r\nc\td\r\n")
    crlf_digest = rp._input_digest(path)

    assert crlf_digest == lf_digest, (
        "input digest moved when only the line endings of the working copy "
        "changed - the field is an environment fingerprint, not an input lock"
    )


@pytest.mark.slow  # git plumbing per input; measured 806 ms for 8 digests - over the exemption line (Director 25/08), so slow, per test not per module
def test_input_digest_still_moves_on_a_genuine_content_change(tmp_path: Path) -> None:
    """Machine-independence must not be bought with a false negative.

    ``git rev-parse HEAD:<path>`` would satisfy the test above while ignoring a
    real edit in the working copy. That failure mode is the one PROV-01 rejects
    outright, so it is asserted against here.
    """
    repo = _git_repo(tmp_path)
    path = repo / "schedule.xer"
    path.write_bytes(b"a\tb\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "input")

    before = rp._input_digest(path)
    path.write_bytes(b"a\tb\nEXTRA\n")
    after = rp._input_digest(path)

    assert after["method"] == "git_blob_oid"
    assert after["value"] != before["value"], (
        "a real content change in the working copy went undetected"
    )


@pytest.mark.slow  # git plumbing per input; measured 806 ms for 8 digests - over the exemption line (Director 25/08), so slow, per test not per module
def test_input_digest_of_a_tracked_file_given_as_a_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PROVCRLF01 G5 defect (Mac witness section 3): the method must not depend
    on how the path was typed.

    Every other test here hands ``_input_digest`` an absolute path, which is why
    this got through: they exercised the fallback's OUTPUT SHAPE and never its
    TRIGGER CONDITION. ``RUN_PERIOD.bat`` passes ``%~1`` straight through, so a
    relative ``--workbook`` is the normal invocation, not an edge case - and a
    tracked input arriving that way was silently recorded ``sha256_bytes``.

    The two invocations below are the same file at the same commit on the same
    machine, so they must produce the same record.
    """
    repo = _git_repo(tmp_path)
    (repo / "status_periods").mkdir()
    path = repo / "status_periods" / "period.xer"
    path.write_bytes(b"a\tb\nc\td\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "input")

    absolute = rp._input_digest(path)
    assert absolute["method"] == "git_blob_oid", "premise broken: the file is tracked"

    monkeypatch.chdir(repo)
    relative = rp._input_digest(Path("status_periods/period.xer"))

    assert relative["method"] == "git_blob_oid", (
        "a tracked input took the untracked fallback because it was passed as a "
        "relative path - the recorded method is false"
    )
    assert relative == absolute


@pytest.mark.slow  # git plumbing per input; measured 806 ms for 8 digests - over the exemption line (Director 25/08), so slow, per test not per module
def test_input_digest_falls_back_to_byte_hashing_outside_a_repo(tmp_path: Path) -> None:
    """The fallback is not optional: the workbook may be untracked and a client
    register may sit outside any repo entirely."""
    path = _touch(tmp_path / "loose.xlsx", b"not-in-any-repo")
    entry = rp._input_digest(path)
    assert entry["method"] == "sha256_bytes"
    assert entry["value"] == hashlib.sha256(b"not-in-any-repo").hexdigest()


def test_sha256_stable_for_identical_bytes(tmp_path: Path) -> None:
    a = _touch(tmp_path / "a.bin", b"identical payload")
    b = _touch(tmp_path / "b.bin", b"identical payload")
    assert _sha256_file(a) == _sha256_file(b)


def test_sha256_flips_on_one_byte_change(tmp_path: Path) -> None:
    a = _touch(tmp_path / "a.bin", b"payload-vX")
    before = _sha256_file(a)
    _touch(tmp_path / "a.bin", b"payload-vY")  # one byte differs
    assert _sha256_file(a) != before


# ---------------------------------------------------------------------------
# Dirty-tree guard: both branches (brief section 4)
# ---------------------------------------------------------------------------

def _mock_engine_state(monkeypatch, *, dirty: bool, sha: str | None = "abc123") -> None:
    monkeypatch.setattr(rp, "_resolve_tree_dirty", lambda: dirty)
    monkeypatch.setattr(rp, "_resolve_active_sha", lambda: sha)


class _PastGuard(RuntimeError):
    """Sentinel: raised from a patched resolve_project_inputs to prove the run
    got PAST the dirty-tree guard without doing any engine work."""


def test_guard_refuses_dirty_tree(monkeypatch) -> None:
    _mock_engine_state(monkeypatch, dirty=True)
    # If the guard fails to fire, this makes the test fail loudly rather than
    # silently proceeding into (mocked) input resolution.
    monkeypatch.setattr(
        rp, "resolve_project_inputs",
        lambda *a, **k: pytest.fail("guard did not fire on a dirty tree"),
    )
    with pytest.raises(RuntimeError, match="dirty-tree guard"):
        rp.run_period(workbook_path=Path("nope.xlsx"), allow_dirty=False)


def test_guard_lets_dirty_tree_through_with_allow_dirty(monkeypatch) -> None:
    _mock_engine_state(monkeypatch, dirty=True)
    monkeypatch.setattr(
        rp, "resolve_project_inputs",
        lambda *a, **k: (_ for _ in ()).throw(_PastGuard()),
    )
    with pytest.raises(_PastGuard):
        rp.run_period(workbook_path=Path("nope.xlsx"), allow_dirty=True)


def test_guard_passes_clean_tree(monkeypatch) -> None:
    _mock_engine_state(monkeypatch, dirty=False)
    monkeypatch.setattr(
        rp, "resolve_project_inputs",
        lambda *a, **k: (_ for _ in ()).throw(_PastGuard()),
    )
    with pytest.raises(_PastGuard):
        rp.run_period(workbook_path=Path("nope.xlsx"), allow_dirty=False)
