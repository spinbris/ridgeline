"""Probabilistic escalation, correlated with the Layer-1 factors - ESC-01 part B.

**What this does.** Turns a financial-year cash flow (`src/cash_flow.py`, part A) into an
escalation addend, so that base + contingency + escalation = outturn (GN4-12/03/23/32).

**Sampled per iteration and correlated with the Layer-1 factors. Director ruling 06/09/2026.**

**This module never draws its own uniform** - `escalation_multipliers` takes it as an argument.
A module holding its own `Generator` would be independent of cost no matter what any comment
claimed, which is the defect the stage 7 part B numerics review blocked.

**That is necessary for the ruling but not sufficient, and the difference is stated rather than
glossed.** Taking the uniform as an argument only means this module *cannot* break the
correlation; it does not establish that any caller supplies a correlated one. Today **none can**:
`run_layer1_base` draws `u_corr` locally and returns only `base_array`, the diagnostics and the
per-factor means, so the run's draw is not reachable, and `validate_layer1` requires every
`corr_names` entry to be a factor with a non-empty scope, which `"Escalation"` is not. Delivering
the ruling therefore needs a change to `src/layer1_factors.py` that is **not in this module** -
raised as ESCCORR-01 and owed before escalation is wired to anything published. Until then a
caller could only pass an independent draw, which is why nothing calls this yet.

Escalation belongs in that correlation block on its face: it is driven by commodity prices and
labour rates, and so are the Layer-1 factors it sits beside. Drawing it independently would assert
that the two are unrelated, which nobody believes.

**Compounding.** A financial year's index ratio is cumulative - FY3's is
``(1+r1)(1+r2)(1+r3)`` - and **one rate path is drawn per iteration**, not one rate per year per
iteration. Annual escalation is serially correlated in reality; independent annual draws would
average out across a long programme into an implausibly narrow band, understating exactly the tail
a P90 exists to show.

**Not built here, and stated so it is not assumed:** the register carries no escalation rate and
no base date (`MC_Params` has neither). Wiring these to the register is contract **1.4 -> 1.5**,
a scaffolder change, and it triggers the M1 migration policy ruled on 05/09 - specialist
re-scaffolds, client re-enters. This module takes its rates as an argument so that the arithmetic
can be built, tested and reviewed before that bump is spent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from src.cash_flow import PhasedCost
from src.layer1_factors import fit_pert_from_percentiles, nearest_psd, pert_from_uniform

#: The name escalation takes in the Layer-1 correlation matrix. A caller adds a row and column
#: under this name; `corr_names` then carries it alongside the other factors and one Cholesky
#: draw covers them all.
ESCALATION_FACTOR_NAME = "Escalation"

#: `FY2026-27`. Matched rather than sliced - see `_fy_start_year`.
_FY_PATTERN = re.compile(r"FY(\d{4})-(\d{2})")


class EscalationError(RuntimeError):
    """A precondition failed. Never a silent fallback: an escalation that quietly defaults is a
    number added to a client's outturn that nobody chose."""


@dataclass(frozen=True)
class EscalationRate:
    """One annual escalation rate, as percentiles of a proportional increase.

    Read the same way Layer-1 factors are - `opt`/`p90` are P10/P90 of the rate, `ml` the mode -
    so a register supplying escalation supplies it in the shape it already uses for factors,
    rather than in a second convention nobody remembers.
    """

    opt: float
    ml: float
    p90: float


@dataclass(frozen=True)
class EscalatedCashFlow:
    """A phased cash flow, escalated. Every component is kept so the arithmetic is checkable."""

    real_by_financial_year: dict[str, float]
    #: (n_iter,) escalated total across all years, per iteration.
    nominal_total: np.ndarray
    #: (n_iter,) the escalation addend alone - nominal minus real.
    escalation_addend: np.ndarray
    #: Mean cumulative index per financial year, for disclosure.
    mean_index_by_financial_year: dict[str, float]
    base_date_financial_year: str
    rate_source: str

    @property
    def real_total(self) -> float:
        return sum(self.real_by_financial_year.values())


def _fy_start_year(fy: str) -> int:
    """The opening calendar year of an `FY2026-27` label, refusing anything else.

    Parsed rather than sliced: `int(fy[2:6])` would read a malformed label as a plausible year and
    escalate by a wrong number of years without saying so.
    """
    m = _FY_PATTERN.fullmatch(fy)
    if m is None:
        raise EscalationError(
            f"{fy!r} is not a financial year label; expected the form 'FY2026-27'")
    return int(m.group(1))


def escalation_multipliers(
    *,
    uniform: np.ndarray,
    rate: EscalationRate,
    financial_years: Sequence[str],
    base_financial_year: str,
) -> dict[str, np.ndarray]:
    """Cumulative index ratio per financial year, one rate path per iteration.

    ``uniform`` is (n_iter,) in [0, 1] and **must come from the caller's correlated draw** - see
    the module docstring. One uniform gives one rate for the whole path, which is the ruled
    compounding model: the draw says "this iteration is a high-escalation world", and every year
    in it escalates at that world's rate.

    Years at or before ``base_financial_year`` carry an index of exactly 1.0: money spent at the
    base date has not escalated, and multiplying it by anything would be double counting the base.
    """
    u = np.asarray(uniform, dtype=float)
    if u.ndim != 1:
        raise EscalationError(f"uniform must be one-dimensional, got shape {u.shape}")
    if u.size and (u.min() < 0.0 or u.max() > 1.0):
        raise EscalationError("uniform is not in [0, 1]; it is not a copula draw")
    if base_financial_year not in financial_years:
        raise EscalationError(
            f"base financial year {base_financial_year!r} is not among the cash flow's years "
            f"{list(financial_years)}. Escalation would be measured from a date the project does "
            f"not span, so refusing rather than extrapolating.")

    lo, mode, hi = fit_pert_from_percentiles(rate.opt, rate.ml, rate.p90)
    annual = pert_from_uniform(u, lo, mode, hi)

    # Distance in CALENDAR years, never list position. A cash flow with a gap in it - a risk
    # driving an activity outside the programme window leaves the intervening year with no spend -
    # would otherwise shift every later year's exponent down by one and silently under-escalate.
    base_year = _fy_start_year(base_financial_year)
    out: dict[str, np.ndarray] = {}
    for fy in sorted(financial_years):
        years_from_base = _fy_start_year(fy) - base_year
        if years_from_base < 0:
            raise EscalationError(
                f"{fy} falls before the base year {base_financial_year}. Whether spend before the "
                f"base date should be de-escalated to base-date dollars is a methodology question "
                f"nobody has ruled, so this refuses rather than choosing one silently.")
        # Compounded, not multiplied: three years at r is (1+r)^3, and the difference from 1+3r
        # grows with both the rate and the programme length.
        out[fy] = (1.0 + annual) ** years_from_base
    return out


def escalate(
    *,
    phased: PhasedCost,
    uniform: np.ndarray,
    rate: EscalationRate,
    base_financial_year: str,
    rate_source: str,
) -> EscalatedCashFlow:
    """Apply the index to each year's real cost and return the nominal total and the addend.

    ``rate_source`` names where the rate came from and is carried into the result, because an
    escalation rate belongs to a jurisdiction and a date - a figure escalated by an unattributed
    rate cannot be checked by the person it is shown to.
    """
    if not phased.by_financial_year:
        raise EscalationError("the cash flow is empty; there is nothing to escalate")
    if not rate_source:
        raise EscalationError(
            "no rate source given. An escalation rate without an attribution cannot be checked, "
            "and this product does not publish figures a reader cannot check.")

    years = list(phased.by_financial_year)
    index = escalation_multipliers(
        uniform=uniform, rate=rate, financial_years=years,
        base_financial_year=base_financial_year)

    n_iter = np.asarray(uniform, dtype=float).size
    nominal = np.zeros(n_iter, dtype=float)
    for fy, real in phased.by_financial_year.items():
        nominal += float(real) * index[fy]

    return EscalatedCashFlow(
        real_by_financial_year=dict(phased.by_financial_year),
        nominal_total=nominal,
        escalation_addend=nominal - phased.total,
        mean_index_by_financial_year={fy: float(v.mean()) for fy, v in index.items()},
        base_date_financial_year=base_financial_year,
        rate_source=rate_source,
    )


def correlation_matrix_with_escalation(
    corr: np.ndarray,
    names: Sequence[str],
    correlations_to_factors: Mapping[str, float],
) -> tuple[np.ndarray, list[str]]:
    """Extend a Layer-1 correlation matrix with an escalation row and column.

    This is how the ruling is implemented: escalation becomes a member of the SAME correlated
    block as the Layer-1 factors, so one Cholesky draw covers it and cost together. A caller that
    skipped this and drew separately would get an escalation independent of cost no matter what it
    intended.

    Correlations to factors not present are refused rather than ignored - a mis-typed factor name
    that silently contributed nothing would look exactly like a correlation that was elicited and
    then quietly dropped.
    """
    c = np.asarray(corr, dtype=float)
    k = c.shape[0]
    if c.shape != (k, k):
        raise EscalationError(f"correlation matrix is not square: {c.shape}")
    if len(names) != k:
        raise EscalationError(f"{len(names)} names for a {k}x{k} matrix")
    if ESCALATION_FACTOR_NAME in names:
        raise EscalationError(f"{ESCALATION_FACTOR_NAME!r} is already in the matrix")

    unknown = sorted(set(correlations_to_factors) - set(names))
    if unknown:
        raise EscalationError(
            f"correlations given for factors that are not in the matrix: {unknown}. Available: "
            f"{list(names)}. Refusing rather than ignoring - a mis-typed factor name would look "
            f"identical to a correlation that was elicited and then dropped.")

    # Every factor must be named. A missing one defaulting to 0.0 would assert that escalation is
    # independent of that factor - a methodology claim, made by omission, on a client's number.
    # The 31/08 no-defaults ruling is what forbids that, and B-1 invokes it with full force here.
    missing = sorted(set(names) - set(correlations_to_factors))
    if missing:
        raise EscalationError(
            f"no escalation correlation given for {missing}. Omitting one would silently assert "
            f"independence from it; state 0.0 if that is what was elicited.")

    out = np.ones((k + 1, k + 1), dtype=float)
    out[:k, :k] = c
    for i, name in enumerate(names):
        r = float(correlations_to_factors[name])
        if not -1.0 <= r <= 1.0:
            raise EscalationError(f"correlation to {name!r} is {r}, outside [-1, 1]")
        out[k, i] = out[i, k] = r

    # The register path refuses a non-PSD elicited matrix loudly (`qra_register_parse`). Extending
    # it happens AFTER that gate, so without this an elicited set that is jointly impossible would
    # reach `correlated_uniforms`, be silently repaired to the nearest PSD matrix, and run with
    # correlations nobody elicited - the repair is the answer to a different question.
    psd = nearest_psd(out)
    if psd["invalid"]:
        raise EscalationError(
            f"adding escalation makes the correlation matrix non positive semi-definite "
            f"(min eigenvalue {psd['min_eig']:.4g}). The elicited correlations are jointly "
            f"impossible; fix them rather than accepting a silently repaired matrix.")
    return out, [*names, ESCALATION_FACTOR_NAME]
