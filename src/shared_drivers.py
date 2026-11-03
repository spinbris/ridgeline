"""RISKDRV-01 stage 1: shared risk drivers, read and checked. The engine does not use them yet.

A shared driver is an uncertainty source that acts on many activities at once and moves cost and
time together (Hulett's risk-driver method, AACE 57R-09). It is always present (probability 1),
so it is not a register risk and not a strawman row: hard invariant 2 (the strawman's Time=Yes
rows are the risks that simulate) is untouched. "Shared" keeps the name apart from
``src.sra.cpm.risk_driver_schema.RiskDriver``, which is a per-(risk, activity) mapping.

Two kinds (Director, 02/11/2026, plan R1):

* ``P`` productivity: its own PERT range on the proportional duration delta (P10 / mode / P90,
  read as percentiles like a Layer 1 factor). It scales the original duration of the
  activities under its WBS codes, and the named cost-grid rows and columns by the same delta.
* ``Q`` quantity-linked: no range of its own. It reuses the draw of the one Layer 1 quantity
  factor it names, scaled by an elasticity, on the durations under its WBS codes only. The
  quantity factor already prices the cost, so a ``Q`` driver adds none.

Stage 1 built the sheet, the reader and the checks; stage 2 simulates the drivers
(``src.integrated.base_layer`` draws them, ``src.integrated.driver_pass`` replays the schedule
with them). A register without the sheet runs as before, byte for byte.

Header-driven (hard invariant 10): columns are found by name in the sheet's header row.
Pure data (hard invariant 9).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

#: The register sheet that declares a project's shared drivers. Absent means no drivers.
SHEET = "Shared_Drivers"

#: The two driver kinds (plan R1).
KINDS: tuple[str, ...] = ("P", "Q")

#: The header the reader looks for; every column it reads must be present by name.
COLUMNS: tuple[str, ...] = (
    "Driver_ID", "Name", "Kind", "Tag", "P10", "Mode", "P90", "Linked_Factors", "Elasticity",
    "WBS_Codes", "Grid_Rows", "Grid_Columns", "Ruled_Risks", "Basis",
)

#: A Layer 1 factor with this driver tag prices project time, which the CPM delay cost already
#: prices (INTSCURVE-01 D-4). A quantity-linked driver may not borrow its draw.
_TIME_TAG = "duration"


class SharedDriverError(ValueError):
    """A shared-driver declaration that cannot be used, named by driver and field."""


@dataclass(frozen=True)
class SharedDriver:
    """One declared shared driver. Ranges are proportional deltas on duration (0.2 = +20%)."""

    driver_id: str
    name: str
    kind: str
    tag: str
    p10: float | None
    mode: float | None
    p90: float | None
    linked_factors: tuple[str, ...]
    elasticity: float | None
    wbs_codes: tuple[str, ...]
    grid_rows: tuple[str, ...]
    grid_columns: tuple[str, ...]
    ruled_risks: tuple[str, ...]
    basis: str


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _text(v: Any) -> str:
    return "" if _blank(v) else str(v).strip()


def _list(v: Any) -> tuple[str, ...]:
    """A comma- or semicolon-separated cell as a tuple of trimmed names; blank is empty."""
    if _blank(v):
        return ()
    return tuple(p.strip() for p in str(v).replace(";", ",").split(",") if p.strip())


def _num(v: Any, *, where: str) -> float | None:
    if _blank(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise SharedDriverError(f"{where}: {v!r} is not a number") from None


def parse_shared_drivers(rows: Iterable[tuple[Any, ...]], *, source: str = SHEET
                         ) -> tuple[SharedDriver, ...]:
    """The drivers in a sheet's rows. The header is the first row whose cells include
    ``Driver_ID``; rows after it with a blank ``Driver_ID`` are skipped (notes, spacing)."""
    rows = list(rows)
    header_at = next((i for i, r in enumerate(rows)
                      if any(_text(c) == "Driver_ID" for c in r)), None)
    if header_at is None:
        raise SharedDriverError(f"{source}: no header row carrying 'Driver_ID'")
    header = [_text(c) for c in rows[header_at]]
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise SharedDriverError(f"{source}: header is missing column(s) {missing}")
    col = {name: header.index(name) for name in COLUMNS}

    out: list[SharedDriver] = []
    for r in rows[header_at + 1:]:
        cell = (lambda name, r=r: r[col[name]] if col[name] < len(r) else None)
        did = _text(cell("Driver_ID"))
        if not did:
            continue
        where = f"{source} driver {did}"
        out.append(SharedDriver(
            driver_id=did,
            name=_text(cell("Name")),
            kind=_text(cell("Kind")).upper(),
            tag=_text(cell("Tag")),
            p10=_num(cell("P10"), where=f"{where} P10"),
            mode=_num(cell("Mode"), where=f"{where} Mode"),
            p90=_num(cell("P90"), where=f"{where} P90"),
            linked_factors=_list(cell("Linked_Factors")),
            elasticity=_num(cell("Elasticity"), where=f"{where} Elasticity"),
            wbs_codes=_list(cell("WBS_Codes")),
            grid_rows=_list(cell("Grid_Rows")),
            grid_columns=_list(cell("Grid_Columns")),
            ruled_risks=_list(cell("Ruled_Risks")),
            basis=_text(cell("Basis")),
        ))
    return tuple(out)


def read_shared_drivers(register_path: str | Path) -> tuple[SharedDriver, ...]:
    """The register's declared drivers, or ``()`` when it has no ``Shared_Drivers`` sheet."""
    import openpyxl

    wb = openpyxl.load_workbook(register_path, read_only=True, data_only=True)
    try:
        if SHEET not in wb.sheetnames:
            return ()
        rows = list(wb[SHEET].iter_rows(values_only=True))
    finally:
        wb.close()
    return parse_shared_drivers(rows, source=f"{Path(register_path).name}!{SHEET}")


def validate_shared_drivers(
    drivers: Iterable[SharedDriver],
    *,
    layer1: Any,
    wbs_codes: Iterable[str],
    risk_ids: Iterable[str],
) -> None:
    """Refuse, naming every problem at once, any driver the engine could not use safely.

    ``layer1`` is the register's ``Layer1Config`` (or ``None`` with Layer 1 off); ``wbs_codes``
    are the schedule's WBS short names; ``risk_ids`` the register's risk IDs. The double-count
    rules: a ``P`` driver's tag may not be any Layer 1 factor's driver tag (one source owns one
    uncertainty), a ``Q`` driver may not borrow a time-priced factor, and no two drivers may act
    on the same WBS code.
    """
    drivers = tuple(drivers)
    if not drivers:
        return
    issues: list[str] = []
    wbs = set(wbs_codes)
    risks = set(risk_ids)
    if layer1 is None:
        issues.append("drivers are declared but Layer 1 is off: both kinds act through Layer 1")
    factors = {f.name: f for f in (layer1.factors if layer1 is not None else ())}
    factor_tags = {str(f.driver).strip().lower() for f in factors.values()}
    rows = set(layer1.row_labels) if layer1 is not None else set()
    cols = set(layer1.col_labels) if layer1 is not None else set()

    seen_ids: set[str] = set()
    owner_of: dict[str, str] = {}
    for d in drivers:
        w = f"driver {d.driver_id}"
        if d.driver_id in seen_ids:
            issues.append(f"{w}: duplicate Driver_ID")
        seen_ids.add(d.driver_id)
        if d.kind not in KINDS:
            issues.append(f"{w}: Kind {d.kind!r} is not one of {KINDS}")
        if not d.wbs_codes:
            issues.append(f"{w}: no WBS_Codes, so it acts on no activity")
        for code in d.wbs_codes:
            if code not in wbs:
                issues.append(f"{w}: WBS code {code!r} is not in the schedule")
            elif code in owner_of:
                issues.append(f"{w}: WBS code {code!r} is already driven by {owner_of[code]}")
            else:
                owner_of[code] = d.driver_id
        for rid in d.ruled_risks:
            if rid not in risks:
                issues.append(f"{w}: Ruled_Risks names {rid!r}, which is not in the register")
        if not d.basis:
            issues.append(f"{w}: no Basis; a range without its stated basis is not reviewable")

        if d.kind == "P":
            if None in (d.p10, d.mode, d.p90):
                issues.append(f"{w}: a P driver needs P10, Mode and P90")
            elif not (d.p10 <= d.mode <= d.p90) or d.p10 == d.p90:
                issues.append(f"{w}: P10 <= Mode <= P90 with P10 < P90 does not hold")
            elif d.p10 <= -1.0:
                issues.append(f"{w}: P10 {d.p10} would make a duration zero or negative")
            if not d.tag:
                issues.append(f"{w}: a P driver needs a Tag for the double-count check")
            elif d.tag.lower() in factor_tags:
                issues.append(f"{w}: Tag {d.tag!r} is already a Layer 1 factor's driver; one "
                              "source must own one uncertainty")
            if d.linked_factors or d.elasticity is not None:
                issues.append(f"{w}: Linked_Factors and Elasticity are for Q drivers only")
            if not d.grid_rows or not d.grid_columns:
                issues.append(f"{w}: a P driver needs Grid_Rows and Grid_Columns for its cost")
            for r in d.grid_rows:
                if layer1 is not None and r not in rows:
                    issues.append(f"{w}: grid row {r!r} is not in Layer1_Base")
            for c in d.grid_columns:
                if layer1 is not None and c not in cols:
                    issues.append(f"{w}: grid column {c!r} is not in Layer1_Base")
        elif d.kind == "Q":
            if len(d.linked_factors) != 1:
                issues.append(f"{w}: a Q driver links exactly one Layer 1 factor, so each "
                              "WBS code's duration follows one quantity; got "
                              f"{len(d.linked_factors)}")
            for name in d.linked_factors:
                f = factors.get(name)
                if f is None:
                    if layer1 is not None:
                        issues.append(f"{w}: linked factor {name!r} is not a Layer 1 factor")
                elif str(f.driver).strip().lower() == _TIME_TAG:
                    issues.append(f"{w}: linked factor {name!r} prices project time, which the "
                                  "delay cost already prices (D-4)")
            if d.elasticity is None or d.elasticity <= 0:
                issues.append(f"{w}: a Q driver needs a positive Elasticity")
            if any(v is not None for v in (d.p10, d.mode, d.p90)):
                issues.append(f"{w}: a Q driver takes its range from its linked factor; leave "
                              "P10, Mode and P90 blank")
            if d.grid_rows or d.grid_columns:
                issues.append(f"{w}: a Q driver adds no cost; leave Grid_Rows and Grid_Columns "
                              "blank")
    if issues:
        raise SharedDriverError(
            "RISKDRV-01: the register's shared drivers cannot be used:\n  - "
            + "\n  - ".join(issues))
