"""DASHGATE-01 P5: the route smoke check and the drift check, run offline against a local fixture.

No network in any test: `fetch` is stubbed with a dict of served responses. The routes are the
app's own (one per `page.tsx` under `dashboard/app/`), and **each served page mirrors the real
static export's shape** (PM R-8): the shell - header title, guidance strip, active tab - is absent,
because this app renders it on the client. Measured on the real build, `dashboard/out/risks/index.html` has no
`<header>`, no `aria-current` and no title text. Each check passes on the clean fixture and goes red
on its own defect: a stray project, a route that 404s, a non-HTML route, an unknown path served
200, a byte mismatch, a drifted `engine_sha`, an unregistered pathname site.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "release"))

import route_smoke_check as smoke  # noqa: E402
import served_vs_promoted_check as drift  # noqa: E402

DASHBOARD = REPO / "dashboard"
GOLDEN = REPO / "tests" / "golden" / "period_json" / "wind_synth" / "period_20260228.json"
BASE = "https://preview.invalid"
NAMED = ["synthetic_wind"]
PERIOD = "period_20260228.json"


#: A static-export page as the real build writes it: scripts, and no shell (measured, R-8).
PAGE = b'<!DOCTYPE html><html lang="en"><head></head><body><script src="/_next/x.js"></script></body></html>'


def app_routes() -> list[str]:
    """One route per `page.tsx` under `dashboard/app/` - the app's own routes."""
    app = DASHBOARD / "app"
    return sorted("/" if p.parent == app else "/" + p.parent.relative_to(app).as_posix()
                  for p in app.rglob("page.tsx"))


def _served_site(tmp_path: Path, *, projects=NAMED, drop_route=None, content_type="text/html",
                 served_period=None):
    """(out_dir, data_dir, fetch): a built out/, a promoted data/, and what the 'server' returns."""
    routes = app_routes()
    assert "/" in routes and "/risks" in routes, routes
    out = tmp_path / "out"
    served: dict[str, tuple] = {}
    for route in routes:
        page = out / "index.html" if route == "/" else out / route.strip("/") / "index.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_bytes(PAGE)
        url_path = "/" if route == "/" else route + "/"
        ctype = content_type if route == "/risks" else "text/html"
        if route != drop_route:
            served[BASE + url_path] = (200, {"Content-Type": ctype}, PAGE, None)
    (out / "404.html").write_text("404", encoding="utf-8")

    data = tmp_path / "data" / "synthetic_wind"
    data.mkdir(parents=True)
    data.joinpath(PERIOD).write_bytes(GOLDEN.read_bytes())
    served[f"{BASE}/data/synthetic_wind/{PERIOD}"] = (
        200, {}, served_period if served_period is not None else GOLDEN.read_bytes(), None)
    served[f"{BASE}/data/projects.json"] = (
        200, {}, json.dumps({"projects": list(projects)}).encode(), None)

    def fetch(url, follow):
        return served.get(url, (404, {}, b"", None))

    return out, tmp_path / "data", fetch


def _smoke(tmp_path, **kw):
    out, data, fetch = _served_site(tmp_path, **kw)
    return smoke.run(BASE, fetch=fetch, dashboard=DASHBOARD, out_dir=out, data_dir=data, named=NAMED)


def test_a_non_html_route_reds(tmp_path):
    failures = _smoke(tmp_path, content_type="application/json").failures
    assert any(f.startswith("/risks/ -> 200 but Content-Type") for f in failures), failures


def test_the_check_no_longer_claims_rendered_elements():
    """R-8: nothing about titles, guidance strips or tabs, which the static HTML cannot carry."""
    assert not hasattr(smoke, "safe_snippet") and not hasattr(smoke, "parse_route_table")


def test_the_smoke_check_passes_a_clean_site(tmp_path):
    assert _smoke(tmp_path).failures == []


def test_the_smoke_check_reds_on_a_stray_project(tmp_path):
    failures = _smoke(tmp_path, projects=["synthetic_road", "synthetic_wind"]).failures
    assert any("projects.json" in f and "synthetic_road" in f for f in failures), failures


def test_the_smoke_check_reds_on_a_missing_route(tmp_path):
    failures = _smoke(tmp_path, drop_route="/risks").failures
    assert any(f.startswith("/risks/ -> 404") for f in failures), failures


def test_the_sweep_finds_this_tree_s_five_sites_and_no_other(tmp_path):
    report = smoke.Report()
    smoke.check_pathname_sites(report, DASHBOARD)
    assert report.failures == []
    assert len(smoke.KNOWN_PATHNAME_SITES) == 5
    assert len({rel for rel, _ in smoke.KNOWN_PATHNAME_SITES}) == 5


def test_the_sweep_reds_on_an_unregistered_site(tmp_path):
    root = tmp_path / "dashboard"
    (root / "components").mkdir(parents=True)
    (root / "components" / "NewThing.tsx").write_text(
        'export const x = (pathname: string) => pathname === "/risks";\n', encoding="utf-8")
    report = smoke.Report()
    smoke.check_pathname_sites(report, root)
    assert any("components/NewThing.tsx" in f for f in report.failures), report.failures  # path-walker: plant


def test_the_404_check_reds_when_unknown_paths_are_masked(tmp_path):
    report = smoke.Report()
    smoke.check_404(report, BASE, lambda url, follow: (200, {}, b"", None))
    assert report.failures


# --- the drift check ---------------------------------------------------------------------------

def _drift(tmp_path, served_doc):
    data = tmp_path / "data" / "synthetic_wind"
    data.mkdir(parents=True)
    data.joinpath(PERIOD).write_bytes(GOLDEN.read_bytes())
    return drift.run(BASE, fetch=lambda url: served_doc, data_dir=tmp_path / "data", named=NAMED)


def _golden() -> dict:
    return json.loads(GOLDEN.read_bytes().decode("utf-8"))


def test_the_drift_check_matches_the_promoted_build(tmp_path):
    assert _drift(tmp_path, _golden()) == 0


def test_the_drift_check_reds_on_a_drifted_engine_sha(tmp_path, capsys):
    served = copy.deepcopy(_golden())
    served["meta"]["engine_sha"] = "0" * 40
    assert _drift(tmp_path, served) == 1
    assert "meta.engine_sha" in capsys.readouterr().out


def test_a_fetch_failure_is_incomplete_not_green(tmp_path):
    def fail(url):
        raise drift.FetchError("HTTP 404")

    data = tmp_path / "data" / "synthetic_wind"
    data.mkdir(parents=True)
    data.joinpath(PERIOD).write_bytes(GOLDEN.read_bytes())
    assert drift.run(BASE, fetch=fail, data_dir=tmp_path / "data", named=NAMED) == 2


def test_neither_check_carries_a_built_in_url(monkeypatch):
    monkeypatch.delenv("DASHBOARD_BASE_URL", raising=False)
    for module in (smoke, drift):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "https://" not in source.replace("https://<preview-host>", ""), module.__name__
        assert module.main([]) == 2, f"{module.__name__} ran with no base URL given"


def test_a_run_with_the_bypass_secret_set_never_prints_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VERCEL_AUTOMATION_BYPASS_SECRET", "s3cr3t-value")
    _smoke(tmp_path / "a", projects=["synthetic_road"])  # a failing run prints the most
    _drift(tmp_path / "b", _golden())
    assert "s3cr3t-value" not in capsys.readouterr().out


# --- Round 1, numerics WARN 1 and breaker N3: each element, and check 3, can red --------------------

import pytest  # noqa: E402


def test_a_served_period_whose_bytes_differ_reds(tmp_path):
    failures = _smoke(tmp_path, served_period=GOLDEN.read_bytes() + b" ").failures
    assert any("bytes differ" in f for f in failures), failures


# --- Round 1, breaker W6 / numerics WARN 2 / N3: sites registered by file AND line ---------------

def _site_tree(tmp_path: Path) -> Path:
    """The five registered files, copied as they are, into a scratch dashboard root."""
    root = tmp_path / "dashboard"
    for key in smoke.KNOWN_PATHNAME_SITES:
        rel = key[0]  # (file, line)
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes((DASHBOARD / rel).read_bytes())
    return root


def test_the_registered_sites_are_exactly_what_the_sweep_sees(tmp_path):
    report = smoke.Report()
    smoke.check_pathname_sites(report, _site_tree(tmp_path))
    assert report.failures == []


def test_a_new_lookup_inside_a_registered_file_reds(tmp_path):
    root = _site_tree(tmp_path)
    header = root / "components" / "AppHeader.tsx"
    header.write_text(header.read_text(encoding="utf-8")
                      + '\nconst other = OTHER_TABLE[pathname] ?? "";\n', encoding="utf-8")
    report = smoke.Report()
    smoke.check_pathname_sites(report, root)
    assert any("unregistered" in f and "OTHER_TABLE" in f for f in report.failures), report.failures


def test_a_registered_site_no_longer_seen_reds(tmp_path):
    root = _site_tree(tmp_path)
    strip = root / "components" / "GuidanceStrip.tsx"
    strip.write_text("\n".join(line for line in strip.read_text(encoding="utf-8").splitlines()
                               if "GUIDANCE[normalisePath(pathname)]" not in line), encoding="utf-8")
    report = smoke.Report()
    smoke.check_pathname_sites(report, root)
    assert any("no longer seen" in f and "GuidanceStrip.tsx" in f for f in report.failures), report.failures


# --- Round 2, numerics WARN: a site is counted, so a duplicated lookup line reds -----------------

def test_a_duplicated_lookup_line_in_a_registered_file_reds(tmp_path):
    root = _site_tree(tmp_path)
    strip = root / "components" / "GuidanceStrip.tsx"
    line = "const copy = GUIDANCE[normalisePath(pathname)];"
    strip.write_text(strip.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8")
    report = smoke.Report()
    smoke.check_pathname_sites(report, root)
    assert any("seen 2 times" in f and "GuidanceStrip.tsx" in f for f in report.failures), report.failures


def test_the_headline_says_what_check_1_proves():
    """Round 2, breaker WARN-2: `main()` prints the docstring on a setup error."""
    first = smoke.__doc__.strip().splitlines()[0]
    assert "render" not in first.lower(), first
    assert "200" in first and "404" in first, first
