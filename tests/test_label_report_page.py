"""REPORTPAGE-01: the post-render label step refuses a page that is not fit to publish.

`scripts/label_report_page.py` turns the nbconvert HTML into the page served at /report/. On
14/10/2026 the page it wrote carried seven private-term hits, every one inside the base64 of an
embedded chart, by chance; the client gate went red. The step now re-encodes such a chart
losslessly, and refuses any page that still trips a shipped-file check.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("label_report_page",
                                               REPO / "scripts" / "label_report_page.py")
lrp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lrp)


def _png(level: int = 6) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (40, 30), (31, 78, 121, 255)).save(buf, format="PNG", compress_level=level)
    return buf.getvalue()


def _page(png: bytes) -> str:
    return ('<html><head><title>x</title></head><body><img src="data:image/png;base64,'
            + base64.b64encode(png).decode() + '"></body></html>')


def test_an_embedded_chart_that_trips_a_check_is_re_encoded_losslessly():
    first = _png()
    tripping_b64 = base64.b64encode(first)
    trips = lambda name, blob: ["tripped"] if tripping_b64 in blob else []
    out = lrp.clear_embedded_images(_page(first), trips)
    assert trips("index.html", out.encode()) == []
    b64 = out.split("base64,")[1].split('"')[0]
    with Image.open(io.BytesIO(base64.b64decode(b64))) as im:
        assert im.tobytes() == Image.new("RGBA", (40, 30), (31, 78, 121, 255)).tobytes()


def test_a_clear_page_is_left_byte_for_byte():
    page = _page(_png())
    assert lrp.clear_embedded_images(page, lambda name, blob: []) == page


def test_a_page_that_still_trips_a_check_is_refused():
    with pytest.raises(lrp.Refused, match="trips a shipped-file check"):
        lrp.refuse_unless_clear("<p>anything</p>", lambda name, blob: ["term[0]"])
    with pytest.raises(lrp.Refused, match="every lossless compression level"):
        lrp.clear_embedded_images(_page(_png()), lambda name, blob: ["always"])


def test_the_step_refuses_without_the_term_list(monkeypatch, tmp_path, capsys):
    html = tmp_path / "in.html"
    html.write_text(_page(_png()), encoding="utf-8")
    prov = tmp_path / "provenance.json"
    prov.write_text(json.dumps({
        "project": "synthetic_wind", "run_date": "2026-10-14", "timestamp": "t",
        "engine_sha": "0" * 40, "engine_tree_dirty": False, "mode": "prod",
        "params": {"seed": 42, "iterations": 100_000}, "input_sha256": {},
        "cross_validation_all_pass": True}), encoding="utf-8")
    monkeypatch.setenv("CLIENT_GATE_TERMS", str(tmp_path / "absent.txt"))
    out = tmp_path / "out"
    assert lrp.main(["--html", str(html), "--provenance", str(prov), "--out-dir", str(out)]) == 1
    assert "term list is not here" in capsys.readouterr().out
    assert not out.exists()
