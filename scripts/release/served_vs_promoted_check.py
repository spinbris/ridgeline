"""Served-vs-promoted check: does the site serve the build we promoted? (RELEASE_PROCEDURE step 8)

Ported from the archived active-management repository's
script of the same name, read at `6c071ff`, against this tree's live state: the
promoted set is `data/<project>/period_*.json` for each project named for publication
(`publishable_projects()`), served at `/data/<project>/<name>`, where the archive had one flat
`data/`. It has no built-in URL: the base comes from the command line or DASHBOARD_BASE_URL.

Why it exists: every other check fires on a deploy, so a build promoted into `data/` and never
deployed is invisible. This is a STEADY-STATE probe - stdlib only, no build needed - that compares
provenance fields, not bytes (the route smoke check already byte-compares): it answers "which
build, run when, from what inputs?", which is the question a human reads.

Fields compared, per period:
    schema_version          top level, not under meta
    meta.engine_run_date
    meta.engine_sha
    meta.input_sha256       the input key set; per input, its shape and its value

    python scripts/release/served_vs_promoted_check.py <base-url>

A `file://` base works too, so a local control needs no network. Preview deployments sit behind
Vercel SSO: set VERCEL_AUTOMATION_BYPASS_SECRET (never printed).

Exit 0 = every period matches on every field. 1 = everything was fetched and at least one field
differs. 2 = could not complete the comparison (a fetch failed, a body would not parse, the promoted
set is missing, or SSO intercepted). Fetch failure DOMINATES a mismatch: a run that could not read
every period is not a trustworthy green or red.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DATA_DIR = REPO_ROOT / "data"
TIMEOUT = 30
BASE_ENV_VAR = "DASHBOARD_BASE_URL"
BYPASS_ENV_VAR = "VERCEL_AUTOMATION_BYPASS_SECRET"
MISSING = object()


class FetchError(Exception):
    pass


def _digest_shape(entry: object) -> str:
    if isinstance(entry, str):
        return "bare string"
    if isinstance(entry, dict):
        return "record{" + ",".join(sorted(entry)) + "}"
    return f"unexpected {type(entry).__name__}"


def _digest_value(entry: object) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return str(entry.get("value"))
    return repr(entry)


def extract(doc: dict) -> dict[str, object]:
    """Flatten the compared surface into {field label: value}."""
    meta = doc.get("meta") or {}
    fields: dict[str, object] = {
        "schema_version": doc.get("schema_version", MISSING),
        "meta.engine_run_date": meta.get("engine_run_date", MISSING),
        "meta.engine_sha": meta.get("engine_sha", MISSING),
    }
    digests = meta.get("input_sha256")
    if not isinstance(digests, dict):
        fields["meta.input_sha256"] = (
            MISSING if digests is None else f"unexpected {type(digests).__name__}")
        return fields
    fields["meta.input_sha256 (input keys)"] = ", ".join(sorted(digests))
    for key in sorted(digests):
        fields[f"meta.input_sha256.{key} (shape)"] = _digest_shape(digests[key])
        fields[f"meta.input_sha256.{key} (value)"] = _digest_value(digests[key])
    return fields


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url)
    secret = os.environ.get(BYPASS_ENV_VAR)
    if secret and not url.startswith("file:"):
        req.add_header("x-vercel-protection-bypass", secret)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            status = getattr(r, "status", None)
            location = r.headers.get("Location") if r.headers else None
            body = r.read()
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        raise FetchError(f"URLError: {e.reason}") from e
    except OSError as e:
        raise FetchError(f"{type(e).__name__}: {e}") from e
    if location and "vercel.com/sso-api" in location:
        raise FetchError("intercepted by Vercel SSO (deployment protection, NOT drift). "
                         f"Set {BYPASS_ENV_VAR} and re-run.")
    if status is not None and status != 200:
        raise FetchError(f"HTTP {status}")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise FetchError(f"body is not JSON ({type(e).__name__})") from e


def show(value: object) -> str:
    return "<absent>" if value is MISSING else str(value)


def compare(name: str, promoted: dict, served: dict) -> list[str]:
    p_fields, s_fields = extract(promoted), extract(served)
    diffs = []
    for label in list(p_fields) + [k for k in s_fields if k not in p_fields]:
        p, s = p_fields.get(label, MISSING), s_fields.get(label, MISSING)
        if p != s:
            diffs.append(label)
            print(f"  DIFF  {label}\n          promoted (data/): {show(p)}\n          served          : {show(s)}")
    if diffs:
        print(f"  FAIL  {name}: {len(diffs)} field(s) differ")
    else:
        print(f"  ok    {name}: all {len(p_fields)} compared field(s) match")
    return diffs


def run(base: str, *, fetch: Callable[[str], dict] = fetch_json, data_dir: Path = DATA_DIR,
        named: list[str] | None = None) -> int:
    if named is None:
        from src.sra.cpm.bindings.registry import publishable_projects
        named = publishable_projects()
    base = base.rstrip("/")
    local = [(p, path) for p in named for path in sorted((data_dir / p).glob("period_*.json"))]
    if not local:
        print(f"FAIL: no promoted set - no period_*.json under {data_dir}/<named project>/ "
              f"for {named}")
        return 2
    print(f"Served-vs-promoted check against {base}: {len(local)} period(s) across {named}\n")
    total, errors = 0, []
    for project, path in local:
        name = f"{project}/{path.name}"
        print(name)
        try:
            promoted = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            errors.append(f"{name}: promoted copy unreadable - {type(e).__name__}")
            print(f"  ERROR {errors[-1]}\n")
            continue
        try:
            served = fetch(f"{base}/data/{project}/{path.name}")
        except FetchError as e:
            errors.append(f"{name}: {e}")
            print(f"  ERROR could not fetch - {e}\n")
            continue
        total += len(compare(name, promoted, served))
        print()
    if errors:
        print(f"RESULT: INCOMPLETE - {len(errors)} period(s) could not be compared:")
        for msg in errors:
            print(f"  - {msg}")
        if total:
            print(f"  ({total} field difference(s) in the periods that did compare)")
        return 2
    if total:
        print(f"RESULT: DRIFT - {total} field difference(s). The site is not serving the promoted build.")
        return 1
    print("RESULT: MATCH - the site serves the promoted build on every compared field.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    base = argv[0] if argv else os.environ.get(BASE_ENV_VAR, "")
    if len(argv) > 1 or not base:
        print(__doc__)
        return 2
    return run(base)


if __name__ == "__main__":
    raise SystemExit(main())
