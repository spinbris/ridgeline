"""GOLDEN01 - golden-number regression harness core.

Project-agnostic self-verification loop for the generalised ``qra_core`` engine.
Committed reference ("golden") headline numbers that every change is tested
against, so a moved P50/P80/P90/mean is caught automatically. A moved headline
number is a bug unless it is an approved (blessed) methodology change.

Design (per the GOLDEN01 build brief + PM rulings 24/07/2026):

- **Project-agnostic.** No ``if project == "<a project>"`` anywhere. Projects are
  rows in ``projects.toml``; confidentiality is a per-project DATA attribute.
- **Two tiers, chosen by the registry, not by code.** ``confidential = false``
  routes goldens to the committed ``manifests/<project>/`` tier; ``true`` routes
  them to the gitignored ``local/<project>/`` tier. Only the manifest location
  and the breadth of input hashing differ, both read from the registry.
- **Registry-dispatched adapter.** ``run(project, seed, n_iter)`` dispatches to
  a small set of engine entry points keyed by the row's ``adapter``. The seed is
  injected explicitly per call (never relying on a module ``SEED`` global).

This module is the shared core imported by both ``tests/golden/test_golden.py``
(the pytest suite) and ``scripts/bless_goldens.py`` (the blessing script).

Nothing here writes manifests or runs ``--approve``; blessing lives in the
script and is Director-gated.
"""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

# tests/golden/golden_harness.py -> parents[2] = repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from src.git_identity import git_env  # noqa: E402
from src.git_identity import input_digest as _input_digest  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Env var that arms the confidential (local) tier. Set on the data machine(s)
#: via the shell profile. When set, the confidential tier MUST run and a
#: missing/moved manifest or input is a FAILURE, not a skip. Unset (fresh clone
#: / CI), the confidential tier skips cleanly.
ENV_GUARD = "QRA_GOLDEN_LOCAL"

#: Project-selection env the engine bindings resolve against. The adapters set
#: and restore this per run (mirroring the capture scripts), so a golden run
#: cannot leak a binding selection across the suite.
ENV_PROJECT = "QRA_PROJECT"

#: Default iteration count for a golden run. Determinism holds at any n with a
#: seeded RNG, so 10k proves value-neutrality exactly as 100k does but fast.
GOLDEN_N_ITER = 10_000

#: Headline statistics that make up a golden. Exact-equality asserted on x86-64; another
#: architecture gets one part in a billion (tests/arch_guard.same_value, XPLATTOL-01).
HEADLINE_KEYS = ("p50", "p80", "p90", "mean")

_GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
_REGISTRY_PATH = _GOLDEN_DIR / "projects.toml"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectRow:
    """One project registry row. Paths + flags only - NO headline numbers."""

    project: str
    adapter: str
    confidential: bool
    seed: int
    scenarios: tuple[str, ...]
    inputs: tuple[str, ...]  # repo-relative, forward-slash, hashed & asserted


def load_registry(path: Path | None = None) -> dict[str, ProjectRow]:
    """Parse ``projects.toml`` into ``{project_id: ProjectRow}``."""
    path = path or _REGISTRY_PATH
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    projects = raw.get("projects", {})
    rows: dict[str, ProjectRow] = {}
    for pid, cfg in projects.items():
        rows[pid] = ProjectRow(
            project=pid,
            adapter=str(cfg["adapter"]),
            confidential=bool(cfg["confidential"]),
            seed=int(cfg["seed"]),
            scenarios=tuple(str(s) for s in cfg["scenarios"]),
            inputs=tuple(str(p) for p in cfg["inputs"]),
        )
    return rows


def get_row(project: str) -> ProjectRow:
    rows = load_registry()
    if project not in rows:
        raise KeyError(
            f"project {project!r} not in registry {_REGISTRY_PATH.name} "
            f"(have: {sorted(rows)})"
        )
    return rows[project]


def iter_project_scenarios() -> list[tuple[str, str, bool]]:
    """Discovery: ``[(project, scenario, confidential), ...]`` over the registry."""
    out: list[tuple[str, str, bool]] = []
    for row in load_registry().values():
        for scenario in row.scenarios:
            out.append((row.project, scenario, row.confidential))
    return out


# ---------------------------------------------------------------------------
# Hashing / provenance / env
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    """Streamed hex SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def input_digest(path: Path) -> dict[str, str]:
    """Identify an input, recording HOW it was identified.

    The engine's implementation, not a copy: ``src.git_identity.input_digest`` (DIGESTFALLBACK-01).
    A second copy is how FLOW-01's clean git environment reached this harness and not the engine.
    Tracked inputs are a git blob OID; untracked or outside any repository, a byte hash; git not
    installed, a byte hash marked ``"git": "unavailable"``; any other git failure raises, so a
    golden never reports INPUT DIGEST METHOD CHANGED for what was really a git failure.
    """
    return _input_digest(path)


def resolve_input(relpath: str) -> Path:
    """Repo-relative (forward-slash) input path -> absolute Path."""
    return REPO_ROOT / relpath


def current_env() -> dict[str, str]:
    """Actual interpreter/numpy versions. Goldens are guaranteed only here."""
    return {"python": platform.python_version(), "numpy": np.__version__}


def engine_ref() -> str:
    """``git describe`` at bless time (best-effort; 'unknown' on git soft-fail)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "describe", "--tags", "--always", "--dirty"],
            capture_output=True, text=True, check=False, timeout=5, env=git_env(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"
    return (r.stdout.strip() or "unknown") if r.returncode == 0 else "unknown"


# ---------------------------------------------------------------------------
# Headline statistics + float (de)serialisation
# ---------------------------------------------------------------------------


def headline_stats(arr: np.ndarray) -> dict[str, float]:
    """P50/P80/P90/mean of the integrated headline array (exact, no rounding)."""
    p50, p80, p90 = (float(x) for x in np.percentile(arr, [50, 80, 90]))
    return {"p50": p50, "p80": p80, "p90": p90, "mean": float(arr.mean())}


def stats_to_hex(stats: dict[str, float]) -> dict[str, str]:
    """Store floats as ``float.hex()`` so equality is exact after parsing."""
    return {k: float(stats[k]).hex() for k in HEADLINE_KEYS}


def hex_to_float(s: str) -> float:
    return float.fromhex(s)


# ---------------------------------------------------------------------------
# Adapters - registry-dispatched engine entry points
# ---------------------------------------------------------------------------
#
# Each adapter returns the integrated headline as a 1-D numpy array (cost +
# dollarised schedule, per iteration). The seed is passed in explicitly; the
# adapter must NOT rely on a module SEED global. Adapters set and restore
# ENV_PROJECT so a run cannot leak a binding selection across the suite.


def _adapter_wind(seed: int, n_iter: int) -> np.ndarray:
    """Public showcase headline via ``run_wind_showcase.run_integrated``.

    Reuses the production showcase config verbatim. ``run_integrated`` reads the
    module ``N_ITER`` / ``SEED`` at call time, so we force both explicitly
    (seed injection per GOLDEN01 ruling 5) rather than relying on the defaults.
    """
    os.environ["WIND_ITERATIONS"] = str(n_iter)  # read at import by the module
    import scripts.run_wind_showcase as wind

    wind.N_ITER = n_iter
    wind.SEED = seed
    saved = os.environ.get(ENV_PROJECT)
    try:
        wind._activate_wind_binding()  # sets ENV_PROJECT=synthetic_wind
        integ = wind.run_integrated()
    finally:
        if saved is None:
            os.environ.pop(ENV_PROJECT, None)
        else:
            os.environ[ENV_PROJECT] = saved
    return np.asarray(integ["integrated"], dtype=float)


def _adapter_integrated(project: str, seed: int, n_iter: int) -> np.ndarray:
    """The project-parametrised headline: one adapter, any project.

    ROAD-01 §5.2, closing GOLDENADPT-01. Every other adapter here is a closure over ONE
    project - `_adapter_wind` imports a script that hardcodes its own register, xer, capex
    and day rate - so `adapter = "wind"` on a second project would have re-run the WIND
    fixture and returned wind's numbers under that project's name: a golden that passes
    while measuring the wrong project.

    This resolves inputs from the project's binding instead, which GENERIC-01 made possible.
    It reproduces the wind headline **bit-identically** (exact `float.hex()` on p50/p80/p90/
    mean), which is what makes it a generalisation rather than a second answer.
    """
    from scripts.run_project_showcase import run_integrated_for_project

    out = run_integrated_for_project(project, n_iter=n_iter, seed=seed)
    return np.asarray(out["integrated"], dtype=float)


#: Adapter key -> (project, seed, n_iter) -> headline array. `integrated` serves any project
#: with a binding; the two below predate it and are closures over a single project each.
ADAPTERS = {
    "integrated": _adapter_integrated,
    "wind": lambda _project, seed, n_iter: _adapter_wind(seed, n_iter),
}


def run(project: str, seed: int, n_iter: int) -> dict[str, float]:
    """Registry-dispatched runner: ``run(project, seed, n_iter) -> headline``."""
    row = get_row(project)
    if row.adapter not in ADAPTERS:
        raise KeyError(
            f"project {project!r} names adapter {row.adapter!r} with no "
            f"registered entry (have: {sorted(ADAPTERS)})"
        )
    arr = ADAPTERS[row.adapter](project, seed, n_iter)
    return headline_stats(arr)


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------


def manifest_path(row: ProjectRow, scenario: str) -> Path:
    """Committed ``manifests/`` tier for public; gitignored ``local/`` for
    confidential. The location is derived from the registry flag ONLY - never a
    named code branch."""
    tier = "local" if row.confidential else "manifests"
    return _GOLDEN_DIR / tier / row.project / f"{scenario}.json"


def manifest_path_for(project: str, scenario: str) -> Path:
    return manifest_path(get_row(project), scenario)


def input_hashes(row: ProjectRow) -> dict[str, dict[str, str]]:
    """Identity of every registry-listed input (register + companions).

    Keyed by repo-relative forward-slash path so the manifest is stable across
    machines. Every entry is compared by the test: a changed input (register,
    strawman, XER) is reported as provenance-only while every number is
    identical, and fails as INPUT CHANGED when one moved (PROCDIET-01 R7).

    PROVCRLF01: each value is a ``{method, value}`` record rather than a bare
    digest. Keying by path made the manifest stable across machines; recording
    the identity by git blob OID is what makes the VALUE stable across them.
    """
    return {rel: input_digest(resolve_input(rel)) for rel in row.inputs}


def build_manifest(
    row: ProjectRow,
    scenario: str,
    *,
    n_iter: int,
    reason: str,
    by: str,
    date: str,
    ref: str | None = None,
) -> dict:
    """Run the adapter and assemble a manifest. Floats stored as ``float.hex()``.

    ``date`` is passed in by the caller (the harness never reads the wall clock,
    so the bless script owns the timestamp).

    ``ref`` is passed in for the same reason and it is load-bearing. Read here, it
    is read once per manifest, *after* any earlier manifest in the same bless has
    been written - so with more than one project in the registry every project
    after the first is stamped ``-dirty`` by its own sibling, and the stamp points
    at a tree state that exists in no history. One ref taken before the first write
    describes the tree all of them were actually produced from. ``None`` reads it
    here, for callers blessing a single manifest."""
    stats = run(row.project, row.seed, n_iter)
    return {
        "project": row.project,
        "scenario": scenario,
        "adapter": row.adapter,
        "confidential": row.confidential,
        "seed": row.seed,
        "n_iterations": n_iter,
        "inputs_sha256": input_hashes(row),
        "engine_ref": ref if ref is not None else engine_ref(),
        "environment": current_env(),
        "headline": stats_to_hex(stats),
        "blessed": {"date": date, "by": by, "reason": reason},
    }


def load_manifest(path: Path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def headline_floats(manifest: dict) -> dict[str, float]:
    """Parse a manifest's hex headline back to exact floats."""
    return {k: hex_to_float(manifest["headline"][k]) for k in HEADLINE_KEYS}
