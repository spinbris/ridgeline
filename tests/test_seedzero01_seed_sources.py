"""SEEDZERO-01: every seed has a stated source, and is recorded.

P2 (and D2, D3 on result ``-1``): a stated seed is used as given; an unset, blank or 0 one is drawn
once and recorded; a fractional one is refused rather than truncated. P3: the period run takes its
binding's declared seed unless ``--seed`` overrides it, and records which. P4: a check reruns with
its baseline's recorded seed. P5: the Excel route follows the same rule. The guard against a code
default is ``tests/test_seedzero01_no_seed_default.py``.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import shutil
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd
import pytest

from tests.conftest import TEST_MODE_MULTIPLIERS
from tests._fixture_values import FIXTURE_DAY_RATE

REPO = Path(__file__).resolve().parents[1]
ROAD_REGISTER = REPO / "tests" / "fixtures" / "synthetic_road" / "road_register.xlsx"
WIND_REGISTER = REPO / "tests" / "fixtures" / "synthetic_wind" / "wind_register.xlsx"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- D3: one parser; a fraction is refused, never truncated ---------------------------------

def test_a_fractional_seed_is_refused_on_the_tier1_route(monkeypatch):
    monkeypatch.setenv("QRA_PROJECT", "synthetic_road")
    from src.tier1_headless import run_headless_from_workbook

    with pytest.raises(ValueError, match="42.5"):
        run_headless_from_workbook(ROAD_REGISTER, "KH", n_iter=200, seed=42.5, view="owner")


def test_a_fractional_register_seed_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("QRA_PROJECT", "synthetic_wind")  # the legacy reader needs headless_config
    from src.v5_register_reader import read_params_v5

    path = tmp_path / "register.xlsx"
    shutil.copyfile(WIND_REGISTER, path)
    wb = openpyxl.load_workbook(path)
    wb["MC_Params"]["C3"] = 42.5
    wb.save(path)
    with pytest.raises(ValueError, match="42.5"):
        read_params_v5(path)


def test_a_whole_float_seed_is_the_seed(monkeypatch):
    """xlwings hands every Excel number over as a float: 42.0 is 42, not a refusal."""
    from src.rng_streams import parse_seed

    assert parse_seed(42.0, where="test") == 42


# --- D2: the legacy cost MC records the seed it ran with -----------------------------------

def _engine(seed):
    from src.config import ChainConfig, SimConfig
    from src.simulation import MonteCarloEngine
    from src.v5_register_reader import read_risks_v5

    risks = read_risks_v5(str(ROAD_REGISTER))
    return MonteCarloEngine(config=SimConfig(n_iter=500, view="All"), buckets=[],
                            chains=ChainConfig(), risks=risks,
                            corr_coefficients={}, seed=seed).run()


@pytest.mark.parametrize("unset", [None, 0])
def test_an_unset_legacy_seed_is_drawn_and_recorded(unset, monkeypatch):
    monkeypatch.setenv("QRA_PROJECT", "synthetic_road")
    raw = _engine(unset)
    assert isinstance(raw.seed, int) and raw.seed > 0
    np.testing.assert_array_equal(raw.ev_costs, _engine(raw.seed).ev_costs)


def test_a_stated_legacy_seed_is_recorded_as_given(monkeypatch):
    monkeypatch.setenv("QRA_PROJECT", "synthetic_road")
    assert _engine(7).seed == 7


# --- D1: an engine handed no seed refuses by name --------------------------------------------

def test_the_bootstrap_refuses_without_a_seed_or_a_generator():
    from src.bootstrap import bootstrap_convergence, bootstrap_percentile_ci

    sample = np.arange(1_000, dtype=float)
    with pytest.raises((TypeError, ValueError)):
        bootstrap_percentile_ci(sample)
    with pytest.raises((TypeError, ValueError)):
        bootstrap_convergence(sample)


def test_the_stage3_config_refuses_a_missing_seed(monkeypatch):
    monkeypatch.setenv("QRA_PROJECT", "synthetic_road")
    from src.integrated.stage3_config import build_stage3_config

    xer = ROAD_REGISTER.with_name("road_schedule.xer")
    with pytest.raises(ValueError, match="no seed was given"):
        build_stage3_config(register_path=ROAD_REGISTER, xer_path=xer, strawman_path=ROAD_REGISTER,
                            iterations=100, seed=None, caller_module="tests/test_seedzero01")


def test_the_schedule_mc_config_has_no_default_seed():
    from src.sra.cpm.cpm_simulation import ScheduleMCConfig

    assert ScheduleMCConfig(mode_multipliers=TEST_MODE_MULTIPLIERS).seed is None


# --- secondary resamples take the run's seed -----------------------------------------------

def test_the_transparency_walkthrough_has_no_seed_of_its_own():
    from src.sra.sra_config import SRAConfig
    from src.sra.sra_simulation import run_single_scenario_transparency

    scope = pd.DataFrame([{"risk_id": "R001", "time_impact": "Yes", "mode_aggregated": "Series",
                           "probability": 1.0, "opt_days": 1.0, "ml_days": 2.0, "pess_days": 3.0}])
    cfg = SRAConfig(register_path=Path("inputs"), p6_path=Path("inputs"),
                    strawman_path=Path("unused.xlsx"), iterations=1, random_seed=7,
                    day_rate=FIXTURE_DAY_RATE, mode_multipliers=TEST_MODE_MULTIPLIERS)
    with pytest.raises(ValueError, match="no seed was given"):
        run_single_scenario_transparency(cfg, scope)


def test_the_tier1_p80_note_resamples_on_the_run_seed(monkeypatch):
    monkeypatch.setenv("QRA_PROJECT", "synthetic_road")
    import src.tier1_headless as t1

    seen = []
    real = t1.bootstrap_percentile_ci
    monkeypatch.setattr(t1, "bootstrap_percentile_ci",
                        lambda *a, **k: seen.append(k.get("seed")) or real(*a, **k))
    t1.run_headless_from_workbook(ROAD_REGISTER, "KH", n_iter=500, seed=7, view="shared-pool")
    assert seen == [7]


def test_the_page7_convergence_chart_takes_a_seed():
    import inspect

    from src.final.charts import make_methodology_convergence_chart
    from src.final.composer import _generate_v3_charts

    for fn in (make_methodology_convergence_chart, _generate_v3_charts):
        assert inspect.signature(fn).parameters["seed"].default is inspect.Parameter.empty, fn


# --- P5: the Excel route ---------------------------------------------------------------------

class _Range:
    def __init__(self, value):
        self.value = value


class _Name:
    def __init__(self, rng):
        self.refers_to_range = rng


class _Book:
    """The named ranges `_run_and_write` reads and writes. A missing name raises, as xlwings does."""

    def __init__(self, seed_cell):
        self.ranges = {"Set_iterations": _Range(200), "Set_view": _Range("owner"),
                       "Set_risk_prefix": _Range("KH")}
        if seed_cell is not _MISSING:
            self.ranges["Set_seed"] = _Range(seed_cell)
        self.names = self

    def __getitem__(self, name):
        if name not in self.ranges:
            if name.startswith(("Out_", "Corr_flag")):
                self.ranges[name] = _Range(None)
            else:
                raise KeyError(name)
        return _Name(self.ranges[name])


_MISSING = object()


@pytest.fixture
def shell(monkeypatch):
    import src.tier1_xlwings_shell as sh

    calls = []

    def fake_run(grids, *, risk_id_prefix, n_iter, seed, view):
        calls.append(seed)
        return {"p_table": [], "s_curve": {"prob": [], "value": []}, "corr_flag": None,
                "convergence_note": {"p80_ci95_half_width": 0.0, "p80_ci95_half_width_pct": 0.0},
                "triple": {}}

    monkeypatch.setattr(sh, "read_grids_xlwings", lambda book: {})
    monkeypatch.setattr(sh, "run_headless", fake_run)
    return sh, calls


@pytest.mark.parametrize("cell", [0, 0.0, None, ""], ids=["0", "0.0", "None", "blank"])
def test_an_unset_excel_seed_is_drawn_and_written_back(shell, cell):
    sh, calls = shell
    book = _Book(cell)
    sh._run_and_write(book, "Set_iterations", 25_000)
    assert calls[0] > 0
    assert book.ranges["Set_seed"].value == calls[0]


def test_a_stated_excel_seed_is_used_as_given(shell):
    sh, calls = shell
    book = _Book(42.0)
    sh._run_and_write(book, "Set_iterations", 25_000)
    assert calls == [42] and book.ranges["Set_seed"].value == 42.0


def test_a_fractional_excel_seed_is_refused(shell):
    sh, calls = shell
    with pytest.raises(ValueError, match="Set_seed"):
        sh._run_and_write(_Book(42.5), "Set_iterations", 25_000)
    assert calls == []


def test_a_missing_excel_seed_range_is_refused(shell):
    """Set_seed is contract-required (src/register_contract.py). With no range there is nowhere to
    record a drawn seed, so a missing one is refused rather than drawn unrecorded."""
    sh, calls = shell
    with pytest.raises(ValueError, match="Set_seed"):
        sh._run_and_write(_Book(_MISSING), "Set_iterations", 25_000)
    assert calls == []


# --- P3: the period run's seed is the binding's, unless overridden --------------------------

WORKBOOK = REPO / "status_periods" / "wind_period_01.xlsx"


def _period(tmp_path, **seed):
    from src.am.run_period import run_period

    out = run_period(workbook_path=WORKBOOK, project="synthetic_wind", output_dir=tmp_path,
                     main_iterations=300, days_at_risk_iterations=100,
                     counterfactual_iterations=100, project_start=_dt.date(2024, 1, 1),
                     allow_dirty=True, **seed)
    return json.loads(Path(out).read_text(encoding="utf-8"))["meta"]


def test_both_shipped_bindings_declare_the_period_seed():
    from src.sra.cpm.bindings import synthetic_road, synthetic_wind

    for b in (synthetic_road.SYNTHETIC_ROAD_BINDING, synthetic_wind.SYNTHETIC_WIND_BINDING):
        assert b.period_seed == 42, b.name


@pytest.mark.slow
def test_a_period_run_with_no_seed_runs_the_bindings(tmp_path):
    meta = _period(tmp_path)
    assert (meta["seed"], meta["seed_source"]) == (42, "binding")


@pytest.mark.slow
def test_a_period_run_with_a_seed_records_the_override(tmp_path):
    meta = _period(tmp_path, seed=7)
    assert (meta["seed"], meta["seed_source"]) == (7, "override")


def test_the_period_cli_has_no_seed_default(monkeypatch):
    from src.am import run_period as rp

    seen = []
    monkeypatch.setattr(rp, "_run_from_args", lambda args: seen.append(args) or Path("x"))
    rp._main(["--workbook", "w.xlsx"])
    assert seen[0].seed is None


# --- P4: a check reruns with its baseline's recorded seed -----------------------------------

def test_the_showcase_takes_its_seed_from_its_meta(tmp_path):
    wind = _script("run_wind_showcase")
    assert wind.baseline_seed(wind.BASELINE_META) == json.loads(
        wind.BASELINE_META.read_text(encoding="utf-8"))["seed"]

    other = tmp_path / "meta.json"
    other.write_text(json.dumps({"seed": 7}), encoding="utf-8")
    assert wind.baseline_seed(other) == 7

    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps({"iterations": 100}), encoding="utf-8")
    with pytest.raises(SystemExit, match="seed"):
        wind.baseline_seed(bare)


def test_the_kestrel_check_takes_its_seed_from_its_reference(tmp_path):
    kestrel = _script("measure_playbook_kestrel")
    data = json.loads(kestrel.REFERENCE.read_text(encoding="utf-8"))
    assert kestrel.reference_seed() == data["_meta"]["seed"]

    bare = tmp_path / "ref.json"
    bare.write_text(json.dumps({"_meta": {}, "tier1_p50": 1.0}), encoding="utf-8")
    with pytest.raises(SystemExit, match="seed"):
        kestrel.reference_seed(bare)


def test_the_output_pack_runs_each_deliverable_at_its_golden_rows_seed():
    import tests.golden.golden_harness as gh

    pack = _script("output_pack")
    for project, (register, _xer) in pack.DELIVERABLES.items():
        [row] = [r for r in gh.load_registry().values() if register in r.inputs]
        assert pack.deliverable_seed(project) == row.seed


def test_the_period_golden_reruns_at_its_recorded_seed(tmp_path):
    from tests import test_7a_period_json_golden as g

    assert g.GOLDEN_RUN["seed"] == g.golden_seed(g.GOLDEN)
    other = tmp_path / "period.json"
    other.write_text(json.dumps({"meta": {"seed": 7}}), encoding="utf-8")
    assert g.golden_seed(other) == 7


# --- review BLOCKER: the single-run transparency scenario draws on a recorded seed ----------

def test_the_single_run_scenario_records_its_seed_and_reproduces_from_it():
    from tests.test_single_run_shared import (_make_buckets, _make_chains, _make_config,
                                              _make_mixed_risks)
    from src.single_run import run_single

    args = (_make_config(view="All"), _make_buckets(), _make_chains(), _make_mixed_risks())
    drawn = run_single(*args)
    assert isinstance(drawn.seed, int) and drawn.seed > 0
    again = run_single(*args, seed=drawn.seed)
    assert (again.seed, again.total_outturn) == (drawn.seed, drawn.total_outturn)
    assert run_single(*args, seed=7).seed == 7


# --- review WARNs: --seed 0 follows the convention; a declared period seed is fixed ----------

def test_a_period_seed_of_0_is_drawn_and_recorded_as_drawn():
    from src.am.run_period import _period_seed

    assert _period_seed(None, "synthetic_wind") == (42, "binding")
    assert _period_seed(7, "synthetic_wind") == (7, "override")
    seed, source = _period_seed(0, "synthetic_wind")
    assert seed > 0 and source == "drawn"


def test_a_binding_cannot_declare_a_period_seed_of_0():
    from src.sra.cpm.bindings.registry import ProjectBinding

    with pytest.raises(ValueError, match="period_seed"):
        ProjectBinding(name="t", project_name="T", period_seed=0)


def test_the_page7_seed_is_refused_outside_the_charts_swallow(tmp_path):
    from src.final.composer import _generate_v3_charts

    results = {"DP_Review": {"cost_dollars_array": np.arange(2_000, dtype=float)}}
    with pytest.raises(ValueError, match="no seed was given"):
        _generate_v3_charts(results, [], [], [], tmp_path, 1.0, indicative_name="DP_Review",
                            seed=None)
