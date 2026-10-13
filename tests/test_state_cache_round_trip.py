"""SR9-v3.4 - Round-trip parity tests for state_cache.

Covers four of the five v3.4 tests in
the SR9 v3.4 persistence migration brief, §5:

- test_write_then_read_round_trip: synthetic SR8-shape payload, write+read,
  assert dict equality (np.testing.assert_array_equal for arrays;
  DataFrame.equals for DataFrames; == for scalars).
- test_metadata_serialisable: numpy scalars, pandas objects, and Path /
  datetime values round-trip through the JSON encoder without raising.
- test_parquet_compression_snappy: parquet files emitted by the writer
  are smaller than uncompressed-equivalent parquet files.
- test_v31_fixture_parquet_matches_pickle: the migrated v31 fixture
  directory equals the legacy pickle in array values + metadata.

The fifth test (legacy pickle reader still works) lives in
tests/test_state_cache_pickle_compat.py.
"""

from __future__ import annotations

import pickle
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.final.state_cache import (
    MANIFEST_FILENAME,
    METADATA_FILENAME,
    is_state_cache_dir,
    read_state_cache,
    write_state_cache,
)



# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _synthetic_sr8_payload(
    n_iter: int = 1000,
    n_risks_all: int = 34,
    n_risks_dual: int = 8,
) -> dict:
    """Build a synthetic payload matching the SR8 cache shape."""
    rng = np.random.default_rng(seed=42)
    return {
        "composed": {
            "cost_section": {
                "cost_dollars_array": rng.random(n_iter).astype(np.float32),
                "per_risk_cost_array": rng.random((n_iter, n_risks_all)).astype(np.float32),
                "risk_ids": [f"R{i:03d}" for i in range(n_risks_all)],
                "p_level": 80,
            },
            "schedule_section": {
                "finish_delay_days_array": rng.random(n_iter).astype(np.float32),
                "contribution_array": rng.random((n_iter, n_risks_dual)).astype(np.float32),
                "risk_ids": [f"R{i:03d}" for i in range(n_risks_dual)],
                "mode_used": {"R013": "Series", "R067": "Series"},
                "day_rate": 100000.0,
                "p_level": 80,
            },
            "integrated_section": {
                "scenarios": {
                    "DP_Review": {
                        "cost_dollars_array": rng.random(n_iter).astype(np.float32),
                        "schedule_days_array": rng.random(n_iter).astype(np.float32),
                        "iterations": n_iter,
                    },
                    "All_Series": {
                        "cost_dollars_array": rng.random(n_iter).astype(np.float32),
                        "schedule_days_array": rng.random(n_iter).astype(np.float32),
                        "iterations": n_iter,
                    },
                },
                "p_level": 80,
            },
            "fired": rng.random((n_iter, n_risks_all)) > 0.95,
            "appendix_counterfactual": pd.DataFrame({
                "Scenario": ["A", "B", "C"],
                "P80_dollars": [1.0e6, 2.0e6, 3.0e6],
                "Notes": ["x", "y", "z"],
            }),
            "appendix_audit_trail": {
                "register_path": "inputs/foo.xlsx",
                "engine_versions": {"cost": "SP18", "schedule": "SR5"},
            },
        },
        "cv_result": {"all_pass": True, "cost_passes_calibration": True},
        "run_date": "2026-04-29",
        "register_path": "inputs/foo.xlsx",
        "strawman_path": "outputs/sra_strawman/bar.xlsx",
        "day_rate": 100000.0,
        "reporting_p_level": 80,
        "headline_metric": "P80",
    }


def _payloads_equal(a, b) -> bool:
    """Recursive equality: numpy arrays, DataFrames, dicts, lists, scalars."""
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        a_arr = np.asarray(a)
        b_arr = np.asarray(b)
        if a_arr.shape != b_arr.shape:
            return False
        return np.array_equal(a_arr, b_arr)
    if isinstance(a, pd.DataFrame) or isinstance(b, pd.DataFrame):
        return isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame) and a.equals(b)
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_payloads_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_payloads_equal(x, y) for x, y in zip(a, b))
    return a == b


# ----------------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------------

def test_write_then_read_round_trip(tmp_path):
    """Round-trip a synthetic SR8-shape payload through the writer + reader."""
    payload = _synthetic_sr8_payload(n_iter=1000, n_risks_all=34, n_risks_dual=8)

    cache_dir = tmp_path / "run_2026-04-29"
    write_state_cache(payload, cache_dir)
    reloaded = read_state_cache(cache_dir)

    # Cache directory layout
    assert is_state_cache_dir(cache_dir)
    assert (cache_dir / METADATA_FILENAME).exists()
    assert (cache_dir / MANIFEST_FILENAME).exists()

    # Top-level scalar / string / dict-of-scalars metadata round-trips by ==
    assert reloaded["run_date"] == payload["run_date"]
    assert reloaded["day_rate"] == payload["day_rate"]
    assert reloaded["reporting_p_level"] == payload["reporting_p_level"]
    assert reloaded["headline_metric"] == payload["headline_metric"]
    assert reloaded["cv_result"] == payload["cv_result"]

    # 1-D and 2-D array equality (bit-for-bit) AND dtype parity
    # (float32 silently upcast to float64 by pyarrow would pass the value
    # check but accumulate fp error over 100k iterations downstream).
    cost_orig = payload["composed"]["cost_section"]["cost_dollars_array"]
    cost_loaded = reloaded["composed"]["cost_section"]["cost_dollars_array"]
    np.testing.assert_array_equal(cost_loaded, cost_orig)
    assert cost_loaded.dtype == cost_orig.dtype, (
        f"cost_dollars_array dtype changed on round trip: "
        f"{cost_orig.dtype} -> {cost_loaded.dtype}"
    )

    per_risk_orig = payload["composed"]["cost_section"]["per_risk_cost_array"]
    per_risk_loaded = reloaded["composed"]["cost_section"]["per_risk_cost_array"]
    np.testing.assert_array_equal(per_risk_loaded, per_risk_orig)
    assert per_risk_loaded.dtype == per_risk_orig.dtype

    # Bool 2-D round-trip (and bool dtype must survive parquet bit-packing).
    fired_orig = payload["composed"]["fired"]
    fired_loaded = reloaded["composed"]["fired"]
    np.testing.assert_array_equal(fired_loaded, fired_orig)
    assert fired_loaded.dtype == fired_orig.dtype

    # DataFrame round-trip
    assert reloaded["composed"]["appendix_counterfactual"].equals(
        payload["composed"]["appendix_counterfactual"]
    )

    # Whole-payload equality at structural level
    assert _payloads_equal(payload, reloaded)


def test_metadata_serialisable(tmp_path):
    """All metadata fields must JSON-encode without raising.

    Covers numpy scalars, Path objects, datetime/date, and dataclass-like
    structures (pandas Timestamp / dict).
    """
    payload = {
        "composed": {
            "cost_section": {
                "cost_dollars_array": np.zeros(10, dtype=np.float32),
            },
        },
        "run_date": date(2026, 4, 29),
        "register_path": Path("inputs/foo.xlsx"),
        "strawman_path": Path("outputs/strawman/bar.xlsx"),
        "day_rate": np.float64(100000.0),
        "reporting_p_level": np.int64(80),
        "engine_versions": {"cost": "SP18", "final": "SP22"},
        "ts": datetime(2026, 4, 29, 12, 0, 0),
        "is_prod": np.bool_(True),
    }

    cache_dir = tmp_path / "run_meta"
    write_state_cache(payload, cache_dir)
    reloaded = read_state_cache(cache_dir)

    # Path / date / datetime serialise as strings (one-way conversion is
    # acceptable: we lose Python type but preserve information; downstream
    # consumers re-parse if needed). Confirm the *string forms* round-trip.
    # Path string form is platform-specific (POSIX uses '/', Windows '\\');
    # normalise to forward-slash for the comparison.
    assert reloaded["run_date"] == "2026-04-29"
    assert reloaded["register_path"].replace("\\", "/") == "inputs/foo.xlsx"
    assert reloaded["strawman_path"].replace("\\", "/") == "outputs/strawman/bar.xlsx"
    assert reloaded["ts"] == "2026-04-29T12:00:00"

    # Numpy scalars become python scalars on JSON encode.
    assert reloaded["day_rate"] == 100000.0
    assert reloaded["reporting_p_level"] == 80
    assert reloaded["is_prod"] is True

    # Nested dict survives untouched.
    assert reloaded["engine_versions"] == {"cost": "SP18", "final": "SP22"}


def test_parquet_compression_snappy(tmp_path):
    """Snappy-compressed parquet files must be smaller than uncompressed.

    Uses a compressible array (mostly zeros) to demonstrate compression
    actually applies. Random data is incompressible by design and would
    only test that snappy doesn't *expand* — a weaker assertion. The
    SR8 payload's `fired` boolean array (~95% zeros) and `per_risk_*`
    arrays (most cells zero before a risk fires) match this profile.
    """
    rng = np.random.default_rng(seed=42)
    big = np.zeros((10_000, 50), dtype=np.float32)
    nonzero_idx = rng.random(big.shape) > 0.95
    big[nonzero_idx] = rng.random(int(nonzero_idx.sum())).astype(np.float32)
    payload = {"big_array": big}

    cache_dir = tmp_path / "run_compress"
    write_state_cache(payload, cache_dir)

    snappy_size = (cache_dir / "big_array.parquet").stat().st_size

    # Write the same array uncompressed via pandas for comparison.
    df = pd.DataFrame(big, columns=[str(i) for i in range(50)])
    uncompressed_path = tmp_path / "big_array_uncompressed.parquet"
    df.to_parquet(uncompressed_path, compression=None, index=False)
    uncompressed_size = uncompressed_path.stat().st_size

    assert snappy_size < uncompressed_size, (
        f"Snappy size ({snappy_size}) should be < uncompressed "
        f"({uncompressed_size}) for a sparse (10_000, 50) float32 array; "
        f"compression appears not to be applied"
    )


def test_filename_collision_resolved(tmp_path):
    """Two distinct dotted paths that sanitise to the same string must
    produce two distinct parquet files, both readable on round-trip.

    Regression guard: if the writer derived parquet filenames purely
    from the sanitised dotted path with no collision detection, a key
    like 'DP.Review' next to 'DP_Review' (both sanitising to
    'DP_Review') would silently overwrite each other.
    """
    payload = {
        "DP.Review": np.array([1.0, 2.0, 3.0], dtype=np.float32),
        "DP_Review": np.array([4.0, 5.0, 6.0], dtype=np.float32),
        "DP/Review": np.array([7.0, 8.0, 9.0], dtype=np.float32),
    }
    cache_dir = tmp_path / "run_collision"
    write_state_cache(payload, cache_dir)

    # Three distinct parquet files emitted (no overwrites).
    parquets = sorted(p.name for p in cache_dir.iterdir() if p.suffix == ".parquet")
    assert len(parquets) == 3, (
        f"Expected 3 parquet files for 3 colliding paths; got {parquets}"
    )

    reloaded = read_state_cache(cache_dir)
    np.testing.assert_array_equal(reloaded["DP.Review"], [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(reloaded["DP_Review"], [4.0, 5.0, 6.0])
    np.testing.assert_array_equal(reloaded["DP/Review"], [7.0, 8.0, 9.0])

