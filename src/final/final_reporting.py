"""SR9 pure-data accessor functions for notebook consumption.

NO HTML in this module. The notebook (Pass B) calls these accessors and
renders via display(Markdown()) and matplotlib. Each accessor returns a
slice of the composed dict from src.final.composer.compose_final_report_data.

Six accessors mirror the structural sections of the final report:
  - executive summary panel
  - cost section panel
  - schedule section panel
  - integrated section panel
  - appendix A1 (counterfactual table)
  - appendix A2 (methodology)
  - appendix A3 (audit trail) - the one place where specific version numbers
    and file paths appear, per version-pin discipline
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def get_executive_summary_panel_data(composed: dict[str, Any]) -> dict[str, Any]:
    """Return the executive_summary slice for HTML rendering."""
    return dict(composed.get("executive_summary", {}))


def get_cost_section_panel_data(composed: dict[str, Any]) -> dict[str, Any]:
    """Return the cost_section slice for HTML rendering."""
    return dict(composed.get("cost_section", {}))


def get_schedule_section_panel_data(composed: dict[str, Any]) -> dict[str, Any]:
    """Return the schedule_section slice for HTML rendering."""
    return dict(composed.get("schedule_section", {}))


def get_integrated_section_panel_data(composed: dict[str, Any]) -> dict[str, Any]:
    """Return the integrated_section slice for HTML rendering."""
    return dict(composed.get("integrated_section", {}))


def get_appendix_counterfactual_table(composed: dict[str, Any]) -> pd.DataFrame:
    """Return the 12-scenario counterfactual DataFrame for appendix A1."""
    df = composed.get("appendix_counterfactual")
    if df is None:
        return pd.DataFrame()
    return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame(df)


def get_appendix_methodology_data(composed: dict[str, Any]) -> dict[str, Any]:
    """Return the methodology appendix data (A2)."""
    return dict(composed.get("appendix_methodology", {}))


def get_appendix_audit_trail_data(composed: dict[str, Any]) -> dict[str, Any]:
    """Return the audit trail appendix data (A3).

    The one place where specific version numbers and file paths appear,
    per the version-pin discipline. Body narrative elsewhere uses
    role-based language only.
    """
    return dict(composed.get("appendix_audit_trail", {}))


def get_preview_banner(composed: dict[str, Any]) -> str:
    """SR14b D2 Option A — return the preview banner string if set.

    Stage 2.5's composed dict does not carry ``preview_banner``; this
    accessor returns an empty string in that case so notebook
    rendering loops skip cleanly. The Stage 3 standalone composer
    (SR14b session 2) sets the key with the locked
    ``stage3_beta_report.PREVIEW_BANNER_TEXT`` so the HTML and docx
    renders both reflect the preview status.
    """
    return str(composed.get("preview_banner", "") or "")
