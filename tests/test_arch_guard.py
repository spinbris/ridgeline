"""ARM64ULP-01: the x86-64-only guard skips on arm64, runs on x86-64, and sits on both checks."""
from __future__ import annotations

import pytest

from tests.arch_guard import is_x86_64, same_value

import tests.test_qraxl01_0_bit_identity_10k as bit10k
import tests.test_qraxl01_step4_layer1 as step4


@pytest.mark.parametrize("machine, expected", [
    ("AMD64", True), ("x86_64", True), ("arm64", False), ("aarch64", False), ("ARM64", False),
])
def test_is_x86_64(machine, expected):
    assert is_x86_64(machine) is expected


@pytest.mark.parametrize("test", [
    step4.test_owner_view_seed42_pinned_100k,
    bit10k.test_wind_showcase_bit_identity_10k,
], ids=lambda t: t.__name__)
def test_the_two_exact_sample_checks_carry_the_guard(test):
    reasons = [m.kwargs.get("reason", "") for m in getattr(test, "pytestmark", []) if m.name == "skipif"]
    assert any("ARM64ULP-01" in r for r in reasons), f"{test.__name__} is not guarded x86-64-only"


#: The Mac's wind golden mean against the blessed one, 12/10/2026: one ULP apart.
_BLESSED, _MAC = float.fromhex("0x1.4ecea4ea32efbp+22"), float.fromhex("0x1.4ecea4ea32efcp+22")


@pytest.mark.parametrize("machine", ["AMD64", "x86_64"])
def test_x86_64_stays_exact(machine):
    """XPLATTOL-01: where the goldens are blessed, one ULP is still a moved number."""
    assert same_value(_BLESSED, _BLESSED, machine)
    assert not same_value(_MAC, _BLESSED, machine)


@pytest.mark.parametrize("machine", ["arm64", "aarch64"])
def test_another_architecture_allows_one_part_in_a_billion(machine):
    assert same_value(_MAC, _BLESSED, machine)
    assert same_value([_MAC, 1.0], [_BLESSED, 1.0], machine)
    # A real change, one cent on $5.5M (about 2e-9 relative), is still red.
    assert not same_value(_BLESSED + 0.01, _BLESSED, machine)
    assert not same_value([_BLESSED + 0.01], [_BLESSED], machine)
    assert not same_value([_BLESSED], [_BLESSED, 1.0], machine)


def test_the_input_check_runs_on_every_architecture():
    """EXEMPTKEY-01: the input-hash half was split out of the guarded test so arm64 still runs it."""
    marks = getattr(bit10k.test_wind_showcase_inputs_unchanged_10k, "pytestmark", [])
    assert not [m for m in marks if m.name == "skipif"], "the input check has been guarded x86-64-only"
