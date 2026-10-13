"""What correlation contributes to the answer (REPORT01 F-E).

GAP01 F-E: the report told a reader which risks correlate and how strongly, and stopped
there. Two different questions follow, and the Director ruled both (D-1, 12/09/2026):

**Does correlation matter here at all?** AU GN3A v2.0 §4.1, *Accounting for correlation
using sensitivity analysis*, prescribes the method: set correlation to zero, then to
100%, and compare the resulting curves. The measure is the dollar gap between them at
the confidence level used to fix contingency, and the guidance attaches a decision rule
to it - a negligible gap means correlation can be ignored, otherwise the level of
correlation must be examined, discussed and documented by the project team.

**Which group drives the spread?** Leave-one-out variance share per correlation group -
drop the group's risks together and measure the variance the portfolio loses. This is
what the predecessor line reported, and it needs no extra run.

The two answer different questions and neither substitutes for the other. What counts as
"negligible" is the reader's judgement, not this module's: the gap is reported in dollars
and as a share of the elicited result, and GN3A's rule is stated beside it. Inventing a
threshold here would be a methodology decision taken by a section builder.

**Scope.** The bounding varies the Layer-2 correlation-group coefficients, which is what
this engine's correlation *is* - `build_risk_uniform_matrix` correlates the **firing**
draws within a group; severity draws are independent. That is a narrower thing than
GN3A's "each model input" and the page says so.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np

#: GN3A §4.1's bounding pair, plus the elicited case they bracket.
GN3A_MODES: tuple[str, ...] = ("zero", "elicited", "one")

#: Reported P-levels. GN3A names P50 and P90 for Commonwealth-funded projects; P80 is
#: this product's primary reporting level, so all three appear.
DEFAULT_P_LEVELS: tuple[int, ...] = (50, 80, 90)

GN3A_DECISION_RULE = (
    "AU GN3A v2.0 section 4.1: the gap between the zero-correlation and "
    "full-correlation curves at the confidence level used to fix contingency indicates "
    "how much correlation matters to the outcome. If the gap is negligible, correlation "
    "can be ignored; otherwise the level of correlation should be examined, discussed "
    "and documented by the project team, and then carried in the model. What counts as "
    "negligible is a judgement for the project team, not a number this report sets."
)

SCOPE_NOTE = (
    "The bounding varies the correlation-group coefficients, which in this engine "
    "correlate the firing draws within a group; severity draws stay independent. The "
    "elicited row is the model as run, and is the basis of every other figure in this "
    "document."
)

VARIANCE_SHARE_NOTE = (
    "Share of portfolio variance is measured leave-one-out: the group's risks are "
    "removed together and the variance the total loses is attributed to the group. "
    "Shares need not sum to 100% - correlated risks contribute jointly, so the parts "
    "overlap."
)

#: Reported when a group's leave-one-out variance comes out at or below zero. A negative
#: leave-one-out result is not a defect: removing a negatively-contributing group can
#: raise the variance, and rounding it to 0.0% would hide that it happened.
NO_MEASURABLE_SHARE = "Below measurement"


def risk_correlation_groups(risks: Iterable[Any]) -> set[str]:
    """Every non-empty correlation group the risks actually carry.

    The value is collected **raw**, not stripped. ``build_risk_uniform_matrix`` groups on
    and looks up the attribute exactly as it stands, so a group carrying stray whitespace
    is a different key to the engine than its trimmed form. Trimming here would report
    such a group as covered while the engine ran it at the 0.5 default - the defect this
    function exists to prevent, resurrected by a tidy-up. Blank and whitespace-only are
    still skipped: those are an absence, not a group.
    """
    out = set()
    for r in risks:
        group = getattr(r, "correlation_group", "") or ""
        if group.strip():
            out.add(group)
    return out


def uncovered_groups(
    risks: Iterable[Any], elicited: Mapping[str, float]
) -> list[str]:
    """Groups a risk carries that the register's coefficient mapping does not name.

    These run at the engine's hardcoded ``rho=0.5`` fallback
    (``correlations.build_risk_uniform_matrix``), including the parser's own
    ``CG_UNASSIGNED``. That is a fact about the **elicited** model, so the page reports
    it rather than the bounding quietly absorbing it.
    """
    return sorted(risk_correlation_groups(risks) - set(elicited))


def _coefficients_at(
    mode: str,
    elicited: Mapping[str, float],
    all_groups: Iterable[str] | None = None,
) -> dict[str, float]:
    """The coefficient set for one bounding mode.

    ``all_groups`` is every group the risks carry. The bounds are built over that union,
    **not** over the elicited mapping's keys: a group the mapping does not name falls
    through to the engine's ``rho=0.5`` default, so building "zero" and "one" from the
    mapping alone leaves such a group at 0.5 in all three modes. The curves would then
    bound nothing, the gap the GN3A decision rule reads would be understated, and the
    byte-exact elicited check could not see it - the elicited replay stays faithful while
    both bounds are wrong.

    The elicited mode is the mapping as the register states it, unchanged: it is the
    model as run, and adding keys to it would stop it reproducing the run.
    """
    groups = set(elicited) | set(all_groups or ())
    if mode == "zero":
        return {k: 0.0 for k in groups}
    if mode == "one":
        return {k: 1.0 for k in groups}
    if mode == "elicited":
        return dict(elicited)
    raise ValueError(f"mode must be one of {GN3A_MODES}, got {mode!r}")


def run_bounding_triple(
    run_cost_layer_fn: Any,
    *,
    risks: list[Any],
    cg_coefficients: Mapping[str, float],
    n_iter: int,
    seed: int,
    **cost_layer_kwargs: Any,
) -> dict[str, np.ndarray]:
    """Run the cost arm at zero / elicited / one correlation.

    ``run_cost_layer_fn`` is injected so this module stays testable without the engine
    and so the caller keeps ownership of the engine's other arguments. Each mode runs on
    the **same seed**: the modes must differ by their correlation structure alone, and a
    fresh seed per mode would put sampling noise into the gap the whole method reads.
    """
    all_groups = risk_correlation_groups(risks)
    out: dict[str, np.ndarray] = {}
    for mode in GN3A_MODES:
        result = run_cost_layer_fn(
            n_iter=n_iter,
            risks=risks,
            cg_coefficients=_coefficients_at(mode, cg_coefficients, all_groups),
            seed=seed,
            **cost_layer_kwargs,
        )
        out[mode] = np.asarray(result["cost_dollars_array"], dtype=float)
    return out


def build_bounding_table(
    curves: Mapping[str, np.ndarray],
    p_levels: Iterable[int] = DEFAULT_P_LEVELS,
) -> list[dict[str, Any]]:
    """One row per P-level: the three curves and the gap the guidance reads."""
    rows: list[dict[str, Any]] = []
    for p in p_levels:
        zero = float(np.percentile(curves["zero"], p))
        elicited = float(np.percentile(curves["elicited"], p))
        one = float(np.percentile(curves["one"], p))
        gap = one - zero
        rows.append({
            "Confidence level": f"P{p}",
            "Zero correlation ($M)": f"{zero / 1e6:,.3f}",
            "Elicited correlation ($M)": f"{elicited / 1e6:,.3f}",
            "Full correlation ($M)": f"{one / 1e6:,.3f}",
            "Gap, zero to full ($M)": f"{gap / 1e6:,.3f}",
            "Gap as % of elicited": (
                f"{gap / elicited * 100:.1f}%" if elicited else "n/a"
            ),
        })
    return rows


def build_cg_variance_shares(
    per_risk_cost_array: np.ndarray,
    risk_ids: list[str],
    risks: Iterable[Any],
    cg_coefficients: Mapping[str, float],
) -> list[dict[str, Any]]:
    """Leave-one-out variance share per correlation group.

    The group's risks are dropped **together**, which is the point: dropping them one at
    a time measures each risk against a portfolio that still contains its correlated
    siblings, and so misses the very thing the group exists to express.
    """
    per_risk = np.asarray(per_risk_cost_array, dtype=float)
    if per_risk.size == 0 or not risk_ids:
        return []

    group_of = {
        r.risk_id: (getattr(r, "correlation_group", "") or "").strip()
        for r in risks
    }
    columns: dict[str, list[int]] = {}
    for i, rid in enumerate(risk_ids):
        group = group_of.get(rid, "")
        if group:
            columns.setdefault(group, []).append(i)
    if not columns:
        return []

    total = per_risk.sum(axis=1)
    base_var = float(np.var(total))

    rows: list[dict[str, Any]] = []
    for group, cols in columns.items():
        without = total - per_risk[:, cols].sum(axis=1)
        contribution = base_var - float(np.var(without))
        share = contribution / base_var if base_var > 0 else 0.0
        coefficient = cg_coefficients.get(group)
        rows.append({
            "Correlation group": group,
            "Risk count": len(cols),
            "Coefficient": (
                f"{coefficient:.2f}" if isinstance(coefficient, (int, float))
                else "n/a"
            ),
            "Mean contribution ($M)": f"{per_risk[:, cols].sum(axis=1).mean() / 1e6:,.3f}",
            "Share of portfolio variance": (
                NO_MEASURABLE_SHARE if contribution <= 0 else f"{share * 100:.1f}%"
            ),
            "_share": share,
        })
    rows.sort(key=lambda r: -r["_share"])
    for r in rows:
        del r["_share"]
    return rows


#: Reported when the register's coefficient mapping does not name every group its risks
#: carry. Those groups ran at the engine's 0.5 default in the elicited model.
UNCOVERED_GROUPS_NOTE = (
    "The register's correlation-coefficient block does not name every group its risks "
    "carry. The groups below ran at the engine's default coefficient of 0.50 in the "
    "elicited model. The bounding drives them to zero and one with the rest, so the gap "
    "is a true bound, but the elicited row rests on a default rather than an elicited "
    "value for them: {groups}."
)


def build_correlation_sensitivity_section(
    curves: Mapping[str, np.ndarray] | None,
    per_risk_cost_array: np.ndarray | None,
    risk_ids: list[str] | None,
    risks: Iterable[Any],
    cg_coefficients: Mapping[str, float],
    p_levels: Iterable[int] = DEFAULT_P_LEVELS,
) -> dict[str, Any]:
    """The section payload. Data only."""
    bounding = (
        build_bounding_table(curves, p_levels)
        if curves and all(m in curves for m in GN3A_MODES)
        else []
    )
    shares = (
        build_cg_variance_shares(
            per_risk_cost_array, list(risk_ids), risks, cg_coefficients)
        if per_risk_cost_array is not None and risk_ids
        else []
    )
    missing = uncovered_groups(risks, cg_coefficients)
    return {
        "page_correlation_sensitivity": {
            "bounding_table": bounding,
            "variance_share_table": shares,
            "uncovered_groups": missing,
            "uncovered_groups_note": (
                UNCOVERED_GROUPS_NOTE.format(groups=", ".join(missing))
                if missing else ""
            ),
            "decision_rule": GN3A_DECISION_RULE,
            "scope_note": SCOPE_NOTE,
            "variance_share_note": VARIANCE_SHARE_NOTE,
        }
    }


#: Said in the artefact when the elicited counterfactual does not reproduce the run's own
#: cost arm. The bounding is then withheld rather than printed: an elicited row that
#: disagrees with the headline the rest of the document reports is worse than no table.
ELICITED_MISMATCH = (
    "Correlation bounding not reported for this run: the elicited counterfactual did not "
    "reproduce the run's own cost arm exactly, so the zero-to-full gap could not be "
    "attributed to correlation alone."
)


def run_stage3_bounding(
    run_integrated_simulation_fn: Any,
    *,
    integrated_config: Any,
    risks: list[Any],
    risk_scope_df: Any,
    severity_uniforms_by_risk_id: Mapping[str, np.ndarray] | None,
) -> dict[str, np.ndarray]:
    """The bounding triple against the Stage 3 cost arm, as that arm actually ran.

    Reproduction, not re-derivation. The Stage 3 cost arm is
    ``run_integrated_simulation`` called with the joint severity uniforms; this calls the
    same function with the same uniforms, the same config and the same risk scope, and
    varies **only** ``methodology_defaults.cg_coefficients``. Anything else that differed
    would land in the gap and be read as correlation.

    The caller checks the elicited mode against the run's own cost array - see
    :func:`elicited_reproduces_run`. That check is the reason this reconstructs the call
    rather than approximating it.
    """
    import dataclasses

    elicited = dict(integrated_config.methodology_defaults.cg_coefficients)
    all_groups = risk_correlation_groups(risks)
    curves: dict[str, np.ndarray] = {}
    for mode in GN3A_MODES:
        defaults = dataclasses.replace(
            integrated_config.methodology_defaults,
            cg_coefficients=_coefficients_at(mode, elicited, all_groups),
        )
        cfg = dataclasses.replace(integrated_config, methodology_defaults=defaults)
        result = run_integrated_simulation_fn(
            config=cfg,
            risks=risks,
            risk_scope_df=risk_scope_df,
            precomputed_severity_uniforms=severity_uniforms_by_risk_id,
        )
        curves[mode] = np.asarray(result["cost_dollars_array"], dtype=float)
    return curves


def elicited_reproduces_run(
    curves: Mapping[str, np.ndarray], run_cost_dollars_array: np.ndarray
) -> bool:
    """Did the elicited counterfactual reproduce the run's own cost arm, exactly?

    Exact bytes, not a tolerance. The three modes differ only by their coefficients, so
    the elicited one is the same computation the run already did; anything short of
    equality means an argument drifted, and the gap would then carry that drift rather
    than the correlation effect. A tolerance here would let precisely the error this
    exists to catch through.
    """
    elicited = np.asarray(curves.get("elicited", np.empty(0)), dtype=float)
    actual = np.asarray(run_cost_dollars_array, dtype=float)
    return elicited.shape == actual.shape and elicited.tobytes() == actual.tobytes()
