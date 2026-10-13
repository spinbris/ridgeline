# SR9 v3 amendment - 2026-04-26 - presentation-layer reframe.
"""SR9 v3 callout box static text.

Two visually distinct framed boxes rendered on Page 1 of the executive
summary, below the headline range table. Both texts are static (do not
change run to run). Imported by composer, word_generator, and notebook.

Director framing: callouts persuade the reader the analytical approach is
worth investing in. They reveal genuine insights the deterministic
approach misses; they do not oversell findings.
"""

from __future__ import annotations


WHY_MC_MATTERS_TITLE = "Why MC matters here"

WHY_MC_MATTERS = (
    "This project has 32 active risks with probabilities ranging from 2.5% "
    "to 50%. A deterministic approach would either ignore probabilities and "
    "add all worst-case impacts (impossibly conservative), or apply a "
    "gut-feel percentage (10-20%) without grounding in actual risk "
    "inventory.\n\n"
    "Probabilistic Monte Carlo:\n"
    "- Honours each risk's probability and impact distribution\n"
    "- Reveals tail risks that deterministic averaging hides\n"
    "- Surfaces empirical firing rates - validating that the engine "
    "matches assigned probabilities (a self-validation check)\n"
    "- Shows where Mode classification matters and where it does not\n"
    "- Produces a contingency number that defends in audit\n\n"
    "This analysis confirms what engineering judgement suggests, adds "
    "quantified confidence intervals, and identifies the small number of "
    "risks that drive most of the contingency. Treatment effort focused on "
    "the top drivers delivers the largest reduction in contingency."
)

HOW_THIS_AGES_WELL_TITLE = "How this analysis ages well"

HOW_THIS_AGES_WELL = (
    "This analysis is structurally robust to changes in inputs. When the "
    "current Mode classifications are amended through PM review, when "
    "commercial inputs (LD rates, IDC parameters) land for the next stage, "
    "when the risk register revises, the analysis re-runs against amended "
    "inputs in 2-3 minutes and produces an updated deliverable.\n\n"
    "The methodology, the engine, the cross-validation framework - these "
    "are durable. Only the inputs change. The investment in this "
    "analytical approach pays off across this project's life and any "
    "future project on the same template."
)
