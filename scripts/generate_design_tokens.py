"""Generate docs/design_tokens.md and docs/design_tokens.json from one source of truth.

Canonical palette source: ../renewables/reports/theme.scss (slate + teal).
Per UX01-T0. Run with: python scripts/generate_design_tokens.py
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"

TOKENS = {
    "slate": "#334155",
    "slate_dark": "#1e293b",
    "slate_light": "#64748b",
    "teal": "#0d9488",
    "teal_dark": "#0f766e",
    "teal_light": "#5eead4",
    "amber": "#d97706",
    "paper": "#ffffff",
    "mist": "#f8fafc",
    "line": "#e2e8f0",
    "warn_red": "#dc2626",
}

FONT = {
    "web": {"primary": "Inter", "fallback": ["Segoe UI", "-apple-system", "Helvetica Neue", "Arial", "sans-serif"]},
    "excel": {"primary": "Segoe UI", "note": "Inter is not a native Excel font on most client machines; Segoe UI is the closest available match to the web/report family."},
}

# D-UX4 (resolved): dashboard's existing mockup-derived navy palette (#1a2332 / #2c4d7a / ...)
# is replaced outright, not reconciled or kept alongside these tokens.
TAB_COLOUR_GROUPS = {
    "Guide": {"hex": TOKENS["teal"], "sheets": ["User Guide"]},
    "Setup": {"hex": TOKENS["slate_light"], "sheets": ["Cover", "Flysheet", "Project Details", "Status"]},
    "Register": {"hex": TOKENS["teal_dark"], "sheets": ["Risk Register", "Risk Matrix", "Risk Scoring", "Top 20"]},
    "Quantification": {
        "hex": TOKENS["slate"],
        "sheets": [
            "Quantification", "Variables", "MC_Params", "Corr_Factors", "BOP Equip List",
            "EMV Tornado", "EMV Summary", "Waterfall Chart", "Pareto Analysis",
        ],
    },
    "AM": {"hex": TOKENS["amber"], "sheets": ["AM_Period_Status", "AM_Milestones", "AM_Mitigation_Log"]},
    "Reference": {
        "hex": TOKENS["slate_dark"],
        "sheets": [],
        "note": "No current sheet maps to this group. Reserved for future glossary/appendix content; not forced onto an existing tab.",
    },
    "Engine_hidden": {
        "hex": TOKENS["line"],
        "sheets": ["Risk Analysis", "Risk Breakdown Structure", "_ChartHelper", "Unify_Audit", "Unify_Memo", "LISTS", "Sheet1"],
        "note": "Hidden per UX01-T1 scope item 4. Sheet1 is a delete-candidate pending the T1 grep confirming zero formula/defined-name references; hex applies only if a hidden tab is ever unhidden by mistake.",
    },
}

HEADER_BAR = {
    "content": "<project name> - <tab/page title> - <date/rev>",
    "fill": TOKENS["slate_dark"],
    "font_color": TOKENS["paper"],
    "accent_underline": TOKENS["teal"],
    "font": FONT["excel"]["primary"],
}

CHART_PALETTE_ORDER = [
    TOKENS["teal"], TOKENS["slate"], TOKENS["amber"],
    TOKENS["teal_light"], TOKENS["slate_light"],
]

EXCEL_SURFACE = {
    "tab_colours": TAB_COLOUR_GROUPS,
    "header_bar": HEADER_BAR,
    "metric_cell": {
        "fill": TOKENS["mist"],
        "border": TOKENS["line"],
        "label_text": TOKENS["teal_dark"],
        "value_text": TOKENS["slate"],
    },
}

DASHBOARD_CSS_VARS = {
    "_replaces_outright": {
        "--color-page": "#f5f6f8", "--color-card": "#ffffff", "--color-header": "#1a2332",
        "--color-accent": "#2c4d7a", "--color-body": "#1a1f2e", "--color-muted": "#5a6478",
    },
    "--color-page": TOKENS["mist"],
    "--color-card": TOKENS["paper"],
    "--color-header": TOKENS["slate_dark"],
    "--color-accent": TOKENS["teal"],
    "--color-accent-dark": TOKENS["teal_dark"],
    "--color-accent-light": TOKENS["teal_light"],
    "--color-body": TOKENS["slate"],
    "--color-muted": TOKENS["slate_light"],
    "--color-border": TOKENS["line"],
    "--color-warn": TOKENS["warn_red"],
    "_status_colours_unchanged": {
        "--color-fired": "#c93545", "--color-closed": "#2d8659",
        "note": "Functional status colours (risk fired / closed), not brand tokens. Not in theme.scss. Recommend T2 keep these as-is unless Director wants them folded into the brand palette too.",
    },
    "font_family": [FONT["web"]["primary"]] + FONT["web"]["fallback"],
}

MATPLOTLIB_PALETTE = CHART_PALETTE_ORDER

QUARTO_SCSS = {
    "recommendation": "Reference ../renewables/reports/theme.scss directly via an @import or shared scss include, rather than duplicating variables.",
    "note": (
        "the engine's actual report template is a Jupyter notebook "
        "(outputs/report_template.ipynb) with inline <style> blocks, not a Quarto qmd pipeline. "
        "this repository has one standalone qmd (content/tropic_ridge_wind_summary.qmd) "
        "and no _quarto.yml project file. T2's qmd scope item needs to target the notebook's inline "
        "styles, not a qmd include."
    ),
}

def build_payload():
    return {
        "source": "../renewables/reports/theme.scss",
        "tokens": TOKENS,
        "font": FONT,
        "excel": EXCEL_SURFACE,
        "dashboard_css_vars": DASHBOARD_CSS_VARS,
        "matplotlib_palette_order": MATPLOTLIB_PALETTE,
        "quarto_scss": QUARTO_SCSS,
    }

def render_markdown(payload):
    lines = []
    lines.append("# Design tokens (UX01-T0)")
    lines.append("")
    lines.append("Generated by `scripts/generate_design_tokens.py` together with `design_tokens.json` ")
    lines.append("so the two cannot drift. Do not hand-edit either file, edit the generator and rerun.")
    lines.append("")
    lines.append(f"Canonical source: `{payload['source']}` (slate + teal). Scss wins on conflict.")
    lines.append("")
    lines.append("## Palette")
    lines.append("")
    lines.append("| token | hex | role |")
    lines.append("|---|---|---|")
    roles = {
        "slate": "body text", "slate_dark": "headings, cover gradient", "slate_light": "secondary text, TOC",
        "teal": "primary accent, metric border", "teal_dark": "links, h3", "teal_light": "eyebrow text on dark",
        "amber": "teaser/warn accent", "paper": "background", "mist": "card/callout background",
        "line": "borders, h2 underline", "warn_red": "warn callouts only",
    }
    for name, hex_val in payload["tokens"].items():
        lines.append(f"| {name} | {hex_val} | {roles.get(name, '')} |")
    lines.append("")
    lines.append(f"Font, web: {payload['font']['web']['primary']}, fallback {', '.join(payload['font']['web']['fallback'])}.")
    lines.append(f"Font, Excel: {payload['font']['excel']['primary']}. {payload['font']['excel']['note']}")
    lines.append("")
    lines.append("## Excel tab colour groups")
    lines.append("")
    lines.append("| group | hex | sheets |")
    lines.append("|---|---|---|")
    for group, spec in payload["excel"]["tab_colours"].items():
        sheets = ", ".join(spec["sheets"]) if spec["sheets"] else "(none currently)"
        lines.append(f"| {group} | {spec['hex']} | {sheets} |")
    lines.append("")
    for group, spec in payload["excel"]["tab_colours"].items():
        if spec.get("note"):
            lines.append(f"Note, {group}: {spec['note']}")
    lines.append("")
    lines.append("## Header bar spec (every visible tab, and dashboard pages)")
    lines.append("")
    hb = payload["excel"]["header_bar"]
    lines.append(f"Content: `{hb['content']}`. Fill {hb['fill']}, font colour {hb['font_color']}, "
                  f"teal underline accent {hb['accent_underline']}, font {hb['font']}.")
    lines.append("")
    lines.append("## Metric cell style (Excel)")
    lines.append("")
    mc = payload["excel"]["metric_cell"]
    lines.append(f"Fill {mc['fill']}, border {mc['border']}, label text {mc['label_text']}, value text {mc['value_text']}.")
    lines.append("")
    lines.append("## Dashboard CSS vars")
    lines.append("")
    lines.append("D-UX4 (resolved): the dashboard's current mockup-derived palette is replaced outright, not merged.")
    lines.append("")
    lines.append("Current values being replaced (`dashboard/app/globals.css`):")
    lines.append("")
    for k, v in payload["dashboard_css_vars"]["_replaces_outright"].items():
        lines.append(f"- `{k}`: `{v}`")
    lines.append("")
    lines.append("New values:")
    lines.append("")
    for k, v in payload["dashboard_css_vars"].items():
        if k.startswith("_") or k == "font_family":
            continue
        lines.append(f"- `{k}`: `{v}`")
    lines.append("")
    lines.append(f"Font family: {', '.join(payload['dashboard_css_vars']['font_family'])}.")
    lines.append("")
    status = payload["dashboard_css_vars"]["_status_colours_unchanged"]
    lines.append(f"Status colours left unchanged: `--color-fired`: `{status['--color-fired']}`, "
                  f"`--color-closed`: `{status['--color-closed']}`. {status['note']}")
    lines.append("")
    lines.append("## Matplotlib / chart palette order")
    lines.append("")
    lines.append("Series order (teal, slate, amber, then tints): " + ", ".join(payload["matplotlib_palette_order"]))
    lines.append("")
    lines.append("## Quarto / report styling")
    lines.append("")
    lines.append(payload["quarto_scss"]["recommendation"])
    lines.append("")
    lines.append(payload["quarto_scss"]["note"])
    lines.append("")
    return "\n".join(lines)

def main():
    payload = build_payload()
    DOCS_DIR.mkdir(exist_ok=True)
    json_path = DOCS_DIR / "design_tokens.json"
    md_path = DOCS_DIR / "design_tokens.md"
    json_text = json.dumps(payload, indent=2)
    json.loads(json_text)  # round-trip check per T0 gate
    json_path.write_text(json_text + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")

if __name__ == "__main__":
    main()
