"""RIDGELINE-01 P3 and P4: the deliverable names the product, the maker and the project's public
name, and its provenance block shows no code name, local path or raw digest method.

HTMLPROV-01: Cell 2 printed the binding key, Cell 7 printed the analyst's full paths and
``git_blob_oid``, and nothing pinned either cell. The cells are executed here against a stand-in
run, so what is checked is what the notebook renders, not what a helper would return.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.final.product import MAKER, PRODUCT_LINE, PRODUCT_NAME, TAGLINE
from src.sra.cpm.bindings import get_binding, project_display_name

REPO = Path(__file__).resolve().parents[1]
NOTEBOOK = REPO / "final_runner.ipynb"
SHIPPED = sorted(p.stem for p in (REPO / "src" / "sra" / "cpm" / "bindings").glob("*.py")
                 if p.stem not in ("__init__", "registry"))

#: Any path separator (gate 3 round 1, N3): a basename carries none, whatever machine made it.
SEPARATOR = re.compile(r"[\\/]")
RAW_METHODS = ("git_blob_oid", "sha256_bytes")


# --- the one declaration ------------------------------------------------------------------

@pytest.mark.parametrize("name", SHIPPED)
def test_the_app_and_the_deliverable_read_one_name_per_project(name, monkeypatch):
    """R-1 (PM ruling): the AM period JSON's name and the deliverable's are the same declaration."""
    from src.am.project_binding import resolve_project_inputs
    from src.final import deliverable

    monkeypatch.setenv("QRA_PROJECT", name)
    binding = get_binding(name)
    app_name = resolve_project_inputs(name).display_name

    monkeypatch.setattr(deliverable, "assert_ready", lambda env: [])
    inputs = deliverable.resolve_inputs(
        {"QRA_PROJECT": name, "REGISTER_FILE": "r.xlsx", "P6_FILE": "s.xer", "STRAWMAN_FILE": "r.xlsx"})

    assert app_name == inputs.project_public_name == project_display_name(binding)
    assert app_name != name, f"{name}: the public name is the binding key"
    assert binding.narrative("report_cover_title").startswith(app_name), (
        f"{name}: the cover names the project differently from the app")


def test_the_wind_showcase_is_tropic_ridge_and_road_keeps_its_cover_name():
    assert project_display_name(get_binding("synthetic_wind")) == "Tropic Ridge Wind Farm"
    assert project_display_name(get_binding("synthetic_road")) == "Kestrel Highway Upgrade"
    wind = get_binding("synthetic_wind")
    for key in ("report_cover_title", "report_header_title", "report_core_title"):
        assert wind.narrative(key).startswith("Tropic Ridge Wind Farm"), key
        assert "Synthetic" not in wind.narrative(key), key


def test_a_binding_without_the_key_falls_back_to_its_project_name_not_its_key():
    from src.sra.cpm.bindings import ProjectBinding

    bare = get_binding("synthetic_road")
    probe = ProjectBinding(**{**{f: getattr(bare, f) for f in bare.__dataclass_fields__},
                              "name": "probe_key", "narrative_templates": {}})
    assert project_display_name(probe) == bare.project_name != "probe_key"


# --- the rendered cells -------------------------------------------------------------------

def _cell(cell_id: str) -> str:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return next("".join(c["source"]) for c in nb["cells"] if c.get("id") == cell_id)


def _stand_in_run(binding_name: str = "synthetic_wind") -> SimpleNamespace:
    binding = get_binding(binding_name)
    inputs = SimpleNamespace(
        project=binding_name,
        project_display_name=binding.narrative("report_cover_title"),
        project_public_name=project_display_name(binding),
        project_note=binding.narrative("project_note"),
    )
    provenance = {
        "run_date": "2026-09-29",
        "params": {"iterations": 1000, "seed": 42, "day_rate": 85000.0},
        "engine_sha": "0123456789abcdef0123456789abcdef01234567",
        "engine_tree_dirty": False,
        "input_sha256": {
            "register": {"method": "git_blob_oid", "value": "c7de22c1adb99712e884aaaa"},
            "xer": {"method": "sha256_bytes", "value": "5cbed8f12994c6f82b1cbbbb"},
        },
    }
    artefacts = [
        # A drive-letter path that is not a home directory: the client gate refuses those in
        # committed text, and the check here is on the drive letter, which this still carries.
        Path(r"D:\work\outturn\outputs\executive_summary_2026-09-29.docx"),
        # The run folder and its manifest, as manifest_path builds them. Neither exists on disk:
        # the page must be the same wherever, and whenever, it is rendered (round 1, W1).
        "/home/analyst/outturn/outputs/runs/2026-09-29_synthetic_wind",
        "/home/analyst/outturn/outputs/runs/2026-09-29_synthetic_wind/provenance.json",
    ]
    return SimpleNamespace(inputs=inputs, provenance=provenance, artefacts=artefacts)


def render_cell(source: str, run: SimpleNamespace) -> str:
    """Execute one notebook cell with ``display`` captured, and return what it rendered."""
    shown: list[str] = []
    namespace = {"run": run, "display": lambda obj: shown.append(str(obj)), "Markdown": str}
    exec(compile(source, "<cell>", "exec"), namespace)
    return "\n".join(shown)


def test_cell_2_names_the_project_the_product_and_the_maker_not_the_binding_key():
    run = _stand_in_run()
    page = render_cell(_cell("426fdffc909f"), run)
    assert "synthetic_wind" not in page, "Cell 2 prints the binding key"
    assert "**Project:** Tropic Ridge Wind Farm" in page
    assert PRODUCT_LINE in page and PRODUCT_NAME in page and MAKER in page


def test_the_front_page_says_tropic_ridge_is_synthetic():
    """'Synthetic' left the title, so the front page must say it, on both surfaces."""
    note = get_binding("synthetic_wind").narrative("project_note")
    assert "synthetic project" in note.lower(), "the wind binding no longer says it is synthetic"
    assert note in render_cell(_cell("426fdffc909f"), _stand_in_run())


def test_cell_7_shows_basenames_and_methods_in_words():
    run = _stand_in_run()
    assert not any(Path(str(p)).exists() for p in run.artefacts), "the stand-in touched the disk"
    page = render_cell(_cell("0ee325d42f33"), run)
    assert "synthetic_wind" not in page, "Cell 7 names the binding key"
    assert "the run folder" in page
    assert not SEPARATOR.search(page), f"Cell 7 prints a path: {page}"
    for raw in RAW_METHODS:
        assert raw not in page, f"Cell 7 prints the raw method {raw}"
    assert "executive_summary_2026-09-29.docx" in page and "provenance.json" in page
    assert "git blob id" in page


def test_every_digest_method_the_engine_records_has_words():
    """``src.git_identity.input_digest`` records exactly these; a new one must be worded."""
    from src.final.run_identity import DIGEST_METHOD_WORDS

    source = (REPO / "src" / "git_identity.py").read_text(encoding="utf-8")
    recorded = set(re.findall(r'"method": "([a-z0-9_]+)"', source))
    assert recorded == set(DIGEST_METHOD_WORDS), recorded ^ set(DIGEST_METHOD_WORDS)


def test_the_checks_red_on_the_cells_they_replaced():
    """The pre-RIDGELINE-01 Cell 2 and Cell 7, verbatim in substance."""
    old_2 = ('display(Markdown(f"**Project binding:** `{run.inputs.project}`"))\n')
    old_7 = ('display(Markdown("\\n".join(f"- `{p}`" for p in run.artefacts)))\n'
             'display(Markdown("\\n".join(f"- `{n}`: `{d[\'method\']}`" '
             'for n, d in run.provenance["input_sha256"].items())))\n')
    run = _stand_in_run()
    assert "synthetic_wind" in render_cell(old_2, run)
    page_7 = render_cell(old_7, run)
    assert SEPARATOR.search(page_7) and "git_blob_oid" in page_7


# --- the Word front page ------------------------------------------------------------------

def test_the_word_title_page_and_core_title_carry_the_product(monkeypatch):
    from docx import Document

    from src.final import word_generator

    monkeypatch.setenv("QRA_PROJECT", "synthetic_wind")
    doc = Document()
    word_generator._add_title_page(doc, {}, {"run_date": "2026-09-29"})
    word_generator._set_doc_core_and_custom_properties(doc, "prod", "0.1.0", "PASS")
    paragraphs = [p.text for p in doc.paragraphs]

    assert paragraphs[0].startswith("Tropic Ridge Wind Farm - Integrated Cost and Schedule Risk")
    assert PRODUCT_LINE in paragraphs
    assert any("is a synthetic project" in p for p in paragraphs), "the Word front page lost it"
    assert doc.core_properties.title.endswith(f" - {PRODUCT_NAME}")
    assert doc.core_properties.title.startswith("Tropic Ridge Wind Farm")


def test_the_tagline_names_the_product_and_not_an_outturn():
    assert TAGLINE.startswith(PRODUCT_NAME) and "risk" in TAGLINE
    assert "outturn" not in TAGLINE.lower()
