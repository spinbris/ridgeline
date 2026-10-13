"""Shared RBS Level 1 numeric-code to discipline-label mapping.

Lifted out of `src.final.sections.criticality._build_phase_map_from_xer`
under SR18 so the same lookup can be applied at the chart-render layer
(where raw WBS short_names like "01" / "10" reach the Y-axis) as well
as at the prefix-heuristic fallback site in the composer.

The labels reflect a PROJWBS Level 1 categorisation read
from the reference project's live .xer
(PROJWBS rows directly beneath the project root `BGP.BoP.WRK.01`). The
pre-SR18 inline dict in `_build_phase_map_from_xer` used a Beta-19b
heuristic (Civil / Structural / Mechanical / Piping / E&I /
Commissioning / Power Island / Sitewide) that did not match the
register's actual WBS short-name to wbs_name pairing and only covered
8 of the 15 numeric codes that surface on Chart 2's Y-axis. The
corrected values here align with the actual .xer and cover all 15
observed codes.

The mapping is applied at two sites:

1. The composer's task_code prefix-heuristic fallback inside
   `_build_phase_map_from_xer` (when the PROJWBS walk fails).
2. The Chart 2 Y-axis tick rendering inside
   `src.final.charts.make_criticality_density_gantt` (when the PROJWBS
   walk succeeds and feeds raw short-name codes through).

Unknown codes pass through unchanged via `resolve_rbs_l1_label`, which
preserves the deliberate fallback behaviour of the original
prefix-heuristic implementation.

Reference: the Beta-19c brief, Item 1; the SR18 brief,
Item 1.
"""

from __future__ import annotations

RBS_L1_PREFIX_MAP: dict[str, str] = {
    "01": "Key Milestones",
    "02": "Project Milestones",
    "03": "Interface Milestones",
    "04": "Approvals / Permits",
    "05": "Preliminaries",
    "06": "General Engineering",
    "07": "General Procurement",
    "08": "General Construction",
    "10": "Power Station Sitewide",
    "20": "Power Island",
    "30": "GT Services",
    "40": "Balance of Plant",
    "50": "Substation",
    "96": "Construction Verification",
    "97": "Pre-Commissioning",
    "98": "Staged Commissioning",
    "99": "Operation & Handover",
}


def resolve_rbs_l1_label(raw_label: str | None) -> str:
    """Map a raw WBS short-name or task_code prefix to its discipline name.

    Lookup is keyed on the trimmed raw label. When the raw label is a
    numeric code present as a key in `RBS_L1_PREFIX_MAP`, the
    corresponding discipline name is returned; otherwise the raw label
    passes through unchanged so callers retain a deterministic axis row
    even for unmapped codes.

    The sentinel `"Unmapped"` (Chart 2's missing-data row) is returned
    verbatim because it is not a numeric code and does not match any
    key.

    Parameters
    ----------
    raw_label : str or None
        Typically a PROJWBS `wbs_short_name` (e.g. `"10"`) or the
        leading dotted segment of a `TASK.task_code` (e.g. `"10"`
        from `"10.C.30.CI.020"`). `None` resolves to the empty string.
    """
    if raw_label is None:
        return ""
    key = str(raw_label).strip()
    if not key:
        return key
    # Active project binding may override a generic label with a project-
    # specific one (e.g. code "50" -> "Wind Grid & Substation").
    overrides = _active_wbs_labels()
    if key in overrides:
        return overrides[key]
    return RBS_L1_PREFIX_MAP.get(key, key)


def _active_wbs_labels() -> dict[str, str]:
    """WBS-label overrides from the active project binding (empty on failure).

    Imported lazily and defensively: a binding-resolution failure must never
    break label rendering — it degrades to the generic base map.
    """
    try:
        from src.sra.cpm.bindings import get_active_binding

        return dict(get_active_binding().wbs_labels)
    except Exception:  # pragma: no cover - defensive
        return {}
