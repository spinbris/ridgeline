"""Schedule-graph construction from parsed XER tables (project-agnostic).

Public surface
--------------
* :func:`build_schedule_graph` — turn ``parse_xer`` output into a
  validated :class:`~src.sra.cpm.graph.ScheduleGraph`, with Kahn's
  topological sort and explicit cycle detection.

Algorithm
---------
1. Validate the required XER tables (``TASK``, ``TASKPRED``,
   ``CALENDAR``) are present and contain the columns this builder
   reads.
2. Build the project-default :class:`~src.sra.cpm.calendar.Calendar`
   from the XER tables (or use an explicitly-passed ``calendar``).
3. Construct one :class:`~src.sra.cpm.graph.Activity` per ``TASK`` row
   (skipping rows with a null ``task_id``).
4. Construct one :class:`~src.sra.cpm.graph.Link` per ``TASKPRED`` row.
   The ``pred_type`` column is mapped element-wise from XER
   (``PR_FS`` / ``PR_SS`` / ``PR_FF`` / ``PR_SF``) to
   :data:`~src.sra.cpm.graph.LinkType` (``FS`` / ``SS`` / ``FF`` /
   ``SF``); any other value raises :class:`ValueError`. Self-loops
   (``pred_id == succ_id``) and orphan references (an id missing from
   ``TASK``) raise immediately with the offending id(s) named.
5. Run Kahn's topological-sort algorithm. If any activity cannot be
   ordered (because it sits inside a cycle), raise
   :class:`ValueError` listing the ids involved.

This module is project-agnostic — no project paths, file names, or
project codes appear here.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from src.sra.cpm.calendar import Calendar, build_default_calendar
from src.sra.cpm.graph import Activity, Link, LinkType, ScheduleGraph

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


#: Mapping from XER ``TASKPRED.pred_type`` values to the
#: :data:`~src.sra.cpm.graph.LinkType` strings stored on :class:`Link`.
_PRED_TYPE_MAP: dict[str, LinkType] = {
    "PR_FS": "FS",
    "PR_SS": "SS",
    "PR_FF": "FF",
    "PR_SF": "SF",
}


class DuplicateTaskCodeError(ValueError):
    """Two ``TASK`` rows share a ``task_code`` (GATECOHORT-01, Director D-3).

    The register names activities by ``task_code``; both ``code_to_id``
    builders in ``stage3_config.py`` are dict
    comprehensions where the last duplicate wins, so a duplicated code makes
    every later code lookup ambiguous — a declared gate could land on the
    wrong activity and pass every check. Refused at graph build, where the
    codes are first seen together.
    """


#: Columns this builder reads from each table. Independent of (and
#: narrower than) ``xer_reader._REQUIRED_COLUMNS`` — we only validate
#: what we actually consume here.
_BUILDER_REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "TASK": (
        "task_id",
        "task_code",
        "task_name",
        "task_type",
        "target_drtn_hr_cnt",
        "total_float_hr_cnt",
        "clndr_id",
    ),
    "TASKPRED": (
        "task_id",
        "pred_task_id",
        "pred_type",
        "lag_hr_cnt",
    ),
    "CALENDAR": (
        "clndr_id",
        "clndr_name",
        "default_flag",
        "day_hr_cnt",
        "week_hr_cnt",
    ),
}


def build_schedule_graph(
    tables: dict[str, pd.DataFrame],
    calendar: Calendar | None = None,
) -> ScheduleGraph:
    """Build a :class:`ScheduleGraph` from parsed XER tables.

    Parameters
    ----------
    tables : dict[str, pandas.DataFrame]
        Output of :func:`src.sra.cpm.xer_reader.parse_xer`. Must contain
        ``TASK``, ``TASKPRED``, and ``CALENDAR``.
    calendar : Calendar | None
        If ``None``, builds a project-default :class:`Calendar` from the
        ``CALENDAR`` (and optional ``NONWORK``) tables via
        :func:`src.sra.cpm.calendar.build_default_calendar`. Pass an
        explicit :class:`Calendar` to override (test fixtures, future
        per-project tuning).

    Returns
    -------
    ScheduleGraph
        With ``topo_order`` computed and validated acyclic.

    Raises
    ------
    ValueError
        If a required table or column is missing; if a ``TASKPRED.pred_type``
        is not one of the canonical four; if a self-loop or precedence
        cycle is detected (the message lists the activity ids involved).
    KeyError
        If a ``TASKPRED`` row references a ``task_id`` not present in
        ``TASK``.
    """
    _validate_input_columns(tables)

    if calendar is None:
        calendar = build_default_calendar(tables)

    activities = _build_activities(tables["TASK"])
    links = _build_links(tables["TASKPRED"], known_ids=set(activities.keys()))

    # Distribute links across each activity's predecessor/successor lists.
    for link in links:
        activities[link.pred_id].successor_links.append(link)
        activities[link.succ_id].predecessor_links.append(link)

    topo_order = _topological_sort(activities, links)

    return ScheduleGraph(
        activities=activities,
        links=links,
        topo_order=topo_order,
        project_default_calendar=calendar,
    )


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------

def _validate_input_columns(tables: dict[str, pd.DataFrame]) -> None:
    """Check that ``tables`` carries the columns this builder reads.

    Raises :class:`ValueError` listing every missing item in one pass.
    """
    issues: list[str] = []
    for table_name, required_columns in _BUILDER_REQUIRED_COLUMNS.items():
        if table_name not in tables:
            issues.append(f"missing table: {table_name}")
            continue
        df = tables[table_name]
        missing = [c for c in required_columns if c not in df.columns]
        if missing:
            issues.append(
                f"table {table_name} missing column(s): " + ", ".join(missing)
            )
    if issues:
        raise ValueError(
            "build_schedule_graph input validation failed:\n  - "
            + "\n  - ".join(issues)
        )


def _build_activities(task_df: pd.DataFrame) -> dict[str, Activity]:
    """One :class:`Activity` per ``TASK`` row with a non-null ``task_id``."""
    if task_df.empty:
        return {}

    # Preserve task_df without mutating; project the columns we need and
    # drop rows with a null task_id (defensive — Primavera always emits
    # task_id, but synthetic exports may skip it).
    columns_used = list(_BUILDER_REQUIRED_COLUMNS["TASK"])
    df = task_df[columns_used].copy()
    df = df[df["task_id"].notna()]

    activities: dict[str, Activity] = {}
    duplicates: list[str] = []
    # itertuples is the fast row iterator — avoids the per-row dict
    # overhead of iterrows while still letting us construct one Activity
    # per row. This is idiomatic for "DataFrame in, dataclass out".
    for row in df.itertuples(index=False, name=None):
        (
            task_id_raw,
            task_code,
            task_name,
            task_type,
            target_drtn,
            total_float,
            clndr_id,
        ) = row
        activity_id = _to_id_str(task_id_raw)

        if activity_id in activities:
            duplicates.append(activity_id)
            continue

        activities[activity_id] = Activity(
            id=activity_id,
            code="" if pd.isna(task_code) else str(task_code),
            name="" if pd.isna(task_name) else str(task_name),
            task_type="" if pd.isna(task_type) else str(task_type),
            original_duration_hours=_to_float(target_drtn, default=0.0),
            total_float_hours=_to_optional_float(total_float),
            calendar_id=_to_optional_id_str(clndr_id),
        )

    if duplicates:
        # Duplicate task_ids in TASK are an XER export error, not a
        # schedule-graph cycle. Surface clearly.
        logger.warning(
            "TASK contains %d duplicate task_id(s); first occurrence wins. "
            "Examples: %s",
            len(duplicates),
            duplicates[:5],
        )

    # GATECOHORT-01 (Director D-3): a task_code shared by two activities
    # is refused, not warned - the register addresses activities by code.
    # Blank codes are not addressable and are left alone.
    seen_codes: dict[str, str] = {}
    duplicate_codes: list[str] = []
    for act in activities.values():
        if not act.code:
            continue
        if act.code in seen_codes:
            duplicate_codes.append(act.code)
        seen_codes[act.code] = act.id
    if duplicate_codes:
        shown = sorted(set(duplicate_codes))
        raise DuplicateTaskCodeError(
            f"TASK carries {len(shown)} task_code(s) shared by more than one activity: "
            f"{shown[:5]}. The register names activities by task_code, so a shared code "
            f"makes every code lookup ambiguous (a declared Gating_Activity_ID could land "
            f"on either). Correct the .xer export or the duplicate codes before running."
        )

    return activities


def _build_links(taskpred_df: pd.DataFrame, *, known_ids: set[str]) -> list[Link]:
    """One :class:`Link` per ``TASKPRED`` row, validated and deduplicated."""
    if taskpred_df.empty:
        return []

    columns_used = list(_BUILDER_REQUIRED_COLUMNS["TASKPRED"])
    df = taskpred_df[columns_used].copy()
    # Vectorised pred_type validation: any value not in the map is an error.
    valid_mask = df["pred_type"].isin(list(_PRED_TYPE_MAP.keys()))
    if not valid_mask.all():
        bad = sorted(set(df.loc[~valid_mask, "pred_type"].astype(str).tolist()))
        raise ValueError(
            "TASKPRED.pred_type contains unrecognised value(s): "
            f"{bad}. Expected subset of {sorted(_PRED_TYPE_MAP.keys())}."
        )

    # Vectorised null-id check before per-row construction.
    null_id_mask = df["task_id"].isna() | df["pred_task_id"].isna()
    if null_id_mask.any():
        n_null = int(null_id_mask.sum())
        logger.warning(
            "TASKPRED contains %d row(s) with a null task_id or pred_task_id; "
            "these rows are skipped",
            n_null,
        )
        df = df[~null_id_mask]

    if df.empty:
        return []

    # Stringify ids vectorised.
    succ_ids = df["task_id"].map(_to_id_str)
    pred_ids = df["pred_task_id"].map(_to_id_str)

    # Self-loop detection (vectorised).
    self_loop_mask = (succ_ids == pred_ids).to_numpy()
    if self_loop_mask.any():
        offenders = sorted(set(succ_ids[self_loop_mask].tolist()))
        raise ValueError(
            "TASKPRED contains self-loop link(s) on activity id(s): "
            + ", ".join(offenders)
        )

    # Orphan-id detection (vectorised).
    pred_unknown = ~pred_ids.isin(known_ids)
    succ_unknown = ~succ_ids.isin(known_ids)
    orphan_mask = (pred_unknown | succ_unknown).to_numpy()
    if orphan_mask.any():
        bad_pred = sorted(set(pred_ids[pred_unknown].tolist()))
        bad_succ = sorted(set(succ_ids[succ_unknown].tolist()))
        parts: list[str] = []
        if bad_pred:
            parts.append("unknown pred_task_id(s): " + ", ".join(bad_pred))
        if bad_succ:
            parts.append("unknown task_id(s): " + ", ".join(bad_succ))
        raise KeyError("TASKPRED references " + "; ".join(parts))

    # Map pred_type once.
    link_types = df["pred_type"].map(_PRED_TYPE_MAP).to_numpy()
    lag_hours = df["lag_hr_cnt"].astype(np.float64).fillna(0.0).to_numpy()
    pred_arr = pred_ids.to_numpy()
    succ_arr = succ_ids.to_numpy()

    # Build Link objects from pre-extracted numpy arrays. Per-row
    # overhead here is the construction of a frozen dataclass, which
    # cannot be eliminated without structural changes; on the 5,982-row
    # a production-sized TASKPRED this measures in tens of ms.
    links: list[Link] = []
    seen: set[tuple[str, str, LinkType, float]] = set()
    n = len(df)
    for i in range(n):
        key = (str(pred_arr[i]), str(succ_arr[i]), link_types[i], float(lag_hours[i]))
        if key in seen:
            continue
        seen.add(key)
        links.append(
            Link(
                pred_id=key[0],
                succ_id=key[1],
                link_type=key[2],
                lag_hours=key[3],
            )
        )

    return links


def _topological_sort(
    activities: dict[str, Activity], links: list[Link]
) -> list[str]:
    """Kahn's algorithm. Raises :class:`ValueError` on cycles.

    The error message lists the activity ids that remain unprocessed —
    these are the ids that sit in (or downstream of) one or more cycles.
    """
    in_degree: dict[str, int] = {aid: 0 for aid in activities}
    for link in links:
        in_degree[link.succ_id] += 1

    # Process roots in insertion order so the topological order is
    # stable and deterministic for a given input.
    queue: deque[str] = deque(aid for aid in activities if in_degree[aid] == 0)
    topo_order: list[str] = []

    while queue:
        node = queue.popleft()
        topo_order.append(node)
        for link in activities[node].successor_links:
            in_degree[link.succ_id] -= 1
            if in_degree[link.succ_id] == 0:
                queue.append(link.succ_id)

    if len(topo_order) != len(activities):
        unprocessed = sorted(aid for aid, deg in in_degree.items() if deg > 0)
        # Cap the list in the message to keep it readable on huge graphs.
        sample = unprocessed[:10]
        suffix = "" if len(unprocessed) <= 10 else f" (+{len(unprocessed) - 10} more)"
        raise ValueError(
            f"Precedence cycle detected: {len(unprocessed)} activity id(s) "
            f"could not be ordered. Involved id(s): "
            + ", ".join(sample)
            + suffix
        )

    return topo_order


# ----------------------------------------------------------------------
# Type-coercion helpers
# ----------------------------------------------------------------------

def _to_id_str(value: object) -> str:
    """Convert a nullable-int / int / str id to a clean string id.

    Pandas' ``Int64`` dtype renders ints as ``"42"``; floats render as
    ``"42.0"``; this helper normalises so an integer-valued id round-trips
    as ``"42"`` regardless of source dtype.
    """
    if value is None or pd.isna(value):
        # Caller is expected to have filtered nulls already; surfacing a
        # placeholder rather than silently swallowing keeps bugs visible.
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, np.integer):
        return str(int(value))
    return str(value)


def _to_optional_id_str(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return _to_id_str(value)


def _to_float(value: object, *, default: float) -> float:
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
