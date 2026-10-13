"""SR9 Pass A tests for disclaimer_text."""

from __future__ import annotations

from src.final import disclaimer_text


def test_get_paragraphs_returns_the_statements_this_run_can_make():
    """PRESENT-01 (P-3/D-3): the list is no longer a fixed ten.

    Two paragraphs are contract-shaped and appear only for a binding that declares a contract
    type; one describes the run's tail risk and appears only when there is one. A project that
    declares neither gets the seven statements that are true of any run.
    """
    paragraphs = disclaimer_text.get_paragraphs()
    assert isinstance(paragraphs, list)
    assert len(paragraphs) == 7
    assert all(isinstance(p, str) for p in paragraphs)
    assert all(len(p) > 50 for p in paragraphs)  # not empty/stub


def test_get_paragraphs_adds_the_tail_risk_statement_only_when_there_is_one():
    tail = {"tail_risk_id": "WT-009", "tail_risk_prob": 0.025,
            "tail_risk_mean_when_fired": 300.0}
    with_tail = disclaimer_text.get_paragraphs(tail_risk=tail)
    assert len(with_tail) == 8
    assert any("WT-009" in p and "2.5%" in p for p in with_tail)
    assert not any("Tail-risk reporting convention" in p
                   for p in disclaimer_text.get_paragraphs())


def test_get_paragraphs_states_the_runs_own_time_impacting_count():
    assert any("the 8 risks flagged" in p
               for p in disclaimer_text.get_paragraphs(dual_coded_count=8))
    assert any("the risks flagged" in p for p in disclaimer_text.get_paragraphs())


def test_get_paragraphs_uses_role_based_language():
    """Disclaimer narrative must not pin V8/V7 register version."""
    paragraphs = disclaimer_text.get_paragraphs()
    full_text = " ".join(paragraphs)
    # No version pins in narrative - role-based language only
    assert "V8" not in full_text
    assert "V7" not in full_text
    # Sanity: role-based phrases should appear
    assert "project risk register" in full_text
    assert "strawman" in full_text.lower()
