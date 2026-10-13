"""RS-D-5 (D-17, S-F F-2): one mode-mix formatter, in ``src/sra``; ``final`` imports it;
an unknown Mode raises rather than rendering ``?`` on one surface and nothing on another.

Written red-first: on the pre-RS-D-5 tree ``src.sra.mode_mix`` does not exist.
"""
from __future__ import annotations

import pytest

from src.sra import mode_mix, sra_simulation
from src.final import executive_summary


def test_final_imports_the_sra_formatter():
    assert executive_summary.format_mode_mix is mode_mix.format_mode_mix
    assert executive_summary.count_modes is mode_mix.count_modes
    assert not hasattr(sra_simulation, "_mode_mix_summary")


def test_dict_and_list_inputs_give_one_label():
    modes = {"WT-001": "Series", "WT-002": "Hybrid", "WT-003": "Parallel", "WT-004": "Series"}
    assert mode_mix.format_mode_mix(modes) == "2S/1H/1P"
    assert mode_mix.format_mode_mix(list(modes.values())) == "2S/1H/1P"
    assert mode_mix.format_mode_mix({}) == "(none)"
    assert mode_mix.format_mode_mix([]) == "(none)"


def test_case_of_a_known_mode_is_tolerated():
    assert mode_mix.format_mode_mix(["series", " HYBRID ", "Parallel"]) == "1S/1H/1P"


@pytest.mark.parametrize("bad", [{"WT-009": "Foo"}, ["Series", "Modee"], {"WT-009": ""}, [None]])
def test_unknown_mode_raises_by_name(bad):
    with pytest.raises(ValueError) as exc:
        mode_mix.format_mode_mix(bad)
    msg = str(exc.value)
    assert "Mode" in msg and ("Foo" in msg or "Modee" in msg or "''" in msg or "None" in msg)
    if isinstance(bad, dict):
        assert "WT-009" in msg


def test_count_modes_has_no_other_bucket():
    counts = mode_mix.count_modes({"a": "Series", "b": "Hybrid", "c": "Parallel", "d": "Series"})
    assert counts == {"Series": 2, "Hybrid": 1, "Parallel": 1}
