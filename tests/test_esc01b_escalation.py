"""ESC-01 part B: probabilistic escalation, correlated with the Layer-1 factors.

Director ruling 06/09/2026: probabilistic, sampled per iteration, correlated with the Layer-1
factors. The correlation is the part these tests work hardest on, because it is the property that
was got wrong in stage 7 part B - a cost arm built its own generator, and the element-wise sum
then paired unrelated draws while looking entirely correct.
"""
from __future__ import annotations

import datetime as _dt

import numpy as np
import pytest

from src.cash_flow import PhasedCost
from src.escalation import (
    ESCALATION_FACTOR_NAME,
    EscalationError,
    EscalationRate,
    correlation_matrix_with_escalation,
    escalate,
    escalation_multipliers,
)
from src.layer1_factors import correlated_uniforms

RATE = EscalationRate(opt=0.01, ml=0.03, p90=0.06)
FYS = ["FY2026-27", "FY2027-28", "FY2028-29"]


def _flat_cash_flow() -> PhasedCost:
    return PhasedCost(
        by_financial_year={fy: 1_000_000.0 for fy in FYS},
        basis_by_bucket={"a": "schedule"},
        programme_window=(_dt.date(2026, 7, 1), _dt.date(2029, 6, 30)),
    )


class TestTheCorrelationIsStructuralNotHopeful:
    """The ruling, implemented so that getting it wrong is impossible rather than unlikely."""

    def test_the_module_never_draws_its_own_uniform(self):
        """**The whole design.** A module holding its own `Generator` would be independent of
        cost whatever any comment claimed. Asserted on code shape per
        the guard convention, since these docstrings discuss drawing constantly."""
        import re
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "src" / "escalation.py").read_text(
            encoding="utf-8")
        assert not re.search(r"default_rng\s*\(|rng\.(random|standard_normal|uniform)\s*\(", source), (
            "src/escalation.py draws its own randomness; it must take the uniform from the "
            "caller's correlated draw or the ruling is not implemented")

    def test_escalation_drawn_from_the_shared_block_correlates_with_a_factor(self):
        """The positive proof: extend the matrix, draw once, and the escalation column moves with
        the factor column it was told to move with."""
        # 0.55, not the 0.8 this first used: with the factors at 0.2 to each other, 0.8 to both
        # is jointly impossible (min eigenvalue -0.13). `nearest_psd` repaired it silently and the
        # test then measured a correlation nobody had elicited - it passed on the repair.
        corr = np.array([[1.0, 0.2], [0.2, 1.0]])
        names = ["Provisions", "Duration"]
        extended, extended_names = correlation_matrix_with_escalation(
            corr, names, {"Provisions": 0.55, "Duration": 0.55})
        assert extended_names[-1] == ESCALATION_FACTOR_NAME

        u, _ = correlated_uniforms(extended, 20_000, np.random.default_rng(42))
        r = np.corrcoef(u[:, 0], u[:, -1])[0, 1]
        assert r > 0.4, f"escalation and Provisions are only correlated {r:.2f}"

    def test_an_independent_draw_would_NOT_correlate(self):
        """The control that makes the test above mean something. Without it, a passing
        correlation could be an artefact of the copula rather than of the shared draw."""
        rng = np.random.default_rng(42)
        corr = np.array([[1.0, 0.2], [0.2, 1.0]])
        u, _ = correlated_uniforms(corr, 20_000, rng)
        separate = rng.random(20_000)          # what drawing independently looks like
        r = abs(np.corrcoef(u[:, 0], separate)[0, 1])
        assert r < 0.05, f"an independent draw correlated {r:.2f}; the control is not a control"

    def test_a_correlation_to_an_unknown_factor_is_refused(self):
        """A mis-typed factor name that silently contributed nothing would look exactly like a
        correlation that was elicited and then dropped."""
        with pytest.raises(EscalationError, match="not in the matrix"):
            correlation_matrix_with_escalation(
                np.array([[1.0]]), ["Provisions"], {"Provislons": 0.8})

    def test_the_extended_matrix_keeps_the_original_correlations(self):
        corr = np.array([[1.0, 0.3], [0.3, 1.0]])
        extended, _ = correlation_matrix_with_escalation(
            corr, ["A", "B"], {"A": 0.5, "B": 0.0})
        assert extended[0, 1] == pytest.approx(0.3)
        assert extended[2, 0] == pytest.approx(0.5)
        assert extended[2, 1] == pytest.approx(0.0)

    def test_an_unstated_correlation_is_refused_rather_than_defaulted_to_zero(self):
        """Found by the ESC-01 numerics review. A factor omitted from the mapping used to become
        0.0, which asserts independence from that factor - a methodology claim made by omission,
        on a client's number. The 31/08 no-defaults ruling is what forbids it."""
        with pytest.raises(EscalationError, match="no escalation correlation given"):
            correlation_matrix_with_escalation(
                np.array([[1.0, 0.3], [0.3, 1.0]]), ["A", "B"], {"A": 0.5})

    def test_a_jointly_impossible_set_is_refused_not_silently_repaired(self):
        """Found by the ESC-01 numerics review. The register path refuses a non-PSD elicited
        matrix loudly; extending it happens after that gate, so without this check the extended
        matrix reached `correlated_uniforms` and was repaired to the nearest PSD one - running
        with correlations nobody elicited, and no flag anywhere."""
        with pytest.raises(EscalationError, match="positive semi-definite"):
            correlation_matrix_with_escalation(
                np.array([[1.0, 0.2], [0.2, 1.0]]), ["A", "B"], {"A": 0.8, "B": 0.8})


class TestCompounding:
    """Ruled: one rate path per iteration, compounded across years."""

    def test_the_base_year_never_escalates(self):
        """Money spent at the base date has not escalated. Multiplying it would double-count the
        base itself."""
        idx = escalation_multipliers(
            uniform=np.full(100, 0.5), rate=RATE,
            financial_years=FYS, base_financial_year="FY2026-27")
        assert np.allclose(idx["FY2026-27"], 1.0)

    def test_the_index_compounds_rather_than_multiplies(self):
        """Three years at r is (1+r)^3, not 1+3r. The gap grows with the rate and the programme
        length, which is exactly where a long project's outturn lives."""
        u = np.full(1000, 0.5)
        idx = escalation_multipliers(
            uniform=u, rate=RATE, financial_years=FYS, base_financial_year="FY2026-27")
        r = idx["FY2027-28"] - 1.0
        assert np.allclose(idx["FY2028-29"], (1.0 + r) ** 2)
        assert np.all(idx["FY2028-29"] > 1.0 + 2.0 * r - 1e-12)

    def test_one_path_per_iteration_not_one_per_year(self):
        """The ruled model. If each year drew separately, a high draw in year 2 would be
        uncorrelated with year 3 - and across a long programme the variance would wash out into
        an implausibly narrow band."""
        u = np.linspace(0.01, 0.99, 5000)
        idx = escalation_multipliers(
            uniform=u, rate=RATE, financial_years=FYS, base_financial_year="FY2026-27")
        r = np.corrcoef(idx["FY2027-28"], idx["FY2028-29"])[0, 1]
        assert r > 0.999, f"the years are only correlated {r:.3f}; that is not one path"

    def test_a_gap_in_the_cash_flow_does_not_shift_the_exponent(self):
        """**The defect the ESC-01 numerics review found.** The exponent was the year's POSITION
        in the sorted list, so a cash flow missing an intervening year - a risk driving an
        activity outside the programme window leaves one with no spend - escalated FY2029-30 by
        (1+r)^1 instead of (1+r)^3. Same year, same rate, a different answer depending on whether
        some other year happened to be present."""
        u = np.full(100, 0.5)
        contiguous = escalation_multipliers(
            uniform=u, rate=RATE,
            financial_years=["FY2026-27", "FY2027-28", "FY2028-29", "FY2029-30"],
            base_financial_year="FY2026-27")
        gapped = escalation_multipliers(
            uniform=u, rate=RATE, financial_years=["FY2026-27", "FY2029-30"],
            base_financial_year="FY2026-27")
        assert np.allclose(gapped["FY2029-30"], contiguous["FY2029-30"]), (
            "a year's escalation changed because a different year was absent")
        r = contiguous["FY2027-28"][0] - 1.0
        assert np.allclose(gapped["FY2029-30"], (1.0 + r) ** 3)

    def test_spend_before_the_base_year_is_refused_not_silently_left_unescalated(self):
        """It used to clamp to an index of 1.0. Whether base-date dollars spent earlier should be
        de-escalated is a methodology question nobody has ruled, and clamping answered it
        silently in the direction that happens to be arithmetically convenient."""
        with pytest.raises(EscalationError, match="falls before the base year"):
            escalation_multipliers(
                uniform=np.full(10, 0.5), rate=RATE,
                financial_years=["FY2025-26", "FY2026-27"],
                base_financial_year="FY2026-27")

    def test_a_malformed_financial_year_label_is_refused(self):
        """The year was read by slicing `fy[2:6]`. A malformed label would slice to a plausible
        number and escalate by a wrong count of years without saying anything."""
        with pytest.raises(EscalationError, match="not a financial year label"):
            escalation_multipliers(
                uniform=np.full(10, 0.5), rate=RATE,
                financial_years=["FY2026-27", "2027-28"],
                base_financial_year="FY2026-27")

    def test_a_base_year_outside_the_cash_flow_is_refused(self):
        with pytest.raises(EscalationError, match="does not span"):
            escalation_multipliers(
                uniform=np.full(10, 0.5), rate=RATE,
                financial_years=FYS, base_financial_year="FY2020-21")

    def test_a_uniform_outside_zero_one_is_refused(self):
        """It would not be a copula draw, so it did not come from the correlated block."""
        with pytest.raises(EscalationError, match="not in \\[0, 1\\]"):
            escalation_multipliers(
                uniform=np.array([0.5, 1.7]), rate=RATE,
                financial_years=FYS, base_financial_year="FY2026-27")


class TestTheEscalatedCashFlow:
    def test_the_addend_is_nominal_minus_real(self):
        out = escalate(
            phased=_flat_cash_flow(), uniform=np.full(500, 0.5), rate=RATE,
            base_financial_year="FY2026-27", rate_source="test")
        assert np.allclose(out.escalation_addend, out.nominal_total - out.real_total)

    def test_escalation_is_positive_on_a_positive_rate(self):
        out = escalate(
            phased=_flat_cash_flow(), uniform=np.full(500, 0.5), rate=RATE,
            base_financial_year="FY2026-27", rate_source="test")
        assert out.escalation_addend.mean() > 0

    def test_a_single_year_cash_flow_at_the_base_year_escalates_by_nothing(self):
        """The degenerate case, and the one the committed wind fixture would produce - its
        schedule spans six weeks inside one financial year."""
        one = PhasedCost(by_financial_year={"FY2026-27": 5_000_000.0})
        out = escalate(
            phased=one, uniform=np.full(200, 0.5), rate=RATE,
            base_financial_year="FY2026-27", rate_source="test")
        assert np.allclose(out.escalation_addend, 0.0)

    def test_an_unattributed_rate_is_refused(self):
        """An escalation rate belongs to a jurisdiction and a date. A figure escalated by an
        unattributed rate cannot be checked by the person it is shown to."""
        with pytest.raises(EscalationError, match="rate source"):
            escalate(phased=_flat_cash_flow(), uniform=np.full(10, 0.5), rate=RATE,
                     base_financial_year="FY2026-27", rate_source="")

    def test_an_empty_cash_flow_is_refused(self):
        with pytest.raises(EscalationError, match="nothing to escalate"):
            escalate(phased=PhasedCost(by_financial_year={}), uniform=np.full(10, 0.5),
                     rate=RATE, base_financial_year="FY2026-27", rate_source="test")

    def test_the_disclosure_fields_are_carried(self):
        """A reader must be able to see the index that was applied and where the rate came from,
        not only the escalated total."""
        out = escalate(
            phased=_flat_cash_flow(), uniform=np.full(50, 0.5), rate=RATE,
            base_financial_year="FY2026-27", rate_source="ABS index, base 2026-07")
        assert out.rate_source == "ABS index, base 2026-07"
        assert out.base_date_financial_year == "FY2026-27"
        assert set(out.mean_index_by_financial_year) == set(FYS)
        assert out.mean_index_by_financial_year["FY2026-27"] == pytest.approx(1.0)


def test_the_register_still_carries_no_escalation_rate():
    """Stated as a test so the next reader knows this is unwired by design, not by oversight.

    Wiring rates to the register is contract 1.4 -> 1.5, a scaffolder change, and it triggers the
    M1 migration policy ruled 05/09 - specialist re-scaffolds, client re-enters. The arithmetic is
    built and reviewable first so that bump is spent once, deliberately.
    """
    from pathlib import Path

    import openpyxl

    reg = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "synthetic_wind"
           / "wind_register.xlsx")
    if not reg.is_file():
        pytest.skip("wind fixture absent")
    wb = openpyxl.load_workbook(reg, data_only=True)
    labels = " ".join(
        str(c) for r in wb["MC_Params"].iter_rows(values_only=True) for c in r if c is not None)
    assert "escalation" not in labels.lower(), (
        "the register now carries an escalation rate - wire it through and delete this test")
