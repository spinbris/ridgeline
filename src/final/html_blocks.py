"""What the HTML body shows for one composed value, as data (DELIVFIX-01, FW-19, FW-20).

The notebook's renderer used to decide this inline, and decided it wrongly in two ways a test
could not reach from a notebook cell: every dict came out as a stack of one-line paragraphs,
never a table (FW-19), and every key reached the reader as its code name (FW-20). The decisions
now live here, returned as a list of blocks, and the notebook only displays them - so this module
stays pure data and is tested without executing the notebook.

A block is ``(kind, payload)``:

- ``("text", str)`` - Markdown. The notebook renders it with its path-safe ``text()``.
- ``("table", DataFrame, show_index)`` - a real table.
- ``("image", str)`` - a chart file.

The treatment of each key, its label and each page's order are the presentation contract's
(``src/final/presentation_contract.py``, ``HTML_FIELDS``). An unmapped key still renders, under
its code name, because a silently dropped value is worse than an ugly one; the test reds on it.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from src.final import presentation_contract as contract

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg"}

#: A cell short enough to sit in a two-column table; anything longer is a paragraph.
_TABLE_CELL_MAX = 200
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")


def is_code_name(key: Any) -> bool:
    """True for a key written for code (``day_rate_dollars_per_workday``), not for a reader."""
    return isinstance(key, str) and _IDENTIFIER.fullmatch(key) is not None


def field(key: str) -> contract.Field:
    """The contract's treatment of ``key``; an unmapped key is labelled with its code name."""
    return contract.HTML_FIELDS.get(key) or contract.Field(
        contract.LABEL, str(key).replace("_", " ").capitalize())


def column_label(column: Any) -> Any:
    return contract.COLUMN_LABELS.get(column, column)


def _image_path(value: Any) -> str | None:
    if not isinstance(value, (str, Path)):
        return None
    try:
        p = Path(value)
        ok = p.suffix.lower() in IMAGE_SUFFIXES and p.is_file()
    except (TypeError, ValueError, OSError):
        return None
    return str(p) if ok else None


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return not value.empty
    if isinstance(value, dict):
        return any(_has_content(v) for v in value.values())
    if isinstance(value, (str, list, tuple)):
        return len(value) > 0
    return True


def _is_scalar_cell(value: Any) -> bool:
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return True
    return (isinstance(value, str) and _image_path(value) is None
            and len(value) <= _TABLE_CELL_MAX and "\n" not in value)


def _formatted(f: contract.Field, value: Any) -> str:
    if f.fmt:
        try:
            return f.fmt.format(value)
        except (ValueError, TypeError):
            pass
    return str(value)


def _cell(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return value


def _records_table(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame.from_records([{k: _cell(v) for k, v in r.items()} for r in rows])
    return df.rename(columns=column_label)


def _dataframe(df: pd.DataFrame) -> tuple:
    show_index = not isinstance(df.index, pd.RangeIndex)
    return ("table", df.rename(columns=column_label), show_index)


def _ordered_keys(d: dict, section: str | None) -> list:
    first = [k for k in contract.HTML_ORDER.get(section or "", ()) if k in d]
    return first + [k for k in d if k not in first]


def _dict(d: dict, out: list, section: str | None) -> None:
    rows: list[tuple[str, str]] = []

    def flush() -> None:
        if rows:
            out.append(("table", pd.DataFrame(rows, columns=["Item", "Value"]), False))
            rows.clear()

    for key in _ordered_keys(d, section):
        value, f = d[key], field(key)
        if f.treatment == contract.HIDDEN or not _has_content(value):
            continue
        if f.treatment == contract.HEADING:
            if _has_content(d.get(f.heads)):
                flush()
                out.append(("text", f"#### {value}"))
        elif f.treatment == contract.ROWS and isinstance(value, dict):
            for child_key, child in value.items():
                cf = field(child_key)
                if cf.treatment != contract.HIDDEN and _has_content(child):
                    rows.append((cf.label, _formatted(cf, child)))
        elif f.treatment == contract.PROSE:
            flush()
            _value(value, out, section=key)
        elif _is_scalar_cell(value):
            rows.append((f.label, _formatted(f, value)))
        else:
            flush()
            out.append(("text", f"**{f.label}**"))
            _value(value, out, section=key)
    flush()


def _value(value: Any, out: list, *, section: str | None) -> None:
    if not _has_content(value):
        return
    if isinstance(value, (pd.DataFrame, pd.Series)):
        out.append(_dataframe(value if isinstance(value, pd.DataFrame) else value.to_frame()))
        return
    image = _image_path(value)
    if image is not None:
        out.append(("image", image))
    elif isinstance(value, dict):
        _dict(value, out, section)
    elif isinstance(value, (list, tuple)):
        if all(isinstance(v, dict) for v in value):
            out.append(("table", _records_table(list(value)), False))
        elif all(isinstance(v, str) and _image_path(v) is None for v in value):
            out.append(("text", "\n".join(f"- {v}" for v in value)))
        else:
            for v in value:
                _value(v, out, section=section)
    else:
        out.append(("text", str(value)))


def blocks(value: Any, *, section: str | None = None) -> list[tuple]:
    """The blocks the HTML body shows for one composed value, in order.

    ``section`` is the composed key the value came from; it selects the page's order.
    """
    out: list[tuple] = []
    _value(value, out, section=section)
    return out


def key_paths(composed: dict, sections: list[str]) -> list[str]:
    """Every key inside ``sections`` that could reach a reader, as a sorted list of paths.

    ``page8_audit_trail/engine_versions/package`` for a dict key, ``page3_cost_drivers/
    drivers_table[]/Risk`` for a column of a list of records, ``.../comparison_table{}/Approach``
    for a DataFrame column. The committed inventory of these is what the label coverage test
    reads, so it needs no composed report of its own.
    """
    found: set[str] = set()

    def walk(value: Any, path: str) -> None:
        if isinstance(value, pd.DataFrame):
            found.update(f"{path}{{}}/{c}" for c in value.columns)
        elif isinstance(value, dict):
            for k, v in value.items():
                found.add(f"{path}/{k}")
                walk(v, f"{path}/{k}")
        elif isinstance(value, (list, tuple)) and value and all(isinstance(v, dict) for v in value):
            for row in value:
                found.update(f"{path}[]/{c}" for c in row)

    for s in sections:
        walk(composed.get(s), s)
    return sorted(found)
