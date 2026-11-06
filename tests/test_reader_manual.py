"""ASKSVC-01 stage B: the Ask box's reader manual describes every field the period data carries.

The Ask service answers from `docs/ask/READER_MANUAL.md` and one period's JSON. A field the
manual does not describe is a field the model would have to guess at, and a manual stamped for
another contract explains the wrong fields (the service refuses that case at run time; this
catches it at commit time).

Two field catalogues, because neither alone is complete:

1. The committed golden period JSON (`tests/golden/period_json/...`), which IS the writer's
   output (`tests/test_7a_period_json_golden.py` holds it equal). It is a first period, so its
   lists of mitigations, delta entries and contingency movements are empty.
2. `dashboard/types/period.ts`, the app's typed contract, which names those fields too.

Every leaf path of (1) must appear in the manual in backticks, with list items as `[]` and
risk-id keys as `<risk_id>`. Every field name declared in (2) must name a segment of at least
one backticked path in the manual. Fast: reads three committed files, runs nothing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.am.json_writer import SCHEMA_VERSION

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
MANUAL = REPO / "docs" / "ask" / "READER_MANUAL.md"
GOLDEN = REPO / "tests" / "golden" / "period_json" / "wind_synth" / "period_20260228.json"
TYPES = REPO / "dashboard" / "types" / "period.ts"

#: A dictionary key that is a risk identifier (WT-021, R-001) rather than a field name.
_RISK_KEY = re.compile(r"^[A-Z]{1,4}-?\d{1,4}$")
#: Interfaces in period.ts that are not period data.
_NOT_PERIOD_DATA = {"PeriodIndex"}


def _manual_text() -> str:
    return MANUAL.read_text(encoding="utf-8")


def manual_paths(text: str) -> set[str]:
    """Every backticked token in the manual."""
    return set(re.findall(r"`([^`\n]+)`", text))


def manual_stamp(text: str) -> str | None:
    """The same rule the Ask service applies to the manual's stamp line, in its own repository."""
    m = re.search(r"^\s*contract_version:\s*([0-9]+(?:\.[0-9]+)*)\s*$", text, re.MULTILINE)
    return m.group(1) if m else None


def leaf_paths(value, prefix: str = "") -> set[str]:
    """Dotted paths to every leaf; list items as `[]`, risk-id keys as `<risk_id>`."""
    out: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            key = "<risk_id>" if _RISK_KEY.match(k) else k
            out |= leaf_paths(v, f"{prefix}.{key}" if prefix else key)
    elif isinstance(value, list):
        if not value:
            out.add(prefix + "[]")
        for item in value:
            out |= leaf_paths(item, prefix + "[]")
    else:
        out.add(prefix)
    return out


def declared_fields(ts: str) -> set[str]:
    """Field names declared in period.ts, outside comments and non-period interfaces."""
    names: set[str] = set()
    skipping = False
    for line in ts.splitlines():
        head = re.match(r"^export (?:interface|type) (\w+)", line)
        if head:
            skipping = head.group(1) in _NOT_PERIOD_DATA
        stripped = line.strip()
        if skipping or stripped.startswith(("//", "*", "/*")):
            continue
        m = re.match(r"^\s*\|?\s*\{?\s*(\w+)\??:\s", line)
        if m:
            names.add(m.group(1))
    return names


def missing_from_manual(text: str) -> tuple[list[str], list[str]]:
    paths = manual_paths(text)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    # An empty list in the golden (a first period logs no mitigations) is covered by any entry
    # for that list's items.
    missing_paths = sorted(p for p in leaf_paths(golden) if p not in paths
                           and not (p.endswith("[]") and any(q.startswith(p) for q in paths)))
    # A typed field is covered when it names any segment of a manual path: a leaf ends one, a
    # block (`meta`, `within_noise`) sits inside one.
    endings = {seg for p in paths for seg in re.split(r"[.\[\]]+", p) if seg}
    missing_fields = sorted(f for f in declared_fields(TYPES.read_text(encoding="utf-8"))
                            if f not in endings)
    return missing_paths, missing_fields


def test_the_manual_is_stamped_for_the_contract_the_writer_emits():
    assert manual_stamp(_manual_text()) == SCHEMA_VERSION, (
        f"docs/ask/READER_MANUAL.md is stamped {manual_stamp(_manual_text())!r}; the writer emits "
        f"{SCHEMA_VERSION!r}. Update the manual for the new contract, then its stamp.")


def test_every_field_the_period_data_carries_has_a_manual_entry():
    missing_paths, missing_fields = missing_from_manual(_manual_text())
    assert not missing_paths, f"period-data fields with no manual entry: {missing_paths}"
    assert not missing_fields, f"period.ts fields with no manual entry: {missing_fields}"


def test_the_check_reds_when_an_entry_is_removed():
    """Red-first, kept: removing one entry must be caught by each catalogue."""
    text = _manual_text()
    assert "`headline.p80_finish`" in text and "`mitigations[].dollars_saved_p80`" in text
    gone_golden = text.replace("`headline.p80_finish`", "headline p80 finish")
    assert "headline.p80_finish" in missing_from_manual(gone_golden)[0]
    gone_typed = text.replace("`mitigations[].dollars_saved_p80`", "dollars saved")
    assert "dollars_saved_p80" in missing_from_manual(gone_typed)[1]


def test_the_check_reds_on_a_wrong_stamp():
    text = _manual_text().replace(f"contract_version: {SCHEMA_VERSION}", "contract_version: 0.9")
    assert manual_stamp(text) == "0.9" != SCHEMA_VERSION


def test_the_golden_is_the_contract_the_manual_describes():
    """If the golden were stale the first check would be checking the wrong fields."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert golden["schema_version"] == SCHEMA_VERSION
