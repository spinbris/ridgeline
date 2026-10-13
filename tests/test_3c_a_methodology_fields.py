"""3c Part A: the premise of ``src/integrated/stage3_config.py``, re-derived from the tree.

``MethodologyDefaults`` declares 22 fields. ``src/integrated/stage3_config.py`` reads two of
them from the register the run is actually using, and leaves the rest to
``build_test_methodology_defaults``, whose values are the reference project's. That is only
safe while nothing reads the rest - and "nothing reads the rest" was a **measurement**, taken
on 04/09/2026, not a property anything enforced.

This is the enforcement. It re-derives the read set from ``src/`` on every run and fails
naming any field beyond the two, so the day a consumer starts reading a third, this reds and
says which - rather than that consumer silently receiving another project's number.

A pass here is not "the design is fine". It is "the design's precondition still holds".
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.sra.methodology_defaults_reader import MethodologyDefaults

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

#: The two fields any engine path actually reads, and where. Adding to this set is a
#: decision about ``stage3_config``'s premise, not a test fix - see that module's docstring.
KNOWN_READ_FIELDS = frozenset({"mode_multipliers", "cg_coefficients"})

FIELD_NAMES = frozenset(MethodologyDefaults.__dataclass_fields__)


SCRIPTS = REPO / "scripts"

#: Ways a field can be read that a plain ``x.methodology_defaults.field`` match would miss.
#: Named because the first version of this guard matched only the direct chain, and the Part A
#: numerics review pointed out that an alias, a ``getattr`` or an ``asdict`` walks straight
#: past it - an enforced-but-escapable check, which is the weaker half of not being enforced.
_DYNAMIC_READERS = ("getattr", "asdict", "astuple", "vars")


def _sources():
    """Every module that could read the object: ``src/`` and ``scripts/``.

    ``scripts/`` is in scope because ``run_wind_showcase`` is the golden's own path - a field
    read there reaches a committed number as surely as one in ``src/``.
    """
    for root in (SRC, SCRIPTS):
        for path in sorted(root.rglob("*.py")):
            yield path


def _methodology_field_reads() -> dict[str, set[str]]:
    """Every read of a MethodologyDefaults field, field -> files, including via an alias."""
    found: dict[str, set[str]] = {}

    for path in _sources():
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:  # a file we cannot parse is a failure, not a skip
            pytest.fail(f"could not parse {rel}: {exc}")

        # Local names bound to a `.methodology_defaults` expression, so `md = cfg.
        # methodology_defaults; md.gp_toc` is caught as well as the direct chain.
        aliases: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute) \
                    and node.value.attr == "methodology_defaults":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        aliases.add(target.id)

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                inner = node.value
                direct = isinstance(inner, ast.Attribute) and inner.attr == "methodology_defaults"
                aliased = isinstance(inner, ast.Name) and inner.id in aliases
                if (direct or aliased) and node.attr in FIELD_NAMES:
                    found.setdefault(node.attr, set()).add(rel)

            # A dynamic read cannot be attributed to one field, so it is reported against a
            # sentinel rather than silently ignored - the guard says "I cannot see through
            # this" instead of pretending nothing happened.
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id in _DYNAMIC_READERS:
                for arg in node.args:
                    reaches_md = (
                        (isinstance(arg, ast.Attribute) and arg.attr == "methodology_defaults")
                        or (isinstance(arg, ast.Name) and arg.id in aliases)
                    )
                    if reaches_md:
                        found.setdefault("<dynamic read>", set()).add(
                            f"{rel} ({node.func.id})")
    return found


def test_no_dynamic_read_hides_a_field_access():
    """``getattr``/``asdict`` on the object would make the field set unknowable statically."""
    dynamic = sorted(_methodology_field_reads().get("<dynamic read>", ()))
    assert dynamic == [], (
        "a MethodologyDefaults object is read dynamically, so which fields are consumed can "
        f"no longer be established from the tree - and stage3_config's premise rests on that "
        f"being knowable: {dynamic}"
    )


def test_only_the_known_fields_are_read_anywhere_in_src():
    reads = _methodology_field_reads()
    unexpected = {f: sorted(files) for f, files in reads.items()
                  if f in FIELD_NAMES and f not in KNOWN_READ_FIELDS}
    assert unexpected == {}, (
        "a MethodologyDefaults field beyond the known two is now read in src/. "
        "src/integrated/stage3_config.py supplies only the known two from the register and "
        "leaves the rest at the reference project's factory values, so this read would hand "
        "another project's number to whatever consumes it. Source that field from the "
        "register before adding it to KNOWN_READ_FIELDS: "
        f"{unexpected}"
    )


def test_the_known_fields_are_still_read_somewhere():
    """The other half: a KNOWN field nobody reads any more should leave the set, or the
    guard's own scope quietly drifts away from what it claims to cover."""
    reads = _methodology_field_reads()
    stale = sorted(KNOWN_READ_FIELDS - set(reads))
    assert stale == [], (
        f"KNOWN_READ_FIELDS names {stale}, which nothing under src/ reads any more. "
        "Drop it from the set so the guard describes the tree it is guarding."
    )


def test_every_known_field_is_a_real_dataclass_field():
    """A typo in KNOWN_READ_FIELDS would silently widen the allowance to nothing."""
    assert KNOWN_READ_FIELDS <= FIELD_NAMES, sorted(KNOWN_READ_FIELDS - FIELD_NAMES)
