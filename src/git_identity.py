"""Git calls that find their repository from the path they ask about, and input identity.

DIGESTFALLBACK-01. Two defects, one module:

- **Environment.** A git call that inherits ``GIT_DIR`` (a git hook in a linked worktree
  exports it, with an absolute ``GIT_INDEX_FILE`` and no ``GIT_WORK_TREE``) answers about
  **another repository**: ``rev-parse HEAD`` returns that repository's SHA with rc 0.
  ``git_env()`` is the environment every repository git call in this tree runs in, and
  ``tests/test_git_identity.py`` reds on a call that does not use it.
- **Silent fallback.** A git call that failed was recorded exactly like an input git does not
  track: ``sha256_bytes``. ``input_digest`` now tells five outcomes apart (brief P1) and raises
  on the one that is neither an answer nor a missing git.

One implementation, imported by both the engine (``src/am/run_period.py``) and the golden
harness (``tests/golden/golden_harness.py``). Two copies is how the environment fix reached the
harness at FLOW-01 and not the engine.

Standard library only, so a stdlib-only script can import it after putting the repository root
on ``sys.path``.
"""
from __future__ import annotations

import functools
import hashlib
import logging
import os
import subprocess
from pathlib import Path

#: Seconds before a git call is abandoned. Local plumbing answers in well under a second;
#: this is a hang detector, and a hang raises (it is not an answer).
GIT_TIMEOUT_SECONDS = 30

# The variables git itself treats as repository-local. Asked of git at run time; this floor is
# the list git 2.45 prints, so a git that failed to answer still has them all cleared.
_GIT_LOCAL_ENV_FLOOR = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
    "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
)

# Discovery variables git does not list as local. Removed so git's upward walk for `.git` and
# the filesystem walk in `_dot_git_above` see the same thing.
_GIT_DISCOVERY_ENV = ("GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM")

#: The marker an input digest carries when git could not be launched (D-1 as amended).
GIT_UNAVAILABLE = "unavailable"


def _without(names) -> dict[str, str]:
    drop = frozenset(names)
    return {k: v for k, v in os.environ.items() if k not in drop}


def _floor_git_env() -> dict[str, str]:
    return _without((*_GIT_LOCAL_ENV_FLOOR, *_GIT_DISCOVERY_ENV))


@functools.lru_cache(maxsize=1)
def _git_local_env_vars() -> frozenset[str]:
    try:
        out = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True,
                             text=True, timeout=10, env=_floor_git_env()).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    return frozenset(out.split()) | frozenset(_GIT_LOCAL_ENV_FLOOR)


def git_env() -> dict[str, str]:
    """This process's environment without git's repository-local and discovery variables.

    Every git call in this tree that asks about a path or about this repository passes
    ``env=git_env()``, so git finds the repository by walking up from ``-C``/``cwd`` and never
    from whatever repository the caller happens to be operating on.
    """
    return _without(_git_local_env_vars() | frozenset(_GIT_DISCOVERY_ENV))


class GitIdentityError(RuntimeError):
    """Git is present but did not answer: never recorded as an untracked input."""


class GitUnavailableError(OSError):
    """Git could not be launched. Only this is recorded as "git unavailable"; an ``OSError``
    from anything else (reading the input, walking its folders) is not."""


def _dot_git_above(folder: Path) -> Path | None:
    """The first ``.git`` entry, directory or file, in ``folder`` or any folder above it.

    A linked worktree's ``.git`` is a file, so existence is the test, not ``is_dir``.
    """
    for d in (folder, *folder.parents):
        if (d / ".git").exists():
            return d / ".git"
    return None


def _run_git(args: list[str], path: Path) -> subprocess.CompletedProcess[bytes]:
    """Run one git call for ``path``. Failing to launch is ``GitUnavailableError``; a timeout
    is not an answer and raises ``GitIdentityError``."""
    try:
        return subprocess.run(args, capture_output=True, timeout=GIT_TIMEOUT_SECONDS,
                              env=git_env())
    except OSError as exc:
        raise GitUnavailableError(f"cannot launch {args[0]}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitIdentityError(
            f"{' '.join(args)} timed out after {exc.timeout}s identifying {path}"
        ) from exc


def _failed(r: subprocess.CompletedProcess[bytes], path: Path, why: str) -> GitIdentityError:
    stderr = r.stderr.decode("utf-8", errors="replace").strip()
    return GitIdentityError(
        f"{' '.join(r.args)} exited {r.returncode} identifying {path}: {why}."
        + (f" git said: {stderr}" if stderr else "")
    )


def git_blob_oid(path: Path) -> str | None:
    """The git blob OID of ``path``; None if git positively does not track it.

    Outcomes (DIGESTFALLBACK-01 brief P1):

    - ``ls-files --error-unmatch`` rc 0: tracked, the OID is returned.
    - rc 1: not tracked, inside a repository. None.
    - rc 128 **and** no ``.git`` entry in the input's folder or any folder above: outside any
      repository. None.
    - Launching git fails: ``GitUnavailableError``, which ``input_digest`` records as the byte
      hash with the git-unavailable marker.
    - Anything else raises ``GitIdentityError`` naming the command, the exit code and the path:
      rc 128 with a ``.git`` above it, any other exit code, a timeout, an empty OID.

    **Why the two 128s can be told apart without reading stderr.** With the repository-local
    and discovery variables removed (``git_env``), git has one way left to find a repository:
    walk up from ``-C <folder>`` looking for ``.git``. The same walk on the filesystem predicts
    its answer. No ``.git`` above, and 128 is the truthful "not a repository". A ``.git`` above
    and still 128 means git failed for another reason: dubious ownership (``safe.directory``),
    a corrupt repository, or a variable that survived.

    Blind spots:

    - a ``.git`` that is not a repository (a stray empty folder, say) makes every input below
      it raise. That is loud, not silent.
    - a repository mounted across a filesystem boundary: git stops its walk at the boundary
      and the filesystem walk does not, so an input there raises. Also loud.

    PROVCRLF01. ``git hash-object`` applies the path's ``.gitattributes`` filters before
    computing the OID, so the result is line-ending-normalised and identical on every machine
    holding the same content. It is computed from the working copy rather than read from HEAD,
    so a genuine edit still moves the digest. The ``ls-files`` check is load-bearing:
    ``hash-object`` succeeds OUTSIDE a repository too, returning a raw-byte OID as
    machine-dependent as the digest it replaces.

    ``path`` is resolved before probing. ``-C`` changes git's working directory, so a RELATIVE
    pathspec would be re-interpreted against it, match nothing, and send a tracked input down
    the byte fallback (found by the Mac at G5).
    """
    path = path.resolve()
    parent = path.parent
    ls = _run_git(["git", "-C", str(parent), "ls-files", "--error-unmatch", "--", str(path)],
                  path)
    if ls.returncode == 1:
        return None
    if ls.returncode == 128:
        dot_git = _dot_git_above(parent)
        if dot_git is None:
            return None
        raise _failed(ls, path, f"git refused a repository that exists at {dot_git}")
    if ls.returncode != 0:
        raise _failed(ls, path, "not an answer ls-files gives")
    out = _run_git(["git", "-C", str(parent), "hash-object", "--", str(path)], path)
    if out.returncode != 0:
        raise _failed(out, path, "hash-object failed on a tracked input")
    oid = out.stdout.decode("ascii", errors="replace").strip()
    if not oid:
        raise _failed(out, path, "hash-object printed no OID")
    return oid


def sha256_file(path: Path) -> str:
    """Streamed hex SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def input_digest(path: Path) -> dict[str, str]:
    """Identify an input, recording HOW it was identified.

    Tracked inputs are identified by git blob OID, what git itself treats as the identity of
    the content. An untracked input, or one outside any repository (a client register may sit
    anywhere), falls back to byte-hashing. The method travels with the value, because a
    provenance field that silently switches method is the same defect one layer up.

    With git not installed the byte hash is recorded with ``"git": "unavailable"`` beside
    ``method`` and ``value``, so the entry says why it is not a blob OID (Director, D-1 as
    amended). ``method`` stays ``sha256_bytes`` because that is what was computed; a distinct
    method string would fail the dashboard's ``method`` enum. Any other git failure raises.
    """
    try:
        oid = git_blob_oid(path)
    except GitUnavailableError as exc:
        logging.getLogger(__name__).warning(
            "git unavailable (%s); %s identified by byte hash", exc, path)
        return {"method": "sha256_bytes", "value": sha256_file(path), "git": GIT_UNAVAILABLE}
    if oid is not None:
        return {"method": "git_blob_oid", "value": oid}
    return {"method": "sha256_bytes", "value": sha256_file(path)}
