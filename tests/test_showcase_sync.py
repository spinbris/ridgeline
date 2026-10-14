"""SHOWCASESYNC-01: everything the showcase quotes comes from one recorded run.

On 14/10/2026 the committed number files were the current run's, the five charts were drawn from
an earlier run (the cost S-curve marked P80 at $5.68M against $5.42M in the numbers beside it), and
the summary qmd typed the older figures by hand. Nothing noticed: the snapshot test guarded the
number files only, the copy into docs/showcase/ was by hand, and the qmd's figures were literals.

These tests hold the whole set to one run. The record (``wind_run_meta.json``) names a run id;
every chart carries that id in a PNG text chunk; the quoted values carry it; and every figure in
the qmd is a span bound to a named value and must show that value, formatted. Re-cut the set with

    WIND_ITERATIONS=100000 python scripts/run_wind_showcase.py --publish

on a clean tree. Nothing here is fixed by hand.
"""
from __future__ import annotations

import functools
import importlib.util
import json
import re
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
SHOWCASE = REPO / "docs" / "showcase"
META = SHOWCASE / "run" / "wind_run_meta.json"
VALUES = SHOWCASE / "run" / "wind_quoted_values.json"
FIGS = SHOWCASE / "figs"
SCRIPT = REPO / "scripts" / "run_wind_showcase.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


quotes = _load("showcase_quotes", REPO / "scripts" / "showcase_quotes.py")


@functools.lru_cache(maxsize=None)
def _rws():
    """The showcase script, loaded on first use. Importing it reads the committed showcase record
    (its seed), so a module-level load fails collection in a clean clone without docs/
    (tests/test_goldcoll01_collection_guard.py, the increment lane of 14/10/2026)."""
    return _load("run_wind_showcase", SCRIPT)

#: The charts the script draws, by its own names: a chart it stops drawing, or a stray one left
#: in the folder, is a set that no longer comes from one run.
CHARTS = ("wind_activity_criticality.png", "wind_cost_density.png", "wind_cost_s_curve.png",
          "wind_cost_tornado.png", "wind_schedule_finish_s_curve.png")

REGEN = ("Re-cut the whole set on a clean tree with\n"
         "    WIND_ITERATIONS=100000 python scripts/run_wind_showcase.py --publish")


def _json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _qmd() -> str:
    return _rws().SUMMARY_QMD.read_text(encoding="utf-8")


# --- the committed set ------------------------------------------------------------------------

def test_the_record_names_its_run():
    meta = _json(META)
    assert re.fullmatch(r"[0-9a-f-]{36}", meta.get("run_id", "")), (
        f"wind_run_meta.json names no run id.\n{REGEN}")
    assert meta.get("run_timestamp"), f"wind_run_meta.json carries no run timestamp.\n{REGEN}"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta.get("run_date", "")), (
        f"wind_run_meta.json carries no run date.\n{REGEN}")


def test_every_chart_is_drawn_by_the_recorded_run():
    run_id = _json(META)["run_id"]
    present = sorted(p.name for p in FIGS.glob("*.png"))
    assert present == sorted(CHARTS), (
        f"docs/showcase/figs holds {present}, the script draws {sorted(CHARTS)}.\n{REGEN}")
    wrong = {}
    for name in CHARTS:
        with Image.open(FIGS / name) as im:
            got = im.text.get(_rws().RUN_ID_KEY)
        if got != run_id:
            wrong[name] = got
    assert not wrong, (f"these charts were not drawn by the run wind_run_meta.json records "
                       f"({run_id}): {wrong}.\n{REGEN}")


def test_the_quoted_values_are_the_recorded_run():
    meta, values = _json(META), _json(VALUES)
    assert values["run_id"] == meta["run_id"], (
        f"wind_quoted_values.json is run {values['run_id']}, the record is run "
        f"{meta['run_id']}.\n{REGEN}")
    # The headline in the values and the headline the record states are one number.
    assert values["values"]["integrated.p80"] == meta["integrated_total_p80"]


def test_every_figure_in_the_summary_is_bound_to_a_run_value():
    left = quotes.unbound(_qmd())
    assert not left, ("the summary qmd quotes figures that no run value binds - write each as "
                      '[...]{.run v="<key>" f="<format>"}:\n  ' + "\n  ".join(left))


def test_every_bound_figure_shows_the_recorded_run():
    bad = quotes.mismatches(_qmd(), _json(VALUES)["values"])
    assert not bad, "the summary qmd disagrees with the run:\n  " + "\n  ".join(bad) + f"\n{REGEN}"


def test_the_summary_is_dated_by_its_run():
    date = re.search(r"^date: (.*)$", _qmd(), re.MULTILINE).group(1).strip()
    assert date == _json(META)["run_date"], (
        f"the summary qmd is dated {date}, its run on {_json(META)['run_date']}.\n{REGEN}")


def test_the_summary_front_matter_parses():
    """Gate 3 (14/10/2026): binding the subtitle's figure put a span's double quotes inside a
    double-quoted YAML scalar, and the front matter stopped parsing - any Quarto render, or the
    blog's lift of this file, would fail. Nothing here renders the qmd, so this is the check."""
    import yaml

    front = _qmd().split("---")[1]
    meta = yaml.safe_load(front)
    assert meta["title"] and meta["date"]
    # The check can fail: the 14/10 subtitle, double-quoted, does not parse.
    broken = front.replace(
        "subtitle: '", 'subtitle: "', 1).replace("wind-farm scope'", 'wind-farm scope"', 1)
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(broken)


def test_the_summary_quotes_no_stage_2_5_value():
    """Director, 14/10/2026: everything is the current Stage 3. The values offer none other."""
    keys = {k for _, k, _ in quotes.spans(_qmd())}
    assert not [k for k in keys if "sra" in k or "2_5" in k or "stage25" in k]


# --- the checks themselves can fail (red-first, kept) ------------------------------------------

VALUES_FIXTURE = {"cost.p80": 5_420_044.99, "cost.p80_pct": 0.1084, "day_rate": 35_000.0}


def test_a_typed_figure_is_refused():
    assert quotes.unbound("| P80 | $5.68M | 11.4% |") == ["line 1: | P80 | $5.68M | 11.4% |"]
    assert quotes.unbound("a spread of 32 working days") != []
    assert quotes.unbound("<!--\n$5.68M in a comment\n-->\nplain words") == []


def test_a_stale_bound_figure_is_refused():
    stale = '[$5.68M]{.run v="cost.p80" f="M"}'
    assert quotes.mismatches(stale, VALUES_FIXTURE) == [
        "cost.p80: the qmd shows '$5.68M', the run says '$5.42M'"]
    assert quotes.mismatches('[$5.42M]{.run v="cost.p80" f="M"}', VALUES_FIXTURE) == []
    assert quotes.mismatches('[x]{.run v="nope" f="M"}', VALUES_FIXTURE) != []


def test_fill_rewrites_every_span_and_the_date():
    text = 'date: 2026-06-09\n[old]{.run v="cost.p80" f="M"} at [old]{.run v="day_rate" f="k"}/day'
    out = quotes.fill(text, VALUES_FIXTURE, "2026-10-14")
    assert out == ('date: 2026-10-14\n[$5.42M]{.run v="cost.p80" f="M"} at '
                   '[$35k]{.run v="day_rate" f="k"}/day')
    assert quotes.mismatches(out, VALUES_FIXTURE) == []


def test_a_chart_from_another_run_is_refused(tmp_path):
    """The stamp is what the chart check reads; a chart stamped by another run reads differently."""
    p = tmp_path / "c.png"
    Image.new("RGBA", (4, 4), (31, 78, 121, 255)).save(p, dpi=(150, 150))
    _rws()._stamp_png(p, "run-a")
    _rws()._stamp_png(p, "run-b")
    with Image.open(p) as im:
        assert im.text[_rws().RUN_ID_KEY] == "run-b"
        assert im.getpixel((0, 0)) == (31, 78, 121, 255)
        assert round(im.info["dpi"][0]) == 150


def test_a_chart_that_trips_a_check_is_re_encoded_losslessly():
    pb = _load("publishable_bytes", REPO / "scripts" / "release" / "publishable_bytes.py")
    import io
    im = Image.new("RGBA", (40, 30), (31, 78, 121, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG", compress_level=6)
    first = buf.getvalue()
    # A check that trips on these exact bytes, and on nothing else.
    trips = lambda name, blob: ["tripped"] if blob == first else []
    out = pb.clean_png(first, "c.png", trips)
    assert out != first
    with Image.open(io.BytesIO(out)) as again:
        assert again.tobytes() == im.tobytes()
    assert pb.clean_png(out, "c.png", trips) is out  # clear bytes are left alone
    with pytest.raises(ValueError, match="every lossless compression level"):
        pb.clean_png(first, "c.png", lambda name, blob: ["always"])


def test_publishable_bytes_refuses_without_the_term_list(monkeypatch, tmp_path):
    pb = _load("publishable_bytes", REPO / "scripts" / "release" / "publishable_bytes.py")
    monkeypatch.setenv("CLIENT_GATE_TERMS", str(tmp_path / "absent.txt"))
    with pytest.raises(FileNotFoundError, match="term list is not here"):
        pb.load_findings()


@pytest.mark.parametrize("dirty,allow,n_iter,why", [
    (True, False, 100_000, "dirty tree"),
    (False, True, 100_000, "--allow-dirty"),
    (False, False, 50_000, "below the floor"),
])
def test_publish_refuses_what_cannot_ship(monkeypatch, dirty, allow, n_iter, why):
    rws = _rws()
    monkeypatch.setattr(rws, "_resolve_tree_dirty", lambda: dirty)
    monkeypatch.setattr(rws, "_resolve_engine_sha", lambda: "0" * 40)  # no git in the fast lane
    monkeypatch.setattr(rws, "N_ITER", n_iter)
    monkeypatch.setattr(rws, "_activate_wind_binding",
                        lambda: pytest.fail(f"--publish ran the engine on a {why}"))
    argv = ["--publish"] + (["--allow-dirty"] if allow else [])
    with pytest.raises(SystemExit):
        rws.main(argv)
