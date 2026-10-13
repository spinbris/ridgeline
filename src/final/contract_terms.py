"""Wording that depends on the shape of the engagement's contract, not on the analysis.

PRESENT-01 (D-3). Three things the deliverable said were facts about a contract, not about a
project's risk: that the headline contingency sits against a Target Outturn Cost, that a
liquidated-damages and interest-during-construction layer is owed, and that a gain/pain share
governs the party split. A report that states them for a project delivered under a different
contract is wrong in a way no test could see, because each reads as ordinary prose.

They are now resolved from the active binding's ``contract_type``. A binding that declares none
gets the neutral wording, which asserts nothing about the contract; the deferred-layer notes are
omitted entirely rather than softened, because "a layer is deferred" is a claim, and a project
whose contract has no such layer should not be told one is coming.

Adding a contract shape is a row in ``_TERMS`` plus the binding field. The keys are deliberately
few: this module exists to stop contract assumptions leaking into engine text, not to become a
second narrative layer.
"""

from __future__ import annotations

from typing import Any, Mapping


#: Wording for a project whose binding declares no contract type. Every key is answerable
#: without knowing the commercial structure.
NEUTRAL: Mapping[str, Any] = {
    "headline_contingency_label": "Headline contingency",
    # The same label mid-sentence. Declared rather than derived: ``.lower()`` on a label
    # containing an acronym renders "headline toc contingency" in a client document.
    "headline_contingency_inline": "headline contingency",
    "target_cost_basis_note": None,
    "deferred_commercial_layers_note": None,
}

_TERMS: Mapping[str, Mapping[str, Any]] = {
    "target_outturn_cost": {
        "headline_contingency_label": "Headline TOC contingency",
        "headline_contingency_inline": "headline TOC contingency",
        "target_cost_basis_note": (
            "TOC basis. The Target Outturn Cost reference used in commercial framing is "
            "sourced from the Risk Register Variables sheet via the strawman methodology "
            "workbook. Specific dollar values appear only in the audit trail appendix; the "
            "executive summary uses role-based language for the body narrative."
        ),
        "deferred_commercial_layers_note": (
            "Liquidated damages layer deferred. The LD overlay (per-day delay damages above "
            "the contractual grace period) is deferred to a later stage pending commercial "
            "input confirmation. The current deliverable reports schedule slip in days and "
            "dollarises at the day rate; LD treatment will be added when the contractual "
            "parameters are settled."
        ),
    },
}

#: The contract shapes this module knows how to write for.
KNOWN_CONTRACT_TYPES = tuple(_TERMS)


def resolve_contract_type() -> str | None:
    """The active binding's declared contract type, or ``None``.

    An unrecognised value is refused by name rather than silently treated as neutral: a typo in
    a binding would otherwise quietly drop the contract's wording out of a client document.
    """
    from src.sra.cpm.bindings import get_active_binding

    declared = getattr(get_active_binding(), "contract_type", None)
    if declared is None:
        return None
    if declared not in _TERMS:
        raise ValueError(
            f"project binding declares contract_type={declared!r}, which "
            f"src.final.contract_terms does not know how to write for. "
            f"Known: {sorted(_TERMS)}. Add a row to _TERMS or clear the field."
        )
    return declared


def term(key: str) -> Any:
    """Resolve one piece of contract-shape wording for the active project.

    Returns the neutral answer when the binding declares no contract type. A ``None`` answer is
    meaningful: the caller omits that statement rather than printing a softened version of it.
    """
    if key not in NEUTRAL:
        raise KeyError(
            f"unknown contract-term key {key!r}; known keys: {sorted(NEUTRAL)}"
        )
    declared = resolve_contract_type()
    if declared is None:
        return NEUTRAL[key]
    return _TERMS[declared].get(key, NEUTRAL[key])
