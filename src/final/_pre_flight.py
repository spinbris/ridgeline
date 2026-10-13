"""Pre-flight defensive helpers for SR9.

Excel lock files (`~$<filename>.xlsx`) cause openpyxl to fail with
PermissionError or yield stale data. This helper raises early with a
clear message rather than letting downstream reads fail opaquely.
"""

from __future__ import annotations

from pathlib import Path


def assert_strawman_unlocked(strawman_path: Path | str) -> None:
    """Raise RuntimeError if the strawman Excel lock file exists.

    Excel writes a `~$<filename>.xlsx` sentinel in the same directory
    while the workbook is open. Detecting it lets us fail fast instead
    of producing a confusing PermissionError or stale read deeper in
    the call stack.
    """
    p = Path(strawman_path)
    lock = p.parent / f"~${p.name}"
    if lock.exists():
        raise RuntimeError(
            f"Strawman workbook is locked (Excel has it open): {lock}. "
            f"Close Excel and re-run."
        )
