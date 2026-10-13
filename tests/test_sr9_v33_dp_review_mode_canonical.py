"""SR9 v3.3 D5 — the DUMMY_REALISTIC_MODE_OVERRIDE dict is locked.

SNAPSHOTCUT-01 (Director, 11/10/2026): the two single-source-of-truth tests that compared the DP
Review engine's Modes with the strawman's Risk_Scope.Mode_Aggregated read a strawman workbook no
machine here holds, so they could only ever skip. They are retired; this lock is what remains.
"""
from __future__ import annotations

from src.sra.sra_simulation import DUMMY_REALISTIC_MODE_OVERRIDE


def test_dummy_realistic_override_dict_unchanged():
    """Lock the override dict contents to prevent silent additions.

    Per Path A architectural-debt comment in sra_simulation.py: 'Do not
    add new entries to this dict; flag any need for changes to PM for
    Path B prioritisation.' This test enforces that contract."""
    expected = {
        "R017.1": "Series",
        "R067": "Series",
        "R090": "Series",
        "R013": "Hybrid",
        "R026.1": "Hybrid",
        "R015.1": "Parallel",
        "R016.1": "Parallel",
        "R016.2": "Parallel",
    }
    assert DUMMY_REALISTIC_MODE_OVERRIDE == expected, (
        "DUMMY_REALISTIC_MODE_OVERRIDE has changed; flag to PM under Path B."
    )
