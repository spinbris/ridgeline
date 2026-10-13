"""The GN4 escalation hand-off, and the removal of the Model 2 overclaim.

Director ruling 06/09/2026 ("escalation is required"), taken as the **lighter** of the CEGN
review's two ESC-01 options: a documented client-side hand-off, not the GN4 module.

**That distinction is a spec-level one and these tests pin it.** D-1/R-5 rule this product
*contingency only*. A hand-off does not compute escalation - it states that the product does not -
so **R-5 stands untouched**. Building the module would reverse D-1 and reopen D-2 (the GN3B
deterministic layer, currently "moot under R-5"), and remains the Director's decision.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
METHODOLOGY = REPO / "docs" / "system_description" / "METHODOLOGY.md"  # link-rule: the superseded method copy is checked for the overclaim when present, skipped when absent

#: Every binding that ships. Each is checked, because the hand-off's whole point is that a
#: PROJECT cannot drop a statement about the PRODUCT.
SHIPPED_BINDINGS = ("synthetic_wind", "synthetic_road")


def _caveat(project: str) -> str:
    os.environ["QRA_PROJECT"] = project
    from src.final.stage3_beta_report import resolve_cover_caveat

    return resolve_cover_caveat()


class TestTheEscalationHandoffReachesEveryReader:
    @pytest.mark.parametrize("project", SHIPPED_BINDINGS)
    def test_it_survives_a_binding_that_overrides_the_caveat(self, project: str):
        """**The reason it is appended rather than written into the generic text.**

        `resolve_cover_caveat` prefers a binding's own narrative, and a shipped binding may
        override it (`synthetic_wind.py:62`). Placed in
        `_GENERIC_COVER_PAGE_CAVEAT` this statement would have reached no real reader at all -
        it would have been present, tested, and invisible.
        """
        assert "Escalation is not applied" in _caveat(project)

    @pytest.mark.parametrize("project", SHIPPED_BINDINGS)
    def test_the_projects_own_caveat_is_not_lost(self, project: str):
        """Appended, not substituted. A hand-off that ate the project's own warnings would trade
        one honesty problem for another."""
        text = _caveat(project)
        assert text.index("Escalation is not applied") > 40, (
            "the hand-off is at the very start, so the project's caveat was replaced")

    @pytest.mark.parametrize("project", SHIPPED_BINDINGS)
    def test_it_says_the_figures_are_real_terms(self, project: str):
        assert "REAL TERMS" in _caveat(project)

    @pytest.mark.parametrize("project", SHIPPED_BINDINGS)
    def test_it_refuses_the_word_outturn_for_these_figures(self, project: str):
        """The terminology hazard the review rates highest, in the one place a client reads.
        GN4 Appendix C reserves "outturn" for the post-escalation nominal figure - and this
        product is NAMED outturn, which is exactly why the deliverable must disclaim it."""
        text = _caveat(project)
        assert "GN4" in text and "outturn" in text
        assert "nothing here is an outturn figure" in text

    @pytest.mark.parametrize("project", SHIPPED_BINDINGS)
    def test_it_says_who_must_establish_the_base_date(self, project: str):
        """No base date is quoted because the product has none - there is no base-date field
        anywhere in `src/`. Saying so is the honest form: a reader needing an outturn figure must
        know the base date is theirs to establish, not ours to assume."""
        text = _caveat(project)
        assert "does not record" in text and "estimator must state" in text

    def test_the_product_still_has_no_base_date_field(self):
        """The control on the test above. If a base date is ever recorded, the hand-off should
        QUOTE it rather than disclaim it, and this test is what will say so.

        Matched as an IDENTIFIER, not as prose. An earlier version searched for the words "base
        date" and hit the hand-off text itself, which says the product does not record one -
        the guard convention exists because of that class of defect.

        **Scoped to the deliverable path, and this is a real narrowing.** `src/escalation.py` now
        carries `base_date_financial_year`: ESC-01 part B takes a base year as an argument. That
        does not make the caveat false, because nothing published calls it - the same reasoning,
        and the same scope, as the hand-off guard below. What the caveat claims is that the
        *product* records no base date, so that is what this measures.

        **This guard was inert until 06/09/2026.** Its pattern was written as a raw string
        wrapping `base_date` in two literal `0x08` backspace BYTES instead of the two-character
        escape \b - so it compiled to a pattern wrapping the identifier in two literal
        backspace characters, and could never match anything. It
        rendered as `r"base_date"` in grep, in `sed`, and in `inspect.getsource`, so both the
        Builder and the ESC-01 numerics reviewer read it as correct; the reviewer reported the
        suite as red on it, and it was in fact green because the check could not fail. Found by
        disassembling the function when the two disagreed. A sixth guard shape for the register:
        **a pattern that cannot match, hiding behind a rendering that looks right.**
        """
        hits = sorted(
            f.relative_to(REPO).as_posix() for f in (REPO / "src" / "final").rglob("*.py")
            if re.search(r"\bbase_date\b", f.read_text(encoding="utf-8", errors="ignore")))
        assert hits == [], (
            f"the deliverable path now records a base date ({hits}); the escalation hand-off "
            f"should quote it instead of saying the product does not record one")


class TestEscalationIsComputedOnlyOnTheSanctionedPath:
    """The successor to `test_nothing_computes_escalation`, which ESC-01 part B redded by design.

    **Replaced, not deleted.** That guard existed so escalation could not arrive quietly; it has
    now arrived loudly - SPEC v1.6 re-ruled D-1, and `src/escalation.py` implements it. Deleting
    the guard when the thing it guarded appeared would leave nothing behind. Its successor asserts
    the property that matters *now*: escalation exists in exactly one place, on the ruled terms.
    """

    ESCALATION_MODULE = "src/escalation.py"

    def _computing_modules(self) -> list[str]:
        pattern = re.compile(
            r"def\s+\w*escalat|escalation_\w+\s*=|apply_escalat|escalate\s*\(", re.I)
        return sorted(
            f.relative_to(REPO).as_posix() for f in (REPO / "src").rglob("*.py")
            if pattern.search(f.read_text(encoding="utf-8", errors="ignore")))

    def test_exactly_one_module_computes_escalation(self):
        """One home. Escalation arithmetic appearing in a second module is how two answers to the
        same question start, which is the shape the A-5 lesson names."""
        assert self._computing_modules() == [self.ESCALATION_MODULE], (
            f"escalation is computed outside {self.ESCALATION_MODULE}: "
            f"{self._computing_modules()}")

    def test_it_cannot_draw_its_own_randomness(self):
        """The Director's 06/09 ruling - correlated with the Layer-1 factors - implemented
        structurally. A module holding its own Generator would be independent of cost whatever
        its comments said, which is precisely the stage 7 part B defect."""
        source = (REPO / self.ESCALATION_MODULE).read_text(encoding="utf-8")
        assert not re.search(
            r"default_rng\s*\(|rng\.(random|standard_normal|uniform)\s*\(", source), (
            "src/escalation.py draws its own randomness, so it is independent of the cost draws")

    def test_the_hand_off_is_still_TRUE_of_what_the_product_produces(self):
        """**The one that guards the client-facing statement.**

        The cover caveat tells every reader "Escalation is not applied". That is true only while
        nothing on the deliverable path calls the escalation module - the arithmetic exists, the
        wiring does not, and the register carries no rate (contract 1.4 -> 1.5 is unspent).

        The day anything under `src/final/` escalates, the caveat becomes a false statement to a
        client and must move in the same commit. This test is what makes that impossible to
        forget.
        """
        # Matched on CODE SHAPE - an import of the module, or a call into it - never on the word
        # "escalation". The previous version matched the word and therefore had to exclude
        # `stage3_beta_report` by filename to stop the caveat matching itself. That exclusion was
        # load-bearing in the worst direction: the excluded file is the one that assembles the
        # deliverable, so wiring escalation into the very place it would most likely be wired
        # would have passed. Found by the ESC-01 style review.
        wiring = re.compile(
            r"from\s+src\.escalation\s+import|import\s+src\.escalation"
            r"|escalate\s*\(|escalation_multipliers\s*\(")
        callers = sorted(
            f.relative_to(REPO).as_posix() for f in (REPO / "src" / "final").rglob("*.py")
            if wiring.search(f.read_text(encoding="utf-8", errors="ignore")))
        assert callers == [], (
            f"the deliverable path now references escalation ({callers}), so the cover caveat's "
            f"'Escalation is not applied' may be false. Update the hand-off in this commit.")


#: This class tests a private document (the superseded method copy), so it runs wherever that copy
#: is present and skips, naming it, in the public snapshot. The classes above test shipped code.
@pytest.mark.needs_input("docs/system_description/METHODOLOGY.md")  # link-rule: the superseded method copy is checked for the overclaim when present, skipped when absent
class TestTheModel2OverclaimIsGone:
    def test_the_claim_is_removed_from_the_stage_table(self):
        """CEGN review theme 4, severity high: the file claimed full alignment with a model whose
        defining layer §10.1 of the same file says is switched off in production."""
        text = METHODOLOGY.read_text(encoding="utf-8")
        row = next(l for l in text.splitlines() if "Stage 2 | Cost MC" in l)
        assert "fully aligned with Model 2" not in row, (
            "the Stage 2 row claims full alignment with GN3A Risk Factor Model 2 again")

    def test_the_removal_is_explained_where_a_reader_will_find_it(self):
        """A silent deletion of a claim is not a correction - the next reader cannot tell whether
        it was wrong or merely tidied."""
        text = METHODOLOGY.read_text(encoding="utf-8")
        assert "Note on the Stage 2 alignment claim" in text
        assert "deletion of an unsupported claim, not the assertion of a new one" in text

    def test_no_new_positive_claim_was_asserted_in_its_place(self):
        """The Builder removed a claim; it did not make one. Reframing the engine as the GN3A
        Risk Driver Method is a statement about what this product IS, and belongs to the
        Director. This test fails if a future edit quietly supplies that claim here."""
        text = METHODOLOGY.read_text(encoding="utf-8")
        row = next(l for l in text.splitlines() if "Stage 2 | Cost MC" in l)
        assert not re.search(r"Risk Driver Method", row), (
            "a positive alignment claim has been asserted in the Stage 2 row; that is the "
            "Director's statement to make, not the Builder's")
