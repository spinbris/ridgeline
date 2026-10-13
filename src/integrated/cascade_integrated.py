"""SP18c — temporal cascade activation in the integrated engine.

Wires the shared cascade kernel (:mod:`src.integrated._cascade_kernel`) into
:func:`src.integrated.integrated_simulation.run_integrated_simulation`,
adds the no-double-count overlap detector between workbook chains
(``Risk_Network_Edges``) and cascade groups (``Cascade_Group``), and the
legacy chain DeprecationWarning emitter.

Behaviour contract
------------------
* ``cascade_enabled`` defaults to ``False`` (set in
  :class:`src.config.ChainConfig`). The cascade-off path through the
  integrated engine MUST produce structurally identical output to the
  pre-SP18c locked baseline (tag ``pre-sp18c-baseline``). This was verified
  by ``scripts/pre_sp18c_baseline.py --cascade-mode off``, retired by
  DAYRATE-02 (31/08/2026) as dead since SR19; the standing verifier is now
  the golden-number harness, ``pytest -m golden``.
* The cost-only engine
  (:class:`src.simulation.MonteCarloEngine`) continues to call its own
  ``_apply_cascade_groups`` method. The integrated engine wraps the same
  kernel via :func:`apply_cascade_groups_integrated`.

Audit-trail wording invariant
-----------------------------
All commentary emitted by this module describes P-value movement as
"risk-driven outturn above TIC", never "total project cost". Under V8 the
TIC is zero and Layer 1 is unpopulated, so the integrated engine's
P-values are L2 event-risk-only by design (see ``METHODOLOGY.md`` §10.4
and the V8 = L2-only paragraph).
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.integrated._cascade_kernel import (
    CascadeKernelResult,
    apply_cascade_kernel,
)


logger = logging.getLogger(__name__)


__all__ = [
    "CascadeIntegratedResult",
    "apply_cascade_groups_integrated",
    "detect_chain_cascade_overlap",
    "emit_legacy_chain_deprecation_warning",
]


def _resolve_legacy_chain_ids() -> tuple[str, ...]:
    """Flat tuple of the active project's legacy chain trigger/target IDs.

    Derived from the binding's ``legacy_chain_ids`` role map (via
    ``defaults.get_chain_risk_ids``), dropping None/empty. Used only by the
    deprecation emitter below; resolved lazily so the project binding stays
    off this module's import path. Empty for a project with no legacy chain.
    """
    from src.defaults import get_chain_risk_ids

    ids = get_chain_risk_ids()
    flat: list[str] = []
    for key in ("c1_trigger", "c1_target", "c2_trigger"):
        val = ids.get(key)
        if val:
            flat.append(val)
    flat.extend(t for t in (ids.get("c2_targets") or []) if t)
    return tuple(flat)


@dataclass
class CascadeIntegratedResult:
    """Output of :func:`apply_cascade_groups_integrated`."""
    ev_costs: np.ndarray
    ev_days: np.ndarray | None
    audit: list[dict[str, Any]]
    n_groups: int
    group_membership: dict[str, list[int]]


def apply_cascade_groups_integrated(
    *,
    ev_costs: np.ndarray,
    ev_days: np.ndarray | None,
    risks: list[Any],
    risk_ids_dual: list[str],
    dual_lookup: dict[str, dict[str, Any]],
    chain_config: Any,
    rng: np.random.Generator,
    severity_uniforms: dict[str, np.ndarray] | None = None,
    use_raw_days: bool = False,
    audit_sample_cap: int = 100,
) -> CascadeIntegratedResult:
    """Apply the temporal cascade across the integrated engine's per-risk arrays.

    Parameters
    ----------
    ev_costs
        ``(n_iter, n_risks)`` per-risk cost. Modified in place.
    ev_days
        ``(n_iter, n_risks_dual)`` per-risk schedule (post-Mode). Modified
        in place when downstream dual-coded risks are resampled. Pass
        ``None`` to disable schedule-arm updates.
    risks
        Full risk list (length ``n_risks``).
    risk_ids_dual
        Risk IDs (in column order) of the schedule arm — i.e. the
        Time=Yes / dual-coded subset.
    dual_lookup
        ``{risk_id: {mode, mode_multiplier, opt_d, ml_d, pess_d}}`` — one
        entry per dual-coded risk (from ``run_integrated_simulation``).
    chain_config
        Carries cascade_slip_rate / cap / cost_scale_rate.
    rng
        NumPy ``Generator``.
    severity_uniforms
        Optional joint-sampler severity uniforms ``{risk_id: (n_iter,)}``.
    use_raw_days
        Option A vs B (see brief §3 / METHODOLOGY.md §10.4).
    audit_sample_cap
        Cap on the audit-event count.
    """
    mode_multiplier_lookup = {
        rid: float(d.get("mode_multiplier", 1.0))
        for rid, d in dual_lookup.items()
    }
    dual_col_index = {rid: i for i, rid in enumerate(risk_ids_dual)}

    kernel_out = apply_cascade_kernel(
        ev_costs=ev_costs,
        risks=risks,
        chain_config=chain_config,
        rng=rng,
        ev_days=ev_days,
        severity_uniforms=severity_uniforms,
        use_raw_days=use_raw_days,
        mode_multiplier_lookup=mode_multiplier_lookup,
        audit_sample_cap=audit_sample_cap,
    )

    # The kernel updates ev_costs in place. For ev_days we additionally
    # propagate resampled schedule magnitudes to the dual-coded columns
    # using the lookup. The kernel already drew the new fire/uniform
    # decisions into ev_costs; here we mirror them onto ev_days for any
    # downstream cascade-group risk that is also dual-coded.
    if ev_days is not None:
        for group, indices in kernel_out.group_membership.items():
            for i in indices:
                rid = str(getattr(risks[i], "risk_id", f"_{i}"))
                if rid in dual_col_index and rid in dual_lookup:
                    # Mirror the cost arm's fired pattern: where the cost is
                    # zero post-cascade the risk did not (re)fire under the
                    # adjusted probability, so the schedule must also be zero.
                    # Where cost is non-zero, the schedule was redrawn from
                    # the same severity uniform via the kernel's slip update;
                    # here we re-evaluate via the dual_lookup PERT to stay
                    # internally consistent with the joint sampler.
                    fired_mask = ev_costs[:, i] != 0
                    j = dual_col_index[rid]
                    # Zero the days for non-fired iterations.
                    ev_days[~fired_mask, j] = 0.0
                    # For fired iterations, recompute from severity uniform.
                    if np.any(fired_mask) and severity_uniforms and rid in severity_uniforms:
                        from src.distributions import pert_from_uniform
                        d = dual_lookup[rid]
                        u = severity_uniforms[rid][fired_mask]
                        sched_pre = pert_from_uniform(
                            u, float(d["opt_d"]), float(d["ml_d"]), float(d["pess_d"]),
                        )
                        if not use_raw_days:
                            sched_pre = sched_pre * float(d["mode_multiplier"])
                        ev_days[fired_mask, j] = sched_pre

    return CascadeIntegratedResult(
        ev_costs=kernel_out.ev_costs,
        ev_days=kernel_out.ev_days,
        audit=kernel_out.audit,
        n_groups=kernel_out.n_groups,
        group_membership=kernel_out.group_membership,
    )


# ----------------------------------------------------------------------------
# §7 — No-double-count guard between workbook chains and cascade groups
# ----------------------------------------------------------------------------

def detect_chain_cascade_overlap(
    risks: list[Any],
    edges: list[Any],
    *,
    strict: bool = False,
) -> list[dict[str, Any]]:
    """Flag parent-child pairs wired through BOTH ``Risk_Network_Edges``
    AND a shared ``Cascade_Group``.

    Parameters
    ----------
    risks
        Risk list (each must expose ``risk_id`` and ``cascade_group``).
    edges
        Iterable of edge objects / dicts. Each must expose ``parent_id``,
        ``child_id`` and (optionally) ``effect_type``, ``magnitude``.
    strict
        When True, raises :class:`RuntimeError` listing the overlap.
        When False (default), returns the list and logs a WARNING per entry.

    Returns
    -------
    List of overlap dicts, one per parent-child pair found in BOTH layers.
    Empty list ⇒ no overlaps (the V8 base case).
    """
    by_id = {str(getattr(r, "risk_id", "")): r for r in risks}

    def _attr(obj: Any, name: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    overlaps: list[dict[str, Any]] = []
    for edge in edges:
        pid = str(_attr(edge, "parent_id", "") or "")
        cid = str(_attr(edge, "child_id", "") or "")
        if not pid or not cid:
            continue
        parent = by_id.get(pid)
        child = by_id.get(cid)
        if parent is None or child is None:
            continue
        pg = str(getattr(parent, "cascade_group", "") or "").strip()
        cg = str(getattr(child, "cascade_group", "") or "").strip()
        if pg and pg == cg:
            entry = {
                "parent_id": pid,
                "child_id": cid,
                "cascade_group": pg,
                "edge_effect_type": str(_attr(edge, "effect_type", "") or ""),
                "edge_magnitude": float(_attr(edge, "magnitude", 0.0) or 0.0),
                "severity": "error" if strict else "warning",
            }
            overlaps.append(entry)
            logger.warning(
                "[SP18c overlap guard] %s -> %s wired through BOTH "
                "Risk_Network_Edges (effect=%s, magnitude=%.3f) AND "
                "shared Cascade_Group=%r — risk of double-counting "
                "exposure. Resolve before relying on the cascade-on output.",
                pid, cid, entry["edge_effect_type"],
                entry["edge_magnitude"], pg,
            )

    if strict and overlaps:
        raise RuntimeError(
            f"detect_chain_cascade_overlap: {len(overlaps)} overlap(s) "
            f"between Risk_Network_Edges and Cascade_Group; resolve "
            f"before re-running with strict_overlap_check=True. "
            f"First overlap: {overlaps[0]}"
        )
    return overlaps


# ----------------------------------------------------------------------------
# §8 — Legacy chain DeprecationWarning emitter
# ----------------------------------------------------------------------------

def emit_legacy_chain_deprecation_warning(
    risks: list[Any],
    *,
    legacy_ids: tuple[str, ...] | None = None,
) -> list[str]:
    """Emit a ``DeprecationWarning`` if any legacy hardcoded chain ID is in
    the open risk set.

    ``legacy_ids`` defaults to the active project binding's legacy chain
    IDs (resolved lazily via :func:`_resolve_legacy_chain_ids`). Returns the
    list of legacy IDs found — empty where none of a project's
    binding's chain trigger/target IDs are in the V9 Open set, so the
    warning is a no-op for the canonical run.
    """
    if legacy_ids is None:
        legacy_ids = _resolve_legacy_chain_ids()
    open_ids = {str(getattr(r, "risk_id", "")).strip() for r in risks}
    found = [rid for rid in legacy_ids if rid in open_ids]
    if found:
        warnings.warn(
            "Static hardcoded chains _apply_chain1 / _apply_chain2 will be "
            "removed in SP19. Migrate the chain relationships involving "
            f"{found} to Risk_Network_Edges (workbook chains) or to a "
            "shared Cascade_Group (temporal cascade). See "
            "the SP18c temporal cascade brief, §8, and "
            "SP18d for the project-agnostic migration plan.",
            DeprecationWarning,
            stacklevel=2,
        )
    return found
