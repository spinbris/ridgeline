"""The one Mode-multiplier resolver (RS-D-3, D-15, part 3a).

Every place the engine turns a risk's Mode label into its multiplier goes through
:func:`resolve_mode_multiplier`. Until RS-D-3 the schedule cross-check raised by name on a
Mode the grid did not define while four other lookups fell back silently - the SRA engine and
the integrated dual-lookup to ``0.0`` (the risk left the schedule without a word), the report's
tail-risk narrative to ``0.5``. One resolver, one rule: an unknown Mode is a register defect and
the run stops naming the risk.

The grid itself (``{mode_name: multiplier}``) is the caller's to supply. Part 3b of RS-D-3
makes the register the only place it comes from.

Deliberately dependency-free (no pandas): the QRAXL shared core, which also runs inside
Excel's Python, resolves through it too.
"""
from __future__ import annotations

import math
from typing import Any, Mapping


def resolve_mode_multiplier(
    raw_mode: Any,
    mode_multipliers: Mapping[str, float],
    risk_id: Any,
) -> float:
    """Return the grid's multiplier for ``raw_mode``; raise, naming the risk, when the grid
    does not define it.

    Matching is case-insensitive, because Excel's ``MATCH`` on text is: a register that says
    ``hybrid`` resolves to ``Hybrid`` on both sides rather than being rejected by one of them.
    Surrounding whitespace is stripped, which Excel's ``MATCH`` does not do - a known and
    recorded asymmetry (SRA-02 S-E review finding F-6), kept because stripping is the forgiving
    direction.

    Raising rather than returning zero is deliberate (D-14, METHRANGE-01): a zero multiplier
    silently removes the risk from the schedule and is indistinguishable from a legitimate
    Parallel classification.
    """
    resolved = "" if raw_mode is None else str(raw_mode).strip()
    if isinstance(raw_mode, float) and math.isnan(raw_mode):
        resolved = ""
    if resolved.casefold() == "nan":
        # An upstream ``str(value or default)`` turns a NaN cell into the text "nan"
        # (NaN is truthy, so the default never fires). It is a blank, and is named as one.
        resolved = ""
    folded = {str(k).strip().casefold(): v for k, v in mode_multipliers.items()}
    if len(folded) != len(mode_multipliers):
        raise ValueError(
            f"Mode multiplier grid defines the same Mode more than once under different "
            f"spellings: {sorted(str(k) for k in mode_multipliers)}. Fix the register."
        )
    if resolved and resolved.casefold() in folded:
        return float(folded[resolved.casefold()])
    label = "<blank>" if not resolved else resolved
    raise ValueError(
        f"risk {risk_id!r}: Mode is {label!r}, which is not one of the register's Mode "
        f"multipliers {sorted(str(k) for k in mode_multipliers)}. Refusing to treat it as "
        f"zero: a zero Mode multiplier silently removes this risk from the schedule and is "
        f"indistinguishable from a legitimate Parallel classification (D-14, D-15, "
        f"METHRANGE-01)."
    )
