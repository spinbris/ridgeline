"""Engine provenance for the period JSON: this repository's own HEAD.

RS-A2 P-3. The archived AM repository reached the engine through a bootstrap that located
a sibling checkout and pinned its SHA. In one repository there is no sibling and no pin: the
engine that produced a period result is the code at HEAD when it ran, and whether the tree
was clean. ``engine_sha_pinned`` and ``engine_sha_matches_pin`` are dropped from the contract
(Director, 03/09/2026).
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.git_identity import git_env

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str | None:
    try:
        # DIGESTFALLBACK-01: a GIT_DIR inherited from a hook would stamp another repository's SHA.
        r = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=30,
                           env=git_env())
    except (OSError, subprocess.SubprocessError) as exc:
        logging.getLogger(__name__).warning("engine provenance unavailable (%s): %s", args[0], exc)
        return None
    if r.returncode != 0:
        logging.getLogger(__name__).warning("engine provenance unavailable (git %s exited %d)", args[0], r.returncode)
        return None
    return r.stdout.strip()


def resolve_engine_sha() -> str | None:
    """Full SHA of this repository's HEAD, or None outside a repository."""
    return _git("rev-parse", "HEAD")


def resolve_tree_dirty() -> bool | None:
    """True if any tracked file is modified or any untracked-not-ignored file exists."""
    out = _git("status", "--porcelain", "--untracked-files=normal")
    return None if out is None else bool(out.strip())
