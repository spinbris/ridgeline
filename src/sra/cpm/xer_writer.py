"""Primavera P6 XER text writer — the inverse of :mod:`xer_reader`.

Showcase-P2 WS2-C: the one genuinely new piece of engine code in P2. It
serialises a set of XER tables (``TASK`` / ``TASKPRED`` / ``CALENDAR`` /
``PROJWBS`` and any extras) to the tab-delimited XER text format that
:func:`src.sra.cpm.xer_reader.parse_xer` consumes, so a synthetic
synthetic schedule can drive the Stage 3 pipeline unchanged. It scales
up to the full P3 publishable schedule.

Format produced (matching the reader's grammar):

    ERMHDR\\t<version>\\t<date>\\t...           # one header line
    %T\\tTASK                                   # table directive
    %F\\ttask_id\\tproj_id\\t...                 # field (column) names
    %R\\t<v1>\\t<v2>\\t...                        # one row per record
    %T\\tTASKPRED
    ...
    %E                                          # end-of-file terminator

Value formatting is chosen so a round-trip through
:func:`~src.sra.cpm.xer_reader.parse_xer` reproduces the input: ``_date``
columns are emitted ``YYYY-MM-DD HH:MM`` (parseable by ``pd.to_datetime``),
``None``/``NaN`` become empty strings, and numbers use their plain string
form. The output is UTF-8 (the reader's first-choice encoding).
"""
from __future__ import annotations

import datetime as _dt
import logging
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from src.sra.cpm.xer_reader import _REQUIRED_COLUMNS, validate_xer_tables

logger = logging.getLogger(__name__)

__all__ = ["tables_to_xer_text", "write_xer", "REQUIRED_TABLE_COLUMNS"]

#: Re-exported view of the reader's required-column contract, so a fixture
#: author can ask "what columns must TASK carry?" without importing a
#: private name.
REQUIRED_TABLE_COLUMNS: dict[str, tuple[str, ...]] = dict(_REQUIRED_COLUMNS)

#: Default ERMHDR fields. The reader only checks the line starts with
#: ``ERMHDR``; these values are plausible filler (version, export date,
#: project, user, db, module, currency).
_DEFAULT_HEADER = (
    "ERMHDR", "7.0", "2026-01-01", "Project", "admin",
    "admin", "Project Management", "USD",
)


def _format_value(column: str, value: object) -> str:
    """Render a single cell to its XER string form (reader-round-trippable)."""
    # Missing -> empty field.
    if value is None:
        return ""
    if isinstance(value, float) and np.isnan(value):
        return ""
    try:
        if pd.isna(value):  # catches pd.NaT / pd.NA / np.nan
            return ""
    except (TypeError, ValueError):
        pass

    if isinstance(value, (pd.Timestamp, _dt.datetime)):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, _dt.date):
        return value.strftime("%Y-%m-%d %H:%M")

    if isinstance(value, (np.integer,)):
        return str(int(value))
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        # Integers-as-floats (8.0) keep a trailing .0 — harmless, the reader
        # coerces _hr_cnt columns back to float either way.
        return repr(value)

    text = str(value)
    if "\t" in text or "\n" in text:
        raise ValueError(
            f"XER cell for column {column!r} contains a tab/newline, which "
            f"would corrupt the tab-delimited format: {text!r}"
        )
    return text


def _table_records(table: "pd.DataFrame | Sequence[Mapping[str, object]]") -> tuple[list[str], list[dict]]:
    """Normalise a table to ``(ordered_columns, list_of_row_dicts)``."""
    if isinstance(table, pd.DataFrame):
        columns = list(table.columns)
        records = table.to_dict(orient="records")
        return columns, records
    records = [dict(r) for r in table]
    # Column order: first-seen across all records (stable, deterministic).
    columns: list[str] = []
    seen: set[str] = set()
    for rec in records:
        for k in rec:
            if k not in seen:
                seen.add(k)
                columns.append(k)
    return columns, records


def tables_to_xer_text(
    tables: Mapping[str, "pd.DataFrame | Sequence[Mapping[str, object]]"],
    *,
    header: Sequence[str] | None = None,
) -> str:
    """Serialise ``tables`` to XER text (does not write to disk).

    Parameters
    ----------
    tables:
        Mapping of XER table name -> rows (a DataFrame or a sequence of
        row dicts). Column order follows the DataFrame columns or the
        first-seen key order across the row dicts.
    header:
        Optional ERMHDR field list. Defaults to :data:`_DEFAULT_HEADER`.

    Returns
    -------
    str
        The full XER document, ``\\n``-joined, trailing newline included.
    """
    if not tables:
        raise ValueError("tables is empty; nothing to write")

    lines: list[str] = ["\t".join(header or _DEFAULT_HEADER)]
    for table_name, table in tables.items():
        columns, records = _table_records(table)
        if not columns:
            raise ValueError(f"table {table_name!r} declares no columns")
        lines.append(f"%T\t{table_name}")
        lines.append("%F\t" + "\t".join(columns))
        for rec in records:
            cells = [_format_value(col, rec.get(col)) for col in columns]
            lines.append("%R\t" + "\t".join(cells))
    lines.append("%E")
    return "\n".join(lines) + "\n"


def write_xer(
    tables: Mapping[str, "pd.DataFrame | Sequence[Mapping[str, object]]"],
    path: str | Path,
    *,
    header: Sequence[str] | None = None,
    validate: bool = True,
) -> Path:
    """Write ``tables`` to ``path`` as an XER file; return the path.

    When ``validate`` is true (default), the serialised tables are parsed
    back and checked with :func:`~src.sra.cpm.xer_reader.validate_xer_tables`
    before the file is committed, so a malformed fixture fails loudly at
    authoring time rather than deep inside the Stage 3 pipeline.
    """
    text = tables_to_xer_text(tables, header=header)
    if validate:
        # Round-trip through the reader to confirm the file is well-formed
        # and carries the required tables/columns.
        from src.sra.cpm.xer_reader import parse_xer

        tmp = Path(path).with_suffix(Path(path).suffix + ".tmp")
        # write_bytes, not write_text - see the note on the final write below.
        tmp.write_bytes(text.encode("utf-8"))
        try:
            parsed = parse_xer(tmp)
            validate_xer_tables(parsed)
        finally:
            tmp.unlink(missing_ok=True)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # write_bytes, never write_text. `tables_to_xer_text` documents its output as
    # "\n"-joined, and `Path.write_text` opens with newline=None, which translates every
    # "\n" to os.linesep - so on Windows this wrote CRLF. The repository declares
    # `* text=auto eol=lf`, so git normalised on commit and the index stayed clean, but the
    # WORKING TREE copy was CRLF and `git ls-files --eol | grep w/crlf` - the pre-close
    # check - listed every fixture anyone had regenerated. Found at
    # SHOWCASE-02 while authoring a new fixture; it affected all three builders equally.
    out.write_bytes(text.encode("utf-8"))
    logger.info("Wrote XER %s: %d tables", out.name, len(tables))
    return out
