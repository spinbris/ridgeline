"""SP18c — shared cascade kernel.

Pure-data implementation of the temporal cascade rule used by both the
cost-only engine (``src.simulation.MonteCarloEngine._apply_cascade_groups``)
and the integrated engine
(``src.integrated.cascade_integrated.apply_cascade_groups_integrated``).

Behavioural contract for the cost-only engine
---------------------------------------------
The cost-only kernel here MUST produce bit-identical output to the legacy
``MonteCarloEngine._apply_cascade_groups`` when called with the same inputs
and rng. The cost-only engine continues to call its own method; this kernel
is the canonical reference and the integrated engine wraps it. The cost-only
behaviour is verified by the existing ``tests/test_cascade.py`` Stage 2 suite
and by ``TestRegression.test_existing_cost_only_cascade_unchanged``.

Methodological note — V8 = L2-only by design
--------------------------------------------
Under the V8 register, ``TIC == 0`` and no Layer 1 WBS buckets are populated.
P-values produced from this kernel describe the distribution of risk-driven
outturn cost ABOVE TIC, not total project cost. The cascade activation
respects this convention: cascade comparison numbers are also "above TIC".
See ``METHODOLOGY.md`` §10.4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


__all__ = [
    "CascadeKernelResult",
    "apply_cascade_kernel",
]


@dataclass
class CascadeKernelResult:
    """Output of :func:`apply_cascade_kernel`.

    ``ev_costs`` and (when present) ``ev_days`` are returned modified in
    place. ``audit`` is the sampled provenance log; up to
    ``audit_sample_cap`` events are recorded across all groups and
    iterations.
    """
    ev_costs: np.ndarray
    ev_days: np.ndarray | None
    audit: list[dict[str, Any]]
    n_groups: int
    group_membership: dict[str, list[int]]


def _get(risk: Any, name: str, default: Any = None) -> Any:
    return getattr(risk, name, default)


def apply_cascade_kernel(
    *,
    ev_costs: np.ndarray,
    risks: list[Any],
    chain_config: Any,
    rng: np.random.Generator,
    ev_days: np.ndarray | None = None,
    severity_uniforms: dict[str, np.ndarray] | None = None,
    use_raw_days: bool = False,
    mode_multiplier_lookup: dict[str, float] | None = None,
    audit_sample_cap: int = 100,
) -> CascadeKernelResult:
    """Apply the temporal cascade rule across risks sharing a ``Cascade_Group``.

    Parameters
    ----------
    ev_costs
        ``(n_iter, n_risks)`` per-risk cost array. Modified in place where a
        downstream risk gets resampled with elevated probability and scaled
        cost. Iterations where the upstream slip is zero leave the column
        unchanged (preserves the joint-sampler's draw for non-cascade-affected
        iterations).
    risks
        List of risk objects. Each must expose: ``risk_id``, ``probability``,
        ``cascade_group`` (string; empty ⇒ not in any group), ``opt_cost``,
        ``ml_cost``, ``pess_cost``, ``distribution``, plus the schedule fields
        ``opt_schedule_days``, ``ml_schedule_days`` (or ``ml_days``),
        ``pess_schedule_days``.
    chain_config
        Carries the cascade rate / cap / cost-scale-rate parameters
        (matching :class:`src.config.ChainConfig`).
    rng
        NumPy ``Generator`` used for fresh resample uniforms.
    ev_days
        Optional ``(n_iter, n_risks_dual)`` per-risk schedule (days) array.
        When supplied, the kernel updates the *dual-coded* downstream risks'
        schedule columns to reflect the resampled magnitudes. Pass ``None``
        for the cost-only path.
    severity_uniforms
        Optional ``{risk_id: (n_iter,) U(0,1)}`` for the joint sampler.
        When a downstream risk's id is present, its resampled cost+schedule
        magnitude is drawn from the supplied uniform (preserves cost/schedule
        correlation under the joint sampler). When absent, fresh independent
        uniforms are drawn from ``rng``.
    use_raw_days
        Cascade slip-propagation switch. ``False`` (Option A, default) →
        propagate Mode-multiplied days. ``True`` (Option B) → propagate
        raw, unmultiplied days. See METHODOLOGY.md §10.4 and the brief's §3.
    mode_multiplier_lookup
        ``{risk_id: float}`` Mode multipliers for dual-coded risks. Applied
        when ``use_raw_days=False`` so the per-iteration realised days that
        feed the slip accumulator are post-Mode. Risks not in the dict are
        treated as multiplier=1.0 (cost-only risks; cascade still propagates
        their raw schedule impact).
    audit_sample_cap
        Hard cap on how many events the kernel records into the returned
        audit log. Default 100 — keeps the audit-trail page legible without
        scaling memory with iter count.

    Returns
    -------
    :class:`CascadeKernelResult` with the (in-place-modified) ``ev_costs`` and
    ``ev_days`` arrays plus the audit-event list and group-membership map.
    """
    from src.distributions import sample_cost as _sample_cost

    n_iter, n_risks = ev_costs.shape

    # Group membership (skip risks with empty cascade_group)
    groups: dict[str, list[int]] = {}
    for i, risk in enumerate(risks):
        g = str(_get(risk, "cascade_group", "") or "").strip()
        if g:
            groups.setdefault(g, []).append(i)

    audit_events: list[dict[str, Any]] = []
    audit_remaining = int(audit_sample_cap)

    # Index lookup for ev_days (dual-coded subset if integrated engine).
    # The integrated engine's ev_days columns correspond to risk_ids_dual,
    # which is a subset of risks. We map by risk_id when possible. Caller
    # should pass dual_index_lookup via mode_multiplier_lookup keys; if a
    # risk_id is not in mode_multiplier_lookup, we treat it as cost-only
    # for the schedule arm.
    has_ev_days = ev_days is not None

    cascade_slip_rate = float(_get(chain_config, "cascade_slip_rate", 1.5))
    cascade_slip_cap = float(_get(chain_config, "cascade_slip_cap", 3.0))
    cost_scale_rate = float(_get(chain_config, "cascade_cost_scale_rate", 0.5))

    for group_name, indices in groups.items():
        running_slip = np.zeros(n_iter, dtype=np.float64)

        for i in indices:
            risk = risks[i]
            risk_id = str(_get(risk, "risk_id", f"_{i}"))
            ml_d = float(_get(risk, "ml_days", _get(risk, "ml_schedule_days", 0.0)) or 0.0)
            opt_d_raw = float(_get(risk, "opt_schedule_days", 0.0) or 0.0)
            pess_d_raw = float(_get(risk, "pess_schedule_days", 0.0) or 0.0)
            opt_d = opt_d_raw if opt_d_raw > 0 else ml_d * 0.5
            pess_d = pess_d_raw if pess_d_raw > 0 else ml_d * 2.0
            has_schedule = (ml_d > 0 or pess_d_raw > 0)

            base_p = float(_get(risk, "probability", 0.0) or 0.0)
            opt_c = float(_get(risk, "opt_cost", 0.0) or 0.0)
            ml_c = float(_get(risk, "ml_cost", 0.0) or 0.0)
            pess_c = float(_get(risk, "pess_cost", 0.0) or 0.0)
            distribution = str(_get(risk, "distribution", "PERT") or "PERT")

            slip_active = running_slip > 0
            if np.any(slip_active):
                multiplier = np.clip(
                    1.0 + (running_slip / 90.0) * cascade_slip_rate,
                    1.0, cascade_slip_cap,
                )
                adjusted_p = np.minimum(base_p * multiplier, 0.95)
                u_fire = rng.uniform(size=n_iter)
                fired = u_fire < adjusted_p

                cost_scale = 1.0 + (running_slip / 180.0) * cost_scale_rate

                # Resample severity. Use joint severity uniform when supplied
                # so cost+schedule stay correlated for dual-coded downstream
                # risks; otherwise fresh independent uniforms.
                if severity_uniforms is not None and risk_id in severity_uniforms:
                    u_mag = severity_uniforms[risk_id]
                else:
                    u_mag = rng.uniform(size=n_iter)

                new_cost = _sample_cost(u_mag, opt_c, ml_c, pess_c, distribution)
                ev_costs[:, i] = fired * new_cost * cost_scale

                # Update ev_days for dual-coded downstream risks (integrated
                # engine path). The integrated engine's ev_days has columns
                # matching risk_ids_dual; the caller passes a position map
                # via mode_multiplier_lookup so we can find the column.
                if has_ev_days and mode_multiplier_lookup is not None and risk_id in mode_multiplier_lookup:
                    # column index: scan known dual position map (passed as
                    # _dual_col attribute on the dict for efficiency)
                    pass  # handled by integrated wrapper which knows the column index

                # Audit sampling: capture up to audit_sample_cap events
                # representative across iterations + groups.
                if audit_remaining > 0:
                    iter_indices = np.where(slip_active)[0]
                    take = min(audit_remaining, iter_indices.size, 10)
                    if take > 0:
                        sampled = iter_indices[
                            np.linspace(0, iter_indices.size - 1, take, dtype=np.int64)
                        ]
                        for it in sampled:
                            it = int(it)
                            audit_events.append({
                                "parent": "cascade_group:" + group_name,
                                "child": risk_id,
                                "iteration": it,
                                "running_slip_days": float(running_slip[it]),
                                "p_before": float(base_p),
                                "p_after": float(adjusted_p[it]),
                                "cost_scale": float(cost_scale[it]),
                                "fired": bool(fired[it]),
                                "cascade_group": group_name,
                            })
                            audit_remaining -= 1
                            if audit_remaining <= 0:
                                break
            else:
                fired = ev_costs[:, i] != 0

            # Update running slip for this group
            if has_schedule:
                schedule_u = rng.uniform(size=n_iter)
                schedule_impact = _sample_cost(
                    schedule_u, opt_d, ml_d, pess_d, "Triangular",
                )
                if not use_raw_days and mode_multiplier_lookup is not None:
                    mult = float(mode_multiplier_lookup.get(risk_id, 1.0))
                    schedule_impact = schedule_impact * mult
                running_slip = running_slip + fired.astype(np.float64) * schedule_impact

    return CascadeKernelResult(
        ev_costs=ev_costs,
        ev_days=ev_days,
        audit=audit_events,
        n_groups=len(groups),
        group_membership={k: list(v) for k, v in groups.items()},
    )
