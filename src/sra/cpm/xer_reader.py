"""Primavera P6 XER export reader (project-agnostic).

This module is the canonical Stage 3 schedule input layer. It parses any
standard Primavera P6 ``.xer`` flat-file export and returns each table as
a :class:`pandas.DataFrame`. Downstream Stage 3 briefs (Beta-02 graph
builder, Beta-03 CPM kernel) consume the DataFrames produced here.

This module is **project-agnostic** by design — no project paths, file
names, or project codes. Project-specific wire-up belongs in a binding under
``src/sra/cpm/bindings/``.

XER format reference
--------------------
The XER format is a tab-delimited flat file. Format published in the
Primavera P6 SDK (Oracle Primavera EPPM ``.xer`` Import/Export
Specification). Structure:

* The first line is a header beginning with ``ERMHDR``, holding metadata
  (export date, exporter user, source application, currency).
* Tables are introduced by ``%T<TAB><table_name>``.
* Columns are listed on the immediately following ``%F<TAB><col1><TAB>...``
  line.
* Each row is ``%R<TAB><val1><TAB>...``, with one value per column. Empty
  cells render as adjacent tabs.
* The file terminates with ``%E``.

A new ``%T`` starts the next table. The format is stable across recent
Primavera versions (Cloud 26.4 in the live-file tests); column ordering
within a table can vary across exports, which is why this reader uses
header-driven (``%F``) lookup rather than positional indices.

Encoding
--------
Default: cp1252 (Primavera's documented export encoding). UTF-8 is
accepted as an automatic fallback for files that are valid UTF-8 (e.g.,
synthetic test fixtures or non-Primavera exports). Detection is by
``UnicodeDecodeError`` on a strict UTF-8 attempt — cp1252 byte values in
the 0x80-0xFF range that aren't valid UTF-8 lead bytes (notably the smart
quotes 0x91-0x94, ``£`` 0xA3, ``¥`` 0xA5) cause the strict UTF-8 attempt
to fail, at which point the parser falls back to cp1252. Pure-ASCII
files are valid UTF-8 and are read as such.

Type coercion
-------------
Applied in :func:`_coerce_types`. Suffix-based, derived from XER naming
conventions:

* ``*_id`` → :class:`pandas.Int64Dtype` (nullable integer)
* ``*_date`` → ``datetime64[ns]`` via :func:`pandas.to_datetime`
* ``*_hr_cnt``, ``*_pct``, ``*_qty``, ``*_rate``, ``*_num``, ``*_amt``,
  ``*_value``, ``*_number``, ``*_cnt`` → ``float32``
* ``seq_num`` → ``Int64`` (sequence-number override; integer semantics)
* otherwise → object (string), whitespace-stripped

Numeric coercion uses ``errors='coerce'`` so empty cells become NaN /
``<NA>``; this matches Primavera's convention of leaving optional numeric
fields blank rather than zero.

Live-file row counts (a production .xer, data date 22 April 2026)
-------------------------------------------------------------
Confirmed during SR-S3-Beta-01 commissioning against
``Full Report.xer`` (3 MB, 30,445 lines):

==============  ====
Table           Rows
==============  ====
TASK            2025
TASKPRED        5982
CALENDAR           6
PROJWBS         1213
ACTVCODE          57
NONWORK            7
RSRC               6
TASKRSRC        1549
UDFVALUE       15497
==============  ====

Public API
----------
* :func:`parse_xer` — parse a file path, return ``dict[table, DataFrame]``.
* :func:`validate_xer_tables` — assert required tables and columns are
  present; raise :class:`ValueError` listing every missing item.

Module-private helpers (``_parse_header``, ``_split_into_table_blocks``,
``_build_dataframe``, ``_coerce_types``, ``_read_text_with_encoding``)
are not part of the public surface.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Required-column contract (consumed by validate_xer_tables)
# ----------------------------------------------------------------------------

#: Tables and columns required by the Stage 3 pipeline. Tables not listed
#: here (e.g., ``RSRC``, ``TASKRSRC``) may be parsed if present and returned
#: in the dict, but their absence is not a validation failure.
_REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "TASK": (
        "task_id",
        "proj_id",
        "wbs_id",
        "clndr_id",
        "task_code",
        "task_name",
        "task_type",
        "target_drtn_hr_cnt",
        "total_float_hr_cnt",
        "free_float_hr_cnt",
        "early_start_date",
        "early_end_date",
        "late_start_date",
        "late_end_date",
        "target_start_date",
        "target_end_date",
        "cstr_date",
        "cstr_type",
        "driving_path_flag",
    ),
    "TASKPRED": (
        "task_pred_id",
        "task_id",
        "pred_task_id",
        "pred_type",
        "lag_hr_cnt",
    ),
    "CALENDAR": (
        "clndr_id",
        "clndr_name",
        "default_flag",
        "clndr_data",
        "day_hr_cnt",
        "week_hr_cnt",
        "month_hr_cnt",
        "year_hr_cnt",
    ),
    "PROJWBS": (
        "wbs_id",
        "proj_id",
        "parent_wbs_id",
        "wbs_short_name",
        "wbs_name",
        "seq_num",
    ),
}

#: Subset of ``_REQUIRED_COLUMNS`` whose presence is a hard parse-time
#: requirement (per :func:`parse_xer` docstring contract). Other required
#: tables are checked at validation time.
_REQUIRED_TABLES: tuple[str, ...] = ("TASK", "TASKPRED", "CALENDAR")


# ----------------------------------------------------------------------------
# Type-coercion suffix rules (consumed by _coerce_types)
# ----------------------------------------------------------------------------

_SUFFIXES_INT64: tuple[str, ...] = ("_id",)
_SUFFIXES_DATE: tuple[str, ...] = ("_date",)
_SUFFIXES_FLOAT: tuple[str, ...] = (
    "_hr_cnt",
    "_pct",
    "_qty",
    "_rate",
    "_num",
    "_amt",
    "_value",
    "_number",
    "_cnt",
)

#: Columns whose suffix-rule outcome is overridden. ``seq_num`` ends in
#: ``_num`` (would be float) but is semantically integer; ``crt_path_num``
#: similar.
_COLUMN_TYPE_OVERRIDES: dict[str, str] = {
    "seq_num": "Int64",
    "crt_path_num": "Int64",
    "float_path": "Int64",
    "float_path_order": "Int64",
}


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def parse_xer(path: str | Path) -> dict[str, pd.DataFrame]:
    """Parse a Primavera P6 XER export into per-table DataFrames.

    Parameters
    ----------
    path : str or Path
        Path to the ``.xer`` file.

    Returns
    -------
    dict[str, pandas.DataFrame]
        Keys are XER table names (``'TASK'``, ``'TASKPRED'``, ``'CALENDAR'``,
        etc.); values are DataFrames with one column per XER ``%F`` field.
        Type coercion applied per the suffix rules documented at the
        module level. Tables present in the file but not listed in
        :data:`_REQUIRED_COLUMNS` are still returned (opportunistic
        consumption by later briefs).

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If the first non-empty line does not start with ``ERMHDR`` (not a
        valid XER), or if any of the parse-time required tables
        (``TASK``, ``TASKPRED``, ``CALENDAR``) is missing.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"XER file not found: {p}")

    # SR-S3-Beta-10: reject ZIP-based formats (.xlsx, .docx, .xlsb, .xer.zip)
    # at the boundary. Without this guard, an .xlsx fed in here surfaces as
    # a confusing two-stage UnicodeDecodeError from _read_text_with_encoding;
    # the binding-level wiring bug that motivated this guard is documented
    # in the Beta-10 wiring-fix brief, §2.
    with p.open("rb") as _f:
        _magic = _f.read(4)
    if _magic == b"PK\x03\x04":
        raise ValueError(
            f"File at {p} is a ZIP archive (looks like .xlsx/.docx), not "
            "an XER text export. Point the project's binding at its "
            "schedule export (.xer)."
        )

    text = _read_text_with_encoding(p)
    lines = text.splitlines()

    _parse_header(lines)
    table_blocks = _split_into_table_blocks(lines)

    tables: dict[str, pd.DataFrame] = {}
    for table_name, columns, rows in table_blocks:
        tables[table_name] = _build_dataframe(table_name, columns, rows)

    missing_tables = [t for t in _REQUIRED_TABLES if t not in tables]
    if missing_tables:
        raise ValueError(
            "XER missing required table(s): "
            + ", ".join(missing_tables)
            + f" (file: {p.name})"
        )

    logger.info(
        "Parsed XER %s: %d tables, %d total rows",
        p.name,
        len(tables),
        sum(len(df) for df in tables.values()),
    )
    return tables


def validate_xer_tables(tables: dict[str, pd.DataFrame]) -> None:
    """Validate that the parsed tables contain the columns Stage 3 needs.

    Required tables and columns are documented in :data:`_REQUIRED_COLUMNS`.
    The error message lists every missing table and every missing column,
    so the caller sees the full failure set in one pass.

    Parameters
    ----------
    tables : dict[str, pandas.DataFrame]
        Output of :func:`parse_xer`.

    Raises
    ------
    ValueError
        If any required table or column is missing.
    """
    issues: list[str] = []
    for table_name, required_columns in _REQUIRED_COLUMNS.items():
        if table_name not in tables:
            issues.append(f"missing table: {table_name}")
            continue
        df = tables[table_name]
        missing_columns = [c for c in required_columns if c not in df.columns]
        if missing_columns:
            issues.append(
                f"table {table_name} missing column(s): "
                + ", ".join(missing_columns)
            )
    if issues:
        raise ValueError("XER validation failed:\n  - " + "\n  - ".join(issues))


# ----------------------------------------------------------------------------
# Module-private helpers
# ----------------------------------------------------------------------------

def _read_text_with_encoding(path: Path) -> str:
    """Read XER text via UTF-8 → CP1252 → Latin-1 fallback chain.

    Pure-ASCII files are valid UTF-8 and are read with that encoding.
    Files containing cp1252-specific bytes (smart quotes, ``£``, ``¥``,
    accented characters) fail strict UTF-8 decoding because those bytes
    aren't valid UTF-8 lead bytes; the function then falls back to cp1252.

    SR-S3-Beta-10: a Latin-1 final fallback handles XER exports that
    contain bytes undefined in CP1252 (the five undefined slots
    ``0x81 0x8D 0x8F 0x90 0x9D``). Latin-1 maps every byte 0x00-0xFF
    to a code point, so it never raises. The fallback emits a
    ``logger.warning`` so it isn't silent — a Latin-1-only XER is
    unusual and worth flagging for the operator.
    """
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        logger.debug("UTF-8 decode failed for %s; falling back to cp1252", path.name)
    try:
        return raw.decode("cp1252")
    except UnicodeDecodeError:
        logger.warning(
            "XER file %s decoded as latin-1 fallback; CP1252 encountered "
            "an undefined byte (0x81/0x8D/0x8F/0x90/0x9D)",
            path.name,
        )
        return raw.decode("latin-1")


def _parse_header(lines: list[str]) -> None:
    """Validate the file's first non-empty line is an ERMHDR.

    Raises ``ValueError`` if not — used to reject non-XER files early.
    """
    for line in lines:
        if not line.strip():
            continue
        if line.startswith("ERMHDR"):
            return
        raise ValueError(
            "XER file does not start with ERMHDR header (not a valid XER export)"
        )
    raise ValueError("XER file is empty")


def _split_into_table_blocks(
    lines: list[str],
) -> list[tuple[str, list[str], list[list[str]]]]:
    """Split the file body into ``(table_name, columns, rows)`` triples.

    Walks the line stream emitting one block per ``%T`` directive. Rows
    that arrive before any ``%T`` (header-only rows like ``ERMHDR``) are
    ignored; the ``%E`` terminator stops the walk.

    Each row is split on tab and padded with empty strings to the column
    count, defending against XER exports that elide trailing empty
    fields. Rows longer than the column count are truncated with a debug
    log (no real-world XER export emits this; tolerance is a safety
    margin).
    """
    blocks: list[tuple[str, list[str], list[list[str]]]] = []
    current_table: str | None = None
    current_columns: list[str] | None = None
    current_rows: list[list[str]] = []

    def _close_current() -> None:
        nonlocal current_table, current_columns, current_rows
        if current_table is not None and current_columns is not None:
            blocks.append((current_table, current_columns, current_rows))
        current_table = None
        current_columns = None
        current_rows = []

    for line in lines:
        if not line:
            continue
        if line.startswith("%E"):
            break
        if line.startswith("%T\t"):
            _close_current()
            current_table = line[3:].split("\t", 1)[0].strip()
            current_columns = None
            current_rows = []
        elif line.startswith("%F\t"):
            current_columns = line[3:].split("\t")
        elif line.startswith("%R\t"):
            if current_table is None or current_columns is None:
                continue
            row = line[3:].split("\t")
            ncols = len(current_columns)
            if len(row) < ncols:
                row = row + [""] * (ncols - len(row))
            elif len(row) > ncols:
                logger.debug(
                    "Row in %s has %d fields, expected %d; truncating",
                    current_table,
                    len(row),
                    ncols,
                )
                row = row[:ncols]
            current_rows.append(row)
        # other %-directives (none observed in real exports) are ignored

    _close_current()
    return blocks


def _build_dataframe(
    table_name: str,
    columns: list[str],
    rows: list[list[str]],
) -> pd.DataFrame:
    """Build a typed DataFrame from a parsed XER table block.

    Empty tables (``%T`` + ``%F`` but no ``%R`` rows) are also routed
    through :func:`_coerce_types` so that dtype guards in downstream
    consumers (``pd.api.types.is_datetime64_any_dtype`` etc.) hold for
    the empty-table case as well as the populated case.
    """
    if not rows:
        df = pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
    else:
        df = pd.DataFrame(rows, columns=columns)
    return _coerce_types(df, table_name)


def _coerce_types(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """Apply suffix-driven type coercion to a parsed table.

    Mutates ``df`` in place and returns it (the function is module-private
    and only called from :func:`_build_dataframe` against a freshly-
    constructed DataFrame, so there is no aliasing risk; the return value
    is the same object).

    Numeric coercion uses ``errors='coerce'`` so empty / non-numeric
    cells become NaN (or pandas ``<NA>`` for nullable integer columns).
    String columns are left as ``object`` dtype with whitespace stripped.
    """
    for col in df.columns:
        if col in _COLUMN_TYPE_OVERRIDES:
            target = _COLUMN_TYPE_OVERRIDES[col]
            if target == "Int64":
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
            elif target == "float32":
                df[col] = pd.to_numeric(df[col], errors="coerce").astype(np.float32)
            continue

        if col.endswith(_SUFFIXES_INT64):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
        elif col.endswith(_SUFFIXES_DATE):
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif col.endswith(_SUFFIXES_FLOAT):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(np.float32)
        else:
            # String column: strip whitespace.
            df[col] = df[col].astype(str).str.strip()
            # Empty strings are common in XER; downstream code that wants
            # NaN-style emptiness can use .replace('', pd.NA) at consumption
            # time. We keep '' here to avoid silently changing semantics.

    return df
