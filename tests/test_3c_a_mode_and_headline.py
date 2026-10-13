"""3c Part A: the properties that survived the R-4 rebuild, re-expressed against what exists.

NBREBUILD-01's disposition. Retiring the pre-3c notebook and runner redded 29 tests that read
the *source* of those artefacts - the `--mode dev/prod` argument parser, the `_PROD` filename
suffix, "cell 7c does not import sibling renderers", "page 5 cells wrapped dev-only". Most of
them asserted a design that no longer exists and are retired with it.

Some asserted something that still matters, and those are here, rewritten to assert the
**behaviour** rather than the shape of a cell's source text. That is the more durable form: the
old tests broke because the notebook was rebuilt, not because anything they cared about
regressed, which is what a source-shape assertion buys you.

Dev mode is retired from this entry point (Director 04/09/2026, recorded in
`src/final/deliverable.DELIVERABLE_MODE`): the product runs prod, and an explicit request for
dev is refused rather than ignored. The `mode` parameter inside `src/final` is untouched -
removing it is SR10's structural refactor.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.final.deliverable import DELIVERABLE_MODE, manifest_path, resolve_inputs
from src.final.deliverable_preflight import DeliverablePreflightError

REPO = Path(__file__).resolve().parents[1]
WIND_DIR = REPO / "tests" / "fixtures" / "synthetic_wind"


@pytest.fixture
def wind_env() -> dict[str, str]:
    return {
        "QRA_PROJECT": "synthetic_wind",
        "REGISTER_FILE": str(WIND_DIR / "wind_register.xlsx"),
        "P6_FILE": str(WIND_DIR / "wind_schedule.xer"),
        "STRAWMAN_FILE": str(WIND_DIR / "wind_register.xlsx"),
    }


@pytest.fixture
def wind_project():
    import os

    import src.sra.cpm.bindings.synthetic_wind  # noqa: F401  self-registers

    saved = os.environ.get("QRA_PROJECT")
    os.environ["QRA_PROJECT"] = "synthetic_wind"
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("QRA_PROJECT", None)
        else:
            os.environ["QRA_PROJECT"] = saved


# --- survived: prod is the basis (was test_run_final_bat_defaults_to_prod) ----------------

def test_the_deliverable_runs_prod(wind_env, wind_project, tmp_path):
    assert resolve_inputs(wind_env, output_dir=tmp_path).mode == "prod" == DELIVERABLE_MODE


def test_prod_may_be_requested_explicitly(wind_env, wind_project, tmp_path):
    env = dict(wind_env, FINAL_REPORT_MODE="prod")
    assert resolve_inputs(env, output_dir=tmp_path).mode == "prod"


# --- changed deliberately: dev is refused, not honoured and not ignored -------------------

@pytest.mark.parametrize("requested", ["dev", "DEV", "Dev"])
def test_an_explicit_dev_request_is_refused_by_name(requested, wind_env, wind_project, tmp_path):
    """Was `test_run_final_bat_validates_mode_values`, which required dev to be ACCEPTED.

    The refusal, rather than a silent downgrade to prod, is the point: an operator who asked
    for dev and got a prod report without being told would quote it as a dev report.
    """
    env = dict(wind_env, FINAL_REPORT_MODE=requested)
    with pytest.raises(DeliverablePreflightError, match="runs 'prod' only"):
        resolve_inputs(env, output_dir=tmp_path)


def test_an_unrecognised_mode_is_refused_too(wind_env, wind_project, tmp_path):
    env = dict(wind_env, FINAL_REPORT_MODE="staging")
    with pytest.raises(DeliverablePreflightError):
        resolve_inputs(env, output_dir=tmp_path)


def test_the_runner_no_longer_offers_a_mode_switch():
    """The other half: the entry point must not advertise what the engine refuses."""
    text = (REPO / "RUN_FINAL.bat").read_text(encoding="utf-8")
    assert "--mode" not in text
    executable = [ln for ln in text.splitlines()
                  if ln.strip() and not ln.strip().upper().startswith("REM")]
    assert not any("FINAL_REPORT_MODE" in ln for ln in executable), (
        "the runner sets or forwards FINAL_REPORT_MODE; the deliverable pins prod")


# --- survived: the headline metric is honoured (was the --headline/--both parsing) --------

@pytest.mark.parametrize(
    "requested, expected",
    [(None, ("P80",)), ("P80", ("P80",)), ("Mean", ("Mean",)), ("both", ("P80", "Mean"))],
)
def test_the_headline_metric_selection_is_honoured(
    requested, expected, wind_env, wind_project, tmp_path
):
    env = dict(wind_env)
    if requested is not None:
        env["FINAL_REPORT_HEADLINE_METRIC"] = requested
    assert resolve_inputs(env, output_dir=tmp_path).headline_metrics == expected


def test_the_runner_still_offers_the_headline_switch():
    text = (REPO / "RUN_FINAL.bat").read_text(encoding="utf-8")
    assert "--headline" in text
    assert "FINAL_REPORT_HEADLINE_METRIC" in text


# --- changed deliberately: the state cache is keyed by project, not by a mode suffix ------

def test_the_state_cache_path_is_keyed_by_date_and_project():
    """Was `test_notebook_state_cache_cell_uses_mode_suffix_in_state_cache_path`.

    The `_PROD` / `_PROD_MEAN` suffixes existed to keep dev and prod runs of the same day
    apart. With one mode there is nothing to separate, and the project key is what a single
    install serving several projects (D-7) actually needs.
    """
    p = manifest_path("outputs", "synthetic_wind", "2026-09-04")
    assert p.parent.name == "2026-09-04_synthetic_wind"
    assert "_PROD" not in str(p)


def test_two_projects_on_the_same_day_do_not_share_a_cache_directory():
    """What the project key buys, and the reason it replaced the mode suffix."""
    a = manifest_path("outputs", "synthetic_wind", "2026-09-04")
    b = manifest_path("outputs", "refproject", "2026-09-04")
    assert a.parent != b.parent
