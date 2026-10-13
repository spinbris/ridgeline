"""The product's identity, declared once (RIDGELINE-01; SPEC R-11, R-13).

The name and the maker are rulings; the tagline's wording is the Director's to approve. Every
rendered surface that names the product - the deliverable's front page, its HTML title, the Word
core title - reads it from here, so a change is one edit.

The tagline must not use "outturn" (R-12): the published figure is the event-risk contingency.
"""
from __future__ import annotations

PRODUCT_NAME = "Ridgeline"
MAKER = "CBL Analytics"
TAGLINE = f"{PRODUCT_NAME}: cost and schedule risk for capital projects, from bid to handover"

#: The front page's product line: the tagline, then who makes it.
PRODUCT_LINE = f"{TAGLINE}. A {MAKER} product."

#: Appended to a document's title so the product is named beside the project, never in its place.
TITLE_SUFFIX = f" - {PRODUCT_NAME}"
