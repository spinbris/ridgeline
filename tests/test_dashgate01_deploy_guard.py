"""DASHGATE-01 P4: `deploy()` guards between `vercel build` and `vercel deploy`, and refuses to
deploy on any failure.

`_run` is stubbed: the "build" writes a Build Output API v3 tree into `tmp_path`, and "deploy" is
only recorded. **The fixture mirrors the real shape**, measured from the first real `vercel build`
of this tree (SHOWCASEAPP-01 P4, 30/09/2026, CLI 59.1.3, preview target):
- `config.json` - `version: 3`, `routes`, `crons`, `framework`, no `overrides`; the routes are an
  error handler and a 404 catch-all. DASHGATE-01 read the shape from the archived active-management
  repository's build, whose second route's `src` carried regex escapes; that route is kept below as
  its own case, because the guard must not mistake them for path separators.
- The output's `static/data/` holds `projects.json` and one folder per named project, holding
  `index.json` and its period files; both JSON files carry `generated_at`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.am.publish_period as pp
from src.am.publish_period import PublishError

BS = chr(92)


def _write_output(dashboard: Path, *, overrides=None, dest=None, listed=("synthetic_wind",),
                  dirs=("synthetic_wind",), extra_files=()):
    out = dashboard / ".vercel" / "output"
    routes = [{"handle": "error"}, {"status": 404, "src": "^(?!/api).*$", "dest": "/404.html"}]
    if dest is not None:
        routes.append({"src": "^/analyst/drivers$", "dest": dest})
    config = {"version": 3, "routes": routes, "crons": [],
              "framework": {"slug": "nextjs", "version": "15.3.9"}}
    if overrides is not None:
        config["overrides"] = overrides
    (out / "static" / "data").mkdir(parents=True)
    (out / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (out / "static" / "index.html").write_text("<html></html>", encoding="utf-8")
    data = out / "static" / "data"
    stamp = "2026-09-30T05:39:58.439Z"
    (data / "projects.json").write_text(
        json.dumps({"projects": list(listed), "generated_at": stamp}), encoding="utf-8")
    for project in dirs:
        (data / project).mkdir()
        period = "period_20260228.json"
        (data / project / "index.json").write_text(
            json.dumps({"periods": [period], "generated_at": stamp}), encoding="utf-8")
        (data / project / period).write_text("{}", encoding="utf-8")
    for name in extra_files:
        (data / name).write_text("{}", encoding="utf-8")


def _deploy(tmp_path, monkeypatch, *, build_writes=True, **output):
    ran = []

    def run(command, *, cwd, what):
        ran.append(command[:2])
        if command[:2] == ["vercel", "build"] and build_writes:
            _write_output(Path(cwd), **output)

    monkeypatch.setattr(pp, "_run", run)
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    pp.deploy(dashboard)
    return ran


def _refused(tmp_path, monkeypatch, match, **kw):
    ran = []
    with pytest.raises(PublishError, match=match) as exc:
        ran = _deploy(tmp_path, monkeypatch, **kw)
    assert "Nothing was deployed" in str(exc.value)
    return exc


def test_a_clean_build_is_deployed(tmp_path, monkeypatch):
    assert _deploy(tmp_path, monkeypatch) == [["vercel", "build"], ["vercel", "deploy"]]


def test_a_regex_escape_in_a_route_src_is_not_a_path_separator(tmp_path, monkeypatch):
    """The archived guard's own warning: a naive whole-file check false-positives on these. The
    route is the archived build's; this tree's build no longer emits one."""
    def mutate(c):
        c["routes"].append({"src": "^/(.*)" + BS + ".html/?$", "status": 404})
    _config_with(tmp_path, monkeypatch, mutate)  # no refusal


@pytest.mark.parametrize("output", [
    {"overrides": {"analyst" + BS + "drivers.html": {"path": "analyst/drivers"}}},
    {"overrides": {"analyst/drivers.html": {"path": "analyst" + BS + "drivers"}}},  # path-walker: plant - a Vercel route key, not a repository path
    {"dest": "/analyst" + BS + "drivers"},
])
def test_a_windows_path_separator_in_the_config_refuses(tmp_path, monkeypatch, output):
    _refused(tmp_path, monkeypatch, "path separator", **output)


def test_a_project_the_bindings_do_not_name_in_projects_json_refuses(tmp_path, monkeypatch):
    _refused(tmp_path, monkeypatch, "synthetic_road",
             listed=("synthetic_road", "synthetic_wind"), dirs=("synthetic_road", "synthetic_wind"))


def test_an_unnamed_project_directory_refuses_even_when_projects_json_omits_it(tmp_path, monkeypatch):
    _refused(tmp_path, monkeypatch, "other_project", dirs=("synthetic_wind", "other_project"))


def test_a_stray_file_in_the_data_folder_refuses(tmp_path, monkeypatch):
    _refused(tmp_path, monkeypatch, "index.json", extra_files=("index.json",))


def test_a_build_that_wrote_nothing_refuses(tmp_path, monkeypatch):
    _refused(tmp_path, monkeypatch, "no build output", build_writes=False)


def test_a_refusal_never_runs_vercel_deploy(tmp_path, monkeypatch):
    ran = []

    def run(command, *, cwd, what):
        ran.append(command[:2])
        if command[:2] == ["vercel", "build"]:
            _write_output(Path(cwd), listed=("synthetic_road",), dirs=("synthetic_road",))

    monkeypatch.setattr(pp, "_run", run)
    (tmp_path / "dashboard").mkdir()
    with pytest.raises(PublishError):
        pp.deploy(tmp_path / "dashboard")
    assert ran == [["vercel", "build"]], f"vercel deploy ran after the guard refused: {ran}"


# --- R-1 (PM, task -4): the guard fails closed on a shape it does not know ------------------

def _plant_config(dashboard: Path, raw: str) -> None:
    _write_output(dashboard)
    (dashboard / ".vercel" / "output" / "config.json").write_text(raw, encoding="utf-8")


def _refuses_config(tmp_path, monkeypatch, raw: str, match: str):
    ran = []

    def run(command, *, cwd, what):
        ran.append(command[:2])
        if command[:2] == ["vercel", "build"]:
            _plant_config(Path(cwd), raw)

    monkeypatch.setattr(pp, "_run", run)
    (tmp_path / "dashboard").mkdir()
    with pytest.raises(PublishError, match=match):
        pp.deploy(tmp_path / "dashboard")
    assert ran == [["vercel", "build"]], f"vercel deploy ran on an unknown shape: {ran}"


@pytest.mark.parametrize("raw, match", [
    ("{not json", "unreadable"),
    ('["a list, not a document"]', "not a Build Output API version 3"),
    ('{"version": 2, "routes": []}', "not a Build Output API version 3"),
    ('{"routes": []}', "not a Build Output API version 3"),
    ('{"version": 3, "routes": {"handle": "filesystem"}}', "routes"),
    ('{"version": 3, "routes": ["^/x$"]}', "routes"),
    ('{"version": 3, "routes": [{"src": "^/x$", "dest": ["/a", "/b"]}]}', "dest"),
    ('{"version": 3, "routes": [], "overrides": ["analyst/drivers.html"]}', "overrides"),  # path-walker: plant
    ('{"version": 3, "routes": [], "overrides": {"a.html": "a"}}', "overrides"),
    ('{"version": 3, "routes": [], "overrides": {"a.html": {"path": 7}}}', "path"),
])
def test_an_unknown_config_shape_refuses_rather_than_skipping(tmp_path, monkeypatch, raw, match):
    _refuses_config(tmp_path, monkeypatch, raw, match)


# --- Breaker W5 (round 1): every string in config.json is checked, except routes[].src -----------

def _config_with(tmp_path, monkeypatch, mutate):
    def run(command, *, cwd, what):
        if command[:2] == ["vercel", "build"]:
            _write_output(Path(cwd))
            path = Path(cwd) / ".vercel" / "output" / "config.json"
            config = json.loads(path.read_text(encoding="utf-8"))
            mutate(config)
            path.write_text(json.dumps(config), encoding="utf-8")

    monkeypatch.setattr(pp, "_run", run)
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    pp.deploy(dashboard)


def test_a_backslash_in_a_route_header_location_refuses(tmp_path, monkeypatch):
    def mutate(c):
        c["routes"].append({"src": "^/old$", "headers": {"Location": "/analyst" + BS + "drivers"},
                            "status": 308})
    with pytest.raises(PublishError, match="Location"):
        _config_with(tmp_path, monkeypatch, mutate)


def test_a_backslash_in_a_cron_path_refuses(tmp_path, monkeypatch):
    def mutate(c):
        c["crons"] = [{"path": "/api" + BS + "tick", "schedule": "0 * * * *"}]
    with pytest.raises(PublishError, match="crons"):
        _config_with(tmp_path, monkeypatch, mutate)


def test_a_backslash_in_a_field_vercel_adds_later_refuses(tmp_path, monkeypatch):
    def mutate(c):
        c["somethingNew"] = {"nested": ["ok", "a" + BS + "b"]}
    with pytest.raises(PublishError, match="somethingNew"):
        _config_with(tmp_path, monkeypatch, mutate)


def test_an_escaped_regex_in_a_route_src_passes(tmp_path, monkeypatch):
    def mutate(c):
        c["routes"].append({"src": "^/(.*)" + BS + ".txt$", "dest": "/$1.txt"})
    _config_with(tmp_path, monkeypatch, mutate)  # no refusal


def test_a_non_string_route_src_is_an_unknown_shape(tmp_path, monkeypatch):
    """Round 2, NOTE-3: the one field the separator walk skips must at least be a string."""
    _refuses_config(tmp_path, monkeypatch,
                    '{"version": 3, "routes": [{"src": ["^/a$"]}]}', "src")
