"""SR9-v3.4: convert tests/fixtures/sr9_state_cache_v31_baseline.pkl into
the new parquet+JSON layout under tests/fixtures/runs/v31_baseline/.

Behaviour-preserving: the new directory contains the same numpy arrays
and DataFrames as the legacy pickle. Round-trip parity is asserted before
the new layout is written.

This script is idempotent: re-running overwrites the output directory.

Usage:
    python scripts/sr9_v34_migrate_fixture.py
"""

from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.final.state_cache import read_state_cache, write_state_cache  # noqa: E402

LEGACY_PICKLE = REPO_ROOT / "tests" / "fixtures" / "sr9_state_cache_v31_baseline.pkl"
NEW_DIR = REPO_ROOT / "tests" / "fixtures" / "runs" / "v31_baseline"


def _equal(a, b) -> bool:
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        a = np.asarray(a)
        b = np.asarray(b)
        if a.shape != b.shape:
            return False
        return np.array_equal(a, b)
    if isinstance(a, pd.DataFrame) or isinstance(b, pd.DataFrame):
        return a.equals(b)
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_equal(x, y) for x, y in zip(a, b))
    return a == b


def main() -> int:
    if not LEGACY_PICKLE.exists():
        print(f"ERROR: legacy pickle not found at {LEGACY_PICKLE}", file=sys.stderr)
        return 1

    print(f"Reading legacy pickle: {LEGACY_PICKLE}")
    with LEGACY_PICKLE.open("rb") as f:
        legacy_payload = pickle.load(f)

    print(f"Writing parquet+JSON layout to: {NEW_DIR}")
    write_state_cache(legacy_payload, NEW_DIR)

    print("Round-trip parity check...")
    reloaded = read_state_cache(NEW_DIR)
    assert _equal(legacy_payload, reloaded), (
        "Round-trip mismatch: legacy pickle and parquet+JSON load to different "
        "payloads. Investigate before retiring the pickle."
    )

    legacy_size = LEGACY_PICKLE.stat().st_size
    new_size = sum(p.stat().st_size for p in NEW_DIR.iterdir() if p.is_file())
    print(
        f"Sizes: legacy pickle = {legacy_size/1e6:.1f} MB; "
        f"new layout = {new_size/1e6:.1f} MB "
        f"(ratio: {new_size/legacy_size:.2f}x)"
    )
    print("Files in new layout:")
    for p in sorted(NEW_DIR.iterdir()):
        print(f"  {p.name:60s} {p.stat().st_size/1024:>10.1f} KB")
    print("Migration successful. Legacy pickle retained at the original path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
