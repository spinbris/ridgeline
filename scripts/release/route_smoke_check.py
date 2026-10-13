"""Post-deploy route smoke check: every route hard-loads 200 as HTML, and an unknown path 404s (step 5).

Ported from the archived active-management repository's
script of the same name, read at `6c071ff`, against this tree's live state: one data
directory per project (`data/<project>/`), the projects named for publication
(`publishable_projects()`), and FIVE pathname-dependent sites where the archive had four.

Why it hard-loads: data files resolve at literal paths whatever the routing config does, and Next's
client-side navigation never asks the server, so a broken HTML route can ship unseen.

**What it does not check**: the archived check also asserted each route's rendered header
title, guidance strip and active tab. This app renders its whole shell on the client, inside
`<Suspense fallback={null}>` (`dashboard/app/layout.tsx`), so the static HTML carries none of them,
and a check that runs no JavaScript cannot see them. They are verified by hand, per route, in the
procedure's step 6; an automated rendered-page check is not built yet.

Checks:
  0. the pathname-dependent sites in `dashboard/` are exactly the registered set (an unregistered
     one fails);
  1. every route in `dashboard/out/` hard-loads 200 with a `text/html` content type;
  2. an unknown path returns 404;
  3. each named project's served period JSONs byte-match `data/<project>/`;
  4. the served `/data/projects.json` lists exactly the projects named for publication.

Run by the operator against a PREVIEW; the tests run it only offline:

    python scripts/release/route_smoke_check.py https://<preview-host>

The base URL may instead come from DASHBOARD_BASE_URL. Preview deployments sit behind Vercel SSO:
set VERCEL_AUTOMATION_BYPASS_SECRET and it is sent as `x-vercel-protection-bypass`. The secret is
never printed.

Exit 0 = all checks pass; 1 = one or more failures (all listed); 2 = setup error.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DASHBOARD = REPO_ROOT / "dashboard"
OUT_DIR = DASHBOARD / "out"
DATA_DIR = REPO_ROOT / "data"
TIMEOUT = 30
BASE_ENV_VAR = "DASHBOARD_BASE_URL"
BYPASS_ENV_VAR = "VERCEL_AUTOMATION_BYPASS_SECRET"

#: Every source site whose behaviour depends on `usePathname()` (docs/RELEASE_PROCEDURE_dashboard.md,
#: the five-site table), registered by file AND by the line itself (gate 3 round 1, W6): a new
#: lookup inside a registered file is a new site. Check 0 re-runs the sweep and fails both on a
#: site not listed here and on a listed site no longer seen, so neither a sixth site nor a changed
#: one passes silently. A line edited in place must be re-registered here, deliberately.
KNOWN_PATHNAME_SITES = {
    ("components/AppHeader.tsx", 'const pageTitle = PAGE_TITLES[normalisePath(pathname)] ?? "";'):
        "header page title",
    ("components/GuidanceStrip.tsx", "const copy = GUIDANCE[normalisePath(pathname)];"):
        "guidance strip",
    ("components/PageNav.tsx", "const active = normalisePath(pathname) === normalisePath(p.href);"):
        "active nav tab",
    ("lib/PeriodContext.tsx", 'return pathname.startsWith("/analyst") ? "analyst" : "pm";'):
        "roleFromPathname: prefix match, slash-safe by construction",
    ("components/PeriodFreshnessBanner.tsx", 'const isAnalyst = roleFromPathname(pathname) === "analyst";'):
        "role, through roleFromPathname(), so slash-safe",
}

# A line is pathname-DEPENDENT when it mentions `pathname` AND discriminates on it. Operator-based,
# not shape-based: `normalisePath(pathname) === normalisePath(p.href)` must count.
_USES_PATHNAME = re.compile(r"\bpathname\b")
_DISCRIMINATES = re.compile(r"===|!==|\.startsWith\(|\.includes\(|\[[^\]]*pathname[^\]]*\]")
_COMMENT = re.compile(r"^\s*(//|\*|/\*)")
_SKIP_PARTS = {"node_modules", ".next", "out", ".vercel", "__tests__"}

#: (status, headers, body, Location) - the shape `http_fetch` returns and a test stub mirrors.
Fetch = Callable[[str, bool], tuple[int, object, bytes, str | None]]


@dataclass
class Report:
    failures: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.failures.append(msg)
        print(f"  FAIL  {msg}")

    @staticmethod
    def ok(msg: str) -> None:
        print(f"  ok    {msg}")


def is_pathname_site(line: str) -> bool:
    return bool(_USES_PATHNAME.search(line) and _DISCRIMINATES.search(line)
                and not _COMMENT.match(line))


def http_fetch(url: str, follow: bool):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None

    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url)
    secret = os.environ.get(BYPASS_ENV_VAR)
    if secret:
        req.add_header("x-vercel-protection-bypass", secret)
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            return r.status, r.headers, r.read(), r.headers.get("Location")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read(), e.headers.get("Location")


def is_sso(status: int, location: str | None) -> bool:
    return 300 <= status < 400 and bool(location) and "vercel.com/sso-api" in location


def routes_from_out(out_dir: Path) -> list[str]:
    found = []
    for path in sorted(out_dir.rglob("*.html")):
        rel = path.relative_to(out_dir).as_posix()
        if rel == "404.html" or rel.startswith("404/"):
            continue
        if rel == "index.html":
            found.append("/")
        elif rel.endswith("/index.html"):
            found.append("/" + rel[: -len("index.html")])
        else:
            found.append("/" + rel[: -len(".html")])
    return found


def check_pathname_sites(report: Report, dashboard: Path) -> None:
    print("0. Pathname-dependent sites match the registered set")
    seen: dict[tuple[str, str], list[int]] = {}
    for path in sorted(dashboard.rglob("*")):
        if path.suffix not in {".ts", ".tsx"} or _SKIP_PARTS & set(path.relative_to(dashboard).parts):
            continue
        rel = path.relative_to(dashboard).as_posix()
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if is_pathname_site(line):
                seen.setdefault((rel, line.strip()), []).append(i)
    unknown = sorted(set(seen) - set(KNOWN_PATHNAME_SITES))
    gone = sorted(set(KNOWN_PATHNAME_SITES) - set(seen))
    # Round 2, numerics WARN: counted, so a byte-identical lookup added in the same file is a site.
    repeated = sorted(k for k in set(seen) & set(KNOWN_PATHNAME_SITES) if len(seen[k]) > 1)
    for rel, line in unknown:
        report.fail(f"unregistered pathname-dependent site: {rel}:{seen[(rel, line)][0]}: {line}")
    for rel, line in gone:
        report.fail(f"registered site no longer seen: {rel}: {line}")
    for rel, line in repeated:
        report.fail(f"registered site seen {len(seen[(rel, line)])} times: {rel} lines "
                    f"{seen[(rel, line)]}: {line}")
    if unknown or gone or repeated:
        report.fail("bring KNOWN_PATHNAME_SITES and the procedure's table into line, and assert it")
    else:
        report.ok(f"{len(seen)} registered site(s), each seen once and none unregistered")


def check_routes(report: Report, base: str, fetch: Fetch, out_dir: Path) -> None:
    """Every built route hard-loads 200 as HTML. Only what raw HTML can prove: this app's
    shell - header title, guidance strip, active tab - renders on the client, inside `Suspense`, so
    the static HTML does not carry it. Those elements are checked by hand, in step 6."""
    print("1. Every route in out/ hard-loads 200 with a text/html content type")
    routes = routes_from_out(out_dir)
    if not routes:
        report.fail(f"no built routes under {out_dir}")
        return
    for url_path in routes:
        status, headers, _raw, location = fetch(base + url_path, False)
        if is_sso(status, location):
            report.fail(f"{url_path} -> {status} intercepted by Vercel SSO: deployment protection, "
                        f"NOT routing. Set {BYPASS_ENV_VAR} and re-run.")
        elif status != 200:
            report.fail(f"{url_path} -> {status}" + (f" (Location: {location})" if location else ""))
        elif "text/html" not in (headers.get("Content-Type") or "").lower():
            report.fail(f"{url_path} -> 200 but Content-Type is {headers.get('Content-Type')!r}")
        else:
            report.ok(f"{url_path} -> 200, text/html")


def check_404(report: Report, base: str, fetch: Fetch) -> None:
    print("2. A nonexistent path returns 404")
    status = fetch(base + "/__smoke_check_should_not_exist__", True)[0]
    if status == 404:
        report.ok("unknown path -> 404")
    else:
        report.fail(f"unknown path -> {status}, expected 404 (are 404s masked as 200?)")


def check_period_json(report: Report, base: str, fetch: Fetch, data_dir: Path,
                      named: list[str]) -> None:
    print("3. Each named project's period JSONs are served and byte-match data/<project>/")
    for project in named:
        local = sorted((data_dir / project).glob("period_*.json"))
        if not local:
            report.fail(f"no period_*.json under {data_dir / project}")
            continue
        for path in local:
            status, _, body, _ = fetch(f"{base}/data/{project}/{path.name}", True)
            if status != 200:
                report.fail(f"{project}/{path.name} -> {status}")
                continue
            served = hashlib.sha256(body).hexdigest()
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            if served != expected:
                report.fail(f"{project}/{path.name} -> 200 but bytes differ "
                            f"(served {served[:12]}, local {expected[:12]})")
            else:
                report.ok(f"{project}/{path.name} -> 200, bytes match ({served[:12]})")


def check_projects_json(report: Report, base: str, fetch: Fetch, named: list[str]) -> None:
    print("4. The served projects.json lists exactly the projects named for publication")
    status, _, body, _ = fetch(f"{base}/data/projects.json", True)
    if status != 200:
        report.fail(f"/data/projects.json -> {status}")
        return
    try:
        served = json.loads(body.decode("utf-8")).get("projects")
    except (UnicodeDecodeError, ValueError, AttributeError) as exc:
        report.fail(f"/data/projects.json is not a project list ({type(exc).__name__})")
        return
    if sorted(served or []) != sorted(named):
        report.fail(f"/data/projects.json lists {served}; named for publication: {named}")
    else:
        report.ok(f"/data/projects.json lists exactly {named}")


def run(base: str, *, fetch: Fetch = http_fetch, dashboard: Path = DASHBOARD,
        out_dir: Path = OUT_DIR, data_dir: Path = DATA_DIR,
        named: list[str] | None = None) -> Report:
    if named is None:
        from src.sra.cpm.bindings.registry import publishable_projects
        named = publishable_projects()
    base = base.rstrip("/")
    report = Report()
    print(f"Route smoke check against {base}; routes from {out_dir}\n")
    check_pathname_sites(report, dashboard)
    check_routes(report, base, fetch, out_dir)
    check_404(report, base, fetch)
    check_period_json(report, base, fetch, data_dir, named)
    check_projects_json(report, base, fetch, named)
    return report


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    base = argv[0] if argv else os.environ.get(BASE_ENV_VAR, "")
    if len(argv) > 1 or not base:
        print(__doc__)
        return 2
    if not OUT_DIR.is_dir():
        print(f"FAIL: no build output at {OUT_DIR}. Run the dashboard build first.")
        return 2
    report = run(base)
    print()
    if report.failures:
        print(f"RESULT: FAIL - {len(report.failures)} problem(s):")
        for f in report.failures:
            print(f"  - {f}")
        return 1
    print("RESULT: PASS - every route hard-loads 200 as HTML; the unknown path 404s; JSONs "
          "byte-match; projects.json lists exactly the named projects. Rendered elements: step 6.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
