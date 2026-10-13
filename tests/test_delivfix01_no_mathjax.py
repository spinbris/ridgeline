"""DELIVFIX-01 / FW-21: no ``$`` in the report is typeset as mathematics.

nbconvert's lab template loads MathJax with ``$...$`` as inline maths, so the executive summary's
"equivalent to $5.02M at $48,000 per day" rendered the text between the two dollar signs as an
equation. The report carries no mathematics, so ``report_html.j2`` removes MathJax altogether -
which covers every output kind (Markdown, DataFrame HTML, ``HTML()``), where escaping ``$`` in the
notebook would have covered Markdown only.

The conversion here is in-process, with the template ``RUN_FINAL.bat`` itself names: a template
that exists but is not passed would fix nothing, so the first test reads the runner.
"""
import re
from pathlib import Path

import nbformat
import pytest
from nbconvert import HTMLExporter

REPO = Path(__file__).resolve().parents[1]
SENTENCE = "equivalent to $5.02M at $48,000 per day"


def template_passed_by_the_runner() -> Path:
    text = (REPO / "RUN_FINAL.bat").read_text(encoding="utf-8")
    m = re.search(r"^\s*--template-file\s+(\S+)", text, re.MULTILINE)
    assert m, "RUN_FINAL.bat converts the report without the no-MathJax template"
    return REPO / m.group(1)


def _render(template_file) -> str:
    nb = nbformat.v4.new_notebook()
    nb.cells.append(nbformat.v4.new_markdown_cell(SENTENCE))
    exporter = HTMLExporter(template_file=str(template_file)) if template_file else HTMLExporter()
    body, _ = exporter.from_notebook_node(nb)
    return body


def test_the_runner_passes_a_template_that_exists():
    assert template_passed_by_the_runner().is_file()


def test_the_report_loads_no_mathjax():
    html = _render(template_passed_by_the_runner())
    assert "mathjax" not in html.lower(), "MathJax is still loaded, so $...$ is typeset as maths"
    assert "inlineMath" not in html


def test_the_sentence_survives_as_text():
    html = _render(template_passed_by_the_runner())
    assert "$5.02M at $48,000" in html


@pytest.mark.parametrize("template_file", [None], ids=["nbconvert_default"])
def test_red_the_default_export_does_load_mathjax(template_file):
    """The check can fail: without the template, the same notebook loads MathJax."""
    html = _render(template_file)
    assert "inlineMath" in html
