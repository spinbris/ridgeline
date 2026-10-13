"""Beta-mode auto-mapper: expand pattern rules into per-(risk, activity) drivers.

The auto-mapper is the methodology-bearing module that makes the Stage 3
beta possible without a workshop. Each Time=Yes risk carries a strawman
pattern and a total-float threshold; the
auto-mapper turns those into the explicit ``affected_activity_ids`` list
the workshop would otherwise produce.

The two filters
---------------

**Filter A — pattern prefix.** An activity passes iff its
:attr:`~src.sra.cpm.graph.Activity.code` (XER ``task_code``) starts with
any of the rule's :attr:`~src.sra.cpm.risk_driver_schema.AutoMapperRule.pattern_prefixes`.
Strict ``str.startswith`` semantics — substring matches do not pass.

**Filter B — task-type ∩ float threshold.** Within filter A, an activity
is retained iff ``task_type == "TT_Task"`` (excludes WBS summaries
``"TT_WBS"`` and milestones ``"TT_Mile"`` / ``"TT_FinMile"``) **and**
``total_float_hours <= rule.float_threshold_hours``. Activities with
``total_float_hours is None`` are excluded — there is no implicit-zero
treatment. The default threshold is 480 working hours (60 working days
× 8 h/day).

The intersection becomes the risk's
:attr:`~src.sra.cpm.risk_driver_schema.RiskDriver.affected_activity_ids`,
sorted by ``(topo_index, code)`` for deterministic ordering.

Beta vs prod handoff
--------------------

The output of the auto-mapper is functionally identical in shape to the
eventual workshop output, so the handoff to ``prod`` mode is a
config-flip (the orchestrator picks one of two
``dict[risk_id, RiskDriver]`` factories), not a code change. The
``derived_at_run_time`` and ``workshop_validated`` provenance flags on
each :class:`RiskDriver` distinguish the two.

Audit trail
-----------

Each run writes one parquet row per ``(risk_id, activity_id)`` to
``outputs/runs/<date>/auto_risk_driver_assignments.parquet`` (the
SR9 parquet pattern reused for Stage 3). Risks whose expansion produced
zero activities still get one row with ``activity_id == ""`` so the
audit captures the evaluation — silent dropping would mask a pattern
that no longer matches anything in the schedule.

This module is project-agnostic — no project paths, file names, or
project codes appear here. The reusability invariant is locked by the
synthetic-graph tests in :mod:`tests.sra.cpm.test_auto_mapper`.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, fields
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from src.sra._pre_flight import MethodologyValidationError
from src.sra.cpm.risk_driver_schema import (
    AutoMapAuditRow,
    AutoMapperConfig,
    AutoMapperRule,
    GatingRelation,
    RiskDriver,
)

if TYPE_CHECKING:
    from src.sra.cpm.graph import ScheduleGraph

logger = logging.getLogger(__name__)


__all__ = [
    "expand_single_rule",
    "expand_auto_rules",
    "gate_relation",
    "write_audit_trail",
]


def gate_relation(
    gate_id: str,
    cohort_ids: tuple[str, ...],
    graph: "ScheduleGraph",
) -> GatingRelation:
    """Where ``gate_id`` sits relative to ``cohort_ids`` in ``graph``.

    GATECOHORT-01 (Director D-1, 10/09/2026, P-belongs). ``member`` if the
    gate is in the cohort; else ``downstream`` if any cohort member reaches
    it over successor links; else ``upstream`` if it reaches any cohort
    member; else ``unrelated``. Measured on the committed fixtures before
    the rule was written: wind's five out-of-cohort gates are three
    downstream (the milestone the work feeds) and two upstream (the
    milestone the work waits on); an unrelated gate appears in no
    committed register. Reachability is transitive and follows the built
    graph's ``successor_links`` / ``predecessor_links``, so it is the
    precedence the kernel will actually propagate delay along.
    """
    cohort = set(cohort_ids)
    if gate_id in cohort:
        return "member"
    acts = graph.activities

    def _reaches(start: set[str], forward: bool) -> bool:
        seen: set[str] = set()
        stack = list(start)
        while stack:
            node = stack.pop()
            links = acts[node].successor_links if forward else acts[node].predecessor_links
            for link in links:
                nxt = link.succ_id if forward else link.pred_id
                if nxt == gate_id:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return False

    if _reaches(cohort, forward=True):
        return "downstream"
    if _reaches(cohort, forward=False):
        return "upstream"
    return "unrelated"


# ---------------------------------------------------------------------------
# Rule expansion
# ---------------------------------------------------------------------------

def expand_single_rule(
    rule: AutoMapperRule,
    graph: "ScheduleGraph",
    config: AutoMapperConfig | None = None,
) -> RiskDriver:
    """Expand one :class:`AutoMapperRule` against the graph.

    Filter A: activities whose
    :attr:`~src.sra.cpm.graph.Activity.code` starts with any prefix in
    ``rule.pattern_prefixes``.

    Filter B: activities passing A whose
    ``task_type == "TT_Task"`` (when
    ``config.require_task_type_TT_Task`` is ``True``, the default) **and**
    ``total_float_hours <= rule.float_threshold_hours``. Activities with
    ``total_float_hours is None`` are excluded (no implicit-zero
    treatment).

    Order is deterministic: the resulting
    :attr:`RiskDriver.affected_activity_ids` tuple is sorted by
    ``(topo_index, code)``. The ``code`` tiebreaker handles activities
    that share the same topo position only via duplicate ids — which the
    graph already rejects — but is retained as a defensive secondary key
    so two activities with the same topo index would still produce a
    stable order.

    Emits WARNING via ``logging`` when:

    * the expanded list is empty (no activity matches both filters)
    * its size is below ``config.min_activities_warning_threshold`` (and
      not zero — zero is logged separately), unless the expansion is exactly
      the rule's own gating activity, which is the intended cohort (FW-25)
    * its size is above ``config.max_activities_warning_threshold``

    Parameters
    ----------
    rule : AutoMapperRule
        The per-risk rule.
    graph : ScheduleGraph
        Live schedule graph against which to evaluate the filters.
    config : AutoMapperConfig | None
        Universal knobs. Defaults to ``AutoMapperConfig()``.

    Returns
    -------
    RiskDriver
        With ``derived_at_run_time=True`` and
        ``workshop_validated=False``. Carries the rule's PERT params
        and probability verbatim.
    """
    cfg = config or AutoMapperConfig()

    # Filter A — pattern prefix match. Iterating activities.values() is
    # O(n_act) per rule; rules are O(n_risks) so total is O(n_risks ·
    # n_act). With n_risks≈15 and n_act≈2,000 that's negligible relative
    # to the per-iteration MC cost.
    filter_a = [
        a for a in graph.activities.values()
        if any(a.code.startswith(p) for p in rule.pattern_prefixes)
    ]

    # Filter B — task_type AND float threshold. Activities with
    # ``total_float_hours is None`` (typically milestones whose float was
    # not computed by P6) are excluded — no implicit-zero treatment.
    filter_b = [
        a for a in filter_a
        if (
            (not cfg.require_task_type_TT_Task or a.task_type == "TT_Task")
            and a.total_float_hours is not None
            and a.total_float_hours <= rule.float_threshold_hours
        )
    ]

    # Deterministic ordering: by topo position, then code as tiebreaker.
    # The topo index lookup falls back to len(topo_order) for ids absent
    # from topo_order — guarded by ScheduleGraph.__post_init__ but kept
    # defensive here so a future graph variant cannot silently shuffle
    # the audit-trail row order.
    topo_index = {act_id: i for i, act_id in enumerate(graph.topo_order)}
    filter_b.sort(key=lambda a: (topo_index.get(a.id, len(graph.topo_order)), a.code))

    affected = tuple(a.id for a in filter_b)

    # GATECOHORT-01 — the gate's relation to the cohort it was declared
    # for. Computed here because every route that expands a rule passes
    # through this function, so one seam covers the binding route, the
    # register route and the showcase scripts. An empty cohort is left to
    # the zero-expansion warning below and the SR16 refusal on the binding
    # route; a relation against nothing would only mislead.
    relation: GatingRelation | None = None
    if rule.injection_method == "discrete_event_additive_days" and rule.gating_activity_id:
        if not affected:
            # Director, 10/09/2026, on the GATECOHORT-01 review's BLOCKER:
            # refuse the empty cohort on every route. The kernel skips an
            # empty-cohort driver before the discrete write
            # (risk_injection.py:301), so a discrete rule whose prefix
            # matched nothing reached it carrying a gate and lost its whole
            # delay silently. The binding route's SR16 refusal used to catch
            # this only because it ignored the declared gate and auto-picked;
            # the register route never caught it.
            gate = graph.activities.get(rule.gating_activity_id)
            gate_code = gate.code if gate is not None else rule.gating_activity_id
            raise MethodologyValidationError(
                f"Risk {rule.risk_id!r}: prefix {', '.join(rule.pattern_prefixes)!r} binds "
                f"no activity in the current .xer (task type and float filter applied), yet "
                f"the row declares Gating_Activity_ID {gate_code!r} under "
                f"'discrete_event_additive_days'. The kernel skips a driver with no cohort "
                f"before it writes to the gate, so this risk's delay would vanish from the "
                f"schedule headline with nothing on screen. Widen the register's "
                f"Prefix_List or correct the .xer baseline this register targets."
            )
        relation = gate_relation(rule.gating_activity_id, affected, graph)
        if relation == "unrelated":
            gate = graph.activities.get(rule.gating_activity_id)
            gate_code = gate.code if gate is not None else rule.gating_activity_id
            raise MethodologyValidationError(
                f"Risk {rule.risk_id!r}: Gating_Activity_ID {gate_code!r} is unrelated to "
                f"the cohort bound by prefix {', '.join(rule.pattern_prefixes)!r} - it is "
                f"neither a member of it, nor upstream of it, nor downstream of it in the "
                f".xer precedence. Under 'discrete_event_additive_days' the whole sampled "
                f"delay is written to that one activity, so an unrelated gate moves the "
                f"schedule headline on an activity the risk does not touch. Correct the "
                f"register's Gating_Activity_ID or its Prefix_List; the engine does not "
                f"choose for you."
            )

    # Warnings — explicit messages with risk_id and pattern_id for grep.
    n = len(affected)
    if n == 0:
        logger.warning(
            "auto_mapper: rule %s (pattern %s) expanded to ZERO activities",
            rule.risk_id, rule.pattern_id,
        )
    elif rule.gating_activity_id and affected == (rule.gating_activity_id,):
        # FW-25: the rule binds its own gating activity and nothing else - one activity is the
        # intended cohort, not a thin match. Warning here put 72 identical lines on a correct
        # period run and taught the reader to ignore this tool's warnings.
        logger.debug(
            "auto_mapper: rule %s (pattern %s) binds its gating activity alone",
            rule.risk_id, rule.pattern_id,
        )
    elif n < cfg.min_activities_warning_threshold:
        logger.warning(
            "auto_mapper: rule %s (pattern %s) expanded to %d activities "
            "(< %d threshold)",
            rule.risk_id, rule.pattern_id, n, cfg.min_activities_warning_threshold,
        )
    elif n > cfg.max_activities_warning_threshold:
        logger.warning(
            "auto_mapper: rule %s (pattern %s) expanded to %d activities "
            "(> %d threshold)",
            rule.risk_id, rule.pattern_id, n, cfg.max_activities_warning_threshold,
        )

    return RiskDriver(
        risk_id=rule.risk_id,
        affected_activity_ids=affected,
        injection_method=rule.injection_method,
        opt_pert=rule.opt_pert,
        ml_pert=rule.ml_pert,
        pess_pert=rule.pess_pert,
        probability=rule.probability,
        pattern_id=rule.pattern_id,
        derived_at_run_time=True,
        workshop_validated=False,
        # SR10.A — copy the rule's Mode classification onto the driver.
        # When the binding does not populate Mode on the rule (default
        # "Series"), the driver inherits the Series default and the
        # kernel's Mode-multiplier lookup yields 1.0 (no behaviour change).
        mode=rule.mode,
        # SR12 — copy the rule's gating activity id verbatim. ``None``
        # for non-discrete-event methods; required (validated by the
        # binding's pre-flight) for discrete_event_additive_days.
        gating_activity_id=rule.gating_activity_id,
        gating_relation=relation,
    )


def expand_auto_rules(
    rules: dict[str, AutoMapperRule],
    graph: "ScheduleGraph",
    config: AutoMapperConfig | None = None,
) -> dict[str, RiskDriver]:
    """Expand a dict of rules into a dict of :class:`RiskDriver`s.

    Output dict iterates in the same order as ``rules`` (Python 3.7+
    insertion-order guarantee). Rules whose expansion produced zero
    activities are **retained** with empty ``affected_activity_ids`` so
    the audit trail records the evaluation — silent dropping would mask
    a methodology issue.

    Parameters
    ----------
    rules : dict[str, AutoMapperRule]
        ``{risk_id: rule}``.
    graph : ScheduleGraph
        Live schedule graph.
    config : AutoMapperConfig | None
        Universal knobs.

    Returns
    -------
    dict[str, RiskDriver]
        Same key set as ``rules``; values are the expanded drivers.
    """
    cfg = config or AutoMapperConfig()
    return {
        risk_id: expand_single_rule(rule, graph, cfg)
        for risk_id, rule in rules.items()
    }


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def _audit_rows_for_driver(driver: RiskDriver) -> list[AutoMapAuditRow]:
    """One :class:`AutoMapAuditRow` per ``(risk_id, activity_id)``.

    Risks with empty ``affected_activity_ids`` produce one row with
    ``activity_id == ""`` so the audit captures the evaluation. The
    pattern_id falls back to the empty string when the driver has no
    pattern provenance (workshop-direct construction).
    """
    pattern_id = driver.pattern_id if driver.pattern_id is not None else ""
    gating_id = driver.gating_activity_id or ""
    if not driver.affected_activity_ids:
        return [
            AutoMapAuditRow(
                risk_id=driver.risk_id,
                activity_id="",
                pattern_id=pattern_id,
                injection_method=driver.injection_method,
                opt_pert=driver.opt_pert,
                ml_pert=driver.ml_pert,
                pess_pert=driver.pess_pert,
                probability=driver.probability,
                derived_at_run_time=driver.derived_at_run_time,
                workshop_validated=driver.workshop_validated,
                mode=driver.mode,
                gating_activity_id=gating_id,
            )
        ]
    return [
        AutoMapAuditRow(
            risk_id=driver.risk_id,
            activity_id=act_id,
            pattern_id=pattern_id,
            injection_method=driver.injection_method,
            opt_pert=driver.opt_pert,
            ml_pert=driver.ml_pert,
            pess_pert=driver.pess_pert,
            probability=driver.probability,
            derived_at_run_time=driver.derived_at_run_time,
            workshop_validated=driver.workshop_validated,
            mode=driver.mode,
            gating_activity_id=gating_id,
            gating_relation=driver.gating_relation,
        )
        for act_id in driver.affected_activity_ids
    ]


def write_audit_trail(
    drivers: dict[str, RiskDriver],
    output_path: Path | str,
) -> Path:
    """Write the per-(risk, activity) assignment table to parquet.

    Schema is derived from
    :class:`~src.sra.cpm.risk_driver_schema.AutoMapAuditRow` — the
    column order matches ``dataclasses.fields(AutoMapAuditRow)``
    exactly. One row per ``(risk_id, activity_id)``; risks with
    zero-expansion produce one row with ``activity_id == ""``.

    Parameters
    ----------
    drivers : dict[str, RiskDriver]
        Output of :func:`expand_auto_rules`.
    output_path : Path | str
        Destination parquet path. Parent directory is created if
        missing (``parents=True, exist_ok=True``).

    Returns
    -------
    Path
        The absolute path written, for the caller to log or hash.
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    columns = [f.name for f in fields(AutoMapAuditRow)]
    rows: list[AutoMapAuditRow] = []
    for driver in drivers.values():
        rows.extend(_audit_rows_for_driver(driver))

    if rows:
        df = pd.DataFrame([asdict(r) for r in rows], columns=columns)
    else:
        # Empty-input edge case — preserve column schema so readers
        # don't have to special-case zero-driver runs.
        df = pd.DataFrame({c: [] for c in columns})

    df.to_parquet(output_path, index=False)

    n_zero = sum(
        1 for d in drivers.values() if not d.affected_activity_ids
    )
    if n_zero:
        logger.warning(
            "write_audit_trail: %d rule(s) had zero-expansion; "
            "recorded with activity_id='' in %s",
            n_zero, output_path,
        )

    return output_path
