"""REG-01 §12.2 lock: the no-silent-zero Mode guard FIRES.

EMV columns are builder-computed literals, so there is no live formula left
to error visibly on a bad Mode. The guarantee moves one layer up: the builder
ASSERTS on a blank/unrecognised Mode for a Time=Yes risk and FAILS the build.
This test watches it fail (a guard never seen to fire is worthless).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO / "scripts" / "build_synthetic_wind_fixture.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("_reg01_builder", BUILD_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BUILDER = _load_builder()


def test_assert_valid_mode_accepts_known_modes():
    for m in ("Series", "Hybrid", "Parallel"):
        assert BUILDER._assert_valid_mode("WT-001", m) == m


@pytest.mark.parametrize("bad", ["", "  ", "series", "Sereis", "None", None])
def test_assert_valid_mode_rejects_bad_modes(bad):
    with pytest.raises(ValueError, match="no-silent-zero"):
        BUILDER._assert_valid_mode("WT-001", bad)


def test_build_fails_on_time_yes_risk_with_blank_mode(tmp_path, monkeypatch):
    """Integration: a Time=Yes risk carrying a blank Mode fails the build."""
    # Corrupt ONE Time=Yes risk's Mode to blank; the build must refuse.
    good = BUILDER.WIND_RISKS
    corrupted = []
    hit = False
    for r in good:
        r = list(r)
        if r[13] == "Yes" and not hit:  # r[13] = Time flag, r[14] = Mode
            r[14] = ""  # blank Mode on a Time=Yes risk
            hit = True
        corrupted.append(tuple(r))
    assert hit, "fixture must contain at least one Time=Yes risk to corrupt"
    monkeypatch.setattr(BUILDER, "WIND_RISKS", corrupted)

    with pytest.raises(ValueError, match="no-silent-zero"):
        BUILDER.build_register(tmp_path / "bad_register.xlsx")


def test_build_succeeds_on_clean_modes(tmp_path):
    """Control: the real (clean) fixture builds without firing the guard."""
    out = tmp_path / "clean_register.xlsx"
    BUILDER.build_register(out)
    assert out.exists() and out.stat().st_size > 5000
