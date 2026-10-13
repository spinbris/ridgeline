"""The elicitation basis, as it reaches a rendered driver table (REPORT01 F-F).

The register records a `Basis of Estimate` per risk - free text naming where the
three-point estimate came from. It is captured by the reader and, before REPORT01, was
printed nowhere, so a reviewer could not tell a workshop-agreed number from a placeholder
while the deliverable carried a banner saying bindings were pending workshop validation.

The header appears **twice** in the register, once in the Contingent Risk Cost section and
once in Time (Working Days), and the two are different claims about different numbers.
The cost drivers table therefore reads ``basis`` and the schedule drivers table reads
``time_basis``; :data:`COST_FIELD` and :data:`TIME_FIELD` name them so a caller cannot
pass the wrong one by writing a bare string.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

#: Column header for the rendered tables. One spelling, so the two arms agree.
BASIS_COLUMN = "Basis of estimate"

#: What an unrecorded basis says. **Not** an empty cell: blank renders as absence of a
#: column value, which a reader can read as "nothing to note" - the opposite of the
#: truth, which is that nobody has said where the number came from (P-5).
NOT_RECORDED = "Not recorded"

#: The two register sections' fields on ``RiskInput``.
COST_FIELD = "basis"
TIME_FIELD = "time_basis"


def _attr(r: Any, name: str) -> Any:
    """Read a field off a RiskInput-like object or dict.

    Mirrors ``cost_drivers._risk_attr``: this layer is fed RiskInput in production and
    dicts or namespaces from several section-builder callers, and the section modules
    already read risks that way.
    """
    return r.get(name, "") if isinstance(r, dict) else getattr(r, name, "")


def basis_lookup(risks: Iterable[Any], field: str) -> dict[str, str]:
    """Map risk id -> recorded basis text for one section's field.

    ``field`` is :data:`COST_FIELD` or :data:`TIME_FIELD` - checked, because the two are
    a single word apart and passing the wrong one would silently print the wrong claim
    about a number rather than fail.
    """
    if field not in (COST_FIELD, TIME_FIELD):
        raise ValueError(
            f"basis field must be {COST_FIELD!r} or {TIME_FIELD!r}, got {field!r}")
    return {_attr(r, "risk_id"): _attr(r, field) for r in risks}


def basis_cell(lookup: dict[str, str], risk_id: str) -> str:
    """Render one table cell from a lookup built by :func:`basis_lookup`.

    Absent, empty and whitespace-only all render as :data:`NOT_RECORDED`. Absent happens
    when the driver ranking (built from the engine's own arrays) carries a risk id with
    no matching register row; borrowing a neighbour's basis there would be worse than
    saying nothing, and raising would fail a report over a cell.
    """
    return (lookup.get(risk_id) or "").strip() or NOT_RECORDED
