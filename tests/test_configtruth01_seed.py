"""CONFIGTRUTH-01 P4 seed limb, as the Director ruled it on 08/10/2026 (PM task -5).

"i would tend to make the random seed of 0 random same as blank, as that tends to suit excel, and why
use a 0 seed?" and "i thought 0 or blank would be just random, ie not replicable and anything else was
seeded/replicable?"

So: ``SR9_SEED`` unset, blank or ``0`` is random - a seed is drawn ONCE, at the start of the run, and
that one value goes to every arm, so no engine ever sees 0 (the standalone cost MC reads 0 as "fresh
random" while Stage 3 and the SRA arm read it as a fixed seed, which made ``SR9_SEED=0`` a mixed run).
A positive whole number is fixed and repeatable; negative or non-numeric is refused by name. The
manifest records the seed actually used, never 0, and where it came from, so a drawn run can be
reproduced by giving its recorded seed back.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.final.deliverable import build_provenance, resolve_inputs, run_engines
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
        "SR9_ITERATIONS": "1000",
    }


def _env(wind_env: dict[str, str], seed: str | None) -> dict[str, str]:
    env = dict(wind_env)
    if seed is not None:
        env["SR9_SEED"] = seed
    return env


@pytest.mark.parametrize("seed", [None, "", "  ", "0", " 0 "])
def test_an_unset_blank_or_zero_seed_is_drawn_never_zero(seed, wind_env, tmp_path):
    inputs = resolve_inputs(_env(wind_env, seed), output_dir=tmp_path)
    assert isinstance(inputs.seed, int) and inputs.seed > 0, inputs.seed
    assert inputs.seed_source == "drawn"


@pytest.mark.parametrize("seed", ["-1", "abc", "1.5", "4e2"])
def test_a_negative_or_non_numeric_seed_is_refused_by_name(seed, wind_env, tmp_path):
    with pytest.raises(DeliverablePreflightError, match="SR9_SEED"):
        resolve_inputs(_env(wind_env, seed), output_dir=tmp_path)


def test_a_positive_seed_is_used_and_said_to_be_the_override(wind_env, tmp_path):
    inputs = resolve_inputs(_env(wind_env, " 123 "), output_dir=tmp_path)
    assert (inputs.seed, inputs.seed_source) == (123, "override")


@pytest.mark.slow
@pytest.mark.parametrize("seed", [None, "0"])
def test_a_drawn_run_is_reproduced_by_its_recorded_seed(seed, wind_env, tmp_path):
    """The red-first of record: a run with no seed, then a second given the first's recorded seed,
    agree exactly on the Stage 3 headline arrays and on the standalone cost-MC reference."""
    first_inputs = resolve_inputs(_env(wind_env, seed), output_dir=tmp_path / "a")
    first = run_engines(first_inputs)
    provenance = build_provenance(first_inputs, first, {}, [])
    recorded = provenance["params"]["seed"]
    assert recorded and provenance["params"]["seed_source"] == "drawn", provenance["params"]

    second = run_engines(resolve_inputs(_env(wind_env, str(recorded)), output_dir=tmp_path / "b"))
    for name, a, b in (
        ("Stage 3 cost", first.stage3_result.cost_result["cost_dollars_array"],
         second.stage3_result.cost_result["cost_dollars_array"]),
        ("Stage 3 schedule", first.stage3_result.schedule_days_array,
         second.stage3_result.schedule_days_array),
        ("standalone cost MC", first.cost_results["cost_dollars_array"],
         second.cost_results["cost_dollars_array"]),
    ):
        assert np.array_equal(np.asarray(a), np.asarray(b)), f"{name} did not reproduce from seed {recorded}"


def test_a_drawn_seed_is_drawn_not_a_constant(wind_env):
    """Gate 3 WARN 4: a draw replaced by a constant must fail here. Eight draws from 2**31 - 1 values
    are all equal with probability (2**31 - 1) ** -7, so this cannot flake in practice; a constant
    makes them equal every time."""
    from src.final.deliverable_preflight import seed_override

    draws = {seed_override({"SR9_SEED": value})[0] for value in ("", "0") * 4}
    assert len(draws) > 1, draws


@pytest.mark.slow
def test_a_drawn_seed_reaches_the_written_provenance_and_the_page_a_re_runner_reads(wind_env, tmp_path):
    """Gate 3 round 2: the reproducibility paragraph points to the seed recorded in the provenance, so the
    seed the engines used must be the one written to provenance.json and printed on the run diagnostic -
    not only the one in the in-memory dict the reproduction test above reads."""
    import json

    from src.final.deliverable import run_deliverable

    run = run_deliverable(env=_env(wind_env, None), output_dir=tmp_path)
    used = int(run.engines.stage3_result.seed_used)
    assert used > 0

    manifest = next(Path(a) for a in run.artefacts if Path(a).name == "provenance.json")
    params = json.loads(manifest.read_text(encoding="utf-8"))["params"]
    assert (params["seed"], params["seed_source"]) == (used, "drawn"), params

    diagnostic = next(Path(a) for a in run.artefacts if Path(a).name.startswith("run_diagnostic_"))
    words = [line.split() for line in diagnostic.read_text(encoding="utf-8").splitlines()]
    assert ["Seed:", str(used)] in words, "the page a re-runner reads does not print the seed the run used"
