"""DELIVFIX-01 / FW-19, FW-20: the committed key inventory still matches the composer.

The fast label test (``test_delivfix01_html_blocks``) reads ``tests/fixtures/
delivfix01_composed_keys.json`` instead of composing a report. That is only sound while the file
matches what the composer actually emits, so this composes both shipped projects and compares.
A red here means a key was added, renamed or removed: re-run ``scripts/inventory_composed_keys.py``
and give any new key a treatment in the presentation contract.

It composes, so it is ``slow`` - the increment lane's, not the stage lane's.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.inventory_composed_keys import OUT, compose_one, inventory, rendered_sections
from src.final.html_blocks import blocks

pytestmark = pytest.mark.slow


def test_the_committed_inventory_is_what_the_composer_emits(tmp_path):
    committed = json.loads(Path(OUT).read_text(encoding="utf-8"))
    live = inventory(tmp_path)
    added = sorted(set(live["paths"]) - set(committed["paths"]))
    gone = sorted(set(committed["paths"]) - set(live["paths"]))
    assert not (added or gone), (
        "the composer's keys have moved since the inventory was taken - re-run "
        f"scripts/inventory_composed_keys.py.\n  added: {added}\n  gone: {gone}")
    assert live["sections"] == committed["sections"]


def _tabular_values(value):
    """Every non-empty DataFrame or list of records inside a composed value."""
    if isinstance(value, pd.DataFrame):
        return [value] if not value.empty else []
    if isinstance(value, dict):
        return [t for v in value.values() for t in _tabular_values(v)]
    if isinstance(value, (list, tuple)) and value and all(isinstance(v, dict) for v in value):
        return [value]
    return []


def _shape(table) -> tuple[int, int]:
    if isinstance(table, pd.DataFrame):
        return table.shape
    return len(table), len({k for row in table for k in row})


def test_every_table_in_a_real_report_renders_as_one_table_of_its_own_shape(tmp_path):
    """FW-19's floor. Each DataFrame or list of records the composer hands over must come out as
    ONE table with its own rows and columns.

    A count of table blocks is not enough, and was the first draft: red-first broke the
    records-to-table rule and the count still passed, because each record then fell through to
    a two-column table of its own - FW-19's shape exactly, counted as "tables". Shapes cannot be
    satisfied that way.
    """
    from src.final import presentation_contract as contract
    from src.final.html_blocks import field

    composed = compose_one("synthetic_wind", "synthetic_wind", "wind", tmp_path)
    for section in rendered_sections():
        value = composed.get(section)
        if isinstance(value, dict):
            value = {k: v for k, v in value.items() if field(k).treatment != contract.HIDDEN}
        rendered = [b[1].shape for b in blocks(value, section=section) if b[0] == "table"]
        for table in _tabular_values(value):
            assert _shape(table) in rendered, (
                f"{section}: a {_shape(table)} table was composed and did not render as one "
                f"table; rendered table shapes: {rendered}")
