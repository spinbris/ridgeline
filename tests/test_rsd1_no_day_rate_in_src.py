"""RS-D-1 (D-13): ``src/`` names no day-rate constant, not even a neutral one.

The rate a run uses comes from the register (``day_rate_default``) and the engine refuses
when it is absent (DAYRATE-02). What survived in ``src/`` was a fixture value for tests that
construct ``SRAConfig`` directly, plus the reference project's derivation comment. Both move
out: the value to the test harness as ``FIXTURE_DAY_RATE``, the comment to nowhere.

Written red-first: on the pre-RS-D-1 tree the constant, its name and the comment are present.
"""
from __future__ import annotations

from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
OLD_NAME = "DEFAULT_" + "DAY_RATE"  # split so this file is not itself a hit


def test_src_does_not_name_the_old_constant():
    hits = sorted(
        str(p.relative_to(SRC.parent))
        for p in SRC.rglob("*.py")
        if OLD_NAME in p.read_text(encoding="utf-8", errors="ignore")
    )
    assert hits == [], f"{OLD_NAME} still named in src/: {hits}"


def test_sra_config_carries_no_rate_and_no_derivation():
    import src.sra.sra_config as cfg

    assert not hasattr(cfg, OLD_NAME)
    source = Path(cfg.__file__).read_text(encoding="utf-8")
    assert "day-rate derivation" not in source
    assert "weekly prelims" not in source


def test_fixture_rate_lives_in_the_harness():
    from tests.conftest import FIXTURE_DAY_RATE

    assert isinstance(FIXTURE_DAY_RATE, float) and FIXTURE_DAY_RATE > 0


# The "SRAConfig still requires day_rate" property is DAYRATE-02's own and is held by
# tests/test_dayrate02_day_rate_contract.py; a bare SRAConfig() here tripped that file's
# source scan at the RS-D merge, so the duplicate is not kept.
