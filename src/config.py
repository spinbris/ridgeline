"""
Dataclasses for Monte Carlo simulation configuration and results.

All parameter structures match the MC_Params and MC_Inputs sheet layouts
in the cost-model workbook. Field names follow the implementation plan
methodology — do not rename without updating reader.py and writer.py.
"""

from dataclasses import dataclass, field
from typing import Optional
import numpy as np


# ---------------------------------------------------------------------------
# Input configuration
# ---------------------------------------------------------------------------

@dataclass
class SimConfig:
    """Global simulation control parameters (MC_Params section A + E)."""
    n_iter: int = 100_000
    seed: int | None = None          # None or 0: drawn per run, recorded (SEEDZERO-01)
    view: str = "All"                # "All" | "BOP" | "CSE"
    tic: float = 300_000_000.0
    contingency: float = 30_000_000.0
    bop_contract: float = 300_000_000.0
    bop_contingency: float = 5_000_000.0
    cse_contingency: float = 5_000_000.0
    party_a_name: str = "BOP Contractor"
    party_b_name: str = "Owner"
    shared_label: str = "Shared"
    programme_seasons: int = 3     # Number of seasonal exposure windows (wet seasons)
    pool_budget: float = 15_000_000.0   # Shared Risk Pool budget ($)
    reporting_p_level: int = 80       # P-level for contribution table (50, 80, or 90)
    # SP18a — Block-bootstrap convergence CI parameters
    bootstrap_n_blocks: int = 100
    bootstrap_n_resamples: int = 1000
    bootstrap_seed: int | None = None   # None or 0: drawn per run (SEEDZERO-01)
    # SP18b — Per-day P-curve parameters (cost-only path; mirror of
    # IntegratedConfig fields for the integrated path)
    per_day_curve_enabled: bool = True
    per_day_cost_bin_size: int = 100_000          # AUD per bin
    per_day_max_cost: int = 200_000_000           # cap for binning
    programme_days: int = 0                        # 0 ⇒ disable curve, warn


@dataclass
class WBSBucket:
    """One Layer 1 WBS cost bucket (MC_Params section B, rows 16-23)."""
    name: str
    base_cost: float
    low_var: float          # e.g. -0.10 means -10%
    high_var: float         # e.g. 0.20 means +20%
    distribution: str       # "Triangular" | "Lognormal" | "PERT"


@dataclass
class ChainConfig:
    """Event chain parameters (MC_Params section C)."""
    c1_trigger_months: float = 3.0
    c1_amplification: float = 2.5
    c2_trigger_weeks: float = 2.0
    c2_cascade_factor: float = 1.5
    # Cascade group parameters (Stage 2) — OFF by default
    cascade_enabled: bool = False       # Set True in MC_Params C32 once agreed
    cascade_slip_rate: float = 1.5      # prob multiplier = 1 + (slip/90)*rate
    cascade_slip_cap: float = 3.0       # max probability multiplier
    cascade_cost_scale_rate: float = 0.5  # extra cost per 180d accumulated slip


@dataclass
class RiskInput:
    """One Layer 2 event risk row (MC_Inputs, one row per risk)."""
    risk_id: str
    description: str
    owner: str              # "BOP Contractor" | "Owner" | "Shared"
    distribution: str       # "Triangular" | "PERT" | "Binary"
    correlation_group: str  # "CG01" .. "CG10" or singleton
    probability: float      # 0.0 – 1.0
    opt_cost: float         # Optimistic cost impact ($)
    ml_cost: float          # Most-likely cost impact ($)
    pess_cost: float        # Pessimistic cost impact ($)
    ml_days: float = 0.0    # Most-likely schedule impact (working days)
    mc_include: bool = True
    basis: str = ""         # Contingent section's Basis of Estimate, free text as elicited
    time_basis: str = ""    # Time section's own Basis of Estimate (REPORT01 D-3)
    recurrence_type: str = ""      # "" | "BINOMIAL" | "POISSON"
    recurrence_param: float = 0.0  # Max Occ for BINOMIAL (0=use programme_seasons); lambda for POISSON
    cascade_group: str = ""         # e.g. "WS-CASCADE" — links risks in same chain
    opt_schedule_days: float = 0.0  # Optimistic schedule impact (days)
    pess_schedule_days: float = 0.0 # Pessimistic schedule impact (days)
    # Qualitative fields for risk card display (Stage B)
    cause: str = ""
    consequence: str = ""
    existing_controls: str = ""
    risk_status: str = "Open"
    direction: str = "Threat"          # "Threat" or "Opportunity" - inferred from description prefix
    rbs_l1: str = ""                   # Risk Breakdown Structure Level 1 (e.g. "_4.External_Risks")
    rbs_l2: str = ""                   # Risk Breakdown Structure Level 2 (e.g. "4.3_Environmental")
    # SP18b — per-day P-curve: project day (1-indexed) on which the risk is
    # planned to occur if it fires. 0 means "unspecified" — per-day curve
    # treats unspecified risks as occurring at programme_days // 2 with a
    # logged warning. Read from the V8 register's optional `Planned_Day`
    # column; absent column ⇒ all risks default to 0.
    planned_day: int = 0

    @property
    def ml_schedule_days(self) -> float:
        """Alias for ml_days — used by cascade logic for consistency."""
        return self.ml_days

    @ml_schedule_days.setter
    def ml_schedule_days(self, value: float) -> None:
        object.__setattr__(self, "ml_days", value)


def _binding_gp_toc() -> float:
    """Resolve the active project's TOC. Imported lazily: src.defaults reaches
    the binding registry, which imports this module."""
    from src.defaults import get_default_gp_toc

    return get_default_gp_toc()


@dataclass
class GainPainConfig:
    """Target cost contract gain/pain share parameters.

    Defaults used when gain/pain is OFF. Parameters will be
    read from MC_Params when the feature is enabled.
    """
    # DAYRATE-02 (ruling A1-7): the per-project TOC contract value is resolved
    # from the ACTIVE project binding, not carried as a literal in engine code.
    # The binding already holds it in headless_config and publishes it through
    # headless_config, which is the correct home - a contract value is a
    # project identifier. QRAXL-01 Coupling C moved defaults.DEFAULT_GP_TOC the
    # same way and missed this field default. Fails loud with no project
    # selected, or under a binding that publishes no TOC.
    toc: float = field(default_factory=_binding_gp_toc)  # Target Outturn Cost ($)
    share_split: float = 0.5          # BOP's share of gain/pain (0.5 = 50/50)
    max_reward_pct: float = 0.05      # Max gainshare as % of TOC (5%)
    max_risk_pct: float = 0.05        # Max painshare as % of TOC (5%)
    enabled: bool = False             # Go/no-go flag — OFF until client agrees


# ---------------------------------------------------------------------------
# Output structures
# ---------------------------------------------------------------------------

@dataclass
class SimRawResults:
    """Raw arrays from a simulation run, before percentile analysis."""
    l1_cost: np.ndarray           # (n_iter,) — Layer 1 total outturn per iteration
    l1_buckets: np.ndarray        # (n_iter, 8) — per-bucket variation
    ev_costs: np.ndarray          # (n_iter, n_risks) — Layer 2 cost per risk per iter
    n_iter: int = 0
    n_risks: int = 0
    seed: int | None = None       # the seed the run drew from (SEEDZERO-01 D2)


@dataclass
class TornadoEntry:
    """One row in the tornado chart."""
    risk_id: str
    description: str
    variance_contribution: float   # Absolute variance reduction ($^2)
    std_contribution: float        # sqrt of above, for display ($)
    owner: str = ""
    layer: str = ""                # "Layer 1" or "Layer 2"


@dataclass
class SingleRunBucket:
    """One Layer 1 bucket in a single-run detail."""
    name: str
    base_cost: float
    var_pct: float
    impact: float
    distribution: str


@dataclass
class SingleRunEvent:
    """One Layer 2 event in a single-run detail."""
    risk_id: str
    description: str
    owner: str
    probability: float             # risk probability used for this draw
    fired: bool
    cost_impact: float
    days_impact: float
    distribution: str = ""        # "Triangular" | "PERT" | "Binary"
    chain_note: str = ""          # e.g. "Chain 1 triggered: elevated P=43%"
    per_occurrence_costs: list = field(default_factory=list)  # per-hit costs for recurring risks


@dataclass
class SingleRunResult:
    """Complete single-iteration output for MC_SingleRun sheet."""
    view: str = "All"              # stakeholder view for this run
    seed: int | None = None        # the seed this scenario drew from (SEEDZERO-01)
    buckets: list = field(default_factory=list)
    events: list = field(default_factory=list)
    l1_total_variation: float = 0.0
    l1_outturn: float = 0.0       # TIC + L1 variation
    l2_total: float = 0.0         # sum of all fired event costs
    total_outturn: float = 0.0    # l1_outturn + l2_total
    # Party breakdowns
    bop_l2: float = 0.0
    cse_l2: float = 0.0
    shared_l2: float = 0.0
    bop_outturn: float = 0.0
    cse_outlay: float = 0.0
    bop_vs_contract: float = 0.0
    bop_vs_contingency: float = 0.0
    cse_vs_contingency: float = 0.0
    # Pool metrics (Shared view)
    pool_budget: float = 0.0
    pool_budget_label: str = "Pool budget"  # dynamic: e.g. "P80 contingency" when sized to P-level
    pool_headroom: float = 0.0
    n_fired: int = 0
    n_risks: int = 0
