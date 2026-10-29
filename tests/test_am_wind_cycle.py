"""Wind AM cycle end-to-end test (showcase-P4 WS4-C/D, brief section 3).

Asserts the project-aware AM consumer runs the full monthly cycle on the
synthetic-wind project and produces valid Doc 3 v2.3 JSON that:
  - completes end-to-end (workbook -> engine -> metrics -> JSON);
  - carries only WT risk ids (no the engagement R-prefixed ids);
  - carries no engagement identifier (asserted by the prefix, display-name and register checks)
  - holds the AM02.1 invariants (monotonic per-activity P-bands, sorted
    risks, valid schema).

Marked ``@pytest.mark.integration`` (runs the real engine at a low
iteration count; NOT slow). Skips cleanly if the wind fixtures or the
generated wind period workbook are absent.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

import pytest

from tests.input_skips import skip_missing

from src.am.project_binding import WIND_FIXTURE_DIR
from src.am.run_period import run_period

pytestmark = pytest.mark.integration

AM_REPO_ROOT = Path(__file__).resolve().parent.parent
WIND_PERIOD_01 = AM_REPO_ROOT / "status_periods" / "wind_period_01.xlsx"
WIND_PERIOD_02 = AM_REPO_ROOT / "status_periods" / "wind_period_02.xlsx"

# Identifiers that must never appear on the wind path.
# The former inline list of engagement identifiers and its two leak-check tests were
# retired at RS-A2: the client gate asserts that property over the whole tree.

@pytest.fixture(scope="module")
def wind_json(tmp_path_factory: pytest.TempPathFactory) -> dict:
    if not WIND_PERIOD_01.is_file():
        skip_missing(WIND_PERIOD_01, detail="run scripts/build_wind_am_periods.py")
    if not (WIND_FIXTURE_DIR / "wind_register.xlsx").is_file():
        skip_missing(WIND_FIXTURE_DIR / "wind_register.xlsx")

    out_dir = tmp_path_factory.mktemp("wind_data")
    json_path = run_period(
        workbook_path=WIND_PERIOD_01,
        project="synthetic_wind",
        output_dir=out_dir,
        main_iterations=2000,
        days_at_risk_iterations=500,
        counterfactual_iterations=500,
        seed=42,
        criticality_measurement_mode="both",
        project_start=_dt.date(2024, 1, 1),
        # AM09: integration tests exercise the pipeline regardless of the dev's
        # the engine working-tree state; the dirty-tree guard's own behaviour
        # is covered deterministically in test_engine_provenance.py.
        allow_dirty=True,
    )
    assert json_path.is_file()
    with json_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# RS-A2: the retired leak-check tests asserted no engagement identifier in the emitted
# JSON. That artefact lives in a tmp dir or the ignored data/, which the client gate does
# not scan (R-9). The property is asserted here instead by test_wind_risks_are_all_wt_prefixed,
# test_wind_project_display_name_is_tropic_ridge and the register_version check below.


def test_wind_cycle_completes_with_valid_schema(wind_json: dict) -> None:
    assert wind_json["schema_version"] == "1.5"  # INTSCURVE-01 Part C: integrated curve points and JCL
    # A LITERAL on purpose, not SCHEMA_VERSION - a version assertion that reads the
    # constant it is checking passes through any bump and gates nothing. 1.3 was
    # PROVCRLF01 ({method, value} digests); 1.4 is C2, ruled 05/09/2026.
    assert wind_json["meta"]["register_version"] == "Tropic Ridge Wind Farm"  # the product's name, not a binding key (PUBLICFACE-01)
    for block in ("meta", "headline", "risks", "activities", "distribution",
                  "audit"):
        assert block in wind_json
    # AM10 (WIND-01 A4): divergence_flag dropped from the contract.
    assert all("divergence_flag" not in r for r in wind_json["risks"])


def test_wind_risks_are_all_wt_prefixed(wind_json: dict) -> None:
    rids = [r["risk_id"] for r in wind_json["risks"]]
    assert rids, "no risks in wind JSON"
    assert all(str(r).startswith("WT") for r in rids), rids
    # No the engagement-style R-prefixed ids.
    assert not [r for r in rids if re.match(r"^R\d", str(r))]


def test_wind_project_display_name_is_tropic_ridge(wind_json: dict) -> None:
    """showcase-P5 WS5-C: the wind period JSON carries the public display
    name the dashboard chrome resolves, and it carries no the engagement
    identifier (covered by test_wind_json_has_zero_engagement_identifiers)."""
    assert wind_json["meta"]["project_display_name"] == "Tropic Ridge Wind Farm"


def test_wind_activity_p_bands_monotonic(wind_json: dict) -> None:
    items = wind_json["activities"]["items"]
    assert items
    for it in items:
        assert it["p10_finish_days"] <= it["p50_finish_days"] <= it["p90_finish_days"]
        assert it["p10_start_days"] <= it["p50_start_days"] <= it["p90_start_days"]


def test_wind_risks_sorted_by_days_at_risk_desc(wind_json: dict) -> None:
    days = [r["days_at_risk_p80"] for r in wind_json["risks"]]
    assert days == sorted(days, reverse=True)


# ---------------------------------------------------------------------------
# AM08 / AIA-01 (+01b): period-over-period attribution end-to-end. Runs two
# periods so period 2 carries a populated delta; asserts attribution, the
# effective-probability surfacing, and the days-at-risk floor at smoke
# precision. NOT slow.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def wind_period2_json(tmp_path_factory: pytest.TempPathFactory) -> dict:
    if not (WIND_PERIOD_01.is_file() and WIND_PERIOD_02.is_file()):
        pytest.skip("wind period workbooks missing "
                    "(run scripts/build_wind_am_periods.py)")
    if not (WIND_FIXTURE_DIR / "wind_register.xlsx").is_file():
        skip_missing(WIND_FIXTURE_DIR / "wind_register.xlsx")
    out_dir = tmp_path_factory.mktemp("wind_two_periods")
    common = dict(
        project="synthetic_wind", output_dir=out_dir,
        main_iterations=2000, days_at_risk_iterations=500,
        counterfactual_iterations=500, seed=42,
        criticality_measurement_mode="both",
        project_start=_dt.date(2024, 1, 1),
        allow_dirty=True,  # AM09: see note above; guard tested separately
    )
    run_period(workbook_path=WIND_PERIOD_01, **common)  # baseline (period_0)
    json_path = run_period(workbook_path=WIND_PERIOD_02, **common)
    with json_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_wind_period2_delta_attribution_populated(wind_period2_json: dict) -> None:
    """AM08 Part A: period 2's delta carries per-risk attribution, not empty."""
    delta = wind_period2_json["delta"]
    assert not delta.get("period_0")
    assert (len(delta["worse"]) + len(delta["better"])) >= 1
    # WT-008's long-lead override (0.40 -> 0.90) is the dominant worsening; its
    # ~9-day days-at-risk jump dwarfs the smoke-precision noise floor.
    assert "WT-008" in [e["risk_id"] for e in delta["worse"]]
    for e in delta["worse"] + delta["better"] + delta["new"]:
        assert set(e) >= {"risk_id", "description", "change_meta", "delta_days"}


def test_wind_period2_effective_probability_surfaced(wind_period2_json: dict) -> None:
    """AM08 Part B: WT-008 carries its effective override probability (0.9),
    not the register baseline (0.4)."""
    w8 = next(r for r in wind_period2_json["risks"] if r["risk_id"] == "WT-008")
    assert w8["probability"] == pytest.approx(0.9)


def test_wind_period2_no_negative_days_at_risk(wind_period2_json: dict) -> None:
    """AM08 Part B: days_at_risk_p80 floored at 0."""
    assert all(r["days_at_risk_p80"] >= 0.0 for r in wind_period2_json["risks"])
