"""
Gain/pain share calculation for TOC contract.

For each MC iteration, computes the net financial position of BOP
Contractor and Owner after the gain/pain sharing mechanism applies.

Contract structure:
  If AOC < TOC: gainshare split by share_split, capped at max_reward_pct * TOC
  If AOC > TOC: painshare split by share_split, capped at max_risk_pct * TOC
  Outside caps: excess falls entirely to Owner (owner)

All values in dollars (not millions). Display formatting in writer.py.
"""

import numpy as np

from src.config import GainPainConfig


def compute_gain_pain(
    total_costs: np.ndarray,
    config: GainPainConfig,
) -> dict:
    """Compute gain/pain share outcomes for all iterations.

    Parameters
    ----------
    total_costs : (n_iter,) array — total project outturn per iteration
    config : GainPainConfig — contract parameters

    Returns
    -------
    dict with keys:
      variance        : (n_iter,) — AOC minus TOC (negative = saving)
      bop_net         : (n_iter,) — BOP net position (gain +ve, pain -ve)
      cse_net         : (n_iter,) — CSE net position
      in_gainshare    : (n_iter,) bool — iteration is in gainshare zone
      in_painshare    : (n_iter,) bool — iteration is in painshare zone
      in_neutral      : (n_iter,) bool — variance within deadband (if any)
    """
    max_gain = config.max_reward_pct * config.toc
    max_pain = config.max_risk_pct * config.toc

    variance = total_costs - config.toc

    # Gainshare zone: AOC < TOC (variance < 0)
    saving = np.maximum(-variance, 0)
    bop_gain = np.minimum(saving * config.share_split, max_gain)
    cse_gain = saving - bop_gain

    # Painshare zone: AOC > TOC (variance > 0)
    overrun = np.maximum(variance, 0)
    bop_pain = np.minimum(overrun * config.share_split, max_pain)
    cse_pain = overrun - bop_pain

    # Net position: gain is positive (BOP receives), pain is negative (BOP pays)
    bop_net = bop_gain - bop_pain
    cse_net = cse_gain - cse_pain

    in_gainshare = variance < 0
    in_painshare = variance > 0
    in_neutral = variance == 0

    # Cap-hit flags (tolerance for floating point)
    at_gain_cap = bop_gain >= max_gain - 1e-2
    at_pain_cap = bop_pain >= max_pain - 1e-2

    return {
        "variance": variance,
        "bop_net": bop_net,
        "cse_net": cse_net,
        "in_gainshare": in_gainshare,
        "in_painshare": in_painshare,
        "in_neutral": in_neutral,
        "at_gain_cap": at_gain_cap,
        "at_pain_cap": at_pain_cap,
    }


def compute_gain_pain_summary(
    gp: dict,
    config: GainPainConfig,
) -> dict:
    """Compute summary statistics from gain/pain arrays.

    Returns dict with keys (all dollar values):
      gp_bop_p10, gp_bop_p50, gp_bop_p80, gp_bop_p90
      gp_bop_mean, gp_bop_std
      gp_cse_p10, gp_cse_p50, gp_cse_p80, gp_cse_p90
      gp_cse_mean, gp_cse_std
      gp_p_gainshare   : probability of being in gainshare zone
      gp_p_painshare   : probability of being in painshare zone
      gp_bop_max_gain  : maximum possible BOP gain
      gp_bop_max_pain  : maximum possible BOP pain
      gp_toc           : TOC value (for dashboard display)
    """
    bop = gp["bop_net"]
    cse = gp["cse_net"]

    bop_p10, bop_p50, bop_p80, bop_p90 = np.percentile(bop, [10, 50, 80, 90])
    cse_p10, cse_p50, cse_p80, cse_p90 = np.percentile(cse, [10, 50, 80, 90])

    # Asymmetry analytics
    gain_mask = gp["in_gainshare"]
    pain_mask = gp["in_painshare"]
    p_gain = float(np.mean(gain_mask))
    p_pain = float(np.mean(pain_mask))

    # Expected value contributions (probability-weighted conditional means)
    e_gain = float(np.mean(bop[gain_mask])) * p_gain if p_gain > 0 else 0.0
    e_pain = float(np.mean(np.abs(bop[pain_mask]))) * p_pain if p_pain > 0 else 0.0
    asymmetry = e_gain / e_pain if e_pain > 0 else float("inf")

    # Cap utilisation: fraction of zone iterations that hit the cap
    gain_cap_util = (
        float(np.mean(gp["at_gain_cap"][gain_mask])) if p_gain > 0 else 0.0
    )
    pain_cap_util = (
        float(np.mean(gp["at_pain_cap"][pain_mask])) if p_pain > 0 else 0.0
    )

    return {
        "gp_bop_p10": float(bop_p10),
        "gp_bop_p50": float(bop_p50),
        "gp_bop_p80": float(bop_p80),
        "gp_bop_p90": float(bop_p90),
        "gp_bop_mean": float(np.mean(bop)),
        "gp_bop_std": float(np.std(bop)),
        "gp_cse_p10": float(cse_p10),
        "gp_cse_p50": float(cse_p50),
        "gp_cse_p80": float(cse_p80),
        "gp_cse_p90": float(cse_p90),
        "gp_cse_mean": float(np.mean(cse)),
        "gp_cse_std": float(np.std(cse)),
        "gp_p_gainshare": p_gain,
        "gp_p_painshare": p_pain,
        "gp_bop_max_gain": config.max_reward_pct * config.toc,
        "gp_bop_max_pain": config.max_risk_pct * config.toc,
        "gp_toc": config.toc,
        "gp_e_gain": e_gain,
        "gp_e_pain": e_pain,
        "gp_asymmetry_ratio": asymmetry,
        "gp_gain_cap_util": gain_cap_util,
        "gp_pain_cap_util": pain_cap_util,
    }


def find_fair_share(
    total_costs: np.ndarray,
    config: GainPainConfig,
    tol: float = 0.01,
    lo: float = 0.3,
    hi: float = 0.7,
    max_iter: int = 50,
) -> tuple[float, float]:
    """Bisection search for the share_split where asymmetry_ratio ≈ 1.0.

    Returns (fair_split, final_asymmetry_ratio).
    """
    # dataclasses, not copy: copy.replace is Python 3.13+, and this repo's lock is
    # 3.12 (NUMPY2-01 pins numpy<2, which publishes no cp313 wheel). GainPainConfig
    # is a dataclass, so the two are identical here. CONSOLIDATE-01 step 3.
    from dataclasses import replace

    for _ in range(max_iter):
        mid = (lo + hi) / 2
        trial = replace(config, share_split=mid)
        gp = compute_gain_pain(total_costs, trial)
        summary = compute_gain_pain_summary(gp, trial)
        ratio = summary["gp_asymmetry_ratio"]
        if abs(ratio - 1.0) < tol:
            return mid, ratio
        # ratio > 1: BOP gains more than loses → increase BOP share (more skin)
        if ratio > 1.0:
            lo = mid
        else:
            hi = mid
    return mid, ratio


def compute_regret(
    total_costs: np.ndarray,
    config: GainPainConfig,
    fixed_markup_pct: float = 0.05,
) -> dict:
    """Compare gain/pain position vs fixed-price contingency.

    Regret = bop_net(gain/pain) - fixed_markup * target_cost
    Positive regret: gain/pain was better than fixed price.

    Parameters
    ----------
    total_costs : (n_iter,) array of total project outturn per iteration
    config : GainPainConfig
    fixed_markup_pct : lump-sum contingency markup as fraction of TOC

    Returns
    -------
    dict with gp_regret_* keys
    """
    gp = compute_gain_pain(total_costs, config)
    bop_net = gp["bop_net"]
    fixed_profit = fixed_markup_pct * config.toc
    regret = bop_net - fixed_profit

    r_p10, r_p50, r_p90 = np.percentile(regret, [10, 50, 90])
    return {
        "gp_regret_mean": float(np.mean(regret)),
        "gp_regret_p10": float(r_p10),
        "gp_regret_p50": float(r_p50),
        "gp_regret_p90": float(r_p90),
        "gp_p_regret_positive": float(np.mean(regret > 0)),
    }


def compute_pool_drawdown(
    shared_l2: np.ndarray,
    pool_budget: float,
) -> dict:
    """Analyse shared risk pool drawdown.

    Parameters
    ----------
    shared_l2 : (n_iter,) array — total shared L2 costs per iteration
    pool_budget : float — pool budget in dollars

    Returns
    -------
    dict with gp_pool_* keys
    """
    p_exhaust = float(np.mean(shared_l2 > pool_budget))
    # Find the percentile at which the pool exhausts
    if p_exhaust > 0:
        # Percentile where shared_l2 = pool_budget
        exhaust_pctile = float(
            np.searchsorted(np.sort(shared_l2),
                            pool_budget) / len(shared_l2) * 100
        )
    else:
        exhaust_pctile = 100.0  # pool never exhausted

    return {
        "gp_pool_p_exhaust": p_exhaust,
        "gp_pool_exhaust_pctile": exhaust_pctile,
    }
