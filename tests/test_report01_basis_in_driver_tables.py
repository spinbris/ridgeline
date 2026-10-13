"""REPORT01 F-F: the elicitation basis reaches the driver tables.

GAP01 F-F: `Basis of Estimate` is captured per risk and printed nowhere, so a reviewer
cannot see which numbers are workshop-agreed and which are placeholders - while the
deliverable carries a banner saying bindings are pending workshop validation.

Director D-2: the basis lands as a column on the **existing** driver tables rather than
as a table of its own, in both documents.

The register carries the header twice, once per section, and the two arms must not cross
over: the cost drivers table shows the Contingent section's basis, the schedule drivers
table shows the Time section's (`RiskInput.time_basis`, added by D-3).
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.final.sections._basis import BASIS_COLUMN, NOT_RECORDED
from src.final.sections.cost_drivers import build_cost_drivers_section
from src.final.sections.schedule_drivers import build_schedule_drivers_section

COST_BASIS = "ECI agreed - package 4 quotation"
TIME_BASIS = "Workshop agreed - 2026-03-11 session"


def _make_risk(rid: str, **kw) -> SimpleNamespace:
    defaults = {
        "probability": 0.4,
        "ml_cost": 100_000.0,
        "ml_days": 5.0,
        "opt_schedule_days": 1.0,
        "pess_schedule_days": 15.0,
        "pess_cost": 500_000.0,
        "rbs_l1": "10.Civil",
        "correlation_group": "",
        "basis": COST_BASIS,
        "time_basis": TIME_BASIS,
    }
    defaults.update(kw)
    return SimpleNamespace(risk_id=rid, **defaults)


def _integrated(n_iter: int = 300, n_risks: int = 5) -> dict:
    rng = np.random.default_rng(0)
    return {
        "cost_dollars_array": rng.uniform(0, 10_000_000, size=n_iter),
        "schedule_days_array": rng.uniform(0, 30, size=n_iter),
        "per_risk_cost_array": rng.uniform(0, 2_000_000, size=(n_iter, n_risks)),
        "per_risk_schedule_array": rng.uniform(0, 5, size=(n_iter, n_risks)),
        "risk_ids_all": [f"R{i:03d}" for i in range(n_risks)],
        "risk_ids_dual": [f"R{i:03d}" for i in range(n_risks)],
    }


def _cost_tables(risks) -> list[list[dict]]:
    out = build_cost_drivers_section(
        integrated_dp=_integrated(n_risks=len(risks)),
        risks_list=risks,
        risk_titles={r.risk_id: f"Title {r.risk_id}" for r in risks},
        p_level=80,
        headline_metric="P80",
    )
    p3 = out["page3_cost_drivers"]
    return [p3["drivers_table"], p3["drivers_table_full"]]


def _schedule_table(risks) -> list[dict]:
    out = build_schedule_drivers_section(
        integrated_dr=_integrated(n_risks=len(risks)),
        risks_list=risks,
        risk_titles={r.risk_id: f"Title {r.risk_id}" for r in risks},
        indicative_scenario_display="Dummy Realistic",
        mode_used={r.risk_id: "Series" for r in risks},
        appendix_counterfactual=pd.DataFrame(),
    )
    return out["page4_schedule_drivers"]["drivers_table"]


def test_cost_driver_rows_carry_the_contingent_basis():
    risks = [_make_risk(f"R{i:03d}") for i in range(5)]
    for table in _cost_tables(risks):
        assert table, "the cost drivers table is empty; nothing was asserted"
        for row in table:
            assert row[BASIS_COLUMN] == COST_BASIS


def test_schedule_driver_rows_carry_the_time_basis():
    risks = [_make_risk(f"R{i:03d}") for i in range(5)]
    table = _schedule_table(risks)
    assert table, "the schedule drivers table is empty; nothing was asserted"
    for row in table:
        assert row[BASIS_COLUMN] == TIME_BASIS


def test_the_two_arms_do_not_cross_over():
    """The cost table must never show the time basis, nor the schedule table the cost one.

    The register's two Basis of Estimate columns share a header. If a future change
    resolved one lookup for both arms, every same-value fixture would still pass, so
    this fixture gives the two arms deliberately different strings.
    """
    risks = [_make_risk(f"R{i:03d}") for i in range(5)]
    cost_values = {row[BASIS_COLUMN] for t in _cost_tables(risks) for row in t}
    sched_values = {row[BASIS_COLUMN] for row in _schedule_table(risks)}
    assert cost_values == {COST_BASIS}
    assert sched_values == {TIME_BASIS}


def test_an_unrecorded_basis_renders_as_not_recorded_on_both_arms():
    """P-5: blank stays visibly blank.

    An empty cell in the rendered table is one a reader can mistake for agreed. A risk
    with no recorded basis must say so in words.
    """
    risks = [_make_risk(f"R{i:03d}", basis="", time_basis="") for i in range(5)]
    for table in _cost_tables(risks):
        for row in table:
            assert row[BASIS_COLUMN] == NOT_RECORDED
    for row in _schedule_table(risks):
        assert row[BASIS_COLUMN] == NOT_RECORDED


def test_whitespace_only_basis_is_also_not_recorded():
    """A cell holding only spaces is not a recorded basis either.

    Registers are hand-filled; a stray space is indistinguishable from blank to a
    reader and must be to the report.
    """
    risks = [_make_risk(f"R{i:03d}", basis="   ", time_basis="\t") for i in range(5)]
    for row in _cost_tables(risks)[0]:
        assert row[BASIS_COLUMN] == NOT_RECORDED
    for row in _schedule_table(risks):
        assert row[BASIS_COLUMN] == NOT_RECORDED


def test_a_risk_absent_from_the_register_list_reads_as_not_recorded():
    """The driver ranking comes from the engine arrays, the basis from the risk list.

    If the two disagree - a risk id in the arrays with no matching register row - the
    cell must say "not recorded" rather than raise or silently borrow another risk's
    basis.
    """
    risks = [_make_risk(f"R{i:03d}") for i in range(3)]  # arrays carry 5
    out = build_cost_drivers_section(
        integrated_dp=_integrated(n_risks=5),
        risks_list=risks,
        risk_titles=None,
        p_level=80,
        headline_metric="P80",
    )
    table = out["page3_cost_drivers"]["drivers_table_full"]
    unmatched = [r for r in table if r["Risk"] in {"R003", "R004"}]
    assert unmatched, "fixture did not produce an unmatched driver row"
    for row in unmatched:
        assert row[BASIS_COLUMN] == NOT_RECORDED


def test_a_real_register_yields_real_basis_text_not_a_wall_of_not_recorded():
    """The wiring guard.

    Every failure mode of this feature - wrong field name, lookup keyed on the wrong
    thing, the risks list not reaching the builder - renders as `Not recorded` on every
    row, which is exactly what a correctly-working empty register looks like. Only real
    register text tells the two apart, so this reads the committed wind fixture.
    """
    import numpy as np

    from src.v5_register_reader import read_risks_v5

    risks = read_risks_v5(
        "tests/fixtures/synthetic_wind/wind_register.xlsx", risk_id_prefix="WT")
    assert risks, "the wind fixture parsed no risks"
    ids = [r.risk_id for r in risks]
    rng = np.random.default_rng(0)
    integ = {
        "per_risk_cost_array": rng.uniform(0, 2_000_000, size=(200, len(ids))),
        "per_risk_schedule_array": rng.uniform(0, 5, size=(200, len(ids))),
        "risk_ids_all": ids,
        "risk_ids_dual": ids,
    }
    table = build_cost_drivers_section(
        integrated_dp=integ, risks_list=risks, risk_titles=None,
        p_level=80, headline_metric="P80",
    )["page3_cost_drivers"]["drivers_table_full"]

    values = {row[BASIS_COLUMN] for row in table}
    assert values, "no driver rows were produced"
    assert values != {NOT_RECORDED}, (
        "every row read as unrecorded against a register that populates the column - "
        f"the basis is not reaching the table. Got: {values}")
    assert "Wind Farm Beta capex basis" in values
