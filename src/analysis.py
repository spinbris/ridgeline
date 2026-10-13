"""
Post-simulation analysis: percentiles, tornado, S-curve, convergence.

Produces the key-value output table that feeds MC_Engine results range
via XLOOKUP formulas on MC_Outputs and MC_Dashboard.

Key inventory:
  - view_label                                  (e.g. "Shared", "All Risks")
  - p10, p50, p80, p90, mean, std               (primary view — matches mc_view)
  - l1_p10..l1_std                              (Layer 1 only; zeros if view=Shared)
  - bop_p10..bop_std                            (BOP sub-view within current run)
  - cse_p10..cse_std                            (CSE sub-view within current run)
  - risk_premium                                (P50 - TIC)
  - adequacy, overrun, n_risks
  - t0_id..t9_var                               (Tornado top 10, L1 excluded if Shared)
  - conv_1000..conv_30000
  - sc_total_1..sc_total_99, sc_l1_1..sc_l1_99
"""

import numpy as np
from src.config import SimConfig, RiskInput, SimRawResults, TornadoEntry, GainPainConfig
from src.bootstrap import bootstrap_convergence
from src.rng_streams import resolve_seed


# ---------------------------------------------------------------------------
# Stakeholder view filtering
# ---------------------------------------------------------------------------

def _owner_matches(owner: str, party_name: str) -> bool:
    """Check if a risk owner string matches a party name (prefix match)."""
    return owner.strip().lower().startswith(party_name.strip().lower()[:6])


def _is_shared(owner: str, shared_label: str) -> bool:
    return owner.strip().lower() == shared_label.strip().lower()


def compute_party_costs(
    raw: SimRawResults,
    risks: list[RiskInput],
    config: SimConfig,
) -> dict:
    """Compute total cost arrays for each stakeholder view.

    Returns dict with keys: total, l1, l2_all, bop_total, cse_total, shared_l2
    """
    l1 = raw.l1_cost
    l2_all = raw.ev_costs.sum(axis=1) if raw.n_risks > 0 else np.zeros(raw.n_iter)
    total = l1 + l2_all

    # SP11a: All risks are treated as shared pool risks regardless of owner label.
    # The Shared Risk Pool includes all MC Include = Yes risks.
    # When multi-owner structure returns, restore _is_shared()/_owner_matches() filtering here.
    bop_idx = list(range(len(risks)))
    bop_l2 = raw.ev_costs.sum(axis=1) if risks else np.zeros(raw.n_iter)
    bop_total = l1 + bop_l2

    cse_idx = list(range(len(risks)))
    cse_l2 = raw.ev_costs.sum(axis=1) if risks else np.zeros(raw.n_iter)
    cse_total = l1 + cse_l2

    shared_idx = list(range(len(risks)))
    shared_l2 = raw.ev_costs.sum(axis=1) if risks else np.zeros(raw.n_iter)

    return {
        "total": total,
        "l1": l1,
        "l2_all": l2_all,
        "bop_total": bop_total,
        "cse_total": cse_total,
        "shared_l2": shared_l2,
    }


# ---------------------------------------------------------------------------
# Percentiles
# ---------------------------------------------------------------------------

def _pcts(arr: np.ndarray) -> dict:
    """Compute standard percentile set for an array."""
    p10, p50, p80, p90 = np.percentile(arr, [10, 50, 80, 90])
    return {
        "p10": float(p10), "p50": float(p50),
        "p80": float(p80), "p90": float(p90),
        "mean": float(np.mean(arr)), "std": float(np.std(arr)),
    }


# ---------------------------------------------------------------------------
# Tornado — leave-one-out variance decomposition
# ---------------------------------------------------------------------------

def compute_tornado(
    raw: SimRawResults,
    risks: list[RiskInput],
    top_n: int = 10,
    buckets: list = None,
    view: str = "All",
) -> list[TornadoEntry]:
    """Leave-one-out variance decomposition for combined L1 + L2.

    When view=Shared, l1_buckets are all zeros so L1 entries have zero
    variance and naturally fall out of the top 10 — no special handling needed.
    When view=L2Only, L1 buckets are skipped entirely — only L2 risks included.
    Bucket names are read from the buckets list (dynamic) rather than hardcoded.
    """
    if view == "L2Only":
        total = raw.ev_costs.sum(axis=1) if raw.n_risks > 0 else np.zeros(raw.n_iter)
    else:
        total = raw.l1_cost + (
            raw.ev_costs.sum(axis=1) if raw.n_risks > 0 else np.zeros(raw.n_iter)
        )
    base_var = float(np.var(total))
    entries = []

    # Layer 1 buckets — skipped for L2Only (pure event risk analysis)
    if view != "L2Only":
        n_buckets = raw.l1_buckets.shape[1]
        for k in range(n_buckets):
            total_without = total - raw.l1_buckets[:, k] + np.mean(raw.l1_buckets[:, k])
            var_without = float(np.var(total_without))
            var_contrib = max(0.0, base_var - var_without)
            if buckets and k < len(buckets):
                name = buckets[k].name
            else:
                name = f"WBS Bucket {k+1}"
            entries.append(TornadoEntry(
                risk_id=f"L1-{k}",
                description=name,
                variance_contribution=var_contrib,
                std_contribution=float(np.sqrt(var_contrib)),
                owner="",
                layer="Layer 1",
            ))

    # Layer 2 risks
    for i, risk in enumerate(risks):
        total_without = total - raw.ev_costs[:, i]
        var_without = float(np.var(total_without))
        var_contrib = max(0.0, base_var - var_without)
        entries.append(TornadoEntry(
            risk_id=risk.risk_id,
            description=risk.description,
            variance_contribution=var_contrib,
            std_contribution=float(np.sqrt(var_contrib)),
            owner=risk.owner,
            layer="Layer 2",
        ))

    entries.sort(key=lambda e: -e.variance_contribution)
    return entries[:top_n]


# ---------------------------------------------------------------------------
# S-curve data — percentiles 1–99
# ---------------------------------------------------------------------------

def compute_s_curve(raw: SimRawResults, view: str = "All") -> dict:
    """Compute percentile points 1–99 for total and L1-only distributions.

    Returns dict with sc_total_1..sc_total_99 and sc_l1_1..sc_l1_99.
    When view=Shared, sc_total uses pure L2 costs (no TIC).
    """
    if view in ("Shared", "L2Only"):
        total = raw.ev_costs.sum(axis=1) if raw.n_risks > 0 else np.zeros(raw.n_iter)
    else:
        total = raw.l1_cost + (
            raw.ev_costs.sum(axis=1) if raw.n_risks > 0 else np.zeros(raw.n_iter)
        )
    pctiles = list(range(1, 100))
    total_pcts = np.percentile(total, pctiles)
    l1_pcts = np.percentile(raw.l1_cost, pctiles)

    result = {}
    for i, p in enumerate(pctiles):
        result[f"sc_total_{p}"] = float(total_pcts[i])
        result[f"sc_l1_{p}"] = float(l1_pcts[i])
    return result


# ---------------------------------------------------------------------------
# Convergence check — P90 at subsets
# ---------------------------------------------------------------------------

CONVERGENCE_POINTS = [1000, 5000, 10000, 20000, 30000, 50000, 100000]


def compute_convergence(
    raw: SimRawResults,
    view: str = "All",
    n_blocks: int = 100,
    n_resamples: int = 1000,
    seed: int | None = None,
) -> dict:
    """P90 at increasing iteration subsets to verify convergence.

    Returns dict with conv_1000, conv_5000, conv_10000, conv_20000, conv_30000
    (back-compat keys; point estimates) plus a "bootstrap" sub-dict carrying
    the 95% Monte-Carlo-error envelope from
    :func:`src.bootstrap.bootstrap_convergence`.

    When view=Shared or L2Only, uses pure L2 costs (no TIC).
    """
    if view in ("Shared", "L2Only"):
        total = raw.ev_costs.sum(axis=1) if raw.n_risks > 0 else np.zeros(raw.n_iter)
    else:
        total = raw.l1_cost + (
            raw.ev_costs.sum(axis=1) if raw.n_risks > 0 else np.zeros(raw.n_iter)
        )

    grid = [n for n in CONVERGENCE_POINTS if n <= raw.n_iter]
    boot = bootstrap_convergence(
        total,
        percentile=90.0,
        iter_grid=grid if grid else [raw.n_iter],
        n_blocks=n_blocks,
        n_resamples=n_resamples,
        seed=seed,
    )

    # Backward-compatible keys: point estimates only.
    result = {}
    for k, p in zip(boot["iter_grid"], boot["point"]):
        if k in CONVERGENCE_POINTS:
            result[f"conv_{k}"] = float(p)

    # New: full bootstrap envelope.
    result["bootstrap"] = boot
    return result


# ---------------------------------------------------------------------------
# Build the complete output table (key-value pairs for MC_Engine)
# ---------------------------------------------------------------------------

def build_output_table(
    raw: SimRawResults,
    risks: list[RiskInput],
    config: SimConfig,
    gp_config: GainPainConfig = None,
    buckets: list = None,
    data_source: str = "MC_Inputs",
) -> list[list]:
    """Build the key-value pair list for MC_Engine results range.

    Primary p-values (p10/p50/p80/p90/mean/std) always reflect the current
    view so MC_Dashboard shows the right numbers for whatever view was run.

    Sub-view columns (bop_pXX, cse_pXX) are computed from the loaded risks
    and reflect meaningful splits only when view=All. When view=Shared they
    equal the primary view (all loaded risks are Shared).

    view_label key lets MC_Dashboard show the correct column header.
    """
    costs = compute_party_costs(raw, risks, config)
    rows = []

    # --- View metadata ---
    view_labels = {
        "All": "All Risks",
        "BOP": "BOP Contractor",
        "CSE": "Owner",
        "Shared": "Shared (Risk Pool)",
        "L2Only": "Event Risks Only (L2)",
    }
    rows.append(["view_label", view_labels.get(config.view, config.view)])
    rows.append(["view", config.view])
    rows.append(["data_source", data_source])

    # --- Primary view percentiles (always matches current view) ---
    # When view=Shared, use pure L2 pool costs (no TIC) for primary P-values.
    # When view=L2Only, use pure L2 costs (all risks, no TIC).
    if config.view in ("Shared", "L2Only"):
        primary_p = _pcts(costs["l2_all"])
    else:
        primary_p = _pcts(costs["total"])
    for k, v in primary_p.items():
        rows.append([k, v])

    # Risk premium: P50 outturn minus TIC. Not meaningful for Shared/L2Only views.
    if config.view in ("Shared", "L2Only"):
        rows.append(["risk_premium", primary_p["p50"]])  # pure L2 P50
    else:
        rows.append(["risk_premium", primary_p["p50"] - config.tic])

    # --- L1-only percentiles (zeros/flat when view=Shared) ---
    l1_p = _pcts(costs["l1"])
    for k, v in l1_p.items():
        rows.append([f"l1_{k}", v])

    # --- BOP sub-view ---
    bop_p = _pcts(costs["bop_total"])
    for k, v in bop_p.items():
        rows.append([f"bop_{k}", v])

    # --- CSE sub-view ---
    cse_p = _pcts(costs["cse_total"])
    for k, v in cse_p.items():
        rows.append([f"cse_{k}", v])

    # --- Shared L2 pool (always computed; useful even in All view) ---
    if config.view == "L2Only":
        shared_p = _pcts(costs["shared_l2"])  # no TIC for L2Only
    else:
        shared_p = _pcts(costs["shared_l2"] + config.tic)
    for k, v in shared_p.items():
        rows.append([f"shared_{k}", v])
    rows.append(["shared_pool_p80",
                 float(np.percentile(costs["shared_l2"], 80))])
    rows.append(["shared_pool_p90",
                 float(np.percentile(costs["shared_l2"], 90))])

    # --- Adequacy and overrun ---
    if config.view in ("Shared", "L2Only"):
        budget = config.pool_budget
        adequacy = float(np.mean(costs["l2_all"] <= budget))
    else:
        budget = config.tic + config.contingency
        adequacy = float(np.mean(costs["total"] <= budget))
    rows.append(["adequacy", adequacy])
    rows.append(["overrun", 1.0 - adequacy])
    rows.append(["n_risks", raw.n_risks])

    # --- Tornado (top 10) ---
    tornado = compute_tornado(raw, risks, buckets=buckets, view=config.view)
    for i, entry in enumerate(tornado):
        rows.append([f"t{i}_id", entry.risk_id])
        rows.append([f"t{i}_desc", entry.description])
        rows.append([f"t{i}_owner", entry.owner])
        rows.append([f"t{i}_var", entry.std_contribution])

    for i in range(len(tornado), 10):
        rows.append([f"t{i}_id", ""])
        rows.append([f"t{i}_desc", ""])
        rows.append([f"t{i}_owner", ""])
        rows.append([f"t{i}_var", 0.0])

    # --- P-level contribution decomposition (top 10) ---
    # Each risk's share of total variance * P-level = $ contribution to
    # the absolute P-level cost. P-level is configurable via MC_Params.
    # Answers: "which risks drive the $14M P80 pool?" (or P50/P90).
    if config.view == "L2Only":
        total_cost = raw.ev_costs.sum(axis=1) if raw.n_risks > 0 else np.zeros(raw.n_iter)
    else:
        total_cost = raw.l1_cost + (
            raw.ev_costs.sum(axis=1) if raw.n_risks > 0 else np.zeros(raw.n_iter)
        )
    base_var = float(np.var(total_cost))
    p_key = f"p{config.reporting_p_level}"
    p_level_value = primary_p[p_key]

    for i, entry in enumerate(tornado):
        if base_var > 0:
            var_share = entry.variance_contribution / base_var
            p_level_contrib = var_share * p_level_value
        else:
            var_share = 0.0
            p_level_contrib = 0.0
        rows.append([f"t{i}_var_share", var_share])
        rows.append([f"t{i}_plevel_contrib", p_level_contrib])

    for i in range(len(tornado), 10):
        rows.append([f"t{i}_var_share", 0.0])
        rows.append([f"t{i}_plevel_contrib", 0.0])

    # Total P-level and top-10 coverage
    top10_plevel_sum = sum(
        (entry.variance_contribution / base_var * p_level_value) if base_var > 0 else 0.0
        for entry in tornado
    )
    rows.append(["plevel_target", config.reporting_p_level])
    rows.append(["plevel_value", p_level_value])
    rows.append(["plevel_top10_sum", top10_plevel_sum])
    rows.append(["plevel_top10_coverage",
                 top10_plevel_sum / p_level_value if p_level_value != 0 else 0.0])

    # --- Convergence ---
    conv = compute_convergence(
        raw,
        view=config.view,
        n_blocks=getattr(config, "bootstrap_n_blocks", 100),
        n_resamples=getattr(config, "bootstrap_n_resamples", 1000),
        # SEEDZERO-01: unset draws. The envelope it seeds carries the seed and is not written
        # to the table, so the table's values do not depend on it.
        seed=resolve_seed(getattr(config, "bootstrap_seed", None), where="bootstrap_seed")[0],
    )
    for k, v in conv.items():
        # Skip the "bootstrap" sub-dict — Excel cells need scalar values; the
        # CI envelope is consumed by charts/notebooks via compute_convergence directly.
        if k == "bootstrap":
            continue
        rows.append([k, v])

    # --- S-curve data (percentiles 1–99) ---
    sc = compute_s_curve(raw, view=config.view)
    for p in range(1, 100):
        rows.append([f"sc_total_{p}", sc[f"sc_total_{p}"]])
        rows.append([f"sc_l1_{p}", sc[f"sc_l1_{p}"]])

    # --- Shared Risk Pool sizing (always computed) ---
    shared_l2 = costs["shared_l2"]

    pool_budget = getattr(config, 'pool_budget', config.contingency)
    rows.append(["pool_budget", pool_budget])

    rows.append(["pool_p50", float(np.percentile(shared_l2, 50))])
    rows.append(["pool_p80", float(np.percentile(shared_l2, 80))])
    rows.append(["pool_p90", float(np.percentile(shared_l2, 90))])
    rows.append(["pool_p95", float(np.percentile(shared_l2, 95))])
    rows.append(["pool_mean", float(np.mean(shared_l2))])
    rows.append(["pool_std", float(np.std(shared_l2))])
    rows.append(["pool_max", float(np.max(shared_l2))])

    rows.append(["pool_adequacy", float(np.mean(shared_l2 <= pool_budget))])

    # SP11a: All risks are shared pool risks.
    shared_idx = list(range(len(risks)))
    pool_n_risks = len(shared_idx)
    pool_n_costed = sum(
        1 for i in shared_idx
        if risks[i].opt_cost != 0 or risks[i].ml_cost != 0 or risks[i].pess_cost != 0
    )
    pool_pct_costed = pool_n_costed / pool_n_risks if pool_n_risks > 0 else 0.0
    rows.append(["pool_n_risks", pool_n_risks])
    rows.append(["pool_n_costed", pool_n_costed])
    rows.append(["pool_pct_costed", pool_pct_costed])
    rows.append(["pool_data_warning", "Yes" if pool_pct_costed < 0.8 else "No"])

    pool_emv = sum(
        risks[i].probability * risks[i].ml_cost
        for i in shared_idx
    )
    rows.append(["pool_emv", pool_emv])

    # S-curve data for pool distribution (percentiles 1-99 of shared L2)
    pool_pctiles = np.percentile(shared_l2, list(range(1, 100)))
    for i, p in enumerate(range(1, 100)):
        rows.append([f"sc_pool_{p}", float(pool_pctiles[i])])

    # --- Gain/pain share ---
    from src.gain_pain import (
        compute_gain_pain, compute_gain_pain_summary,
        find_fair_share, compute_regret, compute_pool_drawdown,
    )
    if gp_config is None:
        gp_config = GainPainConfig()
    gp_raw = compute_gain_pain(costs["total"], gp_config)
    gp_summary = compute_gain_pain_summary(gp_raw, gp_config)

    # Fair share and regret (only when enabled — bisection is O(n_iter × 20))
    gp_extra = {}
    if gp_config.enabled:
        fair_split, fair_asym = find_fair_share(costs["total"], gp_config)
        gp_extra["gp_fair_split"] = fair_split
        gp_extra["gp_fair_asymmetry"] = fair_asym
        gp_extra.update(compute_regret(costs["total"], gp_config))
        # Pool drawdown analysis
        pool_budget = config.pool_budget if hasattr(config, "pool_budget") else 15_000_000.0
        pool_dd = compute_pool_drawdown(shared_l2, pool_budget)
        gp_extra.update(pool_dd)
    else:
        gp_summary = {k: 0.0 for k in gp_summary}
        gp_extra = {
            "gp_fair_split": 0.0, "gp_fair_asymmetry": 0.0,
            "gp_regret_mean": 0.0, "gp_regret_p10": 0.0,
            "gp_regret_p50": 0.0, "gp_regret_p90": 0.0,
            "gp_p_regret_positive": 0.0,
            "gp_pool_p_exhaust": 0.0, "gp_pool_exhaust_pctile": 0.0,
        }

    for k, v in gp_summary.items():
        rows.append([k, v])
    for k, v in gp_extra.items():
        rows.append([k, v])

    return rows


# ---------------------------------------------------------------------------
# CG (Correlation Group) analysis
# ---------------------------------------------------------------------------

def compute_cg_summary(
    raw: SimRawResults,
    risks: list[RiskInput],
    corr_coefficients: dict[str, float],
    cg_descriptions: dict[str, str],
) -> list[dict]:
    """Group risks by correlation group and compute group-level statistics.

    Analyses L2 event risk structure only (raw.ev_costs). Works correctly
    regardless of view setting because ev_costs always contains L2 event
    costs — L1 costs are stored separately in raw.l1_cost.

    No-fallback policy (Beta-17 SSoT cleanup)
    -----------------------------------------
    ``cg_descriptions`` is required and must come from
    :func:`src.openpyxl_reader.read_cg_descriptions` (the register's
    MC_Params CG block — single source of truth). A CG present in
    ``risks`` but missing from ``cg_descriptions`` renders its
    ``cg_description`` cell as an empty string ``""`` — the absence is
    visible to the reader of the deliverable; nothing hidden. There is
    no hardcoded fallback dict in run code (the earlier
    ``defaults.CG_DESCRIPTIONS`` was deleted).

    Returns list of dicts sorted by pct_of_total_var descending.
    """
    if raw.n_risks == 0:
        return []

    total = raw.ev_costs.sum(axis=1)
    base_var = float(np.var(total))

    # Group risk indices by CG
    groups: dict[str, list[int]] = {}
    for i, risk in enumerate(risks):
        cg = risk.correlation_group
        groups.setdefault(cg, []).append(i)

    results = []
    for cg_code in sorted(groups.keys()):
        member_idx = groups[cg_code]
        group_costs = raw.ev_costs[:, member_idx].sum(axis=1)

        # Percentiles
        p50, p80, p90 = np.percentile(group_costs, [50, 80, 90])

        # EMV for this group
        group_emv = sum(
            risks[i].probability * risks[i].ml_cost for i in member_idx
        )

        # Leave-one-GROUP-out variance contribution
        total_without = total - group_costs
        var_without = float(np.var(total_without))
        var_contrib = max(0.0, base_var - var_without)
        pct_of_total = var_contrib / base_var if base_var > 0 else 0.0

        results.append({
            "cg_code": cg_code,
            "cg_description": cg_descriptions.get(cg_code, ""),
            "n_risks": len(member_idx),
            "rho": corr_coefficients.get(cg_code, 0.5),
            "risk_ids": [risks[i].risk_id for i in member_idx],
            "group_p50": float(p50),
            "group_p80": float(p80),
            "group_p90": float(p90),
            "group_mean": float(np.mean(group_costs)),
            "group_std": float(np.std(group_costs)),
            "group_emv": float(group_emv),
            "var_contribution": var_contrib,
            "pct_of_total_var": pct_of_total,
        })

    results.sort(key=lambda d: -d["pct_of_total_var"])
    return results


def compute_cg_mean(
    raw: SimRawResults,
    risks: list[RiskInput],
) -> dict[str, float]:
    """Return {cg_code: mean_cost_dollars} across all iterations, per CG group.

    For each CG group, sum the per-iteration cost contributions of risks in
    that group, then take np.mean across iterations. SP23 — interim Mean
    additive view to mirror the CG Analysis table's existing P-level columns.

    Risks with empty/None correlation_group are skipped (matching the brief's
    spec). On the V8 register, unassigned risks carry the literal string
    "CG_UNASSIGNED" and are therefore included; if a future register revision
    ever leaves correlation_group blank, those risks would be excluded here
    and the sum of per-CG means would fall short of the portfolio mean.
    """
    if raw.n_risks == 0:
        return {}

    cg_means: dict[str, float] = {}
    cg_groups = sorted({r.correlation_group for r in risks if r.correlation_group})
    for cg in cg_groups:
        risk_indices = [i for i, r in enumerate(risks) if r.correlation_group == cg]
        if risk_indices:
            cg_iter_total = raw.ev_costs[:, risk_indices].sum(axis=1)
            cg_means[cg] = float(np.mean(cg_iter_total))
        else:
            cg_means[cg] = 0.0
    return cg_means


def compute_firing_frequency(
    raw: SimRawResults,
    risks: list[RiskInput],
) -> list[dict]:
    """Compute how often each risk fires across all iterations.

    Returns list of dicts, one per COSTED risk only (risks where all three
    cost estimates are zero are excluded — they fire but contribute $0).
    Sorted by simulated_fire_rate descending.
    """
    if raw.n_risks == 0:
        return []

    results = []
    for i, risk in enumerate(risks):
        has_cost = (risk.opt_cost != 0 or risk.ml_cost != 0 or risk.pess_cost != 0)
        if not has_cost:
            continue

        costs_col = raw.ev_costs[:, i]
        fired_mask = costs_col != 0
        fire_count = int(np.sum(fired_mask))
        fire_rate = fire_count / raw.n_iter

        fired_costs = costs_col[fired_mask]
        mean_if_fired = float(np.mean(fired_costs)) if fire_count > 0 else 0.0
        p90_if_fired = float(np.percentile(fired_costs, 90)) if fire_count > 0 else 0.0

        ratio = fire_rate / risk.probability if risk.probability > 0 else 0.0

        results.append({
            "risk_id": risk.risk_id,
            "description": risk.description,
            "owner": risk.owner,
            "cg": risk.correlation_group,
            "input_probability": risk.probability,
            "simulated_fire_rate": fire_rate,
            "fire_rate_ratio": ratio,
            "mean_cost_if_fired": mean_if_fired,
            "p90_cost_if_fired": p90_if_fired,
        })

    results.sort(key=lambda d: -d["simulated_fire_rate"])
    return results


def compute_diversification_effect(
    raw: SimRawResults,
    risks: list[RiskInput],
    p_level: int = 80,
) -> dict:
    """Compute the diversification benefit from spreading risks across CG groups.

    For each CG group, compute P-level of that group's cost array independently.
    Sum those individual P-levels (the "naive" total). Compare against the
    P-level of the combined total. The gap is the diversification benefit —
    always >= 0 due to sub-additivity of percentile risk measures.
    """
    if raw.n_risks == 0:
        return {
            "sum_individual_p": 0.0, "combined_p": 0.0,
            "diversification_benefit": 0.0, "diversification_pct": 0.0,
        }

    total = raw.ev_costs.sum(axis=1)
    combined_p = float(np.percentile(total, p_level))

    # Group risk indices by CG
    groups: dict[str, list[int]] = {}
    for i, risk in enumerate(risks):
        groups.setdefault(risk.correlation_group, []).append(i)

    sum_individual = 0.0
    for member_idx in groups.values():
        group_costs = raw.ev_costs[:, member_idx].sum(axis=1)
        sum_individual += float(np.percentile(group_costs, p_level))

    benefit = sum_individual - combined_p
    pct = benefit / sum_individual if sum_individual > 0 else 0.0

    return {
        "sum_individual_p": sum_individual,
        "combined_p": combined_p,
        "diversification_benefit": benefit,
        "diversification_pct": pct,
    }


# ---------------------------------------------------------------------------
# RBS Level 1 (Risk Breakdown Structure) analysis
# ---------------------------------------------------------------------------

_RBS_UNCATEGORISED = "(Uncategorised)"
_RBS_UNASSIGNED = "(Unassigned)"


def _rbs_l1_key(risk: RiskInput) -> str:
    label = (risk.rbs_l1 or "").strip()
    return label if label else _RBS_UNCATEGORISED


def _rbs_l1_key_unassigned(risk: RiskInput) -> str:
    label = (risk.rbs_l1 or "").strip()
    return label if label else _RBS_UNASSIGNED


def compute_rbs_l1_summary(
    raw: SimRawResults,
    risks: list[RiskInput],
) -> list[dict]:
    """Group risks by RBS Level 1 category and compute group-level statistics.

    Analyses L2 event risk structure only (raw.ev_costs). Re-aggregation of
    already-correlated per-risk cost columns preserves all intra- and cross-
    group correlation — per-category percentiles are faithful conditional
    measures, but they are NOT additive across categories (see
    compute_rbs_l1_diversification).

    Returns list of dicts sorted by pct_of_total_var descending.
    """
    if raw.n_risks == 0:
        return []

    total = raw.ev_costs.sum(axis=1)
    base_var = float(np.var(total))

    groups: dict[str, list[int]] = {}
    for i, risk in enumerate(risks):
        groups.setdefault(_rbs_l1_key(risk), []).append(i)

    results = []
    for rbs_l1 in sorted(groups.keys()):
        member_idx = groups[rbs_l1]
        group_costs = raw.ev_costs[:, member_idx].sum(axis=1)

        p50, p80, p90 = np.percentile(group_costs, [50, 80, 90])

        group_emv = sum(
            risks[i].probability * risks[i].ml_cost for i in member_idx
        )

        total_without = total - group_costs
        var_without = float(np.var(total_without))
        var_contrib = max(0.0, base_var - var_without)
        pct_of_total = var_contrib / base_var if base_var > 0 else 0.0

        results.append({
            "rbs_l1": rbs_l1,
            "n_risks": len(member_idx),
            "risk_ids": [risks[i].risk_id for i in member_idx],
            "group_p50": float(p50),
            "group_p80": float(p80),
            "group_p90": float(p90),
            "group_mean": float(np.mean(group_costs)),
            "group_std": float(np.std(group_costs)),
            "group_emv": float(group_emv),
            "var_contribution": var_contrib,
            "pct_of_total_var": pct_of_total,
        })

    results.sort(key=lambda d: -d["pct_of_total_var"])
    return results


def compute_rbs_l1_diversification(
    raw: SimRawResults,
    risks: list[RiskInput],
    p_level: int = 80,
) -> dict:
    """Diversification gap across RBS L1 categories at a given P-level.

    `diversification_benefit` = sum of per-category P-levels − portfolio P-level.
    Positive when category P-levels overstate portfolio P-level (the intuitive
    diversification case). Can be NEGATIVE for sparse event-risk portfolios at
    tail percentiles, because percentile is not a coherent risk measure — when
    many categories have near-zero per-category P80 but the portfolio
    accumulates many small tail contributions, the portfolio P80 can exceed
    the sum. Reports the gap in either direction.
    """
    if raw.n_risks == 0:
        return {
            "sum_individual_p": 0.0, "combined_p": 0.0,
            "diversification_benefit": 0.0, "diversification_pct": 0.0,
        }

    total = raw.ev_costs.sum(axis=1)
    combined_p = float(np.percentile(total, p_level))

    groups: dict[str, list[int]] = {}
    for i, risk in enumerate(risks):
        groups.setdefault(_rbs_l1_key(risk), []).append(i)

    sum_individual = 0.0
    for member_idx in groups.values():
        group_costs = raw.ev_costs[:, member_idx].sum(axis=1)
        sum_individual += float(np.percentile(group_costs, p_level))

    benefit = sum_individual - combined_p
    pct = benefit / sum_individual if sum_individual > 0 else 0.0

    return {
        "sum_individual_p": sum_individual,
        "combined_p": combined_p,
        "diversification_benefit": benefit,
        "diversification_pct": pct,
    }


def compute_rbs_l1_mean_contribution(
    raw: SimRawResults,
    risks: list[RiskInput],
) -> dict[str, float]:
    """Return {rbs_l1_label: mean_cost_dollars} across all iterations.

    For each RBS L1 category, sum the per-iteration cost contributions of
    risks in that category, then take np.mean across iterations. Analogous
    to compute_rbs_l1_p80_contribution but using np.mean rather than the
    component-VaR conditional-expectation logic. Uses _rbs_l1_key_unassigned
    so the labelling matches the P80 contribution table's row keys.
    """
    if raw.n_risks == 0:
        return {}

    contributions: dict[str, float] = {}
    groups: dict[str, list[int]] = {}
    for i, risk in enumerate(risks):
        groups.setdefault(_rbs_l1_key_unassigned(risk), []).append(i)
    for label, member_idx in groups.items():
        rbs_iter_total = raw.ev_costs[:, member_idx].sum(axis=1)
        contributions[label] = float(np.mean(rbs_iter_total))
    return contributions


def compute_rbs_l1_p80_contribution(
    raw: SimRawResults,
    risks: list[RiskInput],
    p_level: int = 80,
    band_halfwidth: float = 1.0,
    min_band_samples: int = 200,
) -> tuple[list[dict], dict]:
    """Component decomposition of portfolio P_p into RBS L1 contributions.

    For each category, component_i = E[category_total | portfolio_total in
    band around P_p]. The band is [P_{p-hw}, P_{p+hw}] of the portfolio
    distribution. Sum of components reconciles to the portfolio P_p (to
    within band-width tolerance); shares sum to 100% by construction.

    This is the Euler / component-VaR decomposition — unbiased under any
    correlation structure because raw.ev_costs is already post-correlation.

    Parameters
    ----------
    band_halfwidth : percentile half-width (e.g. 1.0 for P79-P81 band)
    min_band_samples : if the initial band has fewer iterations, widen by
        doubling halfwidth (up to 10pp) and log a warning.

    Returns
    -------
    (rows, summary) : rows are sorted by contribution desc; "(Unassigned)"
    is always placed last regardless of magnitude.
    """
    empty_summary = {
        "portfolio_p80": 0.0,
        "sum_of_contributions": 0.0,
        "reconciliation_gap": 0.0,
        "reconciliation_gap_pct": 0.0,
        "band_n_iterations": 0,
        "band_halfwidth_used": band_halfwidth,
    }
    if raw.n_risks == 0:
        return [], empty_summary

    total = raw.ev_costs.sum(axis=1)
    portfolio_p = float(np.percentile(total, p_level))

    hw = band_halfwidth
    band_mask = np.zeros_like(total, dtype=bool)
    for _ in range(6):
        low = float(np.percentile(total, max(0.0, p_level - hw)))
        high = float(np.percentile(total, min(100.0, p_level + hw)))
        band_mask = (total >= low) & (total <= high)
        if band_mask.sum() >= min_band_samples or hw >= 10.0:
            break
        hw *= 2.0
    band_n = int(band_mask.sum())
    if band_n < min_band_samples:
        import logging
        logging.getLogger(__name__).warning(
            "P%d contribution band has only %d samples (halfwidth=%.2fpp). "
            "Increase iterations for tighter decomposition.",
            p_level, band_n, hw,
        )

    groups: dict[str, list[int]] = {}
    for i, risk in enumerate(risks):
        groups.setdefault(_rbs_l1_key_unassigned(risk), []).append(i)

    rows = []
    for label, member_idx in groups.items():
        category_totals = raw.ev_costs[:, member_idx].sum(axis=1)
        component = float(np.mean(category_totals[band_mask])) if band_n > 0 else 0.0
        rows.append({
            "rbs_l1": label,
            "n_risks": len(member_idx),
            "contribution": component,
        })

    sum_contrib = sum(r["contribution"] for r in rows)
    for r in rows:
        r["share_pct"] = (r["contribution"] / sum_contrib * 100.0) if sum_contrib != 0 else 0.0

    assigned = [r for r in rows if r["rbs_l1"] != _RBS_UNASSIGNED]
    unassigned = [r for r in rows if r["rbs_l1"] == _RBS_UNASSIGNED]
    assigned.sort(key=lambda d: -d["contribution"])
    ordered = assigned + unassigned

    gap = sum_contrib - portfolio_p
    gap_pct = gap / portfolio_p if portfolio_p != 0 else 0.0

    summary = {
        "portfolio_p80": portfolio_p,
        "sum_of_contributions": sum_contrib,
        "reconciliation_gap": gap,
        "reconciliation_gap_pct": gap_pct,
        "band_n_iterations": band_n,
        "band_halfwidth_used": hw,
    }
    return ordered, summary


# ---------------------------------------------------------------------------
# Removal impact — what-if analysis
# ---------------------------------------------------------------------------

def compute_removal_impact(
    raw: SimRawResults,
    risks: list[RiskInput],
    top_n: int = 3,
    p_level: int = 80,
) -> list[dict]:
    """Show P-level impact of removing top N tornado risks.

    Total cost = sum of all ev_costs (pure L2, no TIC). For each of the
    top N risks (by variance contribution), compute P-level without that
    risk and report the reduction. No re-simulation needed.

    Cumulative removal is order-dependent: removing risk 1 changes the
    variance landscape, so risk 2's marginal impact depends on risk 1
    already being removed. Individual reductions are NOT additive.
    """
    if raw.n_risks == 0:
        return []

    total = raw.ev_costs.sum(axis=1)
    original_p = float(np.percentile(total, p_level))

    # Get top N risks by variance contribution (same as tornado ordering)
    tornado = compute_tornado(raw, risks, top_n=top_n, view="L2Only")

    # Map risk_id to column index in ev_costs
    id_to_idx = {r.risk_id: i for i, r in enumerate(risks)}

    results = []
    cumulative_removed = np.zeros(raw.n_iter)

    for entry in tornado:
        idx = id_to_idx.get(entry.risk_id)
        if idx is None:
            continue

        risk_col = raw.ev_costs[:, idx]

        # Individual removal
        total_without = total - risk_col
        removed_p = float(np.percentile(total_without, p_level))
        reduction = original_p - removed_p

        # Cumulative removal (sequential)
        cumulative_removed = cumulative_removed + risk_col
        total_cumulative = total - cumulative_removed
        cumulative_p = float(np.percentile(total_cumulative, p_level))
        cumulative_reduction = original_p - cumulative_p

        results.append({
            "risk_id": entry.risk_id,
            "description": entry.description,
            "original_p": original_p,
            "removed_p": removed_p,
            "reduction": reduction,
            "cumulative_p": cumulative_p,
            "cumulative_reduction": cumulative_reduction,
        })

    return results


# ---------------------------------------------------------------------------
# SP17 B2: Canonical EMV scalars for the bridge waterfall
# ---------------------------------------------------------------------------

def compute_emv_simple(risks: list[RiskInput]) -> float:
    """Compute EMV Simple = sum of p * (Opt + ML + Pess) / 3 across risks.

    Canonical project definition per the EMV-vs-MC critical review
    section 3.3 and Step1_Register_Cleanup_Plan.docx section 5.1:
    EV Simple = (Opt + ML + Pess) / 3, EMV Simple = p * EV Simple.

    Skips risks where probability or any cost is None. Caller filters by
    status if required (e.g. Open-only).
    """
    total = 0.0
    for r in risks:
        if r.probability is None:
            continue
        if r.opt_cost is None or r.ml_cost is None or r.pess_cost is None:
            continue
        ev_simple = (r.opt_cost + r.ml_cost + r.pess_cost) / 3.0
        total += r.probability * ev_simple
    return total


def compute_emv_pert(risks: list[RiskInput]) -> float:
    """Compute EMV PERT = sum of p * (Opt + 4*ML + Pess) / 6 across risks.

    Beta-PERT mean weighting per AACE 44R-08. Skip rule and caller
    responsibilities match compute_emv_simple.
    """
    total = 0.0
    for r in risks:
        if r.probability is None:
            continue
        if r.opt_cost is None or r.ml_cost is None or r.pess_cost is None:
            continue
        ev_pert = (r.opt_cost + 4.0 * r.ml_cost + r.pess_cost) / 6.0
        total += r.probability * ev_pert
    return total
