"""DELIVFIX-01 / FW-27, R-6: the report is titled for what it computes.

The deliverable carries the cost QRA and the SRA together and headlines the integrated contingency -
*"integrated cost plus schedule"* - yet was titled *"Schedule Risk Analysis"*, one arm of it (the
Director, 22/09/2026: "the docx etc is more complete with qra/sra"). R-6 retitles it to what the
report's own methodology cites, AACE RP 113R-21 *"Integrated Cost and Schedule Risk Analysis"*.

There are THREE title keys per project, not one - the cover (which is also the HTML heading, via
``deliverable.py``'s ``project_display_name``), the page header, and the Word document-properties
title - with a fallback for each in ``word_generator.py``. And the browser tab read ``final_runner``,
the notebook's filename, because the notebook carried no ``title``.

Live, because the two tests that pinned the old title (``test_sr9_v32_d6_doc_properties``,
``test_sr9_v32_dual_mode_integration``) skipped on every run; SNAPSHOTCUT-01 retired both.
"""
import json
from pathlib import Path

import pytest

from src.sra.cpm.bindings.registry import get_binding

REPO = Path(__file__).resolve().parents[1]
PRODUCT = "Integrated Cost and Schedule Risk Analysis"
TITLE_KEYS = ("report_cover_title", "report_header_title", "report_core_title")

#: The SHIPPED projects: a project module in src/sra/cpm/bindings/ ("Every project is a
#: binding"). Not ``list_bindings()`` - at collection time that held a test fixture's binding
#: (``fixture_r_prefix``) and not the shipped two, which register when first resolved. Derived from
#: the directory, so a new project is covered without anyone editing this list.
SHIPPED = sorted(p.stem for p in (REPO / "src" / "sra" / "cpm" / "bindings").glob("*.py")
                 if p.stem not in ("__init__", "registry"))


@pytest.mark.parametrize("name", SHIPPED)
def test_every_shipped_projects_titles_name_the_integrated_analysis(name):
    binding = get_binding(name)
    for key in TITLE_KEYS:
        title = binding.narrative(key)
        assert PRODUCT in title, f"{name}.{key} = {title!r} names one arm, not the integrated analysis"


def test_the_shipped_projects_are_the_ones_checked():
    assert SHIPPED == ["synthetic_road", "synthetic_wind"], f"the shipped projects are now {SHIPPED}"


def test_the_browser_tab_is_the_product_not_a_source_file():
    """RIDGELINE-01 (R-5): the tab names the analysis, then the product (``src/final/product.py``).
    The notebook's metadata is a literal nbconvert reads, so this pin is what ties it to that file."""
    from src.final.product import TITLE_SUFFIX

    nb = json.loads((REPO / "final_runner.ipynb").read_text(encoding="utf-8"))
    assert nb["metadata"].get("title") == PRODUCT + TITLE_SUFFIX, (
        "the HTML <title> falls back to the notebook's filename, 'final_runner', without this")


def test_the_word_fallbacks_name_the_integrated_analysis():
    """A project that supplies no title of its own must not fall back to one arm."""
    src = (REPO / "src" / "final" / "word_generator.py").read_text(encoding="utf-8")
    for key in TITLE_KEYS:
        i = src.index(f'_project_title("{key}"') if f'_project_title("{key}"' in src else src.index(
            f"_project_title('{key}'")
        assert PRODUCT in src[i:i + 140], f"the {key} fallback does not name the integrated analysis"
