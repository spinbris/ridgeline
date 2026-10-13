"""
Single-iteration scenario run for MC_SingleRun sheet.

Runs one complete random scenario with full detail visible:
which events fired, what each cost, chain effects triggered,
Layer 1 bucket variations, and party cost breakdowns.

Ported from MC_CodeRef SingleRun PY() cell (the cost-model workbook).
"""

import numpy as np
from scipy import stats

from src.config import (
    SimConfig, WBSBucket, ChainConfig, RiskInput,
    SingleRunBucket, SingleRunEvent, SingleRunResult,
)
from src.distributions import (
    triangular_from_uniform, pert_from_uniform, lognormal_from_uniform,
    sample_cost,
)
from src.defaults import CHAIN_RISK_IDS
from src.rng_streams import resolve_seed
from src.reader import _matches_party, _matches_shared


def run_single(
    config: SimConfig,
    buckets: list[WBSBucket],
    chains: ChainConfig,
    risks: list[RiskInput],
    pool_budget: float = 15_000_000.0,
    pool_budget_label: str = "Pool budget",
    seed: int | None = None,
) -> SingleRunResult:
    """Run one complete random iteration with full detail.

    Returns a SingleRunResult with all intermediate values visible
    for transparency and audit. ``seed`` unset or 0 is drawn here and recorded on the result
    (SEEDZERO-01), so the scenario shown can be reproduced by giving it back.
    """
    seed_used, _ = resolve_seed(seed, where="src.single_run.run_single")
    rng = np.random.default_rng(seed_used)

    # -----------------------------------------------------------
    # Layer 1: WBS bucket variation
    # -----------------------------------------------------------
    bucket_results = []
    l1_total_var = 0.0

    if config.view in ("Shared", "L2Only"):
        # L1 excluded for Shared/L2Only views — pure L2 analysis
        l1_outturn = 0.0
    else:
        for bucket in buckets:
            u = rng.uniform()
            lo = bucket.low_var
            hi = bucket.high_var
            mode = (lo + hi) / 2.0
            dist = bucket.distribution.strip().lower()

            if dist == "lognormal":
                pct = float(lognormal_from_uniform(np.array([u]), lo, hi)[0])
            elif dist == "pert":
                pct = float(pert_from_uniform(np.array([u]), lo, mode, hi)[0])
            else:
                pct = float(triangular_from_uniform(np.array([u]), lo, mode, hi)[0])

            impact = bucket.base_cost * pct
            l1_total_var += impact

            bucket_results.append(SingleRunBucket(
                name=bucket.name,
                base_cost=bucket.base_cost,
                var_pct=pct,
                impact=impact,
                distribution=dist,
            ))

        l1_outturn = config.tic + l1_total_var

    # -----------------------------------------------------------
    # Layer 2: Event risks
    # -----------------------------------------------------------
    event_results = []
    cost_map = {}  # risk_id → cost for chain logic

    for risk in risks:
        rtype = risk.recurrence_type.strip().upper()

        if rtype == "BINOMIAL":
            max_occ = int(risk.recurrence_param)
            if max_occ <= 0:
                max_n = config.programme_seasons
            else:
                max_n = min(max_occ, config.programme_seasons)
            occurrences = int(rng.binomial(n=max_n, p=risk.probability))
            per_occ = []
            for _ in range(occurrences):
                c = float(sample_cost(
                    np.array([rng.uniform()]),
                    risk.opt_cost, risk.ml_cost, risk.pess_cost,
                    risk.distribution,
                )[0])
                per_occ.append(c)
            cost = sum(per_occ)
            cost_map[risk.risk_id] = cost
            event_results.append(SingleRunEvent(
                risk_id=risk.risk_id,
                description=risk.description[:60],
                owner=risk.owner,
                probability=risk.probability,
                fired=occurrences > 0,
                cost_impact=cost,
                days_impact=risk.ml_days * occurrences if occurrences > 0 else 0.0,
                distribution=risk.distribution,
                per_occurrence_costs=per_occ,
            ))

        elif rtype == "POISSON":
            occurrences = int(rng.poisson(lam=risk.recurrence_param))
            per_occ = []
            for _ in range(occurrences):
                c = float(sample_cost(
                    np.array([rng.uniform()]),
                    risk.opt_cost, risk.ml_cost, risk.pess_cost,
                    risk.distribution,
                )[0])
                per_occ.append(c)
            cost = sum(per_occ)
            cost_map[risk.risk_id] = cost
            event_results.append(SingleRunEvent(
                risk_id=risk.risk_id,
                description=risk.description[:60],
                owner=risk.owner,
                probability=risk.probability,
                fired=occurrences > 0,
                cost_impact=cost,
                days_impact=risk.ml_days * occurrences if occurrences > 0 else 0.0,
                distribution=risk.distribution,
                per_occurrence_costs=per_occ,
            ))

        else:
            # Default: single Bernoulli draw (unchanged)
            u = rng.uniform()
            fired = u < risk.probability
            cost = 0.0
            if fired:
                u_mag = rng.uniform()
                cost = float(sample_cost(
                    np.array([u_mag]),
                    risk.opt_cost, risk.ml_cost, risk.pess_cost,
                    risk.distribution,
                )[0])
            cost_map[risk.risk_id] = cost
            event_results.append(SingleRunEvent(
                risk_id=risk.risk_id,
                description=risk.description[:60],
                owner=risk.owner,
                probability=risk.probability,
                fired=fired,
                cost_impact=cost,
                days_impact=risk.ml_days if fired else 0.0,
                distribution=risk.distribution,
            ))

    # -----------------------------------------------------------
    # Cascade groups (Stage 2) — before static chains
    # -----------------------------------------------------------
    if chains.cascade_enabled:
        # Find cascade groups
        casc_groups: dict[str, list[int]] = {}
        for idx, r in enumerate(risks):
            g = r.cascade_group.strip()
            if g:
                casc_groups.setdefault(g, []).append(idx)

        for group_name, indices in casc_groups.items():
            running_slip = 0.0
            for idx in indices:
                r = risks[idx]
                has_schedule = (r.ml_schedule_days > 0 or r.pess_schedule_days > 0)

                base_p = r.probability

                if running_slip > 0:
                    # Downstream risk: resample with slip-adjusted probability
                    mult = min(
                        max(1.0 + (running_slip / 90.0) * chains.cascade_slip_rate, 1.0),
                        chains.cascade_slip_cap,
                    )
                    adj_p = min(base_p * mult, 0.95)

                    new_fire = rng.uniform() < adj_p
                    cost_scale = 1.0 + (running_slip / 180.0) * chains.cascade_cost_scale_rate
                    new_cost = 0.0
                    if new_fire:
                        new_cost = float(sample_cost(
                            np.array([rng.uniform()]),
                            r.opt_cost, r.ml_cost, r.pess_cost, r.distribution,
                        )[0]) * cost_scale

                    cost_map[r.risk_id] = new_cost
                    cascade_note = (
                        f"Cascade {group_name}: slip={running_slip:.0f}d, "
                        f"P adjusted {base_p*100:.0f}%→{adj_p*100:.0f}%"
                    )
                    event_results[idx] = SingleRunEvent(
                        risk_id=r.risk_id,
                        description=r.description[:60],
                        owner=r.owner,
                        probability=adj_p,
                        fired=new_fire,
                        cost_impact=new_cost,
                        days_impact=r.ml_days if new_fire else 0.0,
                        distribution=r.distribution,
                        chain_note=cascade_note,
                        per_occurrence_costs=event_results[idx].per_occurrence_costs,
                    )
                else:
                    # First risk in group: keep original draw
                    new_fire = event_results[idx].fired

                # Update running slip
                if new_fire and has_schedule:
                    opt_d = r.opt_schedule_days if r.opt_schedule_days > 0 else r.ml_schedule_days * 0.5
                    pess_d = r.pess_schedule_days if r.pess_schedule_days > 0 else r.ml_schedule_days * 2.0
                    sched_draw = float(sample_cost(
                        np.array([rng.uniform()]),
                        opt_d, r.ml_schedule_days, pess_d, "Triangular",
                    )[0])
                    running_slip += sched_draw

    # -----------------------------------------------------------
    # Chain 1: trigger → target
    # -----------------------------------------------------------
    chain_ids = CHAIN_RISK_IDS
    c1_trigger_id = chain_ids["c1_trigger"]
    c1_target_id = chain_ids["c1_target"]
    r076_idx = next((i for i, r in enumerate(risks) if r.risk_id == c1_trigger_id), None)
    r015_idx = next((i for i, r in enumerate(risks) if r.risk_id == c1_target_id), None)

    if r076_idx is not None and r015_idx is not None:
        r076 = risks[r076_idx]
        r076_cost = cost_map.get(c1_trigger_id, 0)
        if r076_cost != 0:
            max_pess = max(abs(r076.pess_cost), 1.0)
            months = (abs(r076_cost) / max_pess) * 8.0
            if months >= chains.c1_trigger_months:
                r015 = risks[r015_idx]
                elevated_p = min(r015.probability * chains.c1_amplification, 0.95)
                new_fire = rng.uniform() < elevated_p
                new_cost = 0.0
                if new_fire:
                    new_cost = float(sample_cost(
                        np.array([rng.uniform()]),
                        r015.opt_cost, r015.ml_cost, r015.pess_cost,
                        r015.distribution,
                    )[0])
                cost_map[c1_target_id] = new_cost
                event_results[r015_idx] = SingleRunEvent(
                    risk_id=c1_target_id,
                    description=risks[r015_idx].description[:60],
                    owner=risks[r015_idx].owner,
                    probability=elevated_p,
                    fired=new_fire,
                    cost_impact=new_cost,
                    days_impact=risks[r015_idx].ml_days if new_fire else 0.0,
                    distribution=risks[r015_idx].distribution,
                    chain_note=f"Chain 1: elevated P={elevated_p*100:.0f}% (delay {months:.1f}mo)",
                )

    # -----------------------------------------------------------
    # Chain 2: trigger → targets
    # -----------------------------------------------------------
    c2_trigger_id = chain_ids["c2_trigger"]
    r017_idx = next((i for i, r in enumerate(risks) if r.risk_id == c2_trigger_id), None)

    if r017_idx is not None:
        r017 = risks[r017_idx]
        r017_cost = cost_map.get(c2_trigger_id, 0)
        if r017_cost != 0:
            max_pess = max(abs(r017.pess_cost), 1.0)
            weeks = (abs(r017_cost) / max_pess) * 4.0
            if weeks >= chains.c2_trigger_weeks:
                for target_id in chain_ids["c2_targets"]:
                    t_idx = next((i for i, r in enumerate(risks) if r.risk_id == target_id), None)
                    if t_idx is None:
                        continue
                    t_risk = risks[t_idx]
                    elevated_p = min(t_risk.probability * chains.c2_cascade_factor, 0.95)
                    new_fire = rng.uniform() < elevated_p
                    new_cost = 0.0
                    if new_fire:
                        new_cost = float(sample_cost(
                            np.array([rng.uniform()]),
                            t_risk.opt_cost, t_risk.ml_cost, t_risk.pess_cost,
                            t_risk.distribution,
                        )[0])
                    cost_map[target_id] = new_cost
                    event_results[t_idx] = SingleRunEvent(
                        risk_id=target_id,
                        description=t_risk.description[:60],
                        owner=t_risk.owner,
                        probability=elevated_p,
                        fired=new_fire,
                        cost_impact=new_cost,
                        days_impact=t_risk.ml_days if new_fire else 0.0,
                        distribution=t_risk.distribution,
                        chain_note=f"Chain 2: elevated P={elevated_p*100:.0f}% (delay {weeks:.1f}wk)",
                    )

    # -----------------------------------------------------------
    # Totals and party breakdowns
    # -----------------------------------------------------------
    l2_total = sum(cost_map.values())
    n_fired = sum(1 for ev in event_results if ev.fired)
    n_risks = len(event_results)

    if config.view in ("Shared", "L2Only"):
        # Shared/L2Only view: L1 excluded, pure L2 costs
        shared_l2 = l2_total
        pool_headroom = pool_budget - shared_l2

        return SingleRunResult(
            view=config.view,
            seed=seed_used,
            buckets=bucket_results,
            events=event_results,
            l1_total_variation=0.0,
            l1_outturn=0.0,
            l2_total=l2_total,
            total_outturn=l2_total,  # Pure L2 cost
            shared_l2=shared_l2,
            pool_budget=pool_budget,
            pool_budget_label=pool_budget_label,
            pool_headroom=pool_headroom,
            n_fired=n_fired,
            n_risks=n_risks,
        )
    else:
        # Standard views: full outturn with party breakdowns
        # SP11a: All risks treated as shared pool risks.
        # When multi-owner structure returns, restore owner filtering here.
        shared_l2 = l2_total  # All L2 costs are shared
        bop_l2 = 0.0          # No BOP-only costs in single-owner model
        cse_l2 = 0.0          # No CSE-only costs in single-owner model

        total_outturn = l1_outturn + l2_total
        bop_outturn = l1_outturn + bop_l2 + shared_l2
        cse_outlay = cse_l2 + shared_l2

        return SingleRunResult(
            view=config.view,
            seed=seed_used,
            buckets=bucket_results,
            events=event_results,
            l1_total_variation=l1_total_var,
            l1_outturn=l1_outturn,
            l2_total=l2_total,
            total_outturn=total_outturn,
            bop_l2=bop_l2,
            cse_l2=cse_l2,
            shared_l2=shared_l2,
            bop_outturn=bop_outturn,
            cse_outlay=cse_outlay,
            bop_vs_contract=bop_outturn - config.bop_contract,
            bop_vs_contingency=bop_outturn - config.bop_contract - config.bop_contingency,
            cse_vs_contingency=cse_outlay - config.cse_contingency,
            pool_budget=pool_budget,
            pool_headroom=pool_budget - shared_l2,
            n_fired=n_fired,
            n_risks=n_risks,
        )
