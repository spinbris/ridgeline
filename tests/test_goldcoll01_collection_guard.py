"""GOLDCOLL-01 lock: collection must survive a clone with no confidential inputs.

GOLDCOLL-01 fixed a module-level ``glob.glob(...<register>...)[0]`` that raised
IndexError at import on any machine without the client register. A collection
error takes the whole pytest session down with it, including the PUBLIC golden
gate, which needs none of that data - and the pre-commit hook runs
``pytest -m golden``, so on a clean clone the hook could not pass at all.

Nothing locked that fix in. Reverting the line leaves the lane green on every
machine that holds the client register, which is every machine the lane is
normally run on. That is a check that cannot fail where it is run: the fix's
own failure mode is invisible to it. This is the guard for it (DAYRATE-01
AC-13).

The property, not the line: **with the confidential inputs absent, pytest
collection succeeds.** Any module-level statement in any test file that indexes,
opens or otherwise hard-depends on a confidential artefact breaks it, whether or
not it is the line GOLDCOLL-01 happened to fix.

Mechanism: mirror the repo's Python tree into a temp directory with hardlinks
(cheap - no file data is copied), deliberately omitting ``inputs/``,
``outputs/`` and ``docs/``, then run ``pytest --collect-only`` there in a
subprocess. Hardlinks rather than symlinks because test modules derive the repo
root via ``Path(__file__).resolve()``, which follows a symlink straight back to
the real tree and would find the very files this guard needs absent.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: Mirrored into the sandbox: every top-level directory that carries importable
#: code or configuration. Everything else - notably inputs/, outputs/ and docs/,
#: which between them hold the client register, the strawman and the P6 export -
#: is deliberately absent, which is the clean-clone shape.
#:
#: Omitting a legitimate directory here shows up as a false red (an
#: unimportable module), not a false green, so the failure mode of getting this
#: list wrong is the safe one.
_MIRRORED_DIRS = ("src", "tests", "scripts", "tools")

#: Root-level files pytest needs to behave the same way in the sandbox.
_ROOT_GLOBS = ("pytest.ini", "conftest.py", "pyproject.toml", "setup.cfg", "tox.ini")

_SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache", ".venv", ".git"}


def _link_or_copy(src: Path, dst: Path) -> None:
    """Hardlink ``src`` to ``dst``, falling back to a copy across volumes."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def _mirror_tree(sandbox: Path) -> int:
    """Populate ``sandbox`` with the repo's Python tree. Returns file count."""
    count = 0
    for rel in _MIRRORED_DIRS:
        source_root = REPO / rel
        if not source_root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(source_root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
            rel_dir = Path(dirpath).relative_to(REPO)
            (sandbox / rel_dir).mkdir(parents=True, exist_ok=True)
            for name in filenames:
                _link_or_copy(Path(dirpath) / name, sandbox / rel_dir / name)
                count += 1
    for name in _ROOT_GLOBS:
        src = REPO / name
        if src.is_file():
            _link_or_copy(src, sandbox / name)
            count += 1
    return count


@pytest.mark.slow  # TESTLANE-01 A sweep: shells out (see tests/conftest.py guard)
def test_collection_succeeds_with_confidential_inputs_absent(tmp_path):
    """The clean-clone property GOLDCOLL-01 restored, asserted where it is run.

    Left in the fast lane deliberately, despite forking a full collection: it
    costs ~12s, and a guard that only runs in the slow lane is one more check
    that is not there when it matters. Unlike a clean clone, this runs on
    machines that DO hold the client register - which is the whole point.
    """
    sandbox = tmp_path / "clean_clone"
    sandbox.mkdir()
    linked = _mirror_tree(sandbox)
    assert linked > 100, f"sandbox looks empty ({linked} files) - mirror failed"

    # The confidential artefacts must genuinely be absent, or this guard is
    # vacuous. Assert the absence rather than assuming the omission worked.
    for absent in ("inputs", "outputs", "docs"):
        assert not (sandbox / absent).exists(), (
            f"{absent}/ leaked into the sandbox - the guard would pass "
            "vacuously because the confidential inputs are still reachable"
        )

    env = dict(os.environ)
    # The confidential golden tier hard-fails on a missing input by design
    # (GOLDEN01 rule 5). Collection does not run tests, but leave nothing to
    # chance: this guard is about collection only.
    env.pop("QRA_GOLDEN_LOCAL", None)
    env["PYTHONPATH"] = str(sandbox)

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=str(sandbox), env=env, capture_output=True, text=True, timeout=900,
    )
    combined = proc.stdout + proc.stderr

    assert proc.returncode == 0, (
        "pytest collection FAILED with the confidential inputs absent. A "
        "module-level statement depends on an artefact that is not in a clean "
        "clone, so the whole session dies at collection - including the public "
        "golden gate the pre-commit hook runs.\n"
        f"return code: {proc.returncode}\n"
        f"{combined[-4000:]}"
    )
    # Belt-and-braces on top of the return code. Matched against pytest's own
    # banners rather than a bare "error" substring: hundreds of collected test
    # IDs legitimately contain the word (``test_register_duplicate_raises``,
    # ``_clear_keyerror``), and a substring check on those is a test that fails
    # for the wrong reason.
    banners = [
        line for line in combined.splitlines()
        if line.startswith("ERROR ") or "errors during collection" in line
    ]
    assert not banners, (
        "collection reported an error with confidential inputs absent:\n"
        + "\n".join(banners[:20])
    )
