"""QRAXL-01.0 - capture the bit-identity baselines for the shared-QRA-core work.

Sub-stage QRAXL-01.0 (FLAG B of the QRAXL-01 brief): the named client headlines
that the later ``qra_core`` extraction must reproduce to the last digit are, today,
NOT machine-locked - the wind cost arm is not persisted at all, the wind joint total
lives only in an ``outputs/`` build artefact with no asserting test, and the RefProject
headline exists only as rendered text. This script captures each headline as an
asserted float (plus a raw cost-array fingerprint, the true bit-identity anchor) and
writes ``tests/fixtures/qraxl01_0_baseline.json``, mirroring the ``sr19_cost_baseline``
pattern. ``tests/test_qraxl01_0_bit_identity.py`` then re-runs each production path and
asserts exact ``==`` against this fixture.

Zero engine change: this only READS the current engine via each baseline's OWN
production path (wind -> ``run_wind_showcase.run_integrated``; RefProject ->
``load_integrated_config_stage3`` -> ``run_integrated_simulation_stage3``). Each path
must be pinned via its own wiring - the cost arrays produced by different call surfaces
are NOT guaranteed byte-identical to each other (see the brief's pre-paste note).

Usage
-----
    python scripts/qraxl01_0_capture_baseline.py --baseline wind
    python scripts/qraxl01_0_capture_baseline.py --baseline both

Both baselines are full 100k integrated + CPM-replay runs (multi-minute each).
The RefProject capture refuses to run if the RefProject register is open in Excel
(``~$`` lock file present) - openpyxl would read cached-formula ``None`` values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.git_identity import git_env  # noqa: E402

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "qraxl01_0_baseline.json"

# How many leading elements of the raw cost array to pin as the bit-identity
# fingerprint (sr19 uses 3; 5 is a touch more robust against a coincidental match).
FINGERPRINT_N = 5


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relpath(p: Path | str) -> str:
    """Record a provenance path repo-relative, in posix form (FIXPROV-01).

    An absolute path in a committed fixture resolves on exactly one machine and
    carries a username into version control; it also made the gates unrunnable
    off this box, which is the reason the Mac cross-check of the exact-equality
    pin had never once compared a number.

    An input outside ``REPO_ROOT`` raises rather than falling back to an absolute
    path (S-D review F-2). The fallback this replaces made P-D3's property
    conditional on every input happening to live inside the repo - true today for
    all five, with nothing to catch a register pointed elsewhere tomorrow, which
    would silently re-open FIXPROV-01 in the one artefact class it was raised
    about.
    """
    q = Path(p).resolve()
    try:
        return q.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError(
            "FIXPROV-01: refusing to record a provenance path outside the repo "
            "root, because a committed fixture must carry no absolute path and no "
            f"username.\n  input:     {q}\n  repo root: {REPO_ROOT}\n"
            "Move the input inside the repo, or extend the provenance format to "
            "record out-of-repo inputs deliberately - do not reinstate the "
            "absolute-path fallback."
        ) from exc


def _lock_path(xlsx: Path) -> Path:
    return xlsx.with_name("~$" + xlsx.name)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, env=git_env()
    ).stdout.strip()


def _provenance() -> dict:
    return {
        "engine_sha": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        # tracked-only: untracked additions (tools/, briefs) don't change engine numbers
        "tree_dirty_tracked": bool(
            _git("status", "--porcelain", "--untracked-files=no")
        ),
    }


def capture_wind(n_iter: int = 100_000) -> dict:
    """Capture the wind showcase baselines via run_wind_showcase's own config.

    Reuses ``run_integrated()`` verbatim so the config that produced the
    documented joint total is reproduced exactly. WINDINJ-01 Stage B
    (09/09/2026) moved that total from ``6839231.415137331`` to
    ``7027979.376010474``; the value of record is the one carried by
    ``tests/fixtures/qraxl01_0_baseline.json``, which this script writes and
    ``tests/test_qraxl01_0_bit_identity.py`` asserts. The 50k default
    (``WIND_ITERATIONS``) is NOT the baseline - it must be 100000.
    """
    os.environ["WIND_ITERATIONS"] = str(n_iter)  # read at module import, line 49
    import scripts.run_wind_showcase as wind

    # Force the module global too: if run_wind_showcase was already imported this
    # session (another test), N_ITER is frozen at import and the env var alone
    # would not take. run_integrated reads N_ITER at call time, so this wins.
    wind.N_ITER = n_iter
    # _activate_wind_binding() sets QRA_PROJECT=synthetic_wind globally,
    # which selects the active binding. Restore it afterwards so a same-process
    # RefProject capture (a `--baseline both` run, or the suite's RefProject gate
    # after this wind gate) is not polluted by the wind binding's chain IDs /
    # drivers. Without this the second capture reads the wrong active binding.
    _saved_project = os.environ.get("QRA_PROJECT")
    try:
        wind._activate_wind_binding()  # main() does this before run_integrated (line 786)
        integ = wind.run_integrated()
    finally:
        if _saved_project is None:
            os.environ.pop("QRA_PROJECT", None)
        else:
            os.environ["QRA_PROJECT"] = _saved_project

    cost = np.asarray(integ["cost"], dtype=float)
    ig = np.asarray(integ["integrated"], dtype=float)
    return {
        "entry": "scripts.run_wind_showcase.run_integrated (WIND_ITERATIONS=100000)",
        "seed": int(wind.SEED),
        "iterations": int(wind.N_ITER),
        "day_rate": float(wind.DAY_RATE),
        "n_dual_coded": int(integ["n_dual"]),
        "inputs": {
            "register": {
                "path": _relpath(wind.WIND_REGISTER),
                "sha256": _sha256(Path(wind.WIND_REGISTER)),
            },
            "xer": {
                "path": _relpath(wind.WIND_XER),
                "sha256": _sha256(Path(wind.WIND_XER)),
            },
        },
        "cost_dollars_array_first_n": [float(x) for x in cost[:FINGERPRINT_N]],
        "cost_arm_p80": float(np.percentile(cost, 80)),
        "integrated_total_p80": float(np.percentile(ig, 80)),
        "integrated_total_mean": float(np.mean(ig)),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Capture QRAXL-01.0 bit-identity baselines")
    ap.add_argument("--baseline", choices=["wind"], default="wind")
    ap.add_argument("--iterations", type=int, default=100_000)
    args = ap.parse_args(argv)

    # Merge into any existing fixture so a single-baseline capture does not
    # clobber the other baseline already recorded.
    fixture: dict = {}
    if FIXTURE_PATH.exists():
        fixture = json.loads(FIXTURE_PATH.read_text())

    fixture["purpose"] = (
        "QRAXL-01.0 bit-identity baselines. The later qra_core extraction must "
        "reproduce every value here to the last digit with Layer 1 OFF. Asserted "
        "by tests/test_qraxl01_0_bit_identity.py (exact ==, sr19 Gate C pattern)."
    )
    fixture["captured_on"] = _provenance()
    fixture["fingerprint_n"] = FINGERPRINT_N

    if args.baseline == "wind":
        print(f"[wind] capturing at {args.iterations} iters (this takes minutes)...")
        fixture["wind_showcase"] = capture_wind(args.iterations)
        w = fixture["wind_showcase"]
        print(f"[wind] cost P80 = {w['cost_arm_p80']!r}  "
              f"(${w['cost_arm_p80']/1e6:.2f}M)")
        print(f"[wind] joint P80 = {w['integrated_total_p80']!r}  "
              f"(${w['integrated_total_p80']/1e6:.2f}M)")

    # newline="\n" explicitly. The default translates to CRLF on Windows, which
    # trips the line-ending check: git ls-files --eol must report no w/crlf. The S-C
    # schedule capture already did this; these two older scripts never did, so
    # every capture left the working copy diverged from the LF blob git stores.
    FIXTURE_PATH.write_text(
        json.dumps(fixture, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"\nWrote {FIXTURE_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
