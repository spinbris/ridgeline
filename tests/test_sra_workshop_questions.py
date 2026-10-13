"""Unit tests for src.sra_strawman.workshop_questions."""

from __future__ import annotations

from src.sra_strawman.workshop_questions import (
    OWNER_COMMERCIAL,
    OWNER_DIRECTOR,
    OWNER_ESTIMATOR,
    OWNER_PM,
    PRIORITY_MUST,
    build_questions,
    questions_by_owner,
)


def test_question_count_in_target_range():
    """Brief Section 5.6 calls for 20-30 questions."""
    qs = build_questions()
    assert 20 <= len(qs) <= 30


def test_questions_have_sequential_numbers():
    qs = build_questions()
    assert [q.number for q in qs] == list(range(1, len(qs) + 1))


def test_all_four_owners_represented():
    qs = build_questions()
    owners = {q.owner for q in qs}
    assert OWNER_ESTIMATOR in owners
    assert OWNER_PM in owners
    assert OWNER_COMMERCIAL in owners
    assert OWNER_DIRECTOR in owners


def test_must_priority_questions_exist():
    """Workshop agenda needs at least a handful of Must questions
    to anchor the mandatory discussion."""
    qs = build_questions()
    must = [q for q in qs if q.priority == PRIORITY_MUST]
    assert len(must) >= 5


def test_questions_by_owner_groups_correctly():
    qs = build_questions()
    grouped = questions_by_owner(qs)
    total = sum(len(v) for v in grouped.values())
    assert total == len(qs)
    assert all(all(q.owner == owner for q in v) for owner, v in grouped.items())


def test_extras_are_appended_and_numbered():
    extra = ("Mapping", "Is X ok?", OWNER_PM, "Yes/No", "Test impact", "Nice to have")
    qs = build_questions(extras=[extra])
    assert qs[-1].question == "Is X ok?"
    assert qs[-1].number == len(qs)


def test_no_hardcoded_risk_id_in_workshop_questions():
    """Regression guard consistent with the rest of the SRA subpackage."""
    import re
    from pathlib import Path
    src_path = (
        Path(__file__).resolve().parents[1]
        / "src" / "sra_strawman" / "workshop_questions.py"
    )
    source = src_path.read_text(encoding="utf-8")
    matches = re.findall(r"\bR\d{3,}(?:\.\d+)?\b", source)
    assert not matches, f"Risk ID literals found: {matches}"
