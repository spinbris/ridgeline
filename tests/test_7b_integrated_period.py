"""Stage 7 part B: the integrated result in the period cycle, and contract 1.4.

A-1 (the period engine carries the integrated cost-plus-schedule result, on the SHARED
construction), A-2 (the period JSON carries it), and C-1's engine half (the contract moves to 1.4
with the block as a new OPTIONAL top-level entry, decision C2).

The pinning tests are the ones that matter. The Director ruled on 05/09/2026 that the cost arm is
conditioned by the period exactly as the schedule arm is - so these assert the conditioning
*changes the number*, not merely that a function was called. A test that only checked the block
existed would pass just as happily against a cost arm that ignored the period entirely, which is
the defect the ruling exists to prevent.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from src.am.integrated_period import (
    IntegratedUnavailable,
    apply_pinning_to_risks,
)
from tests.input_skips import skip_missing

REPO = Path(__file__).resolve().parents[1]
WIND_01 = REPO / "status_periods" / "wind_period_01.xlsx"
WIND_02 = REPO / "status_periods" / "wind_period_02.xlsx"
GOLDEN = REPO / "tests" / "golden" / "period_json" / "wind_synth" / "period_20260228.json"


# --- the pinning transform, in isolation -----------------------------------------------------

@dataclass
class _Risk:
    """Stands in for `RiskInput`: `probability` here is the COST-arm probability."""
    risk_id: str
    probability: float


@dataclass
class _State:
    """Stands in for `PinnedRiskState`.

    `new_probability` is the SCHEDULE arm's number - either the workbook's own
    `probability_override`, or (for `kept_baseline`) the driver's time-arm probability. The mock
    carries `action` because keying on it rather than on a value comparison is the whole of the
    B2 fix; a mock without it could not have caught the defect.
    """
    risk_id: str
    action: str
    new_probability: float | None


class TestPinningTheCostRiskSet:
    """`apply_pinning_to_risks` is the whole of the ruling, so it is pinned directly."""

    def test_a_risk_the_period_removed_is_not_priced(self):
        kept, effect = apply_pinning_to_risks(
            [_Risk("R1", 0.5), _Risk("R2", 0.5)],
            [_State("R1", "fired_removed", None)],
        )
        assert [r.risk_id for r in kept] == ["R2"]
        assert effect.removed_risk_ids == ("R1",)

    @pytest.mark.parametrize(
        "action", ["fired_removed", "milestone_excluded", "mitigation_completed_removed"])
    def test_every_removing_action_removes(self, action: str):
        """Named individually rather than trusting one representative: these are three separate
        upstream branches, and a cost arm honouring only one would still look right in the
        audit."""
        kept, effect = apply_pinning_to_risks([_Risk("R1", 0.5)], [_State("R1", action, None)])
        assert kept == [] and effect.n_removed == 1

    def test_a_closed_risk_is_priced_at_zero_and_reported_as_closed(self):
        """The schedule arm zeroes a Closed risk rather than removing it, so the audit can still
        show it. The cost arm matches - and reports it as closed, not as an override, because a
        card saying a closed risk was "re-probabilised" describes the wrong event."""
        kept, effect = apply_pinning_to_risks(
            [_Risk("R1", 0.4)], [_State("R1", "closed_probability_zero", 0.0)])
        assert kept[0].probability == 0.0
        assert effect.n_closed == 1 and effect.n_reprobabilised == 0
        assert effect.closed_risk_ids == ("R1",)

    def test_an_overridden_risk_is_priced_at_the_periods_own_probability(self):
        """`probability_overridden` carries the workbook's `probability_override` - the PERIOD's
        statement about the risk, not a time-arm quantity - so it applies to the cost arm."""
        kept, effect = apply_pinning_to_risks(
            [_Risk("R1", 0.5)], [_State("R1", "probability_overridden", 0.9)])
        assert kept[0].probability == pytest.approx(0.9)
        assert effect.reprobabilised_risk_ids == ("R1",)

    def test_a_kept_baseline_risk_is_NOT_repriced_from_the_time_arm(self):
        """**The B2 regression test, and the reason this module has its current shape.**

        `RiskDriver.probability` is the TIME-arm value (`Risk_Scope.probability_time`);
        `RiskInput.probability` is the COST-arm value; `refproject.py:46-53` documents them as
        deliberately distinct. The first version compared the two and wrote the first into the
        second wherever they differed - so on any register whose columns differ, every unpinned
        risk was silently repriced at its time probability and reported to the client as
        "re-probabilised". The wind fixture could not catch it: its two columns coincide.

        Here they differ on purpose. A cost probability of 0.2 against a time probability of 0.7
        is exactly the shape that was broken.
        """
        kept, effect = apply_pinning_to_risks(
            [_Risk("R1", 0.2)], [_State("R1", "kept_baseline", 0.7)])
        assert kept[0].probability == pytest.approx(0.2), (
            "an unpinned risk was repriced from the schedule arm's time probability")
        assert effect.n_reprobabilised == 0, (
            "an unpinned risk was reported to the client as re-probabilised")

    def test_an_unknown_action_that_removed_the_driver_removes_from_cost_too(self):
        """Fail toward the schedule arm, not toward pricing. If a removing action is added
        upstream and this module does not know it, the risk must still drop out of cost - keeping
        it would mean the two arms diverge silently, which is the whole defect class."""
        kept, effect = apply_pinning_to_risks(
            [_Risk("R1", 0.5)], [_State("R1", "some_future_action", None)])
        assert kept == [] and effect.n_removed == 1

    def test_a_risk_with_no_schedule_state_prices_unchanged(self):
        """A risk absent from the schedule arm's driver set was never *excluded* by the period -
        it was simply never a schedule driver. Dropping it would silently narrow the cost
        marginal, and the total would fall for a reason nobody asked for."""
        kept, effect = apply_pinning_to_risks([_Risk("COST-ONLY", 0.3)], [])
        assert [r.risk_id for r in kept] == ["COST-ONLY"]
        assert kept[0].probability == pytest.approx(0.3)
        assert effect.n_removed == 0 and effect.n_reprobabilised == 0

    def test_input_order_is_preserved(self):
        """The cost engine's per-risk arrays are positional. A reordering here would re-label
        every one of them, silently and consistently, which is worse than crashing."""
        risks = [_Risk(f"R{i}", 0.1 * i) for i in range(1, 6)]
        kept, _ = apply_pinning_to_risks(risks, [_State("R3", "fired_removed", None)])
        assert [r.risk_id for r in kept] == ["R1", "R2", "R4", "R5"]

    def test_the_input_risks_are_not_mutated(self):
        risks = [_Risk("R1", 0.5)]
        apply_pinning_to_risks(risks, [_State("R1", "probability_overridden", 0.9)])
        assert risks[0].probability == pytest.approx(0.5), "the caller's risk objects were mutated"


class TestJointSampling:
    """B1: a dual-coded risk shares ONE severity uniform per iteration across both arms."""

    def test_the_cost_arm_consumes_the_schedule_runs_uniforms(self):
        """Invariant 1 of `integrated_simulation_stage3`, asserted at the call site.

        The first version ran `MonteCarloEngine` standalone with its own generator - the array
        `deliverable.py:274` calls "the cross-validation reference for the cost marginal", the
        REFERENCE arm rather than the headline one. Adding two independently-drawn arrays
        element-wise pairs unrelated draws and understates the tail.
        """
        source = (REPO / "src" / "am" / "integrated_period.py").read_text(encoding="utf-8")
        assert "precomputed_severity_uniforms=severity_uniforms_by_risk_id" in source
        # Matched as a CALL or an IMPORT, not the bare name: the module explains in a comment
        # why the standalone engine is wrong, and a bare-word check hits that comment and can
        # never pass. Same self-reference trap the 3d weasyprint guard had to split a literal to
        # avoid, and it caught this test on its first run.
        import re

        standalone = re.search(r"(?:import\s+MonteCarloEngine|MonteCarloEngine\s*\()", source)
        assert standalone is None, (
            "the standalone cost engine is back; that is the reference arm, not the headline one")

    def test_a_missing_uniform_is_refused_rather_than_drawn(self):
        """The failure this guards is silent: `run_integrated_simulation` would happily draw its
        own uniform for a risk the dict does not carry, breaking joint sampling for exactly the
        dual-coded risks the contract is about - no error, and a plausible number."""
        from src.am.integrated_period import run_integrated_period

        fixtures = REPO / "tests" / "fixtures" / "synthetic_wind"
        if not (fixtures / "wind_register.xlsx").is_file():
            skip_missing(fixtures / "wind_register.xlsx")

        with pytest.raises(ValueError, match="severity uniforms are missing"):
            run_integrated_period(
                register_path=fixtures / "wind_register.xlsx",
                xer_path=fixtures / "wind_schedule.xer",
                strawman_path=fixtures / "wind_register.xlsx",
                project_finish_days=np.zeros(4), deterministic_finish_days=0.0,
                pinned_states=[], severity_uniforms_by_risk_id={},
                iterations=4, seed=42,
            )


# --- the contract ----------------------------------------------------------------------------

def test_the_contract_is_at_1_4():
    """A literal, not a read of the constant: an assertion that reads what it checks passes
    through any bump and gates nothing."""
    from src.am.json_writer import SCHEMA_VERSION

    assert SCHEMA_VERSION == "1.4"


def test_the_app_pins_the_same_version():
    """C-1's two halves must move together. The app now REFUSES a version it was not built
    against (decision A1), so an engine bump without an app bump takes the dashboard down - which
    is the intended failure, but only if the two numbers are actually kept in step."""
    from src.am.json_writer import SCHEMA_VERSION

    loader = (REPO / "dashboard" / "lib" / "loadPeriod.ts").read_text(encoding="utf-8")
    assert f'export const SUPPORTED_SCHEMA_VERSION = "{SCHEMA_VERSION}"' in loader, (
        "the app's SUPPORTED_SCHEMA_VERSION does not match the engine's SCHEMA_VERSION")


def test_the_app_actually_compares_the_version_rather_than_declaring_it():
    """Decision A1 is a CHECK, not a constant. Before part B the version was `z.string()` and the
    1.0 -> 1.1 bump - made specifically so a consumer could detect a field removal - protected
    nobody. A declared-but-unused constant would restore exactly that."""
    loader = (REPO / "dashboard" / "lib" / "loadPeriod.ts").read_text(encoding="utf-8")
    assert "schema_version !== SUPPORTED_SCHEMA_VERSION" in loader, (
        "SUPPORTED_SCHEMA_VERSION is declared but never compared")


def test_the_integrated_block_is_optional_in_the_app_schema():
    """Decision C2. A required block would invalidate every 1.3 artefact and every period from a
    register that cannot dollarise days - an additive change breaking existing documents."""
    loader = (REPO / "dashboard" / "lib" / "loadPeriod.ts").read_text(encoding="utf-8")
    assert "integrated: integratedSchema.optional()," in loader


def test_the_integrated_block_is_not_inside_headline():
    """C2's actual content. `headline` is dates, and `trend` reads it back across periods
    (`json_writer.py`), so folding dollars in would make one block mean different things in
    different periods."""
    golden = json.loads(GOLDEN.read_bytes().decode("utf-8"))
    assert "integrated" in golden, "the golden carries no integrated block"
    dollar_fields = [k for k in golden["headline"] if "dollar" in k or "cost" in k]
    assert dollar_fields == [], f"cost fields leaked into headline: {dollar_fields}"


# --- the integrated arm, end to end ----------------------------------------------------------

def _run_period(workbook: Path, out: Path) -> dict:
    from src.am.run_period import run_period

    path = run_period(
        workbook_path=workbook, project="synthetic_wind", output_dir=out,
        main_iterations=2000, days_at_risk_iterations=500, counterfactual_iterations=500,
        seed=42, criticality_measurement_mode="both",
        project_start=_dt.date(2024, 1, 1), allow_dirty=True,
    )
    return json.loads(path.read_bytes().decode("utf-8"))


@pytest.fixture(scope="module")
def period_01(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """The baseline period: nothing actioned, so pinning is a no-op. Module-scoped because the
    engine run is ~3 s and three tests read the same document."""
    if not WIND_01.is_file():
        skip_missing(WIND_01, detail="run scripts/build_wind_am_periods.py")
    return _run_period(WIND_01, tmp_path_factory.mktemp("p01"))


@pytest.fixture(scope="module")
def period_02(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """The period that actions risks - the control that makes the pinning test able to fail."""
    if not WIND_02.is_file():
        skip_missing(WIND_02, detail="run scripts/build_wind_am_periods.py")
    return _run_period(WIND_02, tmp_path_factory.mktemp("p02"))


@pytest.mark.integration
class TestTheIntegratedArmEndToEnd:
    def test_a_period_carries_the_integrated_block(self, period_01: dict):
        assert period_01["schema_version"] == "1.4"
        block = period_01["integrated"]
        # The arithmetic is reproducible from the block itself, which is the point of carrying
        # the day rate and the marginals rather than the total alone.
        assert block["day_rate"] > 0
        assert block["p50_dollars"] < block["p80_dollars"] < block["p95_dollars"]
        assert block["cost_marginal"]["p80_dollars"] > 0
        assert block["schedule_marginal"]["p80_delay_days"] >= 0

    def test_the_integrated_total_is_reproducible_from_its_own_parts(self, period_01: dict):
        """A reader asked to act on one number should be able to check it from the block. This
        asserts the published parts actually compose - a card that showed a total unrelated to
        the marginals beside it would pass every other test here."""
        b = period_01["integrated"]
        floor = b["cost_marginal"]["mean_dollars"]
        assert b["mean_dollars"] > floor, (
            "the integrated mean is not above its own cost marginal, so the dollarised schedule "
            "contributed nothing")
        implied = b["mean_dollars"] - floor
        assert implied == pytest.approx(
            b["schedule_marginal"]["mean_delay_days"] * b["day_rate"], rel=0.02), (
            "integrated mean minus cost mean does not equal mean delay x day rate; the block's "
            "published parts do not compose into its published total")

    def test_the_period_conditioning_reaches_the_COST_arm(
        self, period_01: dict, period_02: dict
    ):
        """The ruling, asserted as a number rather than a call.

        Wind period 01 is the baseline - nothing actioned, so pinning is a no-op. Period 02
        re-probabilises two risks. If the cost arm were period-blind, both periods would report
        the SAME cost marginal, and this test is what catches that.
        """
        p1, p2 = period_01["integrated"], period_02["integrated"]

        assert p1["pinning"]["risks_reprobabilised"] == 0, (
            "wind period 01 is the baseline; if pinning now bites here the fixture changed and "
            "this test's control is gone")
        assert p2["pinning"]["risks_reprobabilised"] > 0, (
            "wind period 02 no longer conditions any risk, so this test can no longer "
            "distinguish a pinned cost arm from an unpinned one")

        assert p1["cost_marginal"]["mean_dollars"] != p2["cost_marginal"]["mean_dollars"], (
            "the cost marginal is identical across a period that conditions risks and one that "
            "does not - the cost arm is NOT period-aware, and the 05/09 ruling is not "
            "implemented")

    def test_the_deterministic_baseline_is_positive_and_published(self, period_01: dict):
        """The one derivation that deliberately differs from the deliverable's: the period's own
        zero-risk pass, not `min(project_finish_days)`. Published so a reader can reproduce the
        delay rather than take it on trust."""
        assert period_01["integrated"]["deterministic_baseline_days"] > 0


# --- the fail-open path ------------------------------------------------------------------------

def test_a_register_without_a_day_rate_is_a_distinct_failure():
    """`IntegratedUnavailable` exists so a register that cannot dollarise days still produces a
    period. Without a distinct type, `run_period` would have to catch broadly and would swallow
    genuine engine bugs in the arm - which is the swallow 3c spent a review removing."""
    assert issubclass(IntegratedUnavailable, Exception)
    assert not issubclass(IntegratedUnavailable, (ValueError, KeyError, TypeError)), (
        "IntegratedUnavailable subclasses a builtin the arm could raise for an unrelated reason, "
        "so run_period's except clause would catch real bugs and report them as 'unavailable'")


def test_run_period_catches_only_that_type():
    """The other half. A bare `except Exception` around the arm would turn any engine bug into a
    silently missing block with a plausible-looking reason."""
    source = (REPO / "src" / "am" / "run_period.py").read_text(encoding="utf-8")
    assert "except IntegratedUnavailable as exc:" in source
    assert "except Exception" not in source.split("run_integrated_period(")[1][:800], (
        "run_period catches broadly around the integrated arm")


class TestTheFailOpenPathActuallyRuns:
    """W1 and W3 of the re-review, together: the previous version of this guard was UNREACHABLE
    and nobody noticed, because the only tests asserted a class hierarchy and a source string.
    A guard is not evidence until something has driven it.

    These make the arm fail for a real reason and assert the period is still written, with the
    reason on the artefact - which is the whole of the fail-open design.
    """

    @staticmethod
    def _write(monkeypatch, exc: Exception, tmp_path: Path) -> dict:
        import src.integrated.stage3_config as s3
        from src.am.run_period import run_period

        def _raise(*a, **k):
            raise exc

        # Patched at the SOURCE module, because `integrated_period` imports the name inside the
        # function - so it is not a module attribute there and patching it on the importer
        # silently does nothing. The first version of this helper did exactly that and failed
        # with AttributeError, which is the honest outcome; a `raising=False` patch on the
        # importing module would have "passed" while testing nothing.
        monkeypatch.setattr(s3, "build_stage3_config", _raise)

        # Only the cost arm goes through build_stage3_config; the schedule side must still run,
        # because the property under test is that a period survives its failure.

        path = run_period(
            workbook_path=WIND_01, project="synthetic_wind", output_dir=tmp_path,
            main_iterations=500, days_at_risk_iterations=200, counterfactual_iterations=200,
            seed=42, criticality_measurement_mode="both",
            project_start=_dt.date(2024, 1, 1), allow_dirty=True,
        )
        return json.loads(path.read_bytes().decode("utf-8"))

    @pytest.mark.integration
    def test_a_missing_day_rate_still_produces_a_period(self, monkeypatch, tmp_path: Path):
        from src.integrated.run_config_contract import RunConfigError

        if not WIND_01.is_file():
            skip_missing(WIND_01, detail="run scripts/build_wind_am_periods.py")
        doc = self._write(monkeypatch, RunConfigError("no day rate in this register"), tmp_path)

        assert "integrated" not in doc, "the block was written despite the arm failing"
        assert "no day rate in this register" in doc["audit"]["integrated_unavailable"], (
            "the period is missing its integrated block with no recorded reason - absent and "
            "unexplained is the state this design exists to avoid")
        assert doc["headline"]["p80_finish"], "the schedule side did not survive the cost failure"

    @pytest.mark.integration
    def test_a_missing_methodology_default_also_fails_open(self, monkeypatch, tmp_path: Path):
        """The re-review's WARN: `build_stage3_config` reads the reporting P-level, the CG
        coefficients and the calibration tolerances too, raising `MethodologyDefaultsError`.
        None was needed by the period engine before part B, so a narrow catch turned an additive
        feature into a crash for registers that had a day rate but not those."""
        from src.sra.methodology_defaults_reader import MethodologyDefaultsError

        if not WIND_01.is_file():
            skip_missing(WIND_01, detail="run scripts/build_wind_am_periods.py")
        doc = self._write(
            monkeypatch, MethodologyDefaultsError("no calibration tolerances"), tmp_path)

        assert "integrated" not in doc
        assert "no calibration tolerances" in doc["audit"]["integrated_unavailable"]
        assert doc["headline"]["p80_finish"], "a missing methodology default killed the cycle"

    @pytest.mark.integration
    def test_an_ORDINARY_bug_in_the_arm_still_crashes_the_run(self, monkeypatch, tmp_path: Path):
        """The control, and the more important half. If the fail-open path swallowed anything
        else, an engine bug would be reported to the client as a register shortfall and the
        period would publish regardless."""
        if not WIND_01.is_file():
            skip_missing(WIND_01, detail="run scripts/build_wind_am_periods.py")
        with pytest.raises(ZeroDivisionError):
            self._write(monkeypatch, ZeroDivisionError("an ordinary engine bug"), tmp_path)
