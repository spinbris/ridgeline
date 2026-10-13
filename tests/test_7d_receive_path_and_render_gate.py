"""Stage 7 part D: B-1 (the receive path), D-2 (the app-render gate), and SPEC §8's Node pin.

D-2's assertions run in **vitest under jsdom**, not here - the gate is "for that golden JSON,
each route renders the values a snapshot test asserts", and only a DOM that runs the client can
answer that. What this module does for D-2 is make it a gate the repository actually RUNS: the
lane invokes the vitest suite, so a broken render fails the Python lane like anything else. A
test suite nobody runs is not a gate.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.am.json_writer import SCHEMA_VERSION
from src.am.publish_period import (
    PublishError,
    REQUIRED_BLOCKS,
    resolve_plan,
    validate_period_json,
)

REPO = Path(__file__).resolve().parents[1]
DASHBOARD = REPO / "dashboard"
GOLDEN = REPO / "tests" / "golden" / "period_json" / "wind_synth" / "period_20260228.json"

_NODE = shutil.which("node")
_NPM = shutil.which("npm") or shutil.which("npm.cmd")
#: True on a CI runner. GitHub Actions sets it, and so does any runner worth the name.
_IN_CI = os.environ.get("CI", "").lower() in ("1", "true", "yes")


def _render_toolchain_missing() -> str | None:
    """Why the render gate cannot run here, or None if it can.

    CINODE-01: the gate skips wherever Node is absent, and CI set up Python only - so it
    skipped on the ONE machine whose results are meant to be machine-independent, and a green CI
    run had never rendered the app. Node is now installed in `ci.yml`.

    The skip stays, because a developer who has not run `npm install` should not be redded by a
    JS toolchain they were not using. **But it is no longer available to CI.** In CI a missing
    toolchain is a FAILURE naming itself, not a skip: the whole point of that machine is that its
    green means the same thing every time, and a gate that quietly stops running there is the
    false green this repository keeps finding. Same reasoning as the golden-tier read-back in
    `ci.yml` - a gate that skipped is not a gate that passed.
    """
    if _NODE is None:
        return "node is not on PATH"
    if _NPM is None:
        return "npm is not on PATH"
    if not (DASHBOARD / "node_modules" / "vitest").is_dir():
        return "dashboard/node_modules is not installed (run `npm ci` in dashboard/)"
    return None


def _golden() -> dict:
    return json.loads(GOLDEN.read_bytes().decode("utf-8"))


# --- B-1: the receive path refuses rather than guessing ---------------------------------------

class TestThePublishCommandRefusesBeforeItActs:
    """Every check runs before anything is copied, because a period that reaches the client is
    already published. Same reasoning as the register's Validate button: catch it here."""

    def test_a_period_at_the_wrong_contract_is_refused(self, tmp_path: Path):
        """The failure this most exists to prevent. Part B made the app REFUSE a version it was
        not built against, so publishing a mismatched period would deploy a dashboard that
        rejects its own data - a broken client instance, from a command that reported success."""
        doc = _golden()
        doc["schema_version"] = "1.3"
        stale = tmp_path / "period_20260228.json"
        stale.write_text(json.dumps(doc), encoding="utf-8")

        with pytest.raises(PublishError, match="deployed in step"):
            validate_period_json(stale)

    @pytest.mark.parametrize("block", REQUIRED_BLOCKS)
    def test_a_document_missing_any_block_is_refused(self, tmp_path: Path, block: str):
        """Each block named individually rather than one representative: a check that looked at
        `meta` alone would wave through a document with no `risks` at all."""
        doc = _golden()
        doc.pop(block)
        broken = tmp_path / "period_20260228.json"
        broken.write_text(json.dumps(doc), encoding="utf-8")

        with pytest.raises(PublishError, match=block):
            validate_period_json(broken)

    def test_a_project_that_disagrees_with_the_document_is_refused(self, tmp_path: Path):
        """`--project` and `meta.project_key` naming different projects is not a preference to
        resolve - filing a period under the wrong project is how one project's numbers end up
        under another project's name."""
        source = tmp_path / "period_20260228.json"
        source.write_bytes(GOLDEN.read_bytes())

        with pytest.raises(PublishError, match="does not match"):
            resolve_plan(source, "some_other_project", data_root=tmp_path / "data")

    def test_a_project_name_that_would_escape_its_directory_is_refused(self, tmp_path: Path):
        doc = _golden()
        doc["meta"]["project_key"] = "../elsewhere"
        source = tmp_path / "period_20260228.json"
        source.write_text(json.dumps(doc), encoding="utf-8")

        with pytest.raises(PublishError, match="not usable as a directory name"):
            resolve_plan(source, None, data_root=tmp_path / "data")

    def test_nothing_is_written_when_a_check_fails(self, tmp_path: Path):
        """The property behind all of the above: refusing after writing is not refusing."""
        doc = _golden()
        doc["schema_version"] = "0.9"
        source = tmp_path / "period_20260228.json"
        source.write_text(json.dumps(doc), encoding="utf-8")
        data_root = tmp_path / "data"

        with pytest.raises(PublishError):
            resolve_plan(source, None, data_root=data_root)
        assert not data_root.exists(), "the destination tree was created despite the refusal"


class TestThePublishCommandFilesCorrectly:
    def test_it_files_under_the_documents_own_project(self, tmp_path: Path):
        source = tmp_path / "incoming.json"
        source.write_bytes(GOLDEN.read_bytes())
        plan = resolve_plan(source, None, data_root=tmp_path / "data")

        assert plan.project == _golden()["meta"]["project_key"]
        assert plan.destination.parent.name == plan.project
        assert plan.destination.name == "period_20260228.json"

    def test_the_filename_comes_from_the_period_end_not_the_source_name(self, tmp_path: Path):
        """A period renamed on the way in must still be filed by what it IS. Trusting the source
        filename would let `final_v2.json` land as `final_v2.json`, invisible to the manifest."""
        source = tmp_path / "whatever-the-client-called-it.json"
        source.write_bytes(GOLDEN.read_bytes())
        plan = resolve_plan(source, None, data_root=tmp_path / "data")
        assert plan.destination.name == "period_20260228.json"

    def test_republishing_a_period_already_in_place_is_not_an_error(self, tmp_path: Path):
        """Found by running the command for real on the first try: `shutil.copyfile` raises
        `SameFileError`, and re-publishing after an app change is a normal thing to do."""
        from src.am.publish_period import place

        data_root = tmp_path / "data"
        dest_dir = data_root / _golden()["meta"]["project_key"]
        dest_dir.mkdir(parents=True)
        in_place = dest_dir / "period_20260228.json"
        in_place.write_bytes(GOLDEN.read_bytes())

        plan = resolve_plan(in_place, None, data_root=data_root)
        assert plan.already_in_place is True
        place(plan)  # must not raise
        assert in_place.read_bytes() == GOLDEN.read_bytes()


def test_the_publisher_reads_the_contract_rather_than_retyping_it():
    """A second copy of the version would let the publisher accept exactly what the app refuses."""
    source = (REPO / "src" / "am" / "publish_period.py").read_text(encoding="utf-8")
    assert "from src.am.json_writer import SCHEMA_VERSION" in source
    assert f'"{SCHEMA_VERSION}"' not in source, "the contract version is hardcoded in the publisher"


def test_the_deploy_step_is_opt_in():
    """Not caution - evidence. Everything up to the build is verified on this machine; the
    `vercel` calls are not, so the command must not perform them unasked or claim it did."""
    source = (REPO / "src" / "am" / "publish_period.py").read_text(encoding="utf-8")
    assert '"--deploy", action="store_true"' in source
    assert "Built, NOT deployed" in source


# --- SPEC §8: the Node pin ----------------------------------------------------------------

def test_the_dashboard_declares_a_node_floor():
    """SPEC §8 assigned this to stage 7 and the brief did not mention it; raised at signature and
    ruled into part D. An unpinned floor lets a build succeed on one machine and fail on another
    - the same class `requires-python` closed in 3d."""
    pkg = json.loads((DASHBOARD / "package.json").read_text(encoding="utf-8"))
    engines = pkg.get("engines", {})
    assert "node" in engines, "dashboard/package.json declares no engines.node"
    assert engines["node"].startswith(">="), (
        f"engines.node is {engines['node']!r}; a floor is wanted, not a range that could exclude "
        f"newer runtimes")


def test_the_node_floor_is_at_or_above_what_the_framework_requires():
    """The floor must not be LOWER than Next's own, or the pin promises something it cannot keep."""
    next_pkg = DASHBOARD / "node_modules" / "next" / "package.json"
    if not next_pkg.is_file():
        pytest.skip("dashboard/node_modules is not installed")
    declared = json.loads((DASHBOARD / "package.json").read_text(encoding="utf-8"))["engines"]["node"]
    ours = int(declared.lstrip(">=").split(".")[0])

    # READ from the framework, not retyped. The first version opened this file only to decide
    # whether to skip and then compared against a literal 20 - presence of the file mistaken for
    # its content, which is a defect class this repository has hit before. It could not have
    # noticed Next raising its own floor above the pin.
    framework = json.loads(next_pkg.read_text(encoding="utf-8"))["engines"]["node"]
    floors = [int(m) for m in re.findall(r">=\s*(\d+)|\^(\d+)", framework) for m in [m[0] or m[1]] if m]
    assert floors, f"could not read a floor out of Next's engines.node {framework!r}"
    assert ours >= min(floors), (
        f"engines.node {declared!r} is below Next's own {framework!r}; the pin would admit a "
        f"runtime the framework refuses")


def test_ci_pins_a_node_version_that_satisfies_the_declared_floor():
    """CINODE-01's second half: the runner and the product must not drift apart.

    `nightly.yml` pins a Node major for the runner (the render gate runs weekly, PROCDIET-01 A2); `dashboard/package.json` declares the floor the
    product requires. Nothing connects them but this test. Without it the runner could sit below
    the declared floor - CI green on a runtime the product says it does not support - or the
    floor could be raised while CI kept installing the old major, which is worse because the
    green would still look earned.

    The workflow comment claims this control exists. It does now; asserting a control in a
    comment and not installing it is a defect this repository has already hit twice.
    """
    workflow = (REPO / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")
    pinned = re.search(r'node-version:\s*"?(\d+)', workflow)
    assert pinned, "nightly.yml pins no node-version, so the render gate's runtime is whatever is there"

    declared = json.loads((DASHBOARD / "package.json").read_text(encoding="utf-8"))["engines"]["node"]
    floor = int(declared.lstrip(">=").split(".")[0])
    assert int(pinned.group(1)) >= floor, (
        f"nightly.yml pins Node {pinned.group(1)} but dashboard/package.json declares {declared!r}. "
        f"CI would run the render gate on a runtime the product does not support.")


def test_ci_installs_the_dashboard_closure_before_the_lane():
    """A pinned Node with no `npm ci` leaves the gate skipping for the other reason.

    Order matters and is asserted: the install has to precede the stage lane, or the lane runs
    before node_modules exists and the gate fails on the CI branch of the toolchain check -
    correctly, but for a reason nobody would enjoy debugging.
    """
    workflow = (REPO / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")
    assert "npm ci" in workflow, "nightly.yml never installs the dashboard's dependencies"
    assert workflow.index("npm ci") < workflow.index("Full suite"), (
        "the dashboard install comes AFTER the full suite, so the render gate runs first and "
        "finds no node_modules")


# --- D-2: the render gate runs, in this lane ---------------------------------------------------

@pytest.mark.integration
def test_the_app_render_gate_passes():
    """SPEC §3 limb 4's second gate, run from the Python lane so it cannot quietly stop running.

    The assertions live in `dashboard/__tests__/render-gate.test.tsx` and execute in jsdom -
    part A established that a static-export assertion cannot see the app's content at all,
    because every page sits behind a provider that renders `null` until data loads client-side.

    Invoked here rather than left to a separate `npm test` nobody remembers: this repository's
    lane is the gate, and a suite outside it is a suite that rots.
    """
    missing = _render_toolchain_missing()
    if missing is not None:
        if _IN_CI:
            pytest.fail(
                f"the app-render gate cannot run and this is CI: {missing}. A skip here is a "
                f"false green - the run would report success having never rendered the app, "
                f"which is CINODE-01. Install Node and run `npm ci` in dashboard/, or delete "
                f"this gate deliberately rather than letting it lapse.")
        # A FIXED reason, not an f-string. P-B7 forbids building a skip reason from a
        # runtime value, because that is how an absolute path carrying a username reaches
        # a CI log - and the static guard cannot know that these particular strings are
        # literals. The detail is not lost: it is in the CI branch above, which is a
        # failure rather than a skip and is the place a reader actually needs it.
        pytest.skip(
            "the JS toolchain is not installed; the render gate runs where it is "
            "(run `npm ci` in dashboard/). In CI this is a failure, not a skip.")

    result = subprocess.run(
        [_NPM, "run", "test", "--silent"],
        cwd=DASHBOARD, capture_output=True, text=True,
        env={**os.environ, "CI": "1"},
    )
    assert result.returncode == 0, (
        "the app-render gate failed - the app no longer renders the committed golden's values:\n"
        f"{result.stdout[-4000:]}\n{result.stderr[-2000:]}")
