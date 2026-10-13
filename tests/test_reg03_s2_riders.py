"""REG03 S2 durability riders (2) Set_ContractVersion + (3) the Lite-API grep.

Rider (2): the scaffolder emits a Set_ContractVersion cell + named range carrying
the contract version; the Validate button and future readers compare against it.

Rider (3): a grep test over the xlwings shell AND the generated combined dist for
the Lite-forbidden tokens (used_range / .api / .copy()) - the step-6b defect class
that cannot be caught headless, caught at CI time. (The shell alone is also guarded
by tests/test_qraxl01_step6b_shell.py::test_shell_has_no_forbidden_lite_api; this
extends the guard to the generated distributable.)
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

from tools.register_scaffold import CONTRACT_VERSION, build_template

REPO = Path(__file__).resolve().parents[1]
SHELL = REPO / "src" / "tier1_xlwings_shell.py"

#: Lite-forbidden Sheet APIs (documented in the shell header). Each token contains
#: a char outside the base64 alphabet, so it cannot appear inside the dist's
#: base64 _MODULES blob - only in real code or the header doc block (stripped).
FORBIDDEN_TOKENS = (".used_range", ".api", ".copy()")


def _strip_forbidden_doc_block(text: str) -> str:
    """Remove the shell's own 'FORBIDDEN in Lite' documentation block (which names
    the tokens on purpose) so only LIVE code is scanned - mirrors the step-6b
    guard's split. Safe when the markers are absent (returns the text unchanged)."""
    if "FORBIDDEN in Lite" in text and "_GRID_NAMES: dict" in text:
        return text.split("FORBIDDEN in Lite")[0] + text.split("_GRID_NAMES: dict")[-1]
    return text


def test_set_contract_version_named_range_and_value(tmp_path):
    tmpl = build_template(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(tmpl)
    try:
        assert "Set_ContractVersion" in wb.defined_names
        dests = list(wb.defined_names["Set_ContractVersion"].destinations)
        assert dests == [("Settings", "$B$6")], dests
        assert wb["Settings"]["B6"].value == CONTRACT_VERSION
    finally:
        wb.close()


def test_no_forbidden_lite_api_in_shell():
    live = _strip_forbidden_doc_block(SHELL.read_text(encoding="utf-8"))
    for token in FORBIDDEN_TOKENS:
        assert token not in live, f"forbidden Lite API {token!r} in the shell"


def test_shell_exposes_all_button_scripts():
    """Every user action has a physical @script button in the xlwings Lite pane:
    the interactive run, the 100k run, and the contract validator."""
    src = SHELL.read_text(encoding="utf-8")
    for fn in ("run_simulation", "run_simulation_100k", "validate_contract"):
        assert f"def {fn}(" in src, f"missing button @script {fn}"
    assert src.count("@script") >= 3, "each button must be an @script"


def test_no_forbidden_lite_api_in_generated_dist(tmp_path):
    """Generate the combined distributable hermetically and grep it (the real
    pasteable artefact, incl. the appended verbatim shell)."""
    from tools.make_qra_xlwings import build

    dist = build(tmp_path / "qra_xlwings_combined.py")
    live = _strip_forbidden_doc_block(dist.read_text(encoding="utf-8"))
    for token in FORBIDDEN_TOKENS:
        assert token not in live, f"forbidden Lite API {token!r} in the generated dist"


# ---------------------------------------------------------------------------
# Rider (1) - the Validate button (headless validator; the @script is Excel-only)
# ---------------------------------------------------------------------------
from src.register_contract import (  # noqa: E402
    CONTRACT_VERSION, REQUIRED_NAMED_RANGES, check_contract,
)
from tools.register_scaffold import (  # noqa: E402
    CG_CODES, MODE_MULTIPLIERS_DEFAULT,
)

#: A well-formed Grid_Methodology grid (header + 13 CG + 3 mode rows).
_GOOD_METHODOLOGY = (
    [["CG code / Mode", "Coefficient / Multiplier"]]
    + [[code, 0.5] for code in CG_CODES]
    + [[mode, mult] for mode, mult in MODE_MULTIPLIERS_DEFAULT.items()]
)


def test_check_contract_passes_on_intact_contract():
    ok, msg = check_contract(REQUIRED_NAMED_RANGES, _GOOD_METHODOLOGY, CONTRACT_VERSION)
    assert ok is True
    assert "Contract OK" in msg and CONTRACT_VERSION in msg


def test_check_contract_fails_on_missing_named_range():
    present = set(REQUIRED_NAMED_RANGES) - {"Grid_Methodology"}
    ok, msg = check_contract(present, _GOOD_METHODOLOGY, CONTRACT_VERSION)
    assert ok is False
    assert "missing named ranges" in msg and "Grid_Methodology" in msg


def test_check_contract_fails_on_version_mismatch():
    ok, msg = check_contract(REQUIRED_NAMED_RANGES, _GOOD_METHODOLOGY, "0.9")
    assert ok is False
    assert "contract version" in msg and CONTRACT_VERSION in msg


def test_check_contract_fails_on_broken_methodology():
    broken = _GOOD_METHODOLOGY[:-1]  # drop the Parallel mode row
    ok, msg = check_contract(REQUIRED_NAMED_RANGES, broken, CONTRACT_VERSION)
    assert ok is False
    assert "missing mode rows" in msg and "Parallel" in msg


def test_scaffolded_template_passes_check_contract(tmp_path):
    """Integration: a freshly scaffolded template satisfies its own contract."""
    from src.tier1_headless import extract_grids_openpyxl

    tmpl = build_template(tmp_path / "t.xlsx")
    wb = openpyxl.load_workbook(tmpl)
    try:
        present = list(wb.defined_names)
        version = wb["Settings"]["B6"].value
    finally:
        wb.close()
    methodology = extract_grids_openpyxl(str(tmpl))["methodology"]
    ok, msg = check_contract(present, methodology, version)
    assert ok is True, msg
