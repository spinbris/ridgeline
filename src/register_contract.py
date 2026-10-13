"""REG03 register contract - version, required named ranges, headless validator.

Pyodide-clean (stdlib only) so it bundles into the xlwings Lite distributable and
the Validate button can self-check a scaffolded register in-Excel after the user has
hand-edited it (the scaffold-once handover). This is the SINGLE SOURCE of the
contract version + required named-range set, shared by the scaffolder
(``tools/register_scaffold``), the Tier-1 shell's ``validate_contract`` @script, and
the tests - so a contract change cannot silently diverge between them.
"""
from __future__ import annotations

#: Bump on any named-range / contract-shape change. 1.0 = REG03 S1 (skeleton);
#: 1.1 = S2 (EMV-as-Excel formulas + Set_ContractVersion + Out_validation +
#: MC_day_rate); 1.2 = S3 (dynamic cascade Lists sheet + List_* named ranges);
#: 1.3 = REG05-A1 (project-identity metadata Set_Project* names);
#: 1.4 = REG05-A2 (Layer-1 promoted to every register: the four Grid_Layer1_*
#: grids + the Set_Layer1_Enabled off-signal are now required).
CONTRACT_VERSION = "1.4"

#: The REG03 S3 dynamic-cascade list named ranges (OFFSET dynamic ranges on the
#: Lists sheet, sourcing the Risk Register dropdowns). Additive; SRA-02 may add more.
LIST_NAMED_RANGES = frozenset({
    "List_Distribution", "List_MCInclude", "List_TimeImpact", "List_Recurrence",
    "List_Mode", "List_CGCode", "List_RBS_L1", "List_RBS_L2", "List_Package",
    "List_Factor",
})

#: REG05-A1 project-identity metadata cells (a project block on TOC & Instructions;
#: core workbook properties + the analysis-sheet title read from these).
PROJECT_META_NAMES = frozenset({
    "Set_ProjectName", "Set_ProjectNumber", "Set_Client", "Set_PreparedBy",
    "Set_Revision", "Set_IssueDate",
})

#: REG05-A2 Layer-1 grid ranges + the off-signal. Under 1.4 the scaffolder emits
#: an empty, present-but-optional Layer-1 on EVERY register, so these become part
#: of the required contract (reversing the pre-A2 "Layer 1 OFF is valid, the four
#: are added per project" stance). ``Set_Layer1_Enabled`` (default FALSE) gates the
#: read: an empty Layer-1 is a no-op ONLY because the flag ships FALSE. A pre-1.4
#: client register with no Layer-1 sheets fails Validate at 1.4 (migration note,
#: brief §8.3) - acceptable given scaffold-once + versioning.
LAYER1_NAMED_RANGES = frozenset({
    "Grid_Layer1_Base", "Grid_Layer1_Factors", "Grid_Layer1_Allocation",
    "Grid_Layer1_Correlation", "Set_Layer1_Enabled",
})

#: Named ranges every scaffolded Tier-1 register must carry.
REQUIRED_NAMED_RANGES = frozenset({
    "Grid_RiskRegister", "Grid_Methodology",
    "Set_iterations", "Set_seed", "Set_view", "Set_risk_prefix",
    "Set_iterations_max", "Set_ContractVersion", "MC_day_rate",
    "Out_ptable", "Out_scurve", "Out_triple", "Out_conv_halfwidth",
    "Out_conv_pct", "Corr_flag", "Out_validation",
}) | LIST_NAMED_RANGES | PROJECT_META_NAMES | LAYER1_NAMED_RANGES

_MODE_NAMES = ("Series", "Hybrid", "Parallel")
_N_CG = 13

#: The REG05-A2 Layer-1 off-signal cell (Settings). The read boundaries call
#: ``parse_layer1_from_grids`` only when this reads TRUE (else Layer-1 = None).
LAYER1_ENABLED_NAME = "Set_Layer1_Enabled"


def layer1_enabled_flag(value) -> bool:
    """Coerce a ``Set_Layer1_Enabled`` cell value to a bool. Accepts Excel booleans,
    numbers, and the strings TRUE/1/YES/ON (any case). Anything else - blank, None,
    an unrecognised string - reads as FALSE: Layer-1 stays OFF unless explicitly
    enabled, so a present-but-empty Layer-1 never trips the parser (brief §8.1)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"true", "1", "yes", "y", "on"}


#: Stage 7 §5.4, ruled 05/09/2026 (M1). What a client is told when their register stops
#: loading mid-engagement.
#:
#: Rejecting a register the engine does not understand is CORRECT and is not what §5.4 changed -
#: it is the fail-loud behaviour this repository prefers everywhere. What was missing was a path
#: FORWARD: the message named the mismatch and stopped, so a client saw two version numbers they
#: could not act on. Under M1 this string is the policy's only delivery mechanism to a human -
#: a policy recorded in a brief the client never reads is not one they can follow.
#:
#: Appended only on a VERSION mismatch. A register missing a named range is a different failure
#: with a different remedy, and pasting a migration policy onto it would send someone to
#: re-scaffold when they need to fix one range.
MIGRATION_POLICY = (
    "This register was built against an earlier version of the contract. There is no automatic "
    "migration: your risk specialist re-scaffolds the register at the current version and the "
    "register's content is re-entered into it. Keep this workbook - it is the source the "
    "re-entry reads from. Do not edit the contract version by hand: the version is what tells "
    "the engine which shape to expect, and changing it makes a register that loads and is then "
    "read wrongly."
)


def check_contract(present_names, methodology_grid, version_value):
    """Headless contract check. Returns ``(ok: bool, message: str)``.

    Checks: every :data:`REQUIRED_NAMED_RANGES` is present; ``Set_ContractVersion``
    equals :data:`CONTRACT_VERSION`; and ``Grid_Methodology`` carries its 13 ``CGnn``
    rows + the three mode rows. ``methodology_grid`` is the list of (label, value, …)
    row-lists exactly as the shell reads it from ``Grid_Methodology``.
    """
    problems = []

    missing = sorted(REQUIRED_NAMED_RANGES - set(present_names or ()))
    if missing:
        problems.append(f"missing named ranges: {', '.join(missing)}")

    # A version that could not be READ is not a version MISMATCH, and the two need
    # different remedies. `tier1_xlwings_shell.validate_contract` passes None when
    # `Set_ContractVersion` is absent, so without this a register missing named ranges -
    # including the version cell - would be told it "was built against an earlier version"
    # and sent to re-scaffold, when what it needs is the missing range. Part C review W1.
    version_present = version_value is not None and str(version_value).strip() != ""
    version_mismatch = version_present and str(version_value).strip() != CONTRACT_VERSION
    if not version_present:
        problems.append("Set_ContractVersion is absent or blank")
    elif version_mismatch:
        problems.append(
            f"contract version {version_value!r} != expected {CONTRACT_VERSION!r}")

    labels = {
        str(row[0]).strip()
        for row in (methodology_grid or [])
        if row and row[0] is not None
    }
    cg_rows = [
        lab for lab in labels
        if len(lab) == 4 and lab[:2] == "CG" and lab[2:].isdigit()
    ]
    if len(cg_rows) < _N_CG:
        problems.append(
            f"Grid_Methodology has {len(cg_rows)} CG rows, expected {_N_CG}")
    missing_modes = [m for m in _MODE_NAMES if m not in labels]
    if missing_modes:
        problems.append(
            f"Grid_Methodology missing mode rows: {', '.join(missing_modes)}")

    if problems:
        message = "CONTRACT INVALID: " + "; ".join(problems)
        if version_mismatch:
            message += ". " + MIGRATION_POLICY
        return False, message
    return True, (
        f"Contract OK (v{CONTRACT_VERSION}): {len(REQUIRED_NAMED_RANGES)} named "
        f"ranges present, methodology {_N_CG} CG + {len(_MODE_NAMES)} modes.")
