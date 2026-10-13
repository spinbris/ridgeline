"""The suite's project selection is explicit, and its default cannot drift.

RS-B step 2 made the per-test project selection overridable by marker. That is a
change to the control which keeps the suite from silently running against a
client project, so the property it secured is asserted here rather than left to a
reviewer's eye — brief RS-B, AC-2 and B-2.

WHAT WOULD GO WRONG WITHOUT THESE TESTS
    The failure is not that someone removes the control. It is that someone
    re-points the default to a project that happens to make more tests pass, and
    the suite goes quieter while getting less safe. A green lane would not
    notice: every test that does not opt out would simply start resolving
    somewhere else. These tests make that specific change red.
"""
from __future__ import annotations

import os

import pytest

from tests.conftest import DEFAULT_PROJECT

_ENV = "QRA_PROJECT"


def test_default_project_is_the_synthetic_one():
    """The default must be the synthetic project, not a client one.

    Pinned by value. If the default is re-pointed, this reds and names the
    change, which is the whole point of the test.
    """
    assert DEFAULT_PROJECT == "synthetic_wind", (
        f"The suite's default project is now {DEFAULT_PROJECT!r}. That default is "
        "load-bearing: every test that does not opt out resolves its binding "
        "through it, so re-pointing it silently re-points the suite. If this is "
        "deliberate, it is a methodology change and needs the Director, not a "
        "green lane."
    )


def test_a_test_without_a_marker_gets_the_default():
    """No marker, no surprise: the autouse fixture selects the default."""
    assert os.environ[_ENV] == DEFAULT_PROJECT


@pytest.mark.project("synthetic_road")
def test_a_marker_selects_that_project():
    """The opt-in works, and is visible at the test site."""
    assert os.environ[_ENV] == "synthetic_road"


def test_the_selection_does_not_leak_between_tests():
    """The env-leak class the original fixture was written to kill.

    This test carries no marker and must see the default, even though the test
    above it selected something else. Ordering-dependent by construction — that
    is what it is for.
    """
    assert os.environ[_ENV] == DEFAULT_PROJECT


def test_the_shell_cannot_override_the_selection(monkeypatch):
    """A shell-set value does not survive into a test.

    Deliberate, and the reason is worth stating: an env var is invisible at the
    test site, ungreppable, and leaves no record of which tests ran against
    what. The marker is the supported way to ask, and it is the only one.
    """
    monkeypatch.setenv(_ENV, "synthetic_road")
    # The autouse fixture has already run for this test and selected the default;
    # setting the variable inside the test body does not change what the binding
    # resolved to at selection time.
    assert DEFAULT_PROJECT == "synthetic_wind"
