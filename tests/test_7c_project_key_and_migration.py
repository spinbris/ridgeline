"""Stage 7 part C: B-2 (the project key) and B-4 (the migration policy in the failure message).

B-3's thresholds are in `test_7c_period_freshness.py`, which executes them in node.

The app-side assertions here are over source text, and say so. The dashboard has no test harness
until D-2; what these can prove is that the loader is project-scoped and that the corroboration
check exists and is written the way the ruling requires. The behavioural evidence - a real
mismatch refused, a real `?project=` selecting between two projects, an unknown project reported -
is in the running record, from a live DOM read.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

import pytest

from src.register_contract import CONTRACT_VERSION, REQUIRED_NAMED_RANGES, check_contract
from tests.input_skips import skip_missing

REPO = Path(__file__).resolve().parents[1]
LOADER = REPO / "dashboard" / "lib" / "loadPeriod.ts"
COPY_DATA = REPO / "dashboard" / "scripts" / "copy-data.js"
WIND_01 = REPO / "status_periods" / "wind_period_01.xlsx"

_VALID_GRID = (
    [[f"CG{i:02d}", 1.0] for i in range(1, 14)]
    + [["Series", 1.0], ["Parallel", 1.0], ["Hybrid", 1.0]]
)


# --- B-4: the failure message carries the path forward ---------------------------------------

class TestTheMigrationPolicyReachesAHuman:
    """§5.4 ruled M1 - the specialist re-scaffolds and the client re-enters - and ruled the
    message fix IN, because under M1 that message is the policy's ONLY delivery mechanism to a
    human. A policy recorded in a brief the client never reads is not one they can follow."""

    def test_a_version_mismatch_names_the_path_forward(self):
        ok, message = check_contract(list(REQUIRED_NAMED_RANGES), _VALID_GRID, "1.2")
        assert ok is False
        assert "re-scaffold" in message, "the message does not say what to do next"
        assert "no automatic migration" in message.lower(), (
            "the message does not say that no migration exists, so a client may wait for one")

    def test_it_still_names_the_mismatch_itself(self):
        """The policy is appended to the diagnosis, not substituted for it. A specialist needs
        the two version numbers; a client needs the remedy. Both readers use this one string."""
        _, message = check_contract(list(REQUIRED_NAMED_RANGES), _VALID_GRID, "1.2")
        assert "1.2" in message and CONTRACT_VERSION in message

    def test_a_NON_version_failure_does_not_get_the_policy(self):
        """The red-first half. A register missing a named range has a different remedy - fix the
        range - and pasting a re-scaffold instruction onto it would send someone to rebuild their
        workbook when they need to add one name."""
        ok, message = check_contract([], _VALID_GRID, CONTRACT_VERSION)
        assert ok is False, "the control is gone: this call no longer fails"
        assert "missing named ranges" in message
        assert "re-scaffold" not in message, (
            "the migration policy is appended to a failure it does not apply to")

    def test_the_message_warns_against_editing_the_version_by_hand(self):
        """The obvious wrong move, and the one a stuck user will try. A hand-edited version
        produces a register that LOADS and is then read against the wrong shape - which is worse
        than the hard fail it replaced, because it is silent."""
        _, message = check_contract(list(REQUIRED_NAMED_RANGES), _VALID_GRID, "1.2")
        assert "by hand" in message


# --- B-2: the project key, engine side --------------------------------------------------------

@pytest.mark.integration
class TestTheProjectKeyOnTheEngineSide:
    @pytest.fixture(scope="class")
    def run_dir(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        from src.am.run_period import run_period

        if not WIND_01.is_file():
            skip_missing(WIND_01, detail="run scripts/build_wind_am_periods.py")
        out = tmp_path_factory.mktemp("keyed")
        run_period(
            workbook_path=WIND_01, project="synthetic_wind", output_dir=out,
            main_iterations=500, days_at_risk_iterations=200, counterfactual_iterations=200,
            seed=42, criticality_measurement_mode="both",
            project_start=_dt.date(2024, 1, 1), allow_dirty=True,
        )
        return out

    def test_the_period_is_written_under_its_project(self, run_dir: Path):
        """D-7 rules one install serves many projects, and a field alone cannot deliver it:
        `data/period_20260930.json` is ONE filename, so two projects could not both close a
        period on 30 September."""
        assert (run_dir / "synthetic_wind").is_dir()
        assert list((run_dir / "synthetic_wind").glob("period_*.json"))
        assert list(run_dir.glob("period_*.json")) == [], (
            "a period was also written flat, so the layout is ambiguous")

    def test_the_document_declares_its_own_project(self, run_dir: Path):
        doc = json.loads(
            next((run_dir / "synthetic_wind").glob("period_*.json")).read_bytes().decode("utf-8"))
        assert doc["meta"]["project_key"] == "synthetic_wind"

    def test_the_trend_cannot_see_a_period_outside_this_project(
        self, run_dir: Path, tmp_path: Path
    ):
        """Exercised through the CALLER, which is where the defect actually was.

        Two earlier attempts at this test were wrong in instructive ways. The first asserted the
        source string that scopes the output directory - the shape this repository keeps
        criticising. The second called `_build_trend` directly on a private tree, which the
        re-review pointed out **passes under the pre-part-C code too**: that function has always
        globbed only its own `data_dir`, and the defect was `run_period` handing it a SHARED
        directory. A test that cannot fail on the regression it names is not evidence.

        So this plants a period in the flat root - exactly where pre-part-C periods sit, and
        exactly what the old code would have swept up - and runs the engine again for the same
        project. The planted figure must not appear in the trend.
        """
        from src.am.run_period import run_period

        planted_p80 = "2099-12-31"
        (run_dir / "period_20260131.json").write_text(
            json.dumps({"meta": {"period_end_date": "2026-01-31"},
                        "headline": {"p80_finish": planted_p80}}),
            encoding="utf-8")

        wind_02 = REPO / "status_periods" / "wind_period_02.xlsx"
        if not wind_02.is_file():
            skip_missing(wind_02, detail="run scripts/build_wind_am_periods.py")
        written = run_period(
            workbook_path=wind_02, project="synthetic_wind", output_dir=run_dir,
            main_iterations=500, days_at_risk_iterations=200, counterfactual_iterations=200,
            seed=42, criticality_measurement_mode="both",
            project_start=_dt.date(2024, 1, 1), allow_dirty=True,
        )
        doc = json.loads(written.read_bytes().decode("utf-8"))
        seen = [pt.get("p80_finish") for pt in doc["trend"]["periods"]]

        assert planted_p80 not in seen, (
            "a period sitting outside this project's directory reached its trend line - the "
            "flat-layout contamination the project key exists to close")
        assert len(seen) >= 2, (
            "the trend lost this project's own prior period, so the assertion above passed for "
            "the wrong reason")


# --- B-2: the project key, app side (source-level; see the module docstring) -------------------

class TestTheProjectKeyOnTheAppSide:
    def test_the_loader_is_project_scoped(self):
        loader = LOADER.read_text(encoding="utf-8")
        for signature in (
            "export async function loadPeriod(project: string, filename: string)",
            "export async function loadPeriodIndex(project: string)",
            "export async function loadProjectIndex()",
        ):
            assert signature in loader, f"missing: {signature}"

    def test_the_path_is_authoritative_and_the_field_corroborates(self):
        """The consequence of §5.2 ruling the key OPTIONAL, and the thing that had to be written
        this way FROM THE OUTSET: a loader built to trust the field and tightened later is the
        drift the options note exists to prevent, and by the time a mismatch mattered some period
        would already have been read as the wrong project's.

        Asserted as behaviour-in-source: the check must return early on an absent key (so an
        unkeyed period in a project directory is valid) and throw on a present-but-different one.
        """
        loader = LOADER.read_text(encoding="utf-8")
        body = loader[loader.index("export function assertProjectKeyAgrees"):]
        body = body[: body.index("\n}\n")]
        assert "if (declared === undefined) return;" in body, (
            "the corroboration check does not tolerate an absent key, so it treats the OPTIONAL "
            "field as required and would reject valid 1.4 documents")
        assert "throw new Error" in body, (
            "a mismatch between the path and the document's own key is not refused")

    def test_the_copier_keys_on_the_directory_not_the_document(self):
        """The path is authoritative, so the build step must not need to open the documents to
        know which project they belong to - it would then disagree with the loader whenever a
        key was absent."""
        copier = COPY_DATA.read_text(encoding="utf-8")
        # Asserted as BEHAVIOUR, not by the field's name. The first version checked that
        # "project_key" did not appear in the file and hit the docstring explaining why the
        # directory decides - the third time this session that a guard matched its own
        # explanation (see also the 3d weasyprint guard and part B's joint-sampling test).
        # Reading no document at all is the actual property, and JSON.parse is how it would.
        assert "JSON.parse" not in copier, (
            "copy-data.js parses period documents; the directory is what decides which project "
            "a period belongs to, and a build step that reads the key would disagree with the "
            "loader on every document that omits it")
        assert re.search(r"withFileTypes:\s*true", copier), (
            "copy-data.js does not walk directories, so it cannot see per-project layout")

    def test_a_flat_layout_is_named_and_not_published(self):
        """Part C accepted the pre-part-C flat layout as `_unkeyed` so no checkout broke the
        morning it landed. DASHGATE-01 retired that: nothing is published unless it is named,
        and a flat period has no project to name, so it is NOT copied - but it is still
        recognised and REPORTED as the flat layout, never silently dropped or absorbed into a
        project name. The behaviour is run in `tests/test_dashgate01_copy_data.py`."""
        copier = COPY_DATA.read_text(encoding="utf-8")
        assert 'const UNKEYED = "_unkeyed"' in copier
        assert "pre-part-C flat layout" in copier, (
            "the flat case is not distinguished in the build output")
        assert "NOT PUBLISHED" in copier, "an unnamed project is left out without saying so"
