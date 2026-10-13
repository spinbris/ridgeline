"""Stage 7 part A, D-1: the engine-output gate SPEC §3 limb 4 specifies.

SPEC §3 limb 4 defines the app half as two linked gates, "because the app renders and does not
compute": an **engine-output gate** - fixed register, `.xer`, seed and engine SHA produce a period
JSON identical to a committed golden - and an app-render gate over that same golden (D-2, part D).

SPEC §7a asserted the golden already existed: *"The showcase's golden period JSON that §3 limb 4
needs is committed, under `tests/golden/`, because it is synthetic."* **It was not in the tree.**
The stage 7 brief §2 recorded that as a finding - the spec asserting an artefact that does not
exist - and part A creates it. These tests are what make it a gate rather than a file.

**Regenerating it** (only on an approved methodology change, and only from a clean tree, so the
stamp attests to real committed code):

    python -m src.am.run_period --workbook status_periods/wind_period_01.xlsx \\
        --project synthetic_wind --output-dir <tmp> --project-start 2024-01-01

at the iteration counts and seed in `GOLDEN_RUN` below, then copy the emitted file over
`GOLDEN`. A moved number is a bug until a methodology change says otherwise - the GOLDEN01 rule,
applied to a document instead of a manifest.

**Why the comparison is masked, and how far.** A period JSON cannot be byte-identical run to run:
`meta.engine_run_hash` is a fresh `uuid.uuid4()` every run and `meta.engine_run_date` is a
timestamp. `scripts/ws4a_repro_gate.py` already exists to compare two period JSONs with exactly
those neutralised and **every number bit-locked**, so this gate reuses it rather than growing a
second masking rule that could drift from the first. The gate runs in its DEFAULT mode, not
`--mask-rundate`: that flag additionally masks `period_end_date`, which for a fixed register is a
fixed value and must stay compared.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from tests.input_skips import skip_missing
from src.git_identity import git_env

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "golden" / "period_json" / "wind_synth" / "period_20260228.json"
WORKBOOK = REPO / "status_periods" / "wind_period_01.xlsx"
_GATE = REPO / "scripts" / "ws4a_repro_gate.py"


def golden_seed(path: Path = GOLDEN) -> int:
    """The seed the golden records. The rerun takes it from there, never retyped (SEEDZERO-01 P4)."""
    return int(json.loads(path.read_bytes().decode("utf-8"))["meta"]["seed"])

#: The run that produced GOLDEN. Low iteration counts deliberately: this is a reproducibility
#: gate, not a precision claim, and it has to be affordable in the stage lane (~3s).
GOLDEN_RUN = dict(
    project="synthetic_wind",
    main_iterations=2000,
    days_at_risk_iterations=500,
    counterfactual_iterations=500,
    seed=golden_seed(),
    criticality_measurement_mode="both",
    project_start=_dt.date(2024, 1, 1),
)


@pytest.fixture(scope="module")
def golden() -> dict:
    if not GOLDEN.is_file():
        pytest.fail(f"the committed golden is missing: {GOLDEN.relative_to(REPO).as_posix()}")
    return json.loads(GOLDEN.read_bytes().decode("utf-8"))


@pytest.fixture(scope="module")
def fresh_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Re-run the engine at GOLDEN's parameters. Module-scoped: one run serves every test."""
    if not WORKBOOK.is_file():
        skip_missing(WORKBOOK, detail="run scripts/build_wind_am_periods.py")

    from src.am.run_period import run_period

    # allow_dirty: a developer's working tree is dirty by definition mid-change, and the
    # dirty-tree guard has its own coverage in test_engine_provenance.py. The GOLDEN itself was
    # cut clean - test_the_golden_attests_to_committed_code is what holds that line.
    return run_period(
        workbook_path=WORKBOOK,
        output_dir=tmp_path_factory.mktemp("stage7a_fresh"),
        allow_dirty=True,
        **GOLDEN_RUN,
    )


def _gate(baseline: Path, candidate: Path) -> int:
    """Run ws4a_repro_gate in-process, as tests/test_am_ws4a_repro_gate.py does. Its exit code
    is the assertion: 0 = every number identical under the provenance mask, 1 = something moved."""
    spec = importlib.util.spec_from_file_location("ws4a_repro_gate", _GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main(["ws4a_repro_gate.py", str(baseline), str(candidate)])


# --- the artefact SPEC §7a asserted, now actually present ------------------------------------

def test_the_golden_is_committed(golden: dict) -> None:
    """SPEC §7a's claim, which was false when the stage 7 brief was written. A golden that is
    only on the author's disk gates nothing on a fresh clone."""
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", str(GOLDEN.relative_to(REPO).as_posix())],
        cwd=REPO, capture_output=True, text=True, env=git_env())
    assert tracked.returncode == 0, (
        f"{GOLDEN.relative_to(REPO).as_posix()} is not tracked; SPEC §7a requires it committed")


def test_the_golden_is_the_synthetic_project_never_an_engagement(golden: dict) -> None:
    """SPEC §7a routes goldens by `confidential`: the synthetic wind project is committed
    precisely because it is synthetic. A golden cut from a real engagement would put client
    material in a public-releasable tree."""
    registry = (REPO / "tests" / "golden" / "projects.toml").read_text(encoding="utf-8")
    assert "confidential = false" in registry, "wind_synth is no longer the public project"

    assert golden["meta"]["project_display_name"] == "Tropic Ridge Wind Farm"
    assert golden["meta"]["register_version"] == "Tropic Ridge Wind Farm"
    off_project = [r["risk_id"] for r in golden["risks"] if not r["risk_id"].startswith("WT-")]
    assert off_project == [], f"non-wind risk IDs in the golden: {off_project}"


def test_the_golden_attests_to_committed_code(golden: dict) -> None:
    """A golden cut from a dirty tree names a commit whose code is not what ran. `engine_sha`
    would then attest to something that never produced these numbers - the exact failure the
    provenance stamp exists to rule out, baked into the artefact everything else is measured
    against."""
    assert golden["meta"]["engine_tree_dirty"] is False, (
        "the golden was cut from a dirty tree; re-cut it clean")
    assert len(golden["meta"]["engine_sha"]) == 40, golden["meta"]["engine_sha"]


# --- the gate itself -------------------------------------------------------------------------

def test_a_fresh_run_reproduces_the_golden(fresh_run: Path) -> None:
    """SPEC §3 limb 4's engine-output gate. Every number in all eight data blocks - headline,
    trend, risks, mitigations, activities, distribution, delta, audit - bit-identical."""
    assert _gate(GOLDEN, fresh_run) == 0, (
        "the period engine's output moved against the committed golden. Under GOLDEN01 a moved "
        "number is a bug until a methodology change says otherwise; do not re-cut the golden to "
        "make this pass.")


def test_the_run_compared_against_was_genuinely_fresh(golden: dict, fresh_run: Path) -> None:
    """Without this, the test above could be comparing the golden with a copy of itself and
    would pass for the wrong reason. These two fields cannot survive a real re-run: one is a
    fresh uuid4, the other a wall-clock stamp."""
    candidate = json.loads(fresh_run.read_bytes().decode("utf-8"))
    assert candidate["meta"]["engine_run_hash"] != golden["meta"]["engine_run_hash"]
    assert candidate["meta"]["engine_run_date"] != golden["meta"]["engine_run_date"]


# --- red-first: the gate is only evidence if it can fail --------------------------------------

@pytest.mark.parametrize(
    "block, mutate",
    [
        ("headline", lambda d: d["headline"].__setitem__("p80_finish", "2099-01-01")),
        ("risks", lambda d: d["risks"][0].__setitem__("days_at_risk_p80",
                                                      d["risks"][0]["days_at_risk_p80"] + 0.1)),
        ("distribution", lambda d: d["distribution"].__setitem__("__probe__", 1)),
    ],
)
def test_the_gate_reds_when_a_number_moves(
    tmp_path: Path, fresh_run: Path, block: str, mutate
) -> None:
    """A pass is only evidence if the check could have failed. Three blocks, because a gate that
    watches `headline` and nothing else would pass while every risk number drifted."""
    doc = json.loads(fresh_run.read_bytes().decode("utf-8"))
    mutate(doc)
    perturbed = tmp_path / f"perturbed_{block}.json"
    perturbed.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    assert _gate(GOLDEN, perturbed) == 1, (
        f"the gate passed a document whose {block} block was altered - it is not gating that "
        f"block, and a real drift there would land silently")


def test_the_gate_does_not_red_on_the_provenance_fields_alone(
    tmp_path: Path, fresh_run: Path
) -> None:
    """The other half of the boundary. These fields legitimately move between machines and
    commits; if they redded the gate, nobody could run it on a second machine and the gate would
    be turned off rather than fixed."""
    doc = json.loads(fresh_run.read_bytes().decode("utf-8"))
    doc["meta"]["engine_run_hash"] = "00000000-0000-4000-8000-000000000000"
    doc["meta"]["engine_run_date"] = "2099-12-31T23:59:59Z"
    doc["meta"]["engine_sha"] = "0" * 40
    doc["meta"]["engine_tree_dirty"] = True
    relabelled = tmp_path / "relabelled.json"
    relabelled.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    assert _gate(GOLDEN, relabelled) == 0, (
        "the gate redded on provenance identity alone, which is masked by design")
