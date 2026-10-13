"""RIDGELINE-01 gate 3 round 2, WARN 1: one run takes one date.

``run_deliverable`` read the clock for the engine log's folder, again in ``compose`` (which names
the state-cache folder) and again in ``build_provenance`` (which names the manifest's folder). A
run crossing midnight wrote two run folders, and Cell 7, which names the run folder by its relation
to the manifest, then printed the other one's ``<date>_<binding key>``.

The clock here ticks a day on every read, so any second read shows. The engines, the composer's
body, the Word renderer, the Stage 3 emitter and the digests are stubbed; ``run_deliverable``,
``compose``, ``write_artefacts`` and ``build_provenance`` are the real ones, since they are where
the dates were read.

**Round 4 (gate 3 round 3, BLOCKER):** the composer stub returned ``run_date`` at the top level,
a shape the real ``compose_final_report_data`` never produces - it stores it only in
``appendix_audit_trail``. ``write_artefacts`` read the missing key, fell back to the clock on every
production run, and this test passed against the wrong artefact. The stub now places ``run_date``
where the real function's source places it, read from its AST, so the two cannot drift.
"""
from __future__ import annotations

import ast
import datetime as _dt
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

KEY = "probe_key"


def run_date_homes() -> set[str]:
    """Where ``compose_final_report_data`` puts ``run_date``: top-level keys of the dict it returns.

    ``"<top>"`` if the returned dict carries it directly. Read from the function's source, so the
    stub below mirrors the real shape rather than an assumed one.
    """
    from src.final import composer

    fn = ast.parse(inspect.getsource(composer.compose_final_report_data)).body[0]
    holders: set[str] = set()   # local names bound to a dict literal with a "run_date" key
    top: dict | None = None     # the `composed` literal
    homes: set[str] = set()
    for node in ast.walk(fn):
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        if target is None:
            continue
        if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant) \
                and target.slice.value == "run_date":
            homes.add("<top>")
        if isinstance(target, ast.Name) and isinstance(value, ast.Dict):
            keys = [k.value for k in value.keys if isinstance(k, ast.Constant)]
            if target.id == "composed":
                top = value
                if "run_date" in keys:
                    homes.add("<top>")
            elif "run_date" in keys:
                holders.add(target.id)
    assert top is not None, "compose_final_report_data no longer builds a `composed` literal"
    for k, v in zip(top.keys, top.values):
        if isinstance(k, ast.Constant) and isinstance(v, ast.Name) and v.id in holders:
            homes.add(k.value)
    return homes


def _real_shape(run_date: str, homes: set[str]) -> dict:
    composed = {"executive_summary": {"headline_stage3": {}},
                "appendix_audit_trail": {"engine_versions": {}}, "disclaimer_paragraphs": []}
    for home in homes:
        if home == "<top>":
            composed["run_date"] = run_date
        else:
            composed.setdefault(home, {})["run_date"] = run_date
    return composed


def test_the_stub_knows_where_the_real_composer_keeps_run_date():
    """Today: only the audit trail. If the composer ever moves it, the stub moves with it."""
    assert run_date_homes() == {"appendix_audit_trail"}


class _TickingDate(_dt.date):
    """``date.today()`` a day later on every call."""

    reads = 0

    @classmethod
    def today(cls):
        cls.reads += 1
        return _dt.date(2026, 9, 29) + _dt.timedelta(days=cls.reads - 1)


def _run(monkeypatch, tmp_path):
    import src.am._provenance as prov
    import src.am.run_period as run_period
    import src.final.composer as composer
    import src.final.deliverable as deliverable
    import src.final.stage3_composer as stage3_composer
    import src.final.state_cache as state_cache
    import src.final.word_generator as word_generator
    import src.sra.cpm.bindings as bindings

    homes = run_date_homes()  # read from the REAL composer, before it is stubbed below
    _TickingDate.reads = 0
    monkeypatch.setattr(deliverable, "date", _TickingDate)
    monkeypatch.setattr(deliverable, "assert_ready", lambda env: [])
    monkeypatch.setattr(bindings, "get_active_binding", lambda: SimpleNamespace(
        name=KEY, project_name="Probe", narrative=lambda key, default="": default))
    monkeypatch.setattr(deliverable, "run_engines", lambda inputs: MagicMock())
    monkeypatch.setattr(deliverable, "cross_validate", lambda i, e: {"all_pass": True})
    monkeypatch.setattr(composer, "compose_final_report_data",
                        lambda **kw: _real_shape(kw["run_date"], homes))

    def word(*, output_path, **_):
        Path(output_path).write_bytes(b"")
        return {"output_path": str(output_path)}

    def cache(payload, folder):
        Path(folder).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(word_generator, "generate_word_summary", word)
    monkeypatch.setattr(stage3_composer, "emit_stage3_standalone_artefacts",
                        lambda **_: (_ for _ in ()).throw(RuntimeError("not under test")))
    monkeypatch.setattr(state_cache, "write_state_cache", cache)
    monkeypatch.setattr(deliverable, "stage3_config_summary", lambda config: {"iterations": 1})
    monkeypatch.setattr(deliverable, "format_run_diagnostic", lambda **_: "")
    monkeypatch.setattr(run_period, "_input_digest", lambda p: {"method": "sha256_bytes", "value": "0"})
    monkeypatch.setattr(prov, "resolve_engine_sha", lambda: "0" * 40)
    monkeypatch.setattr(prov, "resolve_tree_dirty", lambda: False)

    return deliverable.run_deliverable(
        {"QRA_PROJECT": KEY, "REGISTER_FILE": "r.xlsx", "P6_FILE": "s.xer",
         "STRAWMAN_FILE": "r.xlsx"}, output_dir=tmp_path)


def test_a_run_writes_one_run_folder_whatever_the_clock_does(monkeypatch, tmp_path):
    run = _run(monkeypatch, tmp_path)
    folders = sorted(p.name for p in (tmp_path / "runs").iterdir())
    assert folders == [f"{run.provenance['run_date']}_{KEY}"], (
        f"one run, several run folders: {folders}")
    assert run.composed["appendix_audit_trail"]["run_date"] == run.provenance["run_date"]


def test_cell_7_names_no_binding_key_on_a_run_across_midnight(monkeypatch, tmp_path):
    from src.final.run_identity import artefacts_markdown

    run = _run(monkeypatch, tmp_path)
    assert KEY not in artefacts_markdown(run.artefacts), artefacts_markdown(run.artefacts)
