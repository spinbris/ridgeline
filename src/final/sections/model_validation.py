"""Model-validation evidence: did the sampler do what the register asked? (REPORT01 F-B)

GAP01 F-B: the report showed nothing comparing the simulation's behaviour against its
inputs - no firing frequency against elicited probability, no sampled-against-elicited
magnitude. The cross-validation gate proves the two surfaces agree with **each other**,
which is a different claim: two surfaces can agree and both mis-sample.

Two things a reader has to be told, or the tables mislead:

**The realised rate is post-chain.** The cost arm's mask comes back from
``apply_chain_logic``, which resamples a chained risk at an elevated probability. Such a
risk *should* fire more often than its register cell says. Printed without that note it
reads as a sampler defect.

**A risk fires once per iteration, for both arms** (SPEC R-10, METHFIRE-01). The schedule
replay fires on the cost arm's decisions, so one table against ``Probability`` covers both.
The section says whether this run's schedule record actually matched - checked, not assumed.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np

#: Said once, on the page, beside the tables.
FIRING_BASIS_NOTE = (
    "Realised firing is measured after chain logic. A risk that a chain resamples at an "
    "elevated probability is expected to fire more often than its register cell, and a "
    "difference on such a risk is the chain working, not the sampler failing."
)

ONE_FIRE_DRAW_NOTE = (
    "Each risk has one probability and fires at most once per iteration. The schedule "
    "simulation uses the same firing decisions as the cost simulation, so a risk that "
    "affects both carries its cost and its delay together, or neither."
)

#: Said in the note's place when the check fails: the page must not assert one draw over a run
#: it is untrue of.
FIRE_DRAW_MISMATCH_NOTE = (
    "WARNING: on this run the schedule simulation's firing record does not match the cost "
    "simulation's for at least one risk, so the two did not fire on one draw as the method "
    "requires. Do not rely on this run's schedule figures."
)

MAGNITUDE_NOTE = (
    "Elicited mean is the mean of the distribution the register declares for that risk - "
    "not one formula applied to all of them: the engine samples PERT, triangular, "
    "lognormal or binary according to the Distribution column, and their means differ. "
    "Sampled mean is taken over the iterations where the risk fired, so it is comparable "
    "with the elicited figure rather than diluted by the iterations where nothing "
    "happened."
)

#: Subdivision limit for :func:`elicited_mean`'s adaptive quadrature. Generous: the
#: integrand is a quantile function, smooth except near u=1 for the unbounded case.
_QUADRATURE_LIMIT = 200

#: A risk that never fired has no sampled magnitude to report. Said in words, because a
#: blank or a zero both read as "the magnitude was zero", which is a different claim.
NEVER_FIRED = "Did not fire"


def elicited_mean(opt: float, ml: float, pess: float, distribution: str) -> float:
    """The mean of the distribution the engine would actually sample for this risk.

    Derived from the engine's own sampler rather than from a formula per distribution.
    ``src.distributions.sample_cost`` dispatches on the register's Distribution column -
    PERT and Binary/PERT, Binary, Lognormal, and triangular as the default - and those
    means are not the same number. A table of four closed forms here would be a second
    derivation of the engine's behaviour, free to drift from it the moment a fifth
    distribution is added or the lognormal parameterisation changes, and the drift would
    surface as a phantom sampler deviation in the very table built to detect a real one.

    So: integrate the sampler over the unit interval. ``E[X] = integral of F-inverse(u)
    du``, and the sampler *is* F-inverse. No RNG, no seed, no dependence on the run; it
    cannot disagree with the engine, and a distribution added later is covered without
    touching this module.

    **Adaptive, not a fixed grid.** A uniform midpoint grid truncates the tail of an
    unbounded distribution, and lognormal - the shape reserved for catastrophic-tail
    risks - is unbounded. Measured 12/09/2026 against a 2,000,000-point reference: a
    10,000-point midpoint grid was 0.51% low at a 100:1 pessimistic-to-optimistic ratio
    and 2.64% low at 500:1, while bounded shapes were exact to six figures. That bias
    prints as a phantom positive Difference in the very table built to detect a real one.
    Adaptive quadrature brings the same cases to 0.016% and 0.17%.
    """
    from scipy import integrate

    from src.distributions import sample_cost

    def f(u: float) -> float:
        return float(np.asarray(sample_cost(np.array([u]), opt, ml, pess, distribution))[0])

    value, _ = integrate.quad(f, 0.0, 1.0, limit=_QUADRATURE_LIMIT)
    return float(value)


def _rate_rows(
    fired: np.ndarray,
    risk_ids: list[str],
    elicited: dict[str, float],
    titles: dict[str, str],
) -> list[dict[str, Any]]:
    """One firing row per column of ``fired``, in column order."""
    rows: list[dict[str, Any]] = []
    for i, rid in enumerate(risk_ids):
        realised = float(fired[:, i].mean())
        p = elicited.get(rid)
        rows.append({
            "Risk": rid,
            "Title": titles.get(rid, rid),
            "Elicited probability": "n/a" if p is None else f"{p * 100:.1f}%",
            "Realised firing": f"{realised * 100:.1f}%",
            "Difference": "n/a" if p is None else f"{(realised - p) * 100:+.1f} pp",
        })
    return rows


def _schedule_fires_match_cost(
    fired: np.ndarray, cost_ids: list[str], sched_fired: np.ndarray, sched_ids: list[str],
) -> bool | None:
    """Whether every schedule driver fired on exactly its cost-arm risk's iterations.

    ``None`` when there is no schedule record to check. A driver with no cost-arm column is a
    mismatch, not a skip: the one-draw claim is about every schedule risk.
    """
    if not (sched_fired.size and sched_ids):
        return None
    if not (fired.size and cost_ids) or sched_fired.shape[0] != fired.shape[0]:
        return False
    index = {rid: i for i, rid in enumerate(cost_ids)}
    return all(
        rid in index and np.array_equal(sched_fired[:, j], fired[:, index[rid]])
        for j, rid in enumerate(sched_ids)
    )


def build_model_validation_section(
    stage3_result: dict[str, Any],
    risks: Iterable[Any],
    risk_titles: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the Stage 3 standalone's model-validation payload.

    ``stage3_result`` is the ``_stage3_beta_dict`` shape: the adapter's projection plus
    the binding's own keys. It supplies ``fired_array`` / ``risk_ids_all`` for the cost
    arm and ``schedule_fired_array`` / ``schedule_fired_risk_ids`` for the schedule arm, which
    is checked against the cost arm column by column rather than tabled separately.

    Data only - no rendering.
    """
    titles = risk_titles or {}
    risk_list = list(risks)
    cost_elicited = {r.risk_id: float(r.probability) for r in risk_list}

    fired = np.asarray(stage3_result.get("fired_array", np.zeros((0, 0), dtype=bool)))
    cost_ids = list(stage3_result.get("risk_ids_all", []))
    sched_fired = np.asarray(
        stage3_result.get("schedule_fired_array", np.zeros((0, 0), dtype=bool)))
    sched_ids = list(stage3_result.get("schedule_fired_risk_ids", []))

    cost_rows = (
        _rate_rows(fired, cost_ids, cost_elicited, titles)
        if fired.size and cost_ids else []
    )
    schedule_fires_match_cost = _schedule_fires_match_cost(fired, cost_ids, sched_fired, sched_ids)

    # Sampled-against-elicited magnitude, cost arm. Conditioned on firing, which is what
    # makes it comparable with the elicited three-point input.
    per_risk = np.asarray(
        stage3_result.get("per_risk_cost_array", np.zeros((0, 0), dtype=float)))
    by_id = {r.risk_id: r for r in risk_list}
    magnitude_rows: list[dict[str, Any]] = []
    if per_risk.size and fired.size:
        for i, rid in enumerate(cost_ids):
            risk = by_id.get(rid)
            if risk is None:
                continue
            distribution = str(getattr(risk, "distribution", "") or "PERT")
            elicited = elicited_mean(
                float(risk.opt_cost), float(risk.ml_cost), float(risk.pess_cost),
                distribution)
            mask = fired[:, i]
            if not mask.any():
                sampled_text, diff_text = NEVER_FIRED, NEVER_FIRED
            else:
                sampled_mean = float(per_risk[mask, i].mean())
                sampled_text = f"{sampled_mean / 1e6:,.3f}"
                diff_text = (
                    f"{(sampled_mean - elicited) / elicited * 100:+.1f}%"
                    if elicited else "n/a"
                )
            magnitude_rows.append({
                "Risk": rid,
                "Title": titles.get(rid, rid),
                # Named on the row: two risks with identical three-point inputs and
                # different distributions have different elicited means, and a reader
                # comparing them needs to see why.
                "Distribution": distribution,
                "Elicited mean ($M)": f"{elicited / 1e6:,.3f}",
                "Sampled mean when fired ($M)": sampled_text,
                "Difference": diff_text,
            })

    n_iter = int(fired.shape[0]) if fired.size else 0
    return {
        "page_model_validation": {
            "n_iterations": n_iter,
            "firing_table": cost_rows,
            "schedule_fires_match_cost": schedule_fires_match_cost,
            "cost_magnitude_table": magnitude_rows,
            "firing_basis_note": FIRING_BASIS_NOTE,
            # Asserted only where checked: with no schedule record there is nothing to say.
            "one_fire_draw_note": {True: ONE_FIRE_DRAW_NOTE, False: FIRE_DRAW_MISMATCH_NOTE}.get(
                schedule_fires_match_cost, ""),
            "magnitude_note": MAGNITUDE_NOTE,
        }
    }
