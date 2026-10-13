"""Per-section data builders for the SR9 final-report composer.

SR14a introduces a shared section-builder layer so a Stage 3 composer
(SR14b) can wrap the same data assembly that the Stage 2.5 composer uses.
Each builder is a pure function: it takes the run-state inputs it needs
and returns a presentation-ready dict that the composer merges into its
top-level ``composed`` payload.

Conventions:
- One module per section. Each module exposes ``build_<section>_section``
  with a documented ``Returns`` contract its docstring describes.
- Builders return plain ``dict[str, Any]`` (Decision D2=A). The composer
  applies stage-specific narrative text on top (Decision D3=A); the
  builders themselves do not call ``commentary_text.X.format(...)``.
- Methodology-bearing constants stay in their existing homes
  (``commentary_text.py``, ``executive_summary.py``, etc.). Builders
  import what they need; no new methodology constants are introduced
  in this layer (brief §4.3).

SR14a extracts three sections (audit_trail, risk_matrix, walkthrough).
The remaining six modules (page1_table, s_curves, action_implications,
cost_drivers, schedule_drivers, criticality) are scaffolding stubs whose
extraction is queued as a follow-up brief.
"""

from src.final.sections.action_implications import build_action_implications_section
from src.final.sections.audit_trail import build_audit_trail_section
from src.final.sections.cost_drivers import build_cost_drivers_section
from src.final.sections.criticality import build_criticality_section
from src.final.sections.page1_table import build_page1_table_section
from src.final.sections.risk_matrix import build_risk_matrix_section
from src.final.sections.s_curves import build_s_curves_section
from src.final.sections.schedule_drivers import build_schedule_drivers_section
from src.final.sections.walkthrough import build_walkthrough_section

__all__ = [
    "build_action_implications_section",
    "build_audit_trail_section",
    "build_cost_drivers_section",
    "build_criticality_section",
    "build_page1_table_section",
    "build_risk_matrix_section",
    "build_s_curves_section",
    "build_schedule_drivers_section",
    "build_walkthrough_section",
]
