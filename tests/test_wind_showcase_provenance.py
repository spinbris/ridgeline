"""WIND-04: engine-provenance stamp on the wind showcase run-meta.

Covers the provenance helpers and the dirty-tree guard in
scripts/run_wind_showcase.py. The showcase's main() runs ~100k and is not
unit-testable, so the guard + digest logic is factored into small helpers and
exercised here (both guard branches demonstrated, per brief section 4). The
100k byte-match lock on the quotable figures is proven by the close-out run,
not here.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "run_wind_showcase.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_wind_showcase", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rws = _load_module()


# ---------------------------------------------------------------------------
# Dirty-tree guard: both branches (brief section 4)
# ---------------------------------------------------------------------------

def test_guard_refuses_dirty_tree() -> None:
    with pytest.raises(RuntimeError, match="dirty-tree guard"):
        rws._check_dirty_guard(True, allow_dirty=False)


def test_guard_allows_dirty_tree_with_flag() -> None:
    # no raise
    rws._check_dirty_guard(True, allow_dirty=True)


def test_guard_passes_clean_tree() -> None:
    rws._check_dirty_guard(False, allow_dirty=False)


def test_guard_soft_fail_none_does_not_refuse() -> None:
    # git soft-fail (None) must not block the run.
    rws._check_dirty_guard(None, allow_dirty=False)


# ---------------------------------------------------------------------------
# Provenance shape + per-file input digests
# ---------------------------------------------------------------------------

def test_build_provenance_shape() -> None:
    prov = rws._build_provenance("deadbeef", False)
    assert prov["engine_sha"] == "deadbeef"
    assert prov["engine_tree_dirty"] is False
    # REG-01: strawman dissolved into the register; the digest set drops it.
    assert set(prov["input_sha256"]) == {"register", "xer"}


def test_input_digests_match_hashlib_on_the_fixtures() -> None:
    prov = rws._build_provenance("x", False)
    expected = {
        "register": hashlib.sha256(rws.WIND_REGISTER.read_bytes()).hexdigest(),
        "xer": hashlib.sha256(rws.WIND_XER.read_bytes()).hexdigest(),
    }
    assert prov["input_sha256"] == expected
    # per-file, not concatenated: distinct digests
    assert len(set(prov["input_sha256"].values())) == 2


def test_sha256_stable_and_one_byte_sensitive(tmp_path: Path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"payload-vX")
    before = rws._sha256_file(p)
    q = tmp_path / "g.bin"
    q.write_bytes(b"payload-vX")
    assert rws._sha256_file(q) == before          # stable for identical bytes
    p.write_bytes(b"payload-vY")                    # one byte differs
    assert rws._sha256_file(p) != before
