"""Schema dataclasses for the auto-mapper and risk-injection layers.

Defines the shared vocabulary that
:mod:`src.sra.cpm.auto_mapper` and :mod:`src.sra.cpm.risk_injection`
exchange. Keeping the schema in its own module decouples auto-mapper
output (beta) from the eventual workshop-output (prod) input — both
populate the same :class:`RiskDriver` shape, distinguished only by the
``derived_at_run_time`` and ``workshop_validated`` provenance flags.

The five public exports
-----------------------

* :data:`InjectionMethod` — ``Literal["additive_pert_days",
  "multiplicative_pert_factor"]``. Drives the conversion in
  :func:`src.sra.cpm.risk_injection.sample_risk_deltas`.
* :class:`AutoMapperRule` — beta-mode per-risk rule for algorithmic
  expansion against a :class:`~src.sra.cpm.graph.ScheduleGraph`.
* :class:`RiskDriver` — the resolved per-(risk, activity) assignment.
  Auto-mapper output (beta) and workshop output (prod) share this
  shape.
* :class:`AutoMapperConfig` — universal knobs (default float threshold,
  task-type filter, warning thresholds).
* :class:`AutoMapAuditRow` — one parquet row per ``(risk_id,
  activity_id)`` written by
  :func:`src.sra.cpm.auto_mapper.write_audit_trail`.

This module is project-agnostic — no project paths, file names, or
project codes appear here. The reusability invariant is locked by the
synthetic-graph tests in
:mod:`tests.sra.cpm.test_risk_driver_schema`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


#: Injection mechanics. Pre-SR12 supports two values:
#:
#: * ``"additive_pert_days"`` — legacy additive-broadcast: PERT days
#:   converted to working hours via the project-default calendar's
#:   ``working_hours_per_day`` and broadcast onto every affected
#:   activity. This is the Stage 2.5 baseline mechanic. Kept as the
#:   fallback when a strawman row has ``injection_method`` null/blank
#:   so Stage 2.5 reproducibility is bit-for-bit preserved.
#: * ``"multiplicative_pert_factor"`` — dimensionless factor applied
#:   per-activity against
#:   :attr:`~src.sra.cpm.graph.Activity.original_duration_hours`.
#:
#: SR12 adds two methodology-bearing mechanics that the workshop opts
#: each Time=Yes risk into per the deep research note (14 May 2026):
#:
#: * ``"discrete_event_additive_days"`` — single-event additive: PERT
#:   magnitude written to ONE column (the
#:   :attr:`RiskDriver.gating_activity_id`), not broadcast across the
#:   bound cohort. Methodologically consistent with AACE 57R-09 /
#:   Hulett / CEGN 3A §3.1-§3.3 for single-event discrete delay risks.
#: * ``"productivity_multiplicative_factor"`` — workshop-facing synonym
#:   for ``"multiplicative_pert_factor"``; dispatched to the same
#:   broadcast multiplicative branch. The two names exist so the
#:   strawman can spell out the methodology choice while the kernel
#:   keeps a single per-risk Bernoulli + PERT + broadcast code path.
InjectionMethod = Literal[
    "additive_pert_days",
    "multiplicative_pert_factor",
    "discrete_event_additive_days",
    "productivity_multiplicative_factor",
]
#: RS-D-6: the same three names as a tuple, for readers that validate a register value.
INJECTION_METHODS: tuple[str, ...] = ("additive_pert_days", "discrete_event_additive_days",
                                     "productivity_multiplicative_factor")


#: The three Mode classifications consumed by the schedule arm.
#: ``Series`` is full-impact (multiplier 1.0 against the agreed
#: methodology constant in the register's Mode multiplier grid (RS-D-3));
#: ``Hybrid`` is partial (0.5); ``Parallel`` is zero (0.0). SR10.A
#: surfaces Mode at the schedule-arm CPM driver level so the
#: orchestrator's ``criticality_measurement_mode="mode_independent"``
#: pass can override the multiplier to 1.0 per AACE 65R-11 §5.4. Default
#: ``"Series"`` preserves pre-SR10.A behaviour for synthetic-test
#: callers that construct :class:`RiskDriver` without specifying a Mode.
RiskMode = Literal["Series", "Hybrid", "Parallel"]

#: GATECOHORT-01 (Director D-1, 10/09/2026, P-belongs) — where a discrete-event
#: gate sits relative to its rule's bound cohort. ``member`` is inside it;
#: ``downstream`` is the milestone the cohort's work feeds; ``upstream`` is
#: the milestone the cohort's work waits on. ``unrelated`` is refused at
#: expansion and never reaches a driver.
GatingRelation = Literal["member", "upstream", "downstream", "unrelated"]


def _validate_pert_and_probability(
    cls_name: str,
    opt: float,
    ml: float,
    pess: float,
    probability: float,
) -> None:
    """Validate PERT triple ordering and probability range.

    Catches workshop / binding-layer data-entry errors at construction
    time. Without this guard, an inverted PERT triple would propagate
    silently to NaN deltas (negative Beta-distribution shape parameters
    return NaN from ``scipy.stats.beta.ppf``); a probability outside
    ``[0, 1]`` would produce all-True or all-False fires without
    diagnostic.
    """
    if not (0.0 <= probability <= 1.0):
        raise ValueError(
            f"{cls_name}.probability must be in [0, 1]; got {probability}"
        )
    # Allow opt == ml == pess (degenerate PERT — a constant magnitude).
    if not (opt <= ml <= pess):
        raise ValueError(
            f"{cls_name}: PERT triple must satisfy opt <= ml <= pess; "
            f"got opt={opt}, ml={ml}, pess={pess}"
        )


def _validate_mode(cls_name: str, mode: str) -> None:
    """Reject unknown Mode strings at construction time.

    The kernel looks up ``mode_multipliers[driver.mode]`` per iteration;
    an unknown string would raise mid-batch and the offending risk_id
    would not be in the error context. Catching the typo here surfaces
    it at the binding layer with a clear list of allowed values.
    """
    if mode not in ("Series", "Hybrid", "Parallel"):
        raise ValueError(
            f"{cls_name}.mode must be one of "
            f"('Series', 'Hybrid', 'Parallel'); got {mode!r}"
        )


@dataclass(frozen=True)
class AutoMapperRule:
    """Beta-mode per-risk rule for algorithmic activity-list expansion.

    Consumed by :func:`src.sra.cpm.auto_mapper.expand_single_rule`
    against a :class:`~src.sra.cpm.graph.ScheduleGraph` to produce a
    :class:`RiskDriver`. Project-agnostic — the ``pattern_prefixes`` and
    ``float_threshold_hours`` come from the project's binding layer
    (Beta-06 wires the strawman ``Risk_Activity_Patterns`` sheet into
    these fields).

    Attributes
    ----------
    risk_id : str
        Risk identifier (e.g. ``"R013"``). Carried verbatim onto the
        resulting :class:`RiskDriver`.
    pattern_id : str
        Pattern identifier from the strawman (e.g. ``"P01"``); recorded
        on the audit trail for traceability between expanded rules and
        the source pattern catalogue.
    pattern_prefixes : tuple[str, ...]
        WBS / activity-id prefixes (e.g. ``("10.C", "20.C.")``). An
        activity passes filter A iff
        :attr:`~src.sra.cpm.graph.Activity.code` starts with any prefix.
    float_threshold_hours : float
        Maximum total float (working hours) for filter B. Default in
        :class:`AutoMapperConfig` is ``480.0`` (60 working days × 8 h).
    injection_method : InjectionMethod
        How the PERT magnitudes are interpreted by
        :mod:`~src.sra.cpm.risk_injection`.
    opt_pert : float
        PERT optimistic. Days for ``"additive_pert_days"``, factor for
        ``"multiplicative_pert_factor"``.
    ml_pert : float
        PERT most-likely. Same units as ``opt_pert``.
    pess_pert : float
        PERT pessimistic. Same units as ``opt_pert``.
    probability : float
        ``0.0``–``1.0`` Bernoulli probability the risk fires per
        iteration.
    """

    risk_id: str
    pattern_id: str
    pattern_prefixes: tuple[str, ...]
    float_threshold_hours: float
    injection_method: InjectionMethod
    opt_pert: float
    ml_pert: float
    pess_pert: float
    probability: float
    # SR10.A — Mode classification copied onto the resolved RiskDriver
    # by :func:`src.sra.cpm.auto_mapper.expand_single_rule`. Default
    # "Series" preserves pre-SR10.A behaviour for binding paths that
    # do not populate Mode from the strawman.
    mode: RiskMode = "Series"
    # SR12 — single gating activity for discrete-event injection.
    # Required (non-None, present in graph) when
    # ``injection_method == "discrete_event_additive_days"``; ignored
    # by every other method. Default ``None`` preserves pre-SR12
    # behaviour for the legacy ``additive_pert_days`` / multiplicative
    # paths, where the magnitude broadcasts across the full bound
    # cohort.
    gating_activity_id: str | None = None

    def __post_init__(self) -> None:
        _validate_pert_and_probability(
            "AutoMapperRule",
            self.opt_pert,
            self.ml_pert,
            self.pess_pert,
            self.probability,
        )
        _validate_mode("AutoMapperRule", self.mode)


@dataclass(frozen=True)
class RiskDriver:
    """Resolved per-(risk, activity) assignment.

    Either auto-mapper output (beta) or workshop output (prod). The
    kernel and risk_injection consume this format identically — the only
    difference is provenance, recorded by the
    ``derived_at_run_time`` / ``workshop_validated`` flags.

    Attributes
    ----------
    risk_id : str
        Risk identifier; matches the source
        :class:`AutoMapperRule.risk_id`.
    affected_activity_ids : tuple[str, ...]
        Activity ids (i.e. :attr:`Activity.id`, the XER ``task_id``)
        affected by this risk. Order is deterministic — auto-mapper
        sorts by ``(topo_index, code)`` so that repeated runs against
        the same graph produce identical tuples.
    injection_method : InjectionMethod
        Carried over from the rule.
    opt_pert, ml_pert, pess_pert : float
        PERT parameters in the units implied by ``injection_method``.
    probability : float
        Bernoulli fire probability per iteration.
    pattern_id : str | None
        Pattern identifier from the source rule. ``None`` for workshop
        direct construction (where there is no pattern provenance).
    derived_at_run_time : bool
        ``True`` for auto-mapper output, ``False`` for workshop output.
    workshop_validated : bool
        ``False`` for auto-mapper output, ``True`` for workshop output.
        The two flags are independent: a future replay-from-audit path
        could emit ``derived_at_run_time=False, workshop_validated=False``
        when re-loading a frozen auto-mapper run.
    """

    risk_id: str
    affected_activity_ids: tuple[str, ...]
    injection_method: InjectionMethod
    opt_pert: float
    ml_pert: float
    pess_pert: float
    probability: float
    pattern_id: str | None = None
    derived_at_run_time: bool = False
    workshop_validated: bool = False
    # SR10.A — Mode classification. Default "Series" yields multiplier
    # 1.0 in the register's Mode multiplier grid (RS-D-3), preserving
    # pre-SR10.A behaviour for callers that construct RiskDriver
    # without populating Mode (every existing synthetic test and the
    # a binding's declared audit directory).
    mode: RiskMode = "Series"
    # SR12 — single gating activity id for the discrete-event additive
    # injection mechanic. Required (non-None, present in graph) when
    # :attr:`injection_method` == ``"discrete_event_additive_days"``;
    # ignored otherwise. Default ``None`` preserves pre-SR12 behaviour.
    gating_activity_id: str | None = None
    # GATECOHORT-01 — the gate's relation to the bound cohort, set by
    # :func:`src.sra.cpm.auto_mapper.expand_single_rule` for a discrete-
    # event driver and ``None`` for every other method. Carried so the
    # audit trail can say which shape each row takes.
    gating_relation: GatingRelation | None = None

    def __post_init__(self) -> None:
        _validate_pert_and_probability(
            "RiskDriver",
            self.opt_pert,
            self.ml_pert,
            self.pess_pert,
            self.probability,
        )
        _validate_mode("RiskDriver", self.mode)
        if self.injection_method == "discrete_event_additive_days":
            if not self.gating_activity_id:
                raise ValueError(
                    f"RiskDriver {self.risk_id!r}: "
                    "injection_method='discrete_event_additive_days' "
                    "requires a non-empty gating_activity_id"
                )


@dataclass(frozen=True)
class AutoMapperConfig:
    """Universal knobs for the auto-mapper.

    Defaults match the methodology documented in
    the Stage 3 workshop pre-read, "Methodology".

    Attributes
    ----------
    default_float_threshold_hours : float
        Default 480.0 (60 working days × 8 h/day). Used only if a rule
        omits the threshold; rules currently always carry their own.
    require_task_type_TT_Task : bool
        When ``True`` (default), filter B excludes activities whose
        ``task_type`` is not ``"TT_Task"`` — i.e. WBS summaries
        (``"TT_WBS"``) and milestones (``"TT_Mile"``,
        ``"TT_FinMile"``). Setting to ``False`` retains them; intended
        only for diagnostic runs that want to inspect filter A in
        isolation.
    min_activities_warning_threshold : int
        Emit a WARNING if a rule expands to fewer than this many
        activities (default 5). Zero-expansion is reported separately
        (always logged).
    max_activities_warning_threshold : int
        Emit a WARNING if a rule expands to more than this many
        activities (default 500). Detects overly broad pattern
        prefixes.
    """

    default_float_threshold_hours: float = 480.0
    require_task_type_TT_Task: bool = True
    min_activities_warning_threshold: int = 5
    max_activities_warning_threshold: int = 500


@dataclass(frozen=True)
class AutoMapAuditRow:
    """One row of the parquet audit trail written per run.

    Columns map 1:1 to the parquet schema written by
    :func:`src.sra.cpm.auto_mapper.write_audit_trail`. The dataclass is
    the single source of truth for that schema — the parquet writer
    derives its column list from ``dataclasses.fields(AutoMapAuditRow)``,
    and a test asserts the round-trip column list matches exactly.

    Notes
    -----
    Risks whose expansion produced zero activities still get one row in
    the audit trail with ``activity_id == ""``. Silent dropping would
    mask a methodology issue (a pattern prefix that no longer matches
    anything in the schedule). The empty ``activity_id`` is the
    sentinel; readers filter on it if they want only the non-empty
    assignments.
    """

    risk_id: str
    activity_id: str
    pattern_id: str
    injection_method: InjectionMethod
    opt_pert: float
    ml_pert: float
    pess_pert: float
    probability: float
    derived_at_run_time: bool
    workshop_validated: bool
    # SR10.A — Mode classification persisted to the audit trail so the
    # divergence-table interpretation in SR10.B can be traced back to
    # the per-run inputs. Default "Series" matches RiskDriver.mode's
    # default; the parquet schema picks this up automatically via
    # ``dataclasses.fields(AutoMapAuditRow)`` in
    # :func:`src.sra.cpm.auto_mapper.write_audit_trail`.
    mode: RiskMode = "Series"
    # SR12 — per-risk gating activity id, persisted onto the audit
    # parquet so a workshop reviewer can trace which gating activity
    # the engine wrote to for a ``discrete_event_additive_days`` risk.
    # ``""`` (empty string) for any non-discrete-event method.
    gating_activity_id: str = ""
    # GATECOHORT-01 — the gate's relation to the cohort (member /
    # upstream / downstream); ``None`` for any non-discrete-event method.
    gating_relation: GatingRelation | None = None
