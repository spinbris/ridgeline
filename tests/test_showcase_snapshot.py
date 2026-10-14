"""The committed showcase cannot drift from the engine that produced it.

SHOWCASE-02 S-1, S-2, S-5 and S-7, under D-2(a) and D-3 (signed 19/09/2026). The Director
ruled the production-scale run is **carried forward** rather than re-cut, and that its
summaries are committed so a fresh clone can read the product's demonstration without
running anything. Both rulings put their weight here: a carried-forward run is honest only
while the engine has not moved underneath it, and nothing else in the repository would
notice when it does.

PROCDIET-01 (brief §1 item 4, Director 12/10/2026): the snapshot is no longer held to the
engine commit it names. `engine_sha` and the branch are provenance; a re-cut is owed only when a
number moves, and a moved number reds the goldens and the audit lane's headline diff first.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = REPO_ROOT / "docs" / "showcase" / "run"
META = SNAPSHOT / "wind_run_meta.json"

#: The showcase's own floor, quoted from the meta it writes: a low-n run is NOT a subset of
#: a high-n run. S-5 makes it a gate rather than a note. `run_wind_showcase` defaults to
#: 50,000 and labels that output DRAFT, so this is the check that catches a forgotten
#: WIND_ITERATIONS.
PRODUCTION_SCALE_FLOOR = 100_000

#: Every file D-2(a) commits, and the quoted values SHOWCASESYNC-01 added. The figures and the
#: summary's figures are held to the same run by tests/test_showcase_sync.py.
PROMISED = (
    "wind_quoted_values.json",
    "wind_run_meta.json",
    "wind_integrated_headline.md",
    "wind_cost_qra.md",
    "wind_cost_tornado.csv",
    "wind_sra_schedule.md",
    "wind_stage3_cpm.md",
)

_REGEN = ("Regenerate on a clean tree with\n"
          "    WIND_ITERATIONS=100000 python scripts/run_wind_showcase.py --publish\n"
          "which writes the whole set where it ships (SHOWCASESYNC-01).")


def _meta() -> dict:
    return json.loads(META.read_text(encoding="utf-8"))


def test_the_snapshot_is_present_and_complete():
    """A snapshot missing a file would let every assertion below pass on less."""
    missing = [n for n in PROMISED if not (SNAPSHOT / n).is_file()]
    assert not missing, f"the committed showcase is missing {missing}.\n{_REGEN}"


def test_the_snapshot_came_from_a_production_scale_run():
    """S-5: no number the product shows comes from a draft-scale run."""
    n = _meta()["iterations"]
    assert n >= PRODUCTION_SCALE_FLOOR, (
        f"the committed showcase ran {n:,} iterations, below the "
        f"{PRODUCTION_SCALE_FLOOR:,} floor - run_wind_showcase defaults to 50,000 and "
        f"labels that output DRAFT.\n{_REGEN}")


def test_the_snapshot_attests_a_clean_tree():
    """WIND-04's own words: a SHA stamped over a dirty tree is a false attestation."""
    assert _meta()["engine_tree_dirty"] is False, (
        "the committed showcase was produced over a dirty working tree, so its engine_sha "
        f"does not identify the code that made it.\n{_REGEN}")


def test_the_snapshot_carries_the_disclosure_s7_requires():
    """S-7: the caveat reaches the artefact, not merely the brief.

    A caveat only a brief states is one nothing shows a reader - the position §2.2's trap
    was in. Asserted on the committed copy, so a re-render that drops it fails here rather
    than being noticed by someone reading the deliverable.
    """
    text = (SNAPSHOT / "wind_stage3_cpm.md").read_text(encoding="utf-8")
    for phrase, why in (
        ("zero total float", "why the replay is additive on this project (CPMINERT-01)"),
        ("arithmetically identical", "what the CPM contributes, stated plainly"),
        ("no milestones", "the merge-bias caveat (XERREAL-01)"),
    ):
        assert phrase in text, (
            f"the committed Stage 3 artefact no longer says {phrase!r} - {why}. If the "
            f"wording moved, move this assertion with it; do not drop it")


def test_the_snapshot_is_lf_like_everything_else_committed():
    """The repository declares `* text=auto eol=lf` and the close-out gate greps w/crlf.

    run_wind_showcase wrote CRLF on Windows until this brief fixed it - two write_text
    calls and a csv.writer - so this is the guard on that fix rather than a style note.
    """
    crlf = [p.name for p in sorted(SNAPSHOT.iterdir()) if b"\r\n" in p.read_bytes()]
    assert not crlf, (
        f"committed showcase files carry CRLF: {crlf}. run_wind_showcase must write "
        f"newline=\"\\n\" (and lineterminator=\"\\n\" for the csv); see WRITETEXTEOL-01 "
        f"for the wider class")
