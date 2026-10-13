"""RIDGELINE-01 P7: the app's product name is the deliverable's, and the chrome carries it.

The dashboard is TypeScript, so its product strings are a second copy of ``src/final/product.py``.
This test is what stops the two drifting apart: the tagline is the Director's to approve at H, and
an approved wording that reached one surface only would be the failure it exists to catch.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.final.product import MAKER, PRODUCT_LINE, PRODUCT_NAME, TAGLINE

REPO = Path(__file__).resolve().parents[1]
PRODUCT_TS = REPO / "dashboard" / "lib" / "product.ts"
CHROME = ("dashboard/app/layout.tsx", "dashboard/components/AppHeader.tsx",
          "dashboard/components/AppFooter.tsx")


def ts_const(source: str, name: str) -> str:
    """The value of ``export const NAME = "..."``, joined across a line break."""
    m = re.search(rf'export const {name}\s*=\s*"([^"]*)"', source, re.S)
    assert m, f"{name} is not declared as a string literal in product.ts"
    return m.group(1)


def ts_template(source: str, name: str, values: dict[str, str]) -> str:
    """``export const NAME = `...${X}...`;`` with each ``${X}`` replaced from ``values``."""
    m = re.search(rf"export const {name}\s*=\s*`([^`]*)`", source)
    assert m, f"{name} is not declared as a template literal in product.ts"
    return re.sub(r"\$\{(\w+)\}", lambda g: values[g.group(1)], m.group(1))


def test_the_app_and_the_deliverable_carry_one_product_name_and_tagline():
    source = PRODUCT_TS.read_text(encoding="utf-8")
    assert ts_const(source, "PRODUCT_NAME") == PRODUCT_NAME
    assert ts_const(source, "TAGLINE") == TAGLINE
    # Round 1, W6 (Director): the footer's brand line, maker included.
    assert ts_const(source, "MAKER") == MAKER
    line = ts_template(source, "PRODUCT_LINE", {"TAGLINE": TAGLINE, "MAKER": MAKER})
    assert line == PRODUCT_LINE


def test_the_chrome_reads_the_product_and_no_longer_says_qsra_dashboard():
    for rel in CHROME:
        source = (REPO / rel).read_text(encoding="utf-8")
        assert 'from "@/lib/product"' in source, f"{rel} does not read the product's name"
        assert not re.search(r'=\s*"QSRA Dashboard"', source), f"{rel} still defaults to QSRA Dashboard"
        assert "Monthly QSRA Dashboard" not in source, rel


def test_the_check_reds_on_a_drifted_tagline():
    drifted = 'export const TAGLINE =\n  "Ridgeline: schedule risk for capital projects";\n'
    assert ts_const(drifted, "TAGLINE") != TAGLINE


def test_the_check_reds_on_a_drifted_maker_or_product_line():
    assert ts_const('export const MAKER = "CBL";', "MAKER") != MAKER
    drifted = "export const PRODUCT_LINE = `${TAGLINE}, by ${MAKER}.`;"
    assert ts_template(drifted, "PRODUCT_LINE", {"TAGLINE": TAGLINE, "MAKER": MAKER}) != PRODUCT_LINE


def footer_is_mounted(layout: str) -> bool:
    """The layout imports AppFooter and renders it (round 3, N2): the brand line reaches a page
    only through this mount, and a vitest on the component alone cannot see it removed."""
    return ('import { AppFooter } from "@/components/AppFooter";' in layout
            and re.search(r"<AppFooter\s*/>", layout) is not None)


def test_the_layout_mounts_the_footer_that_carries_the_brand_line():
    layout = (REPO / "dashboard" / "app" / "layout.tsx").read_text(encoding="utf-8")
    assert footer_is_mounted(layout), "layout.tsx no longer mounts <AppFooter />"


def test_the_mount_check_reds_when_the_mount_is_removed():
    layout = (REPO / "dashboard" / "app" / "layout.tsx").read_text(encoding="utf-8")
    assert not footer_is_mounted(layout.replace("<AppFooter />", ""))
