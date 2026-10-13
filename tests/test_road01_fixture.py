"""ROAD-01: the synthetic road project, and the engine defect building it exposed.

Project #2 exists so stage 4 can run a project that is neither the engagement nor the showcase.
Its evidential value depends entirely on its shape coming from the **standard** rather than from
the engine - a project the Builder shaped by reading the code proves only that the Builder can
read the code. So the traceability guard below is not decoration; it is the property.
"""
from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GENERATOR = REPO / "scripts" / "build_synthetic_road_fixture.py"
FIXTURE_DIR = REPO / "tests" / "fixtures" / "synthetic_road"
REGISTER = FIXTURE_DIR / "road_register.xlsx"
SCHEDULE = FIXTURE_DIR / "road_schedule.xer"
RFM3_FACTORS = REPO / "docs" / "reference" / "aust_cegn" / "models" / "RFM3_Risk_factors.csv"  # link-rule: the held road factor table, read by the traceability guard when present


@pytest.fixture(scope="module")
def road():
    """The generator module, imported for its data tables rather than run."""
    spec = importlib.util.spec_from_file_location("road_fixture", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheShapeIsTheStandardsNotTheBuilders:
    """ROAD-01 §A-2. The one property that makes project #2 worth building."""

    @pytest.mark.needs_input("docs/reference/aust_cegn/models/RFM3_Risk_factors.csv")  # link-rule: the traceability guard skips by name when the held road factor table is absent
    def test_every_layer1_factor_name_comes_from_the_departments_road_model(self, road):
        """**The traceability guard.** Asserted against the CSV extracted from the department's
        own road worked example, not against prose - the generator's docstrings discuss factors
        throughout, so a text search would match its own explanation
        (the guard convention).

        A factor name that is not in RFM3 is the Builder inventing a project, which is exactly
        what stage 4 cannot then measure.
        """
        assert RFM3_FACTORS.is_file(), (
            f"the department's road factor table is missing: {RFM3_FACTORS}")
        published = {
            row[0].strip() for row in csv.reader(RFM3_FACTORS.read_text(encoding="utf-8").splitlines())
            if row and row[0].strip()
        }
        ours = {f[0] for f in road.L1_FACTORS}
        invented = sorted(ours - published)
        assert not invented, (
            f"Layer-1 factors not present in the department's road model: {invented}. "
            f"Either cite where they come from or remove them.")

    @pytest.mark.needs_input("docs/reference/aust_cegn/models/RFM3_Risk_factors.csv")  # link-rule: the traceability guard skips by name when the held road factor table is absent
    def test_the_guard_would_notice_an_invented_factor(self, road):
        """The control. If every conceivable name were somehow 'published', the guard above would
        pass on anything and prove nothing."""
        published = {
            row[0].strip() for row in csv.reader(RFM3_FACTORS.read_text(encoding="utf-8").splitlines())
            if row and row[0].strip()
        }
        assert "Tolling gantry allowance" not in published, (
            "the traceability guard cannot distinguish an invented factor from a published one")

    def test_the_factor_set_is_not_a_token(self, road):
        """Stage 4 requires a factor-type risk. Two factors would satisfy that literally and
        exercise nothing; the department's road model carries nineteen cost factors."""
        assert len(road.L1_FACTORS) >= 15


class TestTheCostBasisReconciles:
    def test_the_layer1_base_matrix_sums_to_the_declared_capex(self, road):
        """A base matrix that does not sum to the declared total is a cash flow that looks like an
        answer - the same failure ESC-01 part A guards against one layer up."""
        assert road._BASE_M.sum() * 1e6 == pytest.approx(road.ROAD_CAPEX_TOTAL)

    def test_every_wbs_row_reconciles_to_its_cost_group(self, road):
        """Row-by-row, not just the total: two compensating errors sum correctly."""
        row_totals = road._BASE_M.sum(axis=1) * 1e6
        basis = [v[1] for v in road.CAPEX_BASIS.values()]
        assert len(row_totals) == len(basis)
        for label, got, want in zip(road.L1_ROWS, row_totals, basis):
            assert got == pytest.approx(want), f"{label}: matrix {got:,.0f} vs basis {want:,.0f}"

    def test_the_project_is_above_the_deterministic_threshold(self, road):
        """Director ruling 07/09: above $25M, so the probabilistic method leads and GN3B's
        factor table stays a cross-check (`text/GN3B_deterministic.txt:84`, `:196`)."""
        assert road.ROAD_CAPEX_TOTAL > 25_000_000

    def test_the_elicited_correlation_set_is_jointly_possible(self, road):
        """A non-PSD matrix is silently repaired downstream, so it must be refused here."""
        import numpy as np

        full = road._CORR_LOWER + road._CORR_LOWER.T - np.eye(len(road.L1_CORR_NAMES))
        assert np.linalg.eigvalsh(full).min() > 0


class TestTheScheduleBindsAsDeclared:
    def test_the_register_and_the_mapping_agree_on_which_risks_are_scheduled(self, road):
        time_yes = {r[0] for r in road.ROAD_RISKS if r[13] == "Yes"}
        assert time_yes == set(road.GATING)
        assert time_yes == set(road.PREFIX_MAPPING)

    def test_at_least_one_risk_is_schedule_linked(self, road):
        """`_build_generic_drivers` raises on zero Time=Yes rows, so a cost-only road project
        could not run the schedule arm at all."""
        assert sum(1 for r in road.ROAD_RISKS if r[13] == "Yes") >= 1

    @pytest.mark.integration
    def test_each_prefix_binds_the_number_of_activities_it_declares(self, road):
        """A mapping that expects more activities than exist binds silently short - fewer
        activities carry the delay, and the schedule arm quietly understates."""
        from src.sra.cpm.xer_reader import parse_xer

        if not SCHEDULE.is_file():
            pytest.skip("road schedule fixture absent")
        codes = [str(c) for c in parse_xer(str(SCHEDULE))["TASK"]["task_code"]]
        for rid, (prefix, declared) in sorted(road.PREFIX_MAPPING.items()):
            actual = sum(1 for c in codes if c.startswith(prefix))
            assert actual == declared, (
                f"{rid}: prefix {prefix!r} declares {declared} activities, schedule has {actual}")

    @pytest.mark.integration
    def test_every_gating_activity_exists_in_the_schedule(self, road):
        """A gating id naming no activity is skipped, not guessed - so the risk would silently
        fall back to the programme profile with nothing saying so."""
        from src.sra.cpm.xer_reader import parse_xer

        if not SCHEDULE.is_file():
            pytest.skip("road schedule fixture absent")
        codes = {str(c) for c in parse_xer(str(SCHEDULE))["TASK"]["task_code"]}
        missing = sorted(g for g, _n in road.GATING.values() if g not in codes)
        assert not missing, f"gating activities absent from the schedule: {missing}"


class TestPert1Side01:
    """The engine defect ROAD-01 exposed, and the reason a third project was worth building.

    `fit_pert_from_percentiles` raised `ZeroDivisionError` for any factor whose **optimistic
    equals its most-likely** - a one-sided factor, "this can overrun but will not underrun".
    Ordinary elicitation, and the department's own road model uses it for five of its factors.
    It had never been hit because the only Layer-1 dataset that existed - wind - has none.
    """

    @pytest.mark.parametrize("p90", [0.05, 0.10, 0.25])
    def test_a_one_sided_factor_fits(self, p90: float):
        from src.layer1_factors import fit_pert_from_percentiles

        lo, mode, hi = fit_pert_from_percentiles(0.0, 0.0, p90)
        assert lo < mode < hi

    @pytest.mark.parametrize("p90", [0.05, 0.10, 0.25])
    def test_the_fitted_distribution_really_has_the_requested_percentiles(self, p90: float):
        """**The check that makes the fix a fix rather than a number.** The width is recovered
        from the high anchor because the low one is 0/0 and constrains nothing; refitting must
        return P10 at the mode and P90 where it was asked for."""
        from scipy import stats

        from src.layer1_factors import fit_pert_from_percentiles

        lo, mode, hi = fit_pert_from_percentiles(0.0, 0.0, p90)
        r = (mode - lo) / (hi - lo)
        a, b = 1.0 + 4.0 * r, 1.0 + 4.0 * (1.0 - r)
        assert lo + (hi - lo) * stats.beta.ppf(0.10, a, b) == pytest.approx(0.0, abs=1e-9)
        assert lo + (hi - lo) * stats.beta.ppf(0.90, a, b) == pytest.approx(p90, rel=1e-9)

    def test_the_ordinary_two_sided_fit_is_untouched(self):
        """Bit-identity for every case that worked before. Pinned as literals captured from the
        pre-fix code, so the test cannot agree with whatever the change produced."""
        from src.layer1_factors import fit_pert_from_percentiles

        lo, mode, hi = fit_pert_from_percentiles(-0.01, 0.0, 0.10)
        assert (round(lo, 4), mode, round(hi, 4)) == (-0.0221, 0.0, 0.2522)


class TestTheGoldenMeasuresThisProject:
    """ROAD-01 §5.2 / §6. The sharpest risk in the brief was a **green golden measuring wind**.

    `tests/golden/projects.toml` claimed a new project needed no code change. It was untrue:
    every adapter was a closure over one project, so `adapter = "wind"` on a second project would
    have re-run the wind fixture and reported wind's numbers under the new project's name - a gate
    that passes while measuring nothing (GOLDENADPT-01).
    """

    def test_the_road_row_uses_the_project_parametrised_adapter(self):
        from tests.golden.golden_harness import get_row

        assert get_row("synthetic_road").adapter == "integrated", (
            "the road project is back on a single-project adapter, which would report that "
            "project's numbers under the road project's name")

    def test_every_integrated_row_names_a_resolvable_binding(self):
        """The integrated adapter resolves inputs through the project's **binding**, so for such a
        row the golden key and the binding key must be the same name.

        They are two namespaces that happen to look alike: wind's row is `wind_synth` while its
        binding is `synthetic_wind`, which is harmless only because the wind adapter never
        resolves a binding. This is the check that stops that latent mismatch becoming a real one
        the first time someone copies the wind row.
        """
        from src.sra.cpm.bindings.registry import get_binding
        from tests.golden.golden_harness import load_registry

        for name, row in load_registry().items():
            if row.adapter != "integrated":
                continue
            get_binding(name)  # raises KeyError, naming what IS registered

    def test_the_road_headline_is_not_the_wind_headline(self):
        """The direct refutation. If the adapter were still measuring wind, these would agree -
        and every other check in this class could pass while it did."""
        import json

        wind = json.loads(
            (REPO / "tests/golden/manifests/wind_synth/canonical.json").read_text(encoding="utf-8"))
        road = json.loads(
            (REPO / "tests/golden/manifests/synthetic_road/canonical.json").read_text(
                encoding="utf-8"))
        assert wind != road, "the road manifest is identical to wind's"

    def test_the_road_manifest_is_committed_not_local(self):
        """The road project is synthetic and publishable, like wind: its numbers belong in the
        committed tier, so a fresh clone and CI can run the gate."""
        assert (REPO / "tests/golden/manifests/synthetic_road/canonical.json").is_file()
