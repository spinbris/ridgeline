"""Stage 4 F-29 (D-2, first-rank): the report's CG drivers table must not ask the binding for a
legacy coefficient dictionary the register has already supplied.

Found on 08/09/2026, fourth run of the Kestrel Highway register through RUN_FINAL.bat: every engine
and the cross-validation completed, then `build_cg_drivers_table` imported
`src.defaults.HEADLESS_CG_COEFFICIENTS` eagerly - a binding-sourced legacy value the road binding
omits on purpose - and only then applied the register's coefficients over the top. The import was
the only thing the run used it for. Same shape as F-27, one layer up.

The property: when the caller supplies the register's coefficients, they are the table's
coefficients, and no binding is consulted. The legacy dictionary is asked for only on the path
that has nothing else, which is the legacy cost-MC / test path.
"""
from __future__ import annotations

import pytest

from src.config import RiskInput
from src.final.sections.cost_drivers import build_cg_drivers_table


def _risk(rid: str, cg: str) -> RiskInput:
    return RiskInput(
        risk_id=rid, description="a risk", owner="", distribution="PERT", correlation_group=cg,
        probability=0.3, opt_cost=1.0, ml_cost=2.0, pess_cost=3.0,
    )


@pytest.fixture
def road_active(monkeypatch):
    from src.am.project_binding import activate_project
    monkeypatch.setenv("QRA_PROJECT", "synthetic_road")
    activate_project("synthetic_road")
    yield


def test_register_supplied_coefficients_need_no_binding(road_active):
    """Red before the fix: ValueError from src.defaults, on a call that had every coefficient
    it needed in hand."""
    rows = build_cg_drivers_table(
        [_risk("KH-001", "CG01"), _risk("KH-002", "CG01"), _risk("KH-004", "CG02")],
        cg_descriptions={"CG01": "Establishment", "CG02": "Earthworks"},
        cg_coefficients={"CG01": 0.5, "CG02": 0.6},
    )
    by_cg = {r["cg_id"]: r for r in rows}
    assert by_cg["CG01"]["coefficient"] == 0.5
    assert by_cg["CG02"]["coefficient"] == 0.6
    assert by_cg["CG01"]["member_risk_ids"] == ["KH-001", "KH-002"]


def test_a_cg_the_register_does_not_price_renders_none_not_a_legacy_value(road_active):
    """A coefficient the register does not carry is shown as absent, never borrowed from a
    legacy dictionary - which is what the docstring promised and the old base dict undid."""
    rows = build_cg_drivers_table(
        [_risk("KH-030", "CG08")],
        cg_descriptions={"CG08": "Finishing"},
        cg_coefficients={"CG01": 0.5},
    )
    assert rows[0]["cg_id"] == "CG08" and rows[0]["coefficient"] is None


def test_without_supplied_coefficients_the_legacy_path_is_still_consulted(road_active):
    """The legacy cost-MC / test path keeps its behaviour: no coefficients supplied means the
    binding's headless dictionary is asked for, and a project without one refuses by name."""
    with pytest.raises(ValueError, match="cg_coefficients"):
        build_cg_drivers_table([_risk("KH-001", "CG01")], cg_descriptions={"CG01": "x"})
