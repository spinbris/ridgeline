"""
Core Monte Carlo simulation engine.

Two-layer integrated model run in a single pass per iteration:
  Layer 1 — price/volume risk: continuous uncertainty in 8 WBS cost buckets
  Layer 2 — event risks: discrete events from the risk register

The layers share a correlation structure via correlation groups (CG01–CG10).
Two explicit event chains modify Layer 2 probabilities conditionally.

Ported from MC_CodeRef Cell 2 (the cost-model workbook).
All iteration logic is vectorized numpy — no Python loops over iterations.
"""

import warnings

import numpy as np

from src.config import (
    SimConfig, WBSBucket, ChainConfig, RiskInput, SimRawResults,
)
from src.distributions import (
    triangular_from_uniform, pert_from_uniform, lognormal_from_uniform,
    sample_cost,
)
from src.correlations import (
    build_risk_uniform_matrix, generate_wbs_uniforms,
)
from src.rng_streams import resolve_seed


class MonteCarloEngine:
    """Monte Carlo simulation engine for project cost risk.

    Parameters
    ----------
    config : SimConfig — iteration count, TIC, contingency, stakeholder view
    buckets : list[WBSBucket] — 8 Layer 1 WBS cost buckets
    chains : ChainConfig — event chain trigger thresholds and multipliers
    risks : list[RiskInput] — Layer 2 event risks (already filtered by view)
    corr_coefficients : dict — CG code → rho (e.g. {"CG01": 0.6})
    seed : int | None — random seed; None or 0 draws one, recorded on the result (SEEDZERO-01)
    wbs_rho : float — cross-bucket correlation for Layer 1 (default from defaults.py)
    chain_risk_ids : dict — chain role to risk ID mapping (default from defaults.py)
    """

    def __init__(
        self,
        config: SimConfig,
        buckets: list[WBSBucket],
        chains: ChainConfig,
        risks: list[RiskInput],
        corr_coefficients: dict[str, float],
        seed: int | None = None,
        wbs_rho: float | None = None,
        chain_risk_ids: dict | None = None,
    ):
        from src.defaults import CHAIN_RISK_IDS
        self.config = config
        self.buckets = buckets
        self.chains = chains
        self.risks = risks
        self.corr_coefficients = corr_coefficients
        self.n_iter = config.n_iter
        self.n_risks = len(risks)
        # SEEDZERO-01 D2: an unset seed is drawn here and recorded on the result. It used to be
        # default_rng(None), a run nobody could reproduce because its seed was never known.
        self.seed, self.seed_source = resolve_seed(seed, where="src.simulation.MonteCarloEngine")
        self.rng = np.random.default_rng(self.seed)
        # Stage 4 F-27 (08/09/2026, first-rank): the bucket correlation is resolved where it is
        # used, in _run_layer1, and only when a correlated draw needs it. Resolving it here asked the
        # active binding for headless_config on a path that passes no buckets at all - and the road
        # binding omits headless_config on purpose - so the deliverable could not run a third
        # project. CHAIN_RISK_IDS stays: it has a generic all-None fallback and never raises.
        self.wbs_rho = wbs_rho
        self.chain_ids = chain_risk_ids or CHAIN_RISK_IDS

    # ------------------------------------------------------------------
    # Layer 1 — WBS price/volume variation
    # ------------------------------------------------------------------

    def _run_layer1(self) -> tuple[np.ndarray, np.ndarray]:
        """Simulate Layer 1 WBS bucket variations.

        Returns
        -------
        l1_cost : (n_iter,) total outturn = TIC + sum of bucket variations
        l1_buckets : (n_iter, n_buckets) per-bucket dollar variation
        """
        n_buckets = len(self.buckets)
        rho = self.wbs_rho
        if rho is None and n_buckets > 1:
            # The only reader of the value: generate_correlated_uniforms with two or more
            # variables. Zero buckets returns an empty array and one bucket draws independently,
            # neither touching rho, so a project with no Layer-1 buckets never asks its binding.
            from src.defaults import WBS_CROSS_BUCKET_RHO
            rho = WBS_CROSS_BUCKET_RHO
        pu = generate_wbs_uniforms(self.n_iter, n_buckets, rho, self.rng)
        l1_buckets = np.zeros((self.n_iter, n_buckets))

        for k, bucket in enumerate(self.buckets):
            lo = bucket.low_var
            hi = bucket.high_var
            mode = (lo + hi) / 2.0
            dist = bucket.distribution.strip().lower()

            if dist == "lognormal":
                pct = lognormal_from_uniform(pu[:, k], lo, hi)
            elif dist == "pert":
                pct = pert_from_uniform(pu[:, k], lo, mode, hi)
            else:
                # Default: Triangular
                pct = triangular_from_uniform(pu[:, k], lo, mode, hi)

            l1_buckets[:, k] = bucket.base_cost * pct

        l1_cost = self.config.tic + l1_buckets.sum(axis=1)
        return l1_cost, l1_buckets

    # ------------------------------------------------------------------
    # Layer 2 — event risk firing and magnitude sampling
    # ------------------------------------------------------------------

    def _run_layer2(self) -> np.ndarray:
        """Simulate Layer 2 event risks.

        Returns
        -------
        ev_costs : (n_iter, n_risks) cost impact per risk per iteration
                   Zero where the event did not fire.

        Supports three recurrence modes:
        - "" (default): single Bernoulli draw per iteration
        - "BINOMIAL": Binomial(n, p) occurrences with independent severity draws
        - "POISSON": Poisson(lambda) occurrences with independent severity draws
        """
        if self.n_risks == 0:
            return np.zeros((self.n_iter, 0))

        # Correlated uniforms for event firing (respects CG groups)
        fire_u = build_risk_uniform_matrix(
            self.n_iter, self.risks, self.corr_coefficients, self.rng,
        )

        # Independent uniforms for magnitude sampling (separate from firing)
        mag_u = self.rng.uniform(0, 1, (self.n_iter, self.n_risks))

        ev_costs = np.zeros((self.n_iter, self.n_risks))

        for i, risk in enumerate(self.risks):
            rtype = risk.recurrence_type.strip().upper()

            if rtype == "BINOMIAL":
                # Binomial(n, p) occurrences per iteration
                max_occ = int(risk.recurrence_param)
                if max_occ <= 0:
                    max_n = self.config.programme_seasons
                else:
                    max_n = min(max_occ, self.config.programme_seasons)
                occurrences = self.rng.binomial(
                    n=max_n, p=risk.probability, size=self.n_iter,
                )
                # Vectorised severity pool: draw max_n costs per iteration
                pool_u = self.rng.uniform(size=self.n_iter * max_n)
                mag_pool = sample_cost(
                    pool_u, risk.opt_cost, risk.ml_cost, risk.pess_cost,
                    risk.distribution,
                ).reshape(self.n_iter, max_n)
                # Mask out draws beyond actual occurrence count
                mask = np.arange(max_n)[None, :] < occurrences[:, None]
                ev_costs[:, i] = (mag_pool * mask).sum(axis=1)

            elif rtype == "POISSON":
                # Validation warning if probability != 1.0
                if risk.probability != 1.0:
                    warnings.warn(
                        f"Risk {risk.risk_id}: POISSON recurrence ignores "
                        f"probability field ({risk.probability}); "
                        f"lambda={risk.recurrence_param} drives frequency.",
                        stacklevel=2,
                    )
                occurrences = self.rng.poisson(
                    lam=risk.recurrence_param, size=self.n_iter,
                )
                # Cap pool size to avoid excess memory
                pool_n = min(int(np.max(occurrences)) * 2, 20) if np.max(occurrences) > 0 else 1
                pool_u = self.rng.uniform(size=self.n_iter * pool_n)
                mag_pool = sample_cost(
                    pool_u, risk.opt_cost, risk.ml_cost, risk.pess_cost,
                    risk.distribution,
                ).reshape(self.n_iter, pool_n)
                # Clamp occurrences to pool width
                clamped = np.minimum(occurrences, pool_n)
                mask = np.arange(pool_n)[None, :] < clamped[:, None]
                ev_costs[:, i] = (mag_pool * mask).sum(axis=1)

            else:
                # Default: single Bernoulli draw (unchanged behaviour)
                fired = fire_u[:, i] < risk.probability
                magnitude = sample_cost(
                    mag_u[:, i], risk.opt_cost, risk.ml_cost, risk.pess_cost,
                    risk.distribution,
                )
                ev_costs[:, i] = fired * magnitude

        return ev_costs

    # ------------------------------------------------------------------
    # Event chains
    # ------------------------------------------------------------------

    def _find_risk_index(self, risk_id: str) -> int | None:
        """Find index of a risk by its ID. Returns None if not found."""
        for i, r in enumerate(self.risks):
            if r.risk_id == risk_id:
                return i
        return None

    def _apply_chain1(self, ev_costs: np.ndarray) -> np.ndarray:
        """Chain 1: planning delay → wet season weather.

        If trigger fires AND implied delay >= trigger threshold (months),
        resample target with amplified probability (capped at 0.95).

        Duration proxy from PY() code:
            months = (|cost| / max(|pess|, 1)) * 8.0
        """
        idx_trigger = self._find_risk_index(self.chain_ids["c1_trigger"])
        idx_target = self._find_risk_index(self.chain_ids["c1_target"])

        if idx_trigger is None or idx_target is None:
            return ev_costs

        trigger_risk = self.risks[idx_trigger]
        target_risk = self.risks[idx_target]

        # Duration proxy: map cost to months
        max_pess = max(abs(trigger_risk.pess_cost), 1.0)
        months = (np.abs(ev_costs[:, idx_trigger]) / max_pess) * 8.0

        # Chain triggers where: event fired AND duration >= threshold
        chain_mask = (ev_costs[:, idx_trigger] != 0) & (
            months >= self.chains.c1_trigger_months
        )

        if not np.any(chain_mask):
            return ev_costs

        # Amplified probability (capped at 0.95)
        elevated_prob = min(
            target_risk.probability * self.chains.c1_amplification, 0.95
        )

        # Resample target event for chain-triggered iterations
        n_chain = int(np.sum(chain_mask))
        new_fire = self.rng.uniform(0, 1, n_chain) < elevated_prob
        new_mag = sample_cost(
            self.rng.uniform(0, 1, n_chain),
            target_risk.opt_cost, target_risk.ml_cost, target_risk.pess_cost,
            target_risk.distribution,
        )
        ev_costs[chain_mask, idx_target] = new_fire * new_mag

        return ev_costs

    def _apply_chain2(self, ev_costs: np.ndarray) -> np.ndarray:
        """Chain 2: site establishment delay → downstream cascade.

        If trigger fires AND implied delay >= trigger threshold (weeks),
        resample targets with amplified probability.

        Duration proxy:
            weeks = (|cost| / max(|pess|, 1)) * 4.0
        """
        idx_trigger = self._find_risk_index(self.chain_ids["c2_trigger"])
        if idx_trigger is None:
            return ev_costs

        trigger_risk = self.risks[idx_trigger]
        max_pess = max(abs(trigger_risk.pess_cost), 1.0)
        weeks = (np.abs(ev_costs[:, idx_trigger]) / max_pess) * 4.0

        chain_mask = (ev_costs[:, idx_trigger] != 0) & (
            weeks >= self.chains.c2_trigger_weeks
        )

        if not np.any(chain_mask):
            return ev_costs

        n_chain = int(np.sum(chain_mask))

        for target_id in self.chain_ids["c2_targets"]:
            idx_target = self._find_risk_index(target_id)
            if idx_target is None:
                continue

            target_risk = self.risks[idx_target]
            elevated_prob = min(
                target_risk.probability * self.chains.c2_cascade_factor, 0.95
            )

            new_fire = self.rng.uniform(0, 1, n_chain) < elevated_prob
            new_mag = sample_cost(
                self.rng.uniform(0, 1, n_chain),
                target_risk.opt_cost, target_risk.ml_cost, target_risk.pess_cost,
                target_risk.distribution,
            )
            ev_costs[chain_mask, idx_target] = new_fire * new_mag

        return ev_costs

    # ------------------------------------------------------------------
    # Cascade groups (Stage 2)
    # ------------------------------------------------------------------

    def _apply_cascade_groups(self, ev_costs: np.ndarray) -> np.ndarray:
        """Recursive temporal cascade: running slip elevates downstream P.

        For each cascade group, risks are processed in register row order.
        A running slip accumulator tracks schedule impact from fired risks
        and elevates the probability of downstream risks in the same group.
        """
        # Find all unique non-empty cascade groups
        groups: dict[str, list[int]] = {}
        for i, risk in enumerate(self.risks):
            g = risk.cascade_group.strip()
            if g:
                groups.setdefault(g, []).append(i)

        for group_name, indices in groups.items():
            # running_slip: (n_iter,) accumulated days per iteration
            running_slip = np.zeros(self.n_iter)

            for i in indices:
                risk = self.risks[i]

                has_schedule = (risk.ml_schedule_days > 0 or
                                risk.pess_schedule_days > 0)

                if np.any(running_slip > 0):
                    # Downstream risk: resample with slip-adjusted probability
                    multiplier = np.clip(
                        1.0 + (running_slip / 90.0) * self.chains.cascade_slip_rate,
                        1.0, self.chains.cascade_slip_cap,
                    )

                    base_p = risk.probability
                    adjusted_p = np.minimum(base_p * multiplier, 0.95)

                    new_u = self.rng.uniform(size=self.n_iter)
                    fired = new_u < adjusted_p

                    # Cost scaling: downstream costs scale with accumulated slip
                    cost_scale = 1.0 + (running_slip / 180.0) * self.chains.cascade_cost_scale_rate

                    new_mag = sample_cost(
                        self.rng.uniform(size=self.n_iter),
                        risk.opt_cost, risk.ml_cost, risk.pess_cost,
                        risk.distribution,
                    )
                    ev_costs[:, i] = fired * new_mag * cost_scale
                else:
                    # First risk (no upstream slip): keep _run_layer2 draw
                    fired = ev_costs[:, i] != 0

                # Update running_slip for iterations where this risk fired
                if has_schedule:
                    opt_d = risk.opt_schedule_days if risk.opt_schedule_days > 0 else risk.ml_schedule_days * 0.5
                    pess_d = risk.pess_schedule_days if risk.pess_schedule_days > 0 else risk.ml_schedule_days * 2.0
                    schedule_u = self.rng.uniform(size=self.n_iter)
                    schedule_impact = sample_cost(
                        schedule_u, opt_d, risk.ml_schedule_days, pess_d,
                        "Triangular",
                    )
                    running_slip += fired * schedule_impact

        return ev_costs

    # ------------------------------------------------------------------
    # Main simulation run
    # ------------------------------------------------------------------

    def run(self) -> SimRawResults:
        """Run the full Monte Carlo simulation.

        Sequence (matching Cell 2 exactly):
        1. Layer 1 WBS variation (8 buckets, correlated)
        2. Layer 2 event risk firing and magnitude sampling (correlated by CG)
        3. Chain 1: planning delay → weather amplification
        4. Chain 2: site establishment → downstream cascade
        5. Package results

        Returns
        -------
        SimRawResults with l1_cost, l1_buckets, ev_costs arrays
        """
        # Layer 1 — excluded for Shared-only view (L1 is BOP contractor risk)
        #           excluded for L2Only view (pure event risk analysis, no TIC)
        if self.config.view == "Shared":
            l1_cost = np.full(self.n_iter, self.config.tic)
            l1_buckets = np.zeros((self.n_iter, len(self.buckets)))
        elif self.config.view == "L2Only":
            l1_cost = np.zeros(self.n_iter)
            l1_buckets = np.zeros((self.n_iter, len(self.buckets)))
        else:
            l1_cost, l1_buckets = self._run_layer1()

        # Layer 2
        ev_costs = self._run_layer2()

        # Event chains (modify ev_costs in place)
        if self.n_risks > 0:
            ev_costs = self._apply_chain1(ev_costs)
            ev_costs = self._apply_chain2(ev_costs)
            if self.chains.cascade_enabled:
                ev_costs = self._apply_cascade_groups(ev_costs)

        return SimRawResults(
            l1_cost=l1_cost,
            l1_buckets=l1_buckets,
            ev_costs=ev_costs,
            n_iter=self.n_iter,
            n_risks=self.n_risks,
            seed=self.seed,
        )
