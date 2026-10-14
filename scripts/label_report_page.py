"""REPORTPAGE-01: label the rendered report and write it, with its provenance, into the dashboard.

    python scripts/label_report_page.py --html <nbconvert html> --provenance <run provenance.json>

The input is the HTML ``RUN_FINAL.bat`` writes and the ``provenance.json`` of the same run. The
output is ``dashboard/public/report/index.html`` (served at ``/report/``) and
``dashboard/public/report/provenance.json`` beside it.

This is a post-render step on purpose: the label is added here, not in ``report_html.j2`` or the
notebook, so the client deliverable those produce is unchanged.

It refuses rather than labels a page that is not fit to publish: a cross-validation FAIL (in the
manifest or as the banner in the HTML), a dirty tree, a run that is not production mode or below
the production-scale floor, any asset the page would load from beside itself or from disk, and a
page that trips a shipped-file check (an embedded chart whose base64 trips one by chance is
re-encoded losslessly first).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
OUT_DIR = REPO_ROOT / "dashboard" / "public" / "report"

TITLE = "Tropic Ridge Wind Farm - technical risk report (synthetic)"
#: The same floor the committed showcase is held to (tests/test_showcase_snapshot.py).
PRODUCTION_SCALE_FLOOR = 100_000
#: The banner deliverable.py writes on a cross-validation FAIL (D-11: write, then fail).
FAIL_BANNER = "CROSS-VALIDATION FAILED"

#: An attribute that makes the browser fetch something. A link a reader clicks (``<a href>``) is
#: navigation, not an asset, and is not checked here.
_ASSET_ATTR = re.compile(r"<(?:script|img|link|iframe|source|video|audio|embed)\b[^>]*?"
                         r"\b(?:src|href)\s*=\s*[\"']([^\"']*)[\"']", re.IGNORECASE)
_REMOTE = ("http://", "https://", "data:")


class Refused(Exception):
    pass


def manifest_from(provenance: dict) -> dict:
    """The published subset of a run's provenance: identity and parameters, never a path."""
    params = provenance.get("params") or {}
    return {
        "project": provenance["project"],
        "run_date": provenance["run_date"],
        "timestamp": provenance["timestamp"],
        "engine_sha": provenance["engine_sha"],
        "engine_tree_dirty": provenance["engine_tree_dirty"],
        "mode": provenance["mode"],
        "seed": params["seed"],
        "iterations": params["iterations"],
        "input_sha256": provenance["input_sha256"],
        "cross_validation_all_pass": provenance["cross_validation_all_pass"],
    }


def refuse_unless_publishable(manifest: dict, page: str) -> None:
    if manifest["cross_validation_all_pass"] is not True:
        raise Refused("the run's cross-validation did not pass")
    if FAIL_BANNER in page:
        raise Refused("the HTML carries the cross-validation FAIL banner")
    if manifest["engine_tree_dirty"] is not False:
        raise Refused("the run's tree was not clean, so its engine_sha does not name its code")
    if manifest["mode"] != "prod":
        raise Refused(f"the run is mode {manifest['mode']!r}, not prod")
    if int(manifest["iterations"]) < PRODUCTION_SCALE_FLOOR:
        raise Refused(f"the run is {manifest['iterations']:,} iterations, below the "
                      f"{PRODUCTION_SCALE_FLOOR:,} production-scale floor")
    local = [u for u in local_assets(page)]
    if local:
        raise Refused(f"the page loads assets from beside itself or from disk: {local}")


def local_assets(page: str) -> list[str]:
    """Every asset reference that is not remote or inline - a relative path or a ``file://``."""
    return [u for u in _ASSET_ATTR.findall(page) if not u.lower().startswith(_REMOTE)]


def remote_scripts(page: str) -> list[str]:
    """The scripts the page fetches from a CDN, for the close-out."""
    return sorted({u for u in re.findall(r"<script\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"']", page,
                                         re.IGNORECASE)})


def banner(manifest: dict) -> str:
    sha = manifest["engine_sha"]
    return (
        '<div id="reportpage-label" style="font-family:-apple-system,BlinkMacSystemFont,'
        "'Segoe UI',Roboto,sans-serif;background:#1a2332;color:#fff;padding:14px 20px;"
        'line-height:1.5;font-size:14px">'
        f"<strong>{html.escape(TITLE)}</strong><br>"
        "Synthetic, illustrative data on a fictional project. This is not a client deliverable "
        "and is not for funding decisions.<br>"
        f"Run {html.escape(manifest['run_date'])} &middot; engine commit "
        f'<code title="{html.escape(sha)}">{html.escape(sha[:7])}</code> &middot; '
        f"seed {int(manifest['seed'])} &middot; {int(manifest['iterations']):,} iterations"
        ' &middot; <a href="/" style="color:#9cc3ff">Back to the dashboard</a>'
        "</div>"
    )


def label(page: str, manifest: dict) -> str:
    titled, n = re.subn(r"<title>.*?</title>", f"<title>{html.escape(TITLE)}</title>", page,
                        count=1, flags=re.IGNORECASE | re.DOTALL)
    if n != 1:
        raise Refused("the HTML has no <title> to replace")
    labelled, n = re.subn(r"(<body\b[^>]*>)", lambda m: m.group(1) + banner(manifest), titled,
                          count=1, flags=re.IGNORECASE)
    if n != 1:
        raise Refused("the HTML has no <body> to label")
    return labelled


#: Every PNG nbconvert embeds in the page, as base64 in a data URI.
_EMBEDDED_PNG = re.compile(r"(data:image/png;base64,)([A-Za-z0-9+/=]+)")


def clear_embedded_images(page: str, findings) -> str:
    """The page with any embedded chart whose base64, by chance, trips a shipped-file check
    re-encoded losslessly until it does not (REPORTPAGE-01; the same step SHOWCASESYNC-01's
    charts take). The base64 is what the client gate's TERM limb reads, so it is what is checked."""
    import base64

    from scripts.release.publishable_bytes import clean_png

    def one(m: re.Match) -> str:
        data = base64.b64decode(m.group(2))
        view = lambda b: base64.b64encode(b)  # noqa: E731
        try:
            cleaned = clean_png(data, "index.html", findings, view)
        except ValueError as exc:
            raise Refused(str(exc)) from exc
        return m.group(1) + (m.group(2) if cleaned is data else view(cleaned).decode("ascii"))

    return _EMBEDDED_PNG.sub(one, page)


def refuse_unless_clear(page: str, findings) -> None:
    found = findings("index.html", page.encode("utf-8"))
    if found:
        raise Refused(f"the labelled page trips a shipped-file check: {found}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--html", type=Path, required=True)
    ap.add_argument("--provenance", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)

    page = args.html.read_text(encoding="utf-8")
    manifest = manifest_from(json.loads(args.provenance.read_text(encoding="utf-8")))
    try:
        refuse_unless_publishable(manifest, page)
        from scripts.release.publishable_bytes import load_findings
        try:
            findings = load_findings()
        except FileNotFoundError as exc:
            raise Refused(str(exc)) from exc
        out = clear_embedded_images(label(page, manifest), findings)
        refuse_unless_clear(out, findings)
    except Refused as exc:
        print(f"REFUSED: {exc}")
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "index.html").write_bytes(out.replace("\r\n", "\n").encode("utf-8"))
    (args.out_dir / "provenance.json").write_bytes(
        (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    print(f"wrote {args.out_dir / 'index.html'} and provenance.json")
    for url in remote_scripts(out):
        print(f"  loads from a CDN: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
