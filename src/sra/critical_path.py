"""Critical-path classifier for the SRA workstream.

Classifies every activity AND milestone row in SR1's P6 DataFrame as
Series, Hybrid, or Parallel using the Option Z hybrid rule, adapted for
the 22 April Longest Path baseline.

Methodology note - Longest Path adaptation
------------------------------------------
SR1 confirmed the 22 April P6 file on disk is a Longest Path filter
(1,798 activities, 229 milestones, 355 WBS summaries; 125 P6-Critical
rows total of which 114 are activities and 11 are milestones), not a
full schedule. Within this subset every row is by construction part of
the longest path; the classifier's role is to refine that set into
finish-date-driving (Series), near-critical (Hybrid), and slack-bearing
(Parallel) buckets.

Methodology note - milestone inclusion
--------------------------------------
The classifier classifies all activity AND milestone rows. WBS summary
rows are excluded as aggregation artefacts. Milestones are included
because the SRA targets finish-date slippage, and commercially-binding
milestones (COD, Practical Completion, Takeover) are the gates that
protect that date - excluding them would systematically miss the
methodology's primary concern.

Rule cascade (priority order): S1, S2, S3, H1, H2, default Parallel/P.
"""

from __future__ import annotations

import pandas as pd


# C2 keyword list. Module-level constant for inspection and testing.
COMMERCIALLY_BINDING_KEYWORDS: list[str] = [
    "COD",
    "Commercial Operation",
    "Ready for First Fire",
    "Ready for Hot Commissioning",
    "Practical Completion",
    "Takeover",
]

_REQUIRED_COLS: tuple[str, ...] = (
    "activity_id", "activity_name", "total_float_days",
    "critical_flag", "primary_constraint", "row_type",
)

_CLASSIFIABLE_ROW_TYPES: frozenset[str] = frozenset({"activity", "milestone"})


def classify_activities(p6_df: pd.DataFrame) -> pd.DataFrame:
    """Classify every activity and milestone row as Series, Hybrid, or Parallel.

    Parameters
    ----------
    p6_df : pd.DataFrame
        The DataFrame returned by ``src.sra.p6_reader.read_p6_schedule``.
        Must include columns: activity_id, activity_name, total_float_days,
        critical_flag, primary_constraint, row_type.

    Returns
    -------
    pd.DataFrame
        Copy of the input with two columns appended:
          - mode : one of Series, Hybrid, Parallel, NotApplicable.
          - rule : one of S1, S2, S3, H1, H2, P, NA.

        WBS summary rows and any other non-classifiable row_type get
        mode=NotApplicable, rule=NA.

    Raises
    ------
    ValueError
        If any required column is missing.
    """
    missing = [c for c in _REQUIRED_COLS if c not in p6_df.columns]
    if missing:
        raise ValueError(
            f"classify_activities: input DataFrame missing required "
            f"columns: {missing}"
        )

    out = p6_df.copy()
    modes: list[str] = []
    rules: list[str] = []
    for _, row in out.iterrows():
        if row["row_type"] not in _CLASSIFIABLE_ROW_TYPES:
            modes.append("NotApplicable")
            rules.append("NA")
            continue
        mode, rule = _classify_one(row)
        modes.append(mode)
        rules.append(rule)

    out["mode"] = modes
    out["rule"] = rules
    return out


def _is_commercially_binding(activity_id, activity_name) -> bool:
    """Return True if the row meets either C1 (CSE-KML prefix) or C2 (keyword)."""
    aid = _safe_str(activity_id)
    if aid.startswith("CSE-KML"):
        return True
    name = _safe_str(activity_name).strip().lower()
    if not name:
        return False
    for kw in COMMERCIALLY_BINDING_KEYWORDS:
        if kw.lower() in name:
            return True
    return False


def _classify_one(row: pd.Series) -> tuple[str, str]:
    """Classify a single classifiable row. Returns (mode, rule).

    Rule cascade: S1, S2, S3, H1, H2, default Parallel/P. A row hitting
    both S1 and S3 returns S1 because S1 is checked first. Rows with
    NaN total_float_days that are not P6-Critical fall through every
    rule and land in Parallel/P by cascade default.
    """
    if bool(row.get("critical_flag", False)):
        return "Series", "S1"

    tf_raw = row.get("total_float_days")
    if tf_raw is None or pd.isna(tf_raw):
        tf_zero = False
        tf_in_band = False
    else:
        tf_val = float(tf_raw)
        tf_zero = tf_val == 0.0
        tf_in_band = 0 < tf_val <= 20

    pc_raw = row.get("primary_constraint")
    pc_str = "" if pc_raw is None or pd.isna(pc_raw) else str(pc_raw).strip()
    pc_empty = pc_str == ""

    if tf_zero and pc_empty:
        return "Series", "S2"

    binding = _is_commercially_binding(
        row.get("activity_id"), row.get("activity_name")
    )

    if tf_zero and not pc_empty and binding:
        return "Series", "S3"

    if tf_in_band:
        return "Hybrid", "H1"

    if tf_zero and not pc_empty and not binding:
        return "Hybrid", "H2"

    return "Parallel", "P"


def _safe_str(v) -> str:
    """Coerce any cell value to a stripped string; NaN/None -> ''."""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v)
