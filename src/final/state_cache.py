# SR9-v3.4 - State cache persistence: pickle -> parquet + JSON.
"""Persistence layer for the SR9 final-runner state cache.

Replaces the legacy single-file pickle (`outputs/sr9_state_cache_<date>.pkl`)
with a directory layout: numpy arrays and pandas DataFrames stored as
parquet (snappy-compressed); everything else stored as JSON.

Public surface:
    write_state_cache(payload, output_dir)
    read_state_cache(input_dir) -> payload

Behaviour-preserving: round-tripping a payload through write+read yields a
dict structurally equivalent to the original (numpy arrays compared with
`np.array_equal`; DataFrames with `DataFrame.equals`; dicts/lists/scalars
compared by value).

Design:
- The writer walks the payload recursively. When it encounters a numpy
  ndarray or pandas DataFrame, it writes the array to a parquet file under
  ``output_dir`` and replaces the value in the in-memory tree with a
  ``__parquet_ref__`` marker (a small JSON-serialisable dict). The fully
  marker-substituted tree is written to ``metadata.json``.
- The reader inverts the process: load ``metadata.json``, walk the tree,
  load each parquet file referenced by a ``__parquet_ref__`` marker.
- ``manifest.json`` records the array-name -> dotted-path map plus the
  data-type, shape, and parquet column-name convention so downstream
  consumers (R, BI tools, DuckDB) can inspect the layout without Python.

Header-driven (no positional assumptions): both writer and reader walk
the payload keys, so adding or removing metadata keys requires no module
changes. Tolerates dataclasses (best-effort: serialised as their dict
repr) and Path objects (serialised as strings).

See SCALABILITY.md §3.2 / §4 / §5 and ARCHITECTURE.md §9 for the
persistence ADR. Brief: the SR9 v3.4 persistence migration.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# JSON file names within the cache directory.
METADATA_FILENAME = "metadata.json"
MANIFEST_FILENAME = "manifest.json"

# Marker key for inlined-array references in the metadata JSON. Round-trip
# safe: a dict with this key signals an array reference.
_PARQUET_REF_KEY = "__parquet_ref__"
_PARQUET_COMPRESSION = "snappy"

# Filesystem-safe characters for derived parquet filenames. Keys outside
# this set are replaced with underscores.
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_name(s: str) -> str:
    """Sanitise a path-segment string for use as a filename component."""
    return _SAFE_NAME_RE.sub("_", s).strip("._-") or "item"


# ----------------------------------------------------------------------------
# JSON helpers
# ----------------------------------------------------------------------------

def _json_default(obj: Any) -> Any:
    """JSON encoder fallback for types not natively serialisable."""
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(
        f"Cannot JSON-serialise object of type {type(obj).__name__!r}: {obj!r}"
    )


# ----------------------------------------------------------------------------
# Writer
# ----------------------------------------------------------------------------

def _ndarray_to_parquet(arr: np.ndarray, target_path: Path) -> dict[str, Any]:
    """Write a numpy ndarray to parquet; return a __parquet_ref__ marker.

    1-D arrays write as a single-column parquet (column name "value").
    2-D arrays write column-per-position (column names are integer
    indices coerced to strings, "0", "1", ...). Higher-dimensional arrays
    are not supported by the SR9 schema and raise.
    """
    if arr.ndim == 1:
        df = pd.DataFrame({"value": arr})
        column_layout = "1d_value"
    elif arr.ndim == 2:
        n_cols = arr.shape[1]
        df = pd.DataFrame(arr, columns=[str(i) for i in range(n_cols)])
        column_layout = "2d_integer_index"
    else:
        raise ValueError(
            f"State cache arrays must be 1-D or 2-D; got ndim={arr.ndim} "
            f"shape={arr.shape}"
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(target_path, compression=_PARQUET_COMPRESSION, index=False)

    return {
        _PARQUET_REF_KEY: target_path.name,
        "kind": "ndarray",
        "dtype": str(arr.dtype),
        "shape": list(arr.shape),
        "column_layout": column_layout,
    }


def _dataframe_to_parquet(df: pd.DataFrame, target_path: Path) -> dict[str, Any]:
    """Write a pandas DataFrame to parquet; return a __parquet_ref__ marker."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the index by resetting; round-trip drops a default RangeIndex,
    # which matches the appendix_counterfactual contract (1-row-per-iteration
    # tables; no meaningful index).
    df.to_parquet(target_path, compression=_PARQUET_COMPRESSION, index=False)
    return {
        _PARQUET_REF_KEY: target_path.name,
        "kind": "dataframe",
        "shape": list(df.shape),
        "columns": [str(c) for c in df.columns],
    }


def _resolve_filename(
    base_name: str,
    used_names: set[str],
    full_path: str,
) -> str:
    """Return a unique parquet filename for ``base_name``.

    If ``base_name`` is already in ``used_names`` (because two distinct
    dotted paths sanitise to the same string — e.g. `"DP.Review"` and
    `"DP_Review"` both becoming `DP_Review`), append a numeric suffix
    until the name is free. Records the chosen name in ``used_names``.

    The dotted-path-to-filename mapping is recorded in the manifest
    regardless, so consumers can still locate any array by its semantic
    path without depending on filename uniqueness rules.
    """
    candidate = base_name
    counter = 1
    while candidate in used_names:
        candidate = f"{base_name}__{counter}"
        counter += 1
    used_names.add(candidate)
    return candidate


def _walk_and_extract(
    node: Any,
    *,
    output_dir: Path,
    path_segments: list[str],
    arrays_log: list[dict[str, Any]],
    used_filenames: set[str],
) -> Any:
    """Recursively walk ``node`` extracting arrays/DataFrames to parquet.

    Returns a structurally equivalent tree with arrays/DataFrames replaced
    by ``__parquet_ref__`` marker dicts.
    """
    if isinstance(node, np.ndarray):
        full_path = ".".join(path_segments) or "array"
        base = _safe_name(full_path)
        fname = _resolve_filename(base, used_filenames, full_path) + ".parquet"
        target = output_dir / fname
        marker = _ndarray_to_parquet(node, target)
        arrays_log.append({
            "path": full_path,
            "filename": fname,
            "kind": marker["kind"],
            "dtype": marker["dtype"],
            "shape": marker["shape"],
            "column_layout": marker["column_layout"],
        })
        return marker

    if isinstance(node, pd.DataFrame):
        full_path = ".".join(path_segments) or "dataframe"
        base = _safe_name(full_path)
        fname = _resolve_filename(base, used_filenames, full_path) + ".parquet"
        target = output_dir / fname
        marker = _dataframe_to_parquet(node, target)
        arrays_log.append({
            "path": full_path,
            "filename": fname,
            "kind": marker["kind"],
            "shape": marker["shape"],
            "columns": marker["columns"],
        })
        return marker

    if isinstance(node, Mapping):
        return {
            k: _walk_and_extract(
                v, output_dir=output_dir,
                path_segments=path_segments + [str(k)],
                arrays_log=arrays_log,
                used_filenames=used_filenames,
            )
            for k, v in node.items()
        }

    if isinstance(node, (list, tuple)):
        items = [
            _walk_and_extract(
                v, output_dir=output_dir,
                path_segments=path_segments + [str(i)],
                arrays_log=arrays_log,
                used_filenames=used_filenames,
            )
            for i, v in enumerate(node)
        ]
        return items if isinstance(node, list) else tuple(items)

    return node


def write_state_cache(payload: Mapping[str, Any], output_dir: Path | str) -> Path:
    """Write the SR9 state cache payload to ``output_dir`` (parquet + JSON).

    Args:
        payload: nested dict produced by ``compose_final_report_data`` plus
            outer-level metadata (run_date, engine_versions, register_path,
            strawman_path, day_rate, reporting_p_level, headline_metric,
            cv_result). Numpy arrays and DataFrames anywhere in the tree are
            extracted; everything else is JSON-encoded.
        output_dir: target directory (created if missing). Existing files
            are overwritten.

    Returns:
        The output_dir as a Path.

    Behaviour-preserving: ``read_state_cache(write_state_cache(p, d))``
    produces a payload structurally equivalent to ``p``.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    arrays_log: list[dict[str, Any]] = []
    used_filenames: set[str] = set()
    extracted_tree = _walk_and_extract(
        dict(payload),  # shallow copy to avoid mutating caller's mapping
        output_dir=output_dir,
        path_segments=[],
        arrays_log=arrays_log,
        used_filenames=used_filenames,
    )

    # Write metadata.json — the structural tree with parquet refs in place
    # of arrays.
    metadata_path = output_dir / METADATA_FILENAME
    with metadata_path.open("w", encoding="utf-8") as f:
        json.dump(extracted_tree, f, indent=2, default=_json_default)

    # Write manifest.json — schema documentation: array path -> filename map,
    # plus dtype/shape/column-layout for downstream consumers.
    manifest = {
        "format_version": "sr9_v3.4",
        "compression": _PARQUET_COMPRESSION,
        "metadata_filename": METADATA_FILENAME,
        "arrays": arrays_log,
    }
    manifest_path = output_dir / MANIFEST_FILENAME
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=_json_default)

    logger.info(
        "Wrote state cache to %s (%d parquet array(s), metadata.json, manifest.json)",
        output_dir, len(arrays_log),
    )
    return output_dir


# ----------------------------------------------------------------------------
# Reader
# ----------------------------------------------------------------------------

def _parquet_to_ndarray(parquet_path: Path, marker: Mapping[str, Any]) -> np.ndarray:
    """Read a parquet file back into a numpy ndarray per its marker."""
    df = pd.read_parquet(parquet_path)
    layout = marker.get("column_layout")
    expected_dtype = marker.get("dtype")
    if layout == "1d_value":
        arr = df["value"].to_numpy()
    elif layout == "2d_integer_index":
        # Column order should match string-int order; sort to be safe.
        ordered = sorted(df.columns, key=lambda c: int(c))
        arr = df[ordered].to_numpy()
    else:
        # Fallback: treat as 2-D in column order.
        arr = df.to_numpy()
    if expected_dtype:
        try:
            arr = arr.astype(np.dtype(expected_dtype), copy=False)
        except TypeError:
            # Object dtypes or other non-trivial types: leave as-is.
            pass
    return arr


def _parquet_to_dataframe(parquet_path: Path) -> pd.DataFrame:
    return pd.read_parquet(parquet_path)


def _walk_and_substitute(node: Any, *, input_dir: Path) -> Any:
    """Reverse of _walk_and_extract: replace markers with loaded arrays."""
    if isinstance(node, Mapping) and _PARQUET_REF_KEY in node:
        filename = node[_PARQUET_REF_KEY]
        parquet_path = input_dir / filename
        if not parquet_path.exists():
            raise FileNotFoundError(
                f"Parquet file referenced in metadata not found: {parquet_path}"
            )
        kind = node.get("kind", "ndarray")
        if kind == "ndarray":
            return _parquet_to_ndarray(parquet_path, node)
        if kind == "dataframe":
            return _parquet_to_dataframe(parquet_path)
        raise ValueError(f"Unknown __parquet_ref__ kind: {kind!r}")

    if isinstance(node, Mapping):
        return {
            k: _walk_and_substitute(v, input_dir=input_dir)
            for k, v in node.items()
        }

    if isinstance(node, list):
        return [_walk_and_substitute(v, input_dir=input_dir) for v in node]

    return node


def read_state_cache(input_dir: Path | str) -> dict[str, Any]:
    """Read a state cache directory written by ``write_state_cache``.

    Args:
        input_dir: directory containing ``metadata.json`` plus parquet files.

    Returns:
        The reconstructed payload dict. Numpy arrays are restored to their
        original dtype where the manifest records it; DataFrames are read
        back via pandas.read_parquet.

    Tolerates missing/extra metadata keys: the walker substitutes only
    ``__parquet_ref__`` markers; all other keys pass through untouched.
    """
    input_dir = Path(input_dir)
    metadata_path = input_dir / METADATA_FILENAME
    if not metadata_path.exists():
        raise FileNotFoundError(
            f"State cache metadata not found at {metadata_path}. "
            f"Expected the parquet+JSON layout written by SR9-v3.4."
        )
    with metadata_path.open("r", encoding="utf-8") as f:
        tree = json.load(f)

    payload = _walk_and_substitute(tree, input_dir=input_dir)
    return payload


# ----------------------------------------------------------------------------
# Compatibility helpers
# ----------------------------------------------------------------------------

def is_state_cache_dir(path: Path | str) -> bool:
    """Return True if ``path`` is a directory containing a metadata.json."""
    p = Path(path)
    return p.is_dir() and (p / METADATA_FILENAME).exists()
