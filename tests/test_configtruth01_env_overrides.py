"""CONFIGTRUTH-01 P4 (register item 3): an environment override is a number the run can use, or a refusal.

``SR9_ITERATIONS`` overrides the register's iteration count. Before this stage the deliverable tested
the environment *string*, so ``"0"`` was truthy and reached the engines as an iteration count of 0,
and a non-numeric value surfaced as a bare ``ValueError`` from ``int()``. Unset or blank still means
"the register's".

The seed limb of P4 is the Director's call and is not asserted here.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.final.deliverable import resolve_inputs
from src.final.deliverable_preflight import DeliverablePreflightError

REPO = Path(__file__).resolve().parents[1]
WIND_DIR = REPO / "tests" / "fixtures" / "synthetic_wind"


@pytest.fixture
def wind_env(monkeypatch) -> dict[str, str]:
    import src.sra.cpm.bindings.synthetic_wind  # noqa: F401  self-registers

    monkeypatch.setenv("QRA_PROJECT", "synthetic_wind")
    return {
        "QRA_PROJECT": "synthetic_wind",
        "REGISTER_FILE": str(WIND_DIR / "wind_register.xlsx"),
        "P6_FILE": str(WIND_DIR / "wind_schedule.xer"),
        "STRAWMAN_FILE": str(WIND_DIR / "wind_register.xlsx"),
    }


@pytest.mark.parametrize("value", ["0", "-1", "-50000", "abc", "1.5", "1e5"])
def test_an_iteration_override_that_is_not_a_positive_integer_is_refused_by_name(
        value, wind_env, tmp_path):
    with pytest.raises(DeliverablePreflightError, match="SR9_ITERATIONS"):
        resolve_inputs({**wind_env, "SR9_ITERATIONS": value}, output_dir=tmp_path)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_an_unset_or_blank_iteration_override_means_the_registers(value, wind_env, tmp_path):
    env = dict(wind_env)
    if value is not None:
        env["SR9_ITERATIONS"] = value
    assert resolve_inputs(env, output_dir=tmp_path).iterations is None


def test_a_positive_iteration_override_is_used(wind_env, tmp_path):
    env = {**wind_env, "SR9_ITERATIONS": " 5000 "}
    assert resolve_inputs(env, output_dir=tmp_path).iterations == 5000
