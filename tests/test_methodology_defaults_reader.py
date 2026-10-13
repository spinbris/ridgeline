"""SR19 §6.1 unit tests for the methodology-defaults reader.

Covers happy path against the live RefProject register, missing-range cases, lock-file
detection, type validation, ChainRiskIDs sub-dataclass shape, the
SR19-D6 set-level assertion semantics, sentinel-cell value reads (the
pre-flight assertions on the sentinel anchors were to follow once SR19
§6.6 landed; no such test module exists here or in either archive),
error-message format
includes consumer module + workbook path, and the
build_test_methodology_defaults factory.
"""
from __future__ import annotations
from tests.conftest import TEST_CALIBRATION_TOLERANCES

import json

import openpyxl
import pytest

from src.sra.methodology_defaults_reader import (
    MethodologyDefaults,
    MethodologyDefaultsError,
    build_test_methodology_defaults,
    read_methodology_defaults,
)


from tests._fixture_values import FIXTURE_DAY_RATE
#: Nine tests in this module read the live client register. It is gitignored, so on a
#: fresh clone or in CI they skip naming the input and the row rather than reporting a
#: MethodologyDefaultsError that reads like an engine fault (GOLDCOLL-01).
# ---------------------------------------------------------------------------
# Happy path against the live RefProject register
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_missing_workbook_raises_with_consumer_module_in_message(tmp_path):
    bad_path = tmp_path / "does_not_exist.xlsx"
    with pytest.raises(MethodologyDefaultsError) as exc_info:
        read_methodology_defaults(bad_path, caller_module="src/sra/cpm/bindings/refproject.py")
    msg = str(exc_info.value)
    assert "src/sra/cpm/bindings/refproject.py" in msg
    assert str(bad_path) in msg


def test_lock_file_present_raises(tmp_path):
    """If Excel has the register open, the lock-file pattern ~$file.xlsx is
    present. Reader refuses to proceed because openpyxl may return
    stale cached values."""
    fake_xlsx = tmp_path / "register.xlsx"
    # Make a real minimal xlsx so the existence check passes
    wb = openpyxl.Workbook()
    wb.save(fake_xlsx)
    lock_path = tmp_path / "~$register.xlsx"
    lock_path.write_bytes(b"fake lock")
    with pytest.raises(MethodologyDefaultsError) as exc_info:
        read_methodology_defaults(fake_xlsx, caller_module="test_caller")
    msg = str(exc_info.value)
    assert "locked by Excel" in msg
    assert "test_caller" in msg


def test_missing_named_range_composite_error(tmp_path):
    """A workbook without ANY of the expected named ranges produces a
    composite error listing all missing ranges, not first-fail."""
    fake = tmp_path / "empty.xlsx"
    openpyxl.Workbook().save(fake)
    with pytest.raises(MethodologyDefaultsError) as exc_info:
        read_methodology_defaults(fake, caller_module="src/foo.py")
    msg = str(exc_info.value)
    # Composite: multiple issues in one error per SR19-D1
    assert "issue(s):" in msg
    assert msg.count(" - ") >= 5  # at least several bullet points
    # Each missing range should be named explicitly
    assert "mc_cg_coeffs" in msg
    assert "cfg_chain_risk_ids" in msg
    assert "cfg_expected_dual_coded_risk_ids" in msg
    # And the consumer + workbook path
    assert "src/foo.py" in msg
    assert str(fake) in msg


def test_dataclass_post_init_enforces_count_equals_set_size():
    """SR19-D6: the cross-field invariant catches an edit to the RefProject register that updated
    one of the two cells without updating the other."""
    # Direct construction with mismatched count/set
    with pytest.raises(MethodologyDefaultsError) as exc_info:
        build_test_methodology_defaults(
            expected_dual_coded_count=7,  # disagrees with the 8-element default set
        )
    msg = str(exc_info.value)
    assert "invariant violated" in msg
    assert "count=7" in msg
    assert "len(expected_dual_coded_risk_ids)=8" in msg


# ---------------------------------------------------------------------------
# build_test_methodology_defaults factory
# ---------------------------------------------------------------------------


def test_build_test_factory_returns_valid_dataclass():
    md = build_test_methodology_defaults()
    assert isinstance(md, MethodologyDefaults)
    assert md.cg_coefficients["CG01"] == 0.6
    assert md.expected_dual_coded_count == 8


def test_build_test_factory_overrides_take_effect():
    md = build_test_methodology_defaults(
        mode_multipliers={"Series": 1.0, "Hybrid": 1.0, "Parallel": 1.0},
        default_injection_method="additive_pert_days",
    )
    assert md.mode_multipliers["Hybrid"] == 1.0
    assert md.default_injection_method == "additive_pert_days"
    # Untouched fields keep the default values
    assert md.cg_coefficients["CG01"] == 0.6


# ---------------------------------------------------------------------------
# §6.2 type-level lock: IntegratedConfig requires methodology_defaults
# ---------------------------------------------------------------------------


def test_integrated_config_construction_requires_methodology_defaults(tmp_path):
    """SR19 §6.2 step 6 type-level lock: constructing IntegratedConfig
    without the methodology_defaults kwarg raises TypeError. The required-
    field (kw_only=True, no default) posture means no consumer can hit a
    None branch — the None case is structurally unreachable."""
    from src.integrated.integrated_simulation import IntegratedConfig
    # Missing methodology_defaults entirely
    with pytest.raises(TypeError) as exc_info:
        IntegratedConfig(
            register_path=tmp_path / "r.xlsx",
            p6_path=tmp_path / "p.xlsx",
            strawman_path=tmp_path / "s.xlsx",
            day_rate=FIXTURE_DAY_RATE,
        **TEST_CALIBRATION_TOLERANCES)
    msg = str(exc_info.value)
    # TypeError should name the missing kwarg
    assert "methodology_defaults" in msg, (
        f"TypeError message must name the missing field; got: {msg}"
    )


# ---------------------------------------------------------------------------
# §6.6 SR19-D5 sentinel lock-test (v3 brief commitment)
# ---------------------------------------------------------------------------


def test_sr19_d5_sentinels_are_module_top_constants():
    """SR19-D5 single-grep-target rule: the sentinels must be defined at
    module top in src/sra/_pre_flight.py (not buried inside a function
    body). The 'one grep to find them, one edit to update them'
    discipline only works if they're at module scope."""
    import src.sra._pre_flight as preflight_module
    import inspect

    source = inspect.getsource(preflight_module)
    lines = source.split("\n")
    # Find the line each sentinel is defined on; assert no leading whitespace
    # (i.e., module-top, not function-body)
    cg01_lines = [
        i for i, line in enumerate(lines)
        if line.startswith("SR19_SENTINEL_CG01")
    ]
    float_lines = [
        i for i, line in enumerate(lines)
        if line.startswith("SR19_SENTINEL_FLOAT_THRESHOLD_HOURS")
    ]
    assert cg01_lines, (
        "SR19_SENTINEL_CG01 not found at module top. Single-grep-target "
        "update rule (SR19-D5) requires definition at column 0."
    )
    assert float_lines, (
        "SR19_SENTINEL_FLOAT_THRESHOLD_HOURS not found at module top. "
        "Single-grep-target update rule (SR19-D5) requires definition "
        "at column 0."
    )
