"""SR9 v3.2 Deliverable 2 - the composer drops the keys the deliverable does not carry.

PRESENT-01 (D-4): the function the surgery lives in was renamed for what it does, and the mode
kwarg that selected it is gone, so the two tests of that kwarg's surface went with it.

SNAPSHOTCUT-01 (Director, 11/10/2026): the fifteen tests of the surgery itself, which read the
frozen v3.1 state-cache pickle and could only ever skip (SKIPDEAD-01), are retired.
"""
from __future__ import annotations

import inspect

from src.final import commentary_text, composer


# ---------------------------------------------------------------------------
# Signature surface
# ---------------------------------------------------------------------------

def test_composer_module_exposes_the_drop_pass():
    assert hasattr(composer, "_write_page1_narrative_and_drop_dev_keys")
    assert callable(composer._write_page1_narrative_and_drop_dev_keys)


def test_composer_takes_no_mode_kwarg():
    """PRESENT-01 (D-4) red-first: reinstating the kwarg reds this."""
    sig = inspect.signature(composer.compose_final_report_data)
    assert "mode" not in sig.parameters


# ---------------------------------------------------------------------------
# The limitations list (the compose call itself is integration-tested in D9).
# ---------------------------------------------------------------------------

def test_limitations_current_is_the_neutral_list():
    """One limitations list, and it is the neutral one.

    This paired two lists and asserted they differed. The dev list retired with the dev report
    (PRESENT-01 D-4), so what is left to assert is that the survivor is the neutral one - no
    LD/IDC entry, no PM-review framing.
    """
    lst = list(commentary_text.LIMITATIONS_CURRENT)
    assert not any("Liquidated damages" in x for x in lst)
    assert not any("PM review" in x for x in lst)
