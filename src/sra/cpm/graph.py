"""Schedule graph data model (project-agnostic).

Pure dataclasses describing the inputs to the CPM kernel (Beta-03):

* :class:`Link` — an immutable precedence edge between two activities
  (FS / SS / FF / SF, with optional lag in hours).
* :class:`Activity` — a node carrying static metadata (id, code, name,
  task_type, original duration, calendar binding, plus the activity's
  predecessor and successor links).
* :class:`ScheduleGraph` — the top-level container: a dict of activities,
  a flat list of links, a topological order, and the project-default
  :class:`~src.sra.cpm.calendar.Calendar`.

Per-iteration CPM outputs (early start, early finish, late start, late
finish, total float) are deliberately **not** stored on
:class:`Activity`. Those live in per-iteration arrays produced by the
kernel; :class:`Activity` is the input to the kernel, not the output.

This module is project-agnostic — no project paths, file names, or
project codes appear here. The reusability invariant is locked by the
synthetic-graph tests in :mod:`tests.sra.cpm.test_graph`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from src.sra.cpm.calendar import Calendar


LinkType = Literal["FS", "SS", "FF", "SF"]

#: The four canonical XER precedence types, in the form returned by the
#: reader (i.e. without the ``PR_`` prefix). :class:`Link` validates
#: against this set.
_VALID_LINK_TYPES: frozenset[str] = frozenset({"FS", "SS", "FF", "SF"})


@dataclass(frozen=True)
class Link:
    """Precedence link between two activities.

    Attributes
    ----------
    pred_id : str
        ``task_id`` of the predecessor activity (XER
        ``TASKPRED.pred_task_id``).
    succ_id : str
        ``task_id`` of the successor activity (XER ``TASKPRED.task_id``).
    link_type : LinkType
        Finish-to-Start (``"FS"``), Start-to-Start (``"SS"``),
        Finish-to-Finish (``"FF"``), or Start-to-Finish (``"SF"``).
    lag_hours : float
        Lag in hours; negative values are leads. Sourced from
        ``TASKPRED.lag_hr_cnt``.

    Raises
    ------
    ValueError
        If ``link_type`` is not one of the four canonical values, or if
        ``pred_id`` / ``succ_id`` is empty.
    """

    pred_id: str
    succ_id: str
    link_type: LinkType
    lag_hours: float

    def __post_init__(self) -> None:
        if not self.pred_id:
            raise ValueError("Link.pred_id must be non-empty")
        if not self.succ_id:
            raise ValueError("Link.succ_id must be non-empty")
        if self.link_type not in _VALID_LINK_TYPES:
            raise ValueError(
                f"Link.link_type {self.link_type!r} is not one of "
                f"{sorted(_VALID_LINK_TYPES)}"
            )


@dataclass
class Activity:
    """Static activity data — duration and links only.

    Attributes
    ----------
    id : str
        ``TASK.task_id``. Used as the dictionary key in
        :class:`ScheduleGraph` and in topological ordering.
    code : str
        ``TASK.task_code`` — the human-readable WBS code (e.g. ``A100``).
    name : str
        ``TASK.task_name``.
    task_type : str
        ``TASK.task_type`` (``"TT_Task"``, ``"TT_Mile"``, ``"TT_FinMile"``,
        ...). Forwarded as a string; the kernel decides which types
        contribute to duration.
    original_duration_hours : float
        ``TASK.target_drtn_hr_cnt``. Milestones are zero.
    total_float_hours : float | None
        ``TASK.total_float_hr_cnt``; may be ``None`` for milestones or
        for activities whose float has not yet been calculated by P6.
    calendar_id : str | None
        ``TASK.clndr_id``. Informational only during beta — a single
        project-default calendar is used per Beta-00.5; full per-activity
        calendar resolution is deferred to SR-S3-Prod.
    predecessor_links : list[Link]
        Inbound edges (this activity is the successor).
    successor_links : list[Link]
        Outbound edges (this activity is the predecessor).
    """

    id: str
    code: str
    name: str
    task_type: str
    original_duration_hours: float
    total_float_hours: float | None
    calendar_id: str | None
    predecessor_links: list[Link] = field(default_factory=list)
    successor_links: list[Link] = field(default_factory=list)


@dataclass
class ScheduleGraph:
    """A topologically-sorted activity graph with calendar binding.

    Attributes
    ----------
    activities : dict[str, Activity]
        Keyed by :attr:`Activity.id` (== ``task_id``).
    links : list[Link]
        All precedence links, deduplicated by
        ``(pred_id, succ_id, link_type, lag_hours)``.
    topo_order : list[str]
        Activity ids in a valid topological order; used by the kernel for
        forward-pass iteration. Length equals ``len(activities)`` and is
        a permutation of ``activities.keys()``.
    project_default_calendar : Calendar
        The calendar all activities use during beta. Per Beta-00.5 a
        single project-default calendar is in force; per-activity
        calendar resolution is deferred to SR-S3-Prod.

    Raises
    ------
    ValueError
        If the graph integrity is violated (``topo_order`` length mismatch,
        topo entry references a missing activity, or a link references a
        ``pred_id`` / ``succ_id`` not in :attr:`activities`).
    """

    activities: dict[str, Activity]
    links: list[Link]
    topo_order: list[str]
    project_default_calendar: "Calendar"

    def __post_init__(self) -> None:
        ids = set(self.activities.keys())

        if len(self.topo_order) != len(ids):
            raise ValueError(
                "ScheduleGraph.topo_order length "
                f"({len(self.topo_order)}) != len(activities) ({len(ids)})"
            )
        if set(self.topo_order) != ids:
            missing_in_topo = ids - set(self.topo_order)
            unknown_in_topo = set(self.topo_order) - ids
            parts: list[str] = []
            if missing_in_topo:
                parts.append(
                    "activities missing from topo_order: "
                    + ", ".join(sorted(missing_in_topo)[:5])
                )
            if unknown_in_topo:
                parts.append(
                    "topo_order references unknown ids: "
                    + ", ".join(sorted(unknown_in_topo)[:5])
                )
            raise ValueError("; ".join(parts))

        for link in self.links:
            if link.pred_id not in ids:
                raise ValueError(
                    f"Link references unknown pred_id {link.pred_id!r}"
                )
            if link.succ_id not in ids:
                raise ValueError(
                    f"Link references unknown succ_id {link.succ_id!r}"
                )
