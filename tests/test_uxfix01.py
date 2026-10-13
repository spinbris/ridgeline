"""UXFIX-01: three things the 5b run found, each at the surface a first-time user meets.

Ledger row UXFIX-01, dispositioned by the Director on 12/09/2026 from row 5B-RUN. None of the
three moves a number; all three change what a user is told.

* **F5B-14** - the client deliverable is a rendered notebook, so anything the engines wrote to
  stderr landed in it. On the 5b run the HTML opened with the notebook's own developer
  description and twelve ``auto_mapper`` warnings, before the project's title.
* **F5B-15** - ``--phase`` had no help text, so a first-time user guessed at both the value and
  whether it was required.
* **F5B-16** - publishing a period for the first time into a fresh clone printed "Re-published",
  which reads as though something was overwritten.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def _without_root_handlers() -> Iterator[None]:
    """The notebook's condition: no handler configured, so logging falls back to stderr.

    pytest installs its own root handlers, which would make any stderr assertion pass whether or
    not the code under test does anything - the assertion could not go red. The handlers are put
    back in the finally.
    """
    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers[:] = []
    try:
        yield
    finally:
        root.handlers[:] = saved


def test_engine_logs_are_kept_out_of_the_report_and_written_beside_the_provenance(
    capsys, tmp_path
) -> None:
    """The records are evidence, so they are held and filed - not silenced, and not in the HTML."""
    from src.final.deliverable import captured_engine_log, write_engine_log

    noisy = logging.getLogger("src.sra.cpm.auto_mapper")
    line = "auto_mapper: rule KH-029 expanded to 1 activities (< 5 threshold)"

    # Baseline: with nothing configured, the record reaches stderr - the behaviour that put
    # twelve of these into the client artefact. If this stops being true the limb below is inert.
    with _without_root_handlers():
        noisy.warning(line)
    assert "auto_mapper" in capsys.readouterr().err, (
        "the baseline no longer holds, so the assertion under test proves nothing"
    )

    with _without_root_handlers():
        with captured_engine_log() as records:
            noisy.warning(line)
    captured = capsys.readouterr()

    assert [r.getMessage() for r in records] == [line], (
        "the engine's log records must be kept: they are the auto-mapper's audit trail"
    )
    assert "auto_mapper" not in captured.err, (
        "the record reached stderr, which is what nbconvert renders into the client artefact"
    )
    assert "auto_mapper" not in captured.out

    filed = tmp_path / "runs" / "2026-09-12_p" / "engine_log.txt"
    write_engine_log(filed, records)
    assert line in filed.read_text(encoding="utf-8")
    assert filed.read_bytes().count(b"\r") == 0, "this repository declares no CRLF"


def test_the_engine_log_is_written_even_when_the_run_raises(tmp_path) -> None:
    """The run that raised is the run whose log matters most (numerics panel, 12/09/2026)."""
    from src.final.deliverable import captured_engine_log, write_engine_log

    target = tmp_path / "engine_log.txt"
    with contextlib.suppress(RuntimeError), captured_engine_log() as records:
        try:
            logging.getLogger("src.sra.cpm.auto_mapper").warning("expanded to 1 activities")
            raise RuntimeError("the Stage 3 headline is missing")
        finally:
            write_engine_log(target, records)

    assert "expanded to 1 activities" in target.read_text(encoding="utf-8")


def test_the_notebook_preamble_does_not_render_into_the_deliverable() -> None:
    """The first cell describes the notebook to a developer; the report opens on the project."""
    notebook = json.loads((REPO_ROOT / "final_runner.ipynb").read_text(encoding="utf-8"))
    first = notebook["cells"][0]
    assert first["cell_type"] == "markdown"
    tags = first.get("metadata", {}).get("tags", [])
    assert "dev-note" in tags, (
        "the developer preamble is not tagged, so nbconvert renders it above the project title"
    )
    runner = (REPO_ROOT / "RUN_FINAL.bat").read_text(encoding="utf-8", errors="ignore")
    # The exact flags, not a substring that a comment mentioning dev-note would also satisfy.
    assert "--TagRemovePreprocessor.enabled=True" in runner, (
        "the preprocessor ships disabled, so without this flag the tag changes nothing"
    )
    assert "--TagRemovePreprocessor.remove_cell_tags=dev-note" in runner, (
        "the runner does not remove the tag the notebook carries"
    )


def test_the_phase_flag_says_what_it_wants() -> None:
    """A flag with no help is a flag a first-time user guesses at (F5B-15)."""
    import scripts.build_status_workbook as bsw

    parser = bsw.build_parser()
    phase = next(a for a in parser._actions if "--phase" in getattr(a, "option_strings", []))
    assert phase.help, "--phase has no help text"
    assert not phase.required, "--phase is optional, and the help should not imply otherwise"


def test_a_first_publish_does_not_claim_to_have_re_published() -> None:
    """Nothing is overwritten when the file is already where it belongs (F5B-16)."""
    from src.am.publish_period import PublishPlan, describe_outcome

    in_place = PublishPlan(
        source=Path("data/p/period_20260831.json"), project="p",
        destination=Path("data/p/period_20260831.json"), period_end="2026-08-31",
        replaces_existing=False, already_in_place=True,
    )
    headline, note = describe_outcome(in_place)
    assert "Re-published" not in headline, (
        "a first publish of a file already in place did not replace anything"
    )
    assert headline.startswith("Published")
    assert note, "the user should be told nothing was copied, so the message is not mysterious"

    replacing = PublishPlan(
        source=Path("elsewhere/period_20260831.json"), project="p",
        destination=Path("data/p/period_20260831.json"), period_end="2026-08-31",
        replaces_existing=True, already_in_place=False,
    )
    assert describe_outcome(replacing)[0].startswith("Replaced"), (
        "an overwrite must still say so: that is the case --replace exists to gate"
    )
