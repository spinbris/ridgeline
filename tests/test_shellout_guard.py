"""The shell-out guard refuses what it should, allows what it should, and does
not break the standard library on the way past.

The third clause is not padding. The guard's first working version replaced
``subprocess.Popen`` - a **class** - with a function. ``asyncio/windows_utils.py``
does ``class Popen(subprocess.Popen)`` at import time, so any test that happened
to be the first to import asyncio died with

    TypeError: function() argument 'code' must be code, not str

raised from inside the standard library, naming nothing about this guard. Three
tests in ``test_sr_s3_beta_17_stakeholder_coverage_pack.py`` failed that way.

The reason it is worth a permanent test rather than a fix and a comment is *when*
it showed up. It is **import-order dependent**: if anything imported asyncio
before the fixture patched, the subclassing had already happened and the bug was
invisible. Three full lanes ran green with it present, and it only surfaced when
one file was run on its own during the partition sweep. A defect that hides
behind import order will hide again.
"""
from __future__ import annotations

import importlib
import subprocess
import sys

import pytest


def test_subprocess_popen_can_still_be_subclassed():
    """Reproduce, directly, what ``asyncio/windows_utils.py`` does at import time.

    Deliberately NOT written as ``import asyncio.windows_utils`` plus
    ``issubclass(mod.Popen, subprocess.Popen)``. That version passes alone and
    fails in the lane, because under xdist asyncio is already imported before the
    fixture patches: ``mod.Popen`` then subclasses the *real* ``Popen`` while
    ``subprocess.Popen`` is the guard's stand-in, and ``issubclass`` is false for
    a reason that has nothing to do with the defect. It was written that way
    first and red the stage lane - an order-dependent check for an
    order-dependent bug, which is the one shape that must not be order-dependent.

    Creating the subclass here is the property itself, and it holds whatever has
    been imported: subclassing a function raises ``TypeError``, subclassing a
    class does not.
    """
    class _StdlibStylePopenSubclass(subprocess.Popen):
        pass

    assert isinstance(_StdlibStylePopenSubclass, type), (
        "subprocess.Popen could not be subclassed. tests/conftest.py is patching "
        "it with a function rather than a subclass, which raises TypeError from "
        "inside asyncio at import time and names nothing about the guard."
    )


def test_an_unmarked_test_is_refused_when_it_shells_out():
    """This test is itself the fixture: unmarked, so its own call must be refused."""
    with pytest.raises(AssertionError, match=r"not marked @pytest\.mark\.slow"):
        subprocess.run([sys.executable, "-c", "pass"])


def test_an_unmarked_test_is_refused_when_it_uses_popen_directly():
    """``run`` is not the only route; ``Popen`` is the primitive underneath it."""
    with pytest.raises(AssertionError, match=r"not marked @pytest\.mark\.slow"):
        subprocess.Popen([sys.executable, "-c", "pass"])


@pytest.mark.slow  # the point of this one is that the marker lets it through
def test_a_marked_test_may_shell_out():
    """The other half of the guard: with the marker, the real call happens.

    Without this, a guard that refused unconditionally would look identical to a
    working one from the failing side alone.
    """
    assert subprocess.run([sys.executable, "-c", "pass"]).returncode == 0
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    assert proc.wait() == 0
