"""Tests for src.sra.cpm.xer_reader (SR-S3-Beta-01).

Three test classes:

* **Live-file** — a committed P6 export (the Stage 3 input shape).
* **Synthetic-XER** — minimal hand-constructed XERs covering project-agnostic
  edge cases. These are the *reusability gate*: the parser must work on
  any XER, not just the committed one. Synthetic XERs are constructed via
  ``_make_synthetic_xer`` from a column / row spec, ensuring they are
  XER-format-valid by construction without referencing that file.
* **Encoding** — cp1252 (the documented Primavera default) and UTF-8
  fallback paths.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.sra.cpm.xer_reader import parse_xer, validate_xer_tables

# ---------------------------------------------------------------------------
# Live-file fixture
# ---------------------------------------------------------------------------

# Repository root resolved from this test file's location:
#   tests/sra/cpm/test_xer_reader.py → repo root is parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: REFRETIRE-01 (D-2): the committed synthetic schedule, which every machine has. This was the
#: retired project's 22 MB export, so the live-file tests below skipped everywhere.
_LIVE_XER = _REPO_ROOT / "tests" / "fixtures" / "synthetic_wind" / "wind_schedule.xer"


@pytest.fixture(scope="module")
def live_tables() -> dict[str, pd.DataFrame]:
    """Parse the committed .xer once per module."""
    return parse_xer(_LIVE_XER)


# ---------------------------------------------------------------------------
# Synthetic-XER builder
# ---------------------------------------------------------------------------

def _make_synthetic_xer(
    tables: list[tuple[str, list[str], list[list[str]]]],
    *,
    include_ermhdr: bool = True,
    include_terminator: bool = True,
) -> str:
    """Build a minimal XER format string from a list of table specs.

    Each table spec is ``(table_name, columns, rows)`` where ``rows`` is a
    list-of-list-of-str. The resulting string is XER-format-valid by
    construction.
    """
    parts: list[str] = []
    if include_ermhdr:
        parts.append(
            "ERMHDR\t26.4\t2026-04-22\tProject\tsynthetic@example.com"
            "\tSynthetic User\ttestdb\tProject Management Cloud\tUSD"
        )
    for table_name, columns, rows in tables:
        parts.append(f"%T\t{table_name}")
        parts.append("%F\t" + "\t".join(columns))
        for row in rows:
            parts.append("%R\t" + "\t".join(row))
    if include_terminator:
        parts.append("%E")
    return "\n".join(parts) + "\n"


def _minimal_full_xer_spec() -> list[tuple[str, list[str], list[list[str]]]]:
    """Return a spec covering all required tables with minimum valid rows."""
    return [
        (
            "CALENDAR",
            [
                "clndr_id",
                "default_flag",
                "clndr_name",
                "proj_id",
                "base_clndr_id",
                "last_chng_date",
                "clndr_type",
                "day_hr_cnt",
                "week_hr_cnt",
                "month_hr_cnt",
                "year_hr_cnt",
                "rsrc_private",
                "clndr_data",
            ],
            [
                [
                    "1000",
                    "Y",
                    "Standard 5-Day",
                    "100",
                    "",
                    "2026-01-01 00:00",
                    "CA_Project",
                    "8",
                    "40",
                    "172",
                    "2000",
                    "N",
                    "(0||CalendarData()(()))",
                ]
            ],
        ),
        (
            "PROJWBS",
            [
                "wbs_id",
                "proj_id",
                "obs_id",
                "seq_num",
                "est_wt",
                "proj_node_flag",
                "sum_data_flag",
                "status_code",
                "wbs_short_name",
                "wbs_name",
                "phase_id",
                "parent_wbs_id",
                "ev_user_pct",
                "ev_etc_user_value",
                "orig_cost",
                "indep_remain_total_cost",
                "ann_dscnt_rate_pct",
                "dscnt_period_type",
                "indep_remain_work_qty",
                "anticip_start_date",
                "anticip_end_date",
                "ev_compute_type",
                "ev_etc_compute_type",
                "guid",
                "tmpl_guid",
                "plan_open_state",
            ],
            [
                [
                    "10",
                    "100",
                    "1",
                    "1",
                    "1",
                    "Y",
                    "N",
                    "WS_Open",
                    "ROOT",
                    "Root WBS",
                    "",
                    "",
                    "0.5",
                    "0",
                    "0",
                    "0",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "EC_Cmp_pct",
                    "EE_Rem_hr",
                    "abc-1",
                    "",
                    "",
                ]
            ],
        ),
        (
            "TASK",
            [
                "task_id",
                "proj_id",
                "wbs_id",
                "clndr_id",
                "phys_complete_pct",
                "task_type",
                "duration_type",
                "status_code",
                "task_code",
                "task_name",
                "rsrc_id",
                "total_float_hr_cnt",
                "free_float_hr_cnt",
                "remain_drtn_hr_cnt",
                "target_drtn_hr_cnt",
                "early_start_date",
                "early_end_date",
                "late_start_date",
                "late_end_date",
                "target_start_date",
                "target_end_date",
                "cstr_date",
                "cstr_type",
                "driving_path_flag",
            ],
            [
                [
                    "1",
                    "100",
                    "10",
                    "1000",
                    "0",
                    "TT_Task",
                    "DT_FixedDUR2",
                    "TK_NotStart",
                    "A100",
                    "Mobilise",
                    "",
                    "0",
                    "0",
                    "80",
                    "80",
                    "2026-05-01 07:00",
                    "2026-05-10 17:00",
                    "2026-05-01 07:00",
                    "2026-05-10 17:00",
                    "2026-05-01 07:00",
                    "2026-05-10 17:00",
                    "",
                    "",
                    "Y",
                ],
                [
                    "2",
                    "100",
                    "10",
                    "1000",
                    "0",
                    "TT_Task",
                    "DT_FixedDUR2",
                    "TK_NotStart",
                    "A200",
                    "Excavate",
                    "",
                    "0",
                    "0",
                    "160",
                    "160",
                    "2026-05-11 07:00",
                    "2026-05-30 17:00",
                    "2026-05-11 07:00",
                    "2026-05-30 17:00",
                    "2026-05-11 07:00",
                    "2026-05-30 17:00",
                    "",
                    "",
                    "Y",
                ],
                [
                    "3",
                    "100",
                    "10",
                    "1000",
                    "0",
                    "TT_Task",
                    "DT_FixedDUR2",
                    "TK_NotStart",
                    "A300",
                    "Concrete pour",
                    "",
                    "0",
                    "0",
                    "120",
                    "120",
                    "2026-05-31 07:00",
                    "2026-06-15 17:00",
                    "2026-05-31 07:00",
                    "2026-06-15 17:00",
                    "2026-05-31 07:00",
                    "2026-06-15 17:00",
                    "",
                    "",
                    "Y",
                ],
                [
                    "4",
                    "100",
                    "10",
                    "1000",
                    "0",
                    "TT_FinMile",
                    "DT_FixedDUR2",
                    "TK_NotStart",
                    "A999",
                    "Finish",
                    "",
                    "0",
                    "0",
                    "0",
                    "0",
                    "2026-06-15 17:00",
                    "2026-06-15 17:00",
                    "2026-06-15 17:00",
                    "2026-06-15 17:00",
                    "2026-06-15 17:00",
                    "2026-06-15 17:00",
                    "",
                    "",
                    "N",
                ],
            ],
        ),
        (
            "TASKPRED",
            [
                "task_pred_id",
                "task_id",
                "pred_task_id",
                "proj_id",
                "pred_proj_id",
                "pred_type",
                "lag_hr_cnt",
                "comments",
                "float_path",
                "aref",
                "arls",
            ],
            [
                ["1", "2", "1", "100", "100", "PR_FS", "0", "", "", "", ""],
                ["2", "3", "2", "100", "100", "PR_FS", "0", "", "", "", ""],
                ["3", "4", "3", "100", "100", "PR_FS", "0", "", "", "", ""],
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# Live-file tests (a real .xer, committed)
# ---------------------------------------------------------------------------

class TestLiveFile:
    """Live-file tests against a committed P6 export.

    REFRETIRE-01 (D-2): these read the retired project's export and skipped everywhere. The
    exact table row counts they asserted were that file's own and went with it; the structural
    checks - validation, canonical link types, date and lag types - are what the file is here
    to exercise and hold for any export."""

    @pytest.mark.wallclock  # measures the box, not the code: reds under -n auto
    def test_the_parser_opens_the_live_file_within_budget(self) -> None:
        """Parser opens the live file without error within a generous wall-time budget."""
        t0 = time.perf_counter()
        tables = parse_xer(_LIVE_XER)
        elapsed = time.perf_counter() - t0
        assert tables is not None
        # Per brief §7 risk row: budget < 5s on a typical dev machine.
        assert elapsed < 5.0, f"parse_xer took {elapsed:.2f}s (budget 5s)"

    def test_the_required_tables_are_present_and_populated(
        self, live_tables: dict[str, pd.DataFrame]
    ) -> None:
        """The tables the kernel reads are there and carry rows. The exact counts that stood
        here were one export's own; what the kernel needs is presence and content."""
        for table_name in ("TASK", "TASKPRED", "CALENDAR", "PROJWBS"):
            assert table_name in live_tables, f"missing table {table_name}"
            assert len(live_tables[table_name]) > 0, f"{table_name} parsed as empty"

    def test_required_columns_present(
        self, live_tables: dict[str, pd.DataFrame]
    ) -> None:
        """validate_xer_tables passes without raising on the live file."""
        validate_xer_tables(live_tables)

    def test_pred_types_canonical(
        self, live_tables: dict[str, pd.DataFrame]
    ) -> None:
        """Every TASKPRED.pred_type is one of the canonical four."""
        canonical = {"PR_FS", "PR_SS", "PR_FF", "PR_SF"}
        observed = set(live_tables["TASKPRED"]["pred_type"].unique())
        # A schedule may not exercise all four; assert subset.
        assert observed <= canonical, f"unexpected pred_type values: {observed - canonical}"
        # And FS must be present (it's the dominant link type).
        assert "PR_FS" in observed

    def test_lag_units_hours(
        self, live_tables: dict[str, pd.DataFrame]
    ) -> None:
        """All TASKPRED.lag_hr_cnt values parse as numeric (hours, signed)."""
        lag = live_tables["TASKPRED"]["lag_hr_cnt"]
        assert pd.api.types.is_float_dtype(lag), f"lag_hr_cnt dtype {lag.dtype} not float"
        # All values numeric (no NaN expected — Primavera writes 0 for no lag).
        assert lag.notna().all(), "lag_hr_cnt has unexpected NaN values"

    def test_dates_parsed(
        self, live_tables: dict[str, pd.DataFrame]
    ) -> None:
        """TASK date columns parse cleanly to pandas Timestamps."""
        task = live_tables["TASK"]
        for col in (
            "early_start_date",
            "early_end_date",
            "late_start_date",
            "late_end_date",
        ):
            assert pd.api.types.is_datetime64_any_dtype(task[col]), (
                f"{col} dtype is {task[col].dtype}, expected datetime64"
            )
        # Most rows have non-null early_start_date (some may be NaT for
        # finish-only milestones); assert ≥ 99% non-null as a sanity check.
        non_null_frac = task["early_start_date"].notna().mean()
        assert non_null_frac > 0.99, (
            f"early_start_date {non_null_frac:.2%} non-null, expected >99%"
        )


# ---------------------------------------------------------------------------
# Synthetic-XER smoke tests (project-agnostic)
# ---------------------------------------------------------------------------

class TestSyntheticXer:
    """Reusability gate: parser works on any XER, not just the committed one."""

    def test_synthetic_xer_minimal(self, tmp_path: Path) -> None:
        """A minimal hand-constructed XER parses to expected DataFrames."""
        xer_text = _make_synthetic_xer(_minimal_full_xer_spec())
        xer_path = tmp_path / "minimal.xer"
        xer_path.write_text(xer_text, encoding="utf-8")

        tables = parse_xer(xer_path)
        validate_xer_tables(tables)

        assert set(tables.keys()) == {"CALENDAR", "PROJWBS", "TASK", "TASKPRED"}
        assert len(tables["TASK"]) == 4
        assert len(tables["TASKPRED"]) == 3
        assert len(tables["CALENDAR"]) == 1
        assert len(tables["PROJWBS"]) == 1
        # Spot-check a typed value
        assert tables["TASK"]["task_id"].iloc[0] == 1
        assert tables["TASK"]["target_drtn_hr_cnt"].iloc[0] == np.float32(80.0)
        assert tables["TASK"]["task_code"].iloc[0] == "A100"
        # Spot-check pred linking
        assert tables["TASKPRED"]["pred_type"].iloc[0] == "PR_FS"

    def test_synthetic_xer_missing_required_table_raises(
        self, tmp_path: Path
    ) -> None:
        """An XER without a TASK table raises ValueError."""
        spec = [
            (
                "CALENDAR",
                ["clndr_id", "clndr_name", "default_flag", "clndr_data",
                 "day_hr_cnt", "week_hr_cnt", "month_hr_cnt", "year_hr_cnt"],
                [["1", "Cal", "Y", "()", "8", "40", "172", "2000"]],
            ),
            (
                "TASKPRED",
                ["task_pred_id", "task_id", "pred_task_id", "pred_type", "lag_hr_cnt"],
                [],
            ),
        ]
        xer_path = tmp_path / "no_task.xer"
        xer_path.write_text(_make_synthetic_xer(spec), encoding="utf-8")

        with pytest.raises(ValueError, match=r"missing required table.*TASK"):
            parse_xer(xer_path)

    def test_synthetic_xer_missing_required_column_raises(
        self, tmp_path: Path
    ) -> None:
        """XER with TASK present but missing task_id raises ValueError."""
        spec = _minimal_full_xer_spec()
        # Drop `task_id` from the TASK columns and the leading value from each row.
        for i, (name, columns, rows) in enumerate(spec):
            if name == "TASK":
                new_columns = [c for c in columns if c != "task_id"]
                idx = columns.index("task_id")
                new_rows = [r[:idx] + r[idx + 1:] for r in rows]
                spec[i] = (name, new_columns, new_rows)
                break

        xer_path = tmp_path / "task_no_id.xer"
        xer_path.write_text(_make_synthetic_xer(spec), encoding="utf-8")

        tables = parse_xer(xer_path)  # parse_xer succeeds (TASK is present)
        with pytest.raises(ValueError, match=r"task_id"):
            validate_xer_tables(tables)

    def test_synthetic_xer_no_ermhdr_raises(self, tmp_path: Path) -> None:
        """A file without an ERMHDR header raises ValueError."""
        xer_text = _make_synthetic_xer(
            _minimal_full_xer_spec(), include_ermhdr=False
        )
        xer_path = tmp_path / "no_header.xer"
        xer_path.write_text(xer_text, encoding="utf-8")

        with pytest.raises(ValueError, match=r"ERMHDR"):
            parse_xer(xer_path)

    def test_synthetic_xer_empty_table_handled(self, tmp_path: Path) -> None:
        """A table with %T+%F but zero %R rows produces an empty DataFrame."""
        spec = _minimal_full_xer_spec()
        # Add an empty UDFTYPE table (not in required set).
        spec.append(
            (
                "UDFTYPE",
                [
                    "udf_type_id",
                    "table_name",
                    "udf_type_name",
                    "udf_type_label",
                    "logical_data_type",
                    "super_flag",
                    "indicator_expression",
                    "summary_indicator_expression",
                    "export_flag",
                ],
                [],
            )
        )
        xer_path = tmp_path / "empty_udf.xer"
        xer_path.write_text(_make_synthetic_xer(spec), encoding="utf-8")

        tables = parse_xer(xer_path)
        assert "UDFTYPE" in tables
        assert len(tables["UDFTYPE"]) == 0
        assert list(tables["UDFTYPE"].columns) == [
            "udf_type_id",
            "table_name",
            "udf_type_name",
            "udf_type_label",
            "logical_data_type",
            "super_flag",
            "indicator_expression",
            "summary_indicator_expression",
            "export_flag",
        ]
        # Dtype contract holds for empty tables: suffix rules apply even with
        # zero rows, so downstream dtype-guards behave consistently.
        assert tables["UDFTYPE"]["udf_type_id"].dtype == "Int64"

    def test_synthetic_xer_unknown_table_passes_through(
        self, tmp_path: Path
    ) -> None:
        """Tables not in _REQUIRED_COLUMNS are still parsed and returned."""
        spec = _minimal_full_xer_spec()
        spec.append(
            (
                "FUTURE_FEATURE_TABLE",
                ["id", "label", "weight_pct"],
                [["1", "alpha", "0.25"], ["2", "beta", "0.75"]],
            )
        )
        xer_path = tmp_path / "extra_table.xer"
        xer_path.write_text(_make_synthetic_xer(spec), encoding="utf-8")

        tables = parse_xer(xer_path)
        assert "FUTURE_FEATURE_TABLE" in tables
        assert len(tables["FUTURE_FEATURE_TABLE"]) == 2
        # validate_xer_tables only checks _REQUIRED_COLUMNS — should still pass.
        validate_xer_tables(tables)

    def test_synthetic_xer_extra_columns_handled(self, tmp_path: Path) -> None:
        """Required-table extra columns parse cleanly and remain in the DataFrame."""
        spec = _minimal_full_xer_spec()
        # Extend TASK with two extra columns.
        for i, (name, columns, rows) in enumerate(spec):
            if name == "TASK":
                new_columns = list(columns) + ["custom_text", "custom_pct"]
                new_rows = [list(r) + ["custom-value", "0.42"] for r in rows]
                spec[i] = (name, new_columns, new_rows)
                break
        xer_path = tmp_path / "extra_cols.xer"
        xer_path.write_text(_make_synthetic_xer(spec), encoding="utf-8")

        tables = parse_xer(xer_path)
        validate_xer_tables(tables)
        assert "custom_text" in tables["TASK"].columns
        assert "custom_pct" in tables["TASK"].columns
        # Suffix-rule routes _pct to float32.
        assert tables["TASK"]["custom_pct"].dtype == np.float32
        # custom_text stays as string.
        assert tables["TASK"]["custom_text"].iloc[0] == "custom-value"


# ---------------------------------------------------------------------------
# Encoding tests
# ---------------------------------------------------------------------------

class TestEncoding:
    """cp1252 default with automatic UTF-8 detection for non-Primavera files."""

    def test_utf8_fallback_synthetic(self, tmp_path: Path) -> None:
        """A pure-UTF-8 (ASCII-only) XER parses cleanly."""
        spec = _minimal_full_xer_spec()
        xer_path = tmp_path / "utf8.xer"
        xer_path.write_text(_make_synthetic_xer(spec), encoding="utf-8")

        tables = parse_xer(xer_path)
        validate_xer_tables(tables)
        assert len(tables["TASK"]) == 4

    def test_encoding_smart_quote_in_task_name(self, tmp_path: Path) -> None:
        """A smart quote (cp1252 byte 0x92) round-trips correctly.

        The cp1252-specific right-single-quotation-mark character (0x92)
        is not a valid UTF-8 lead byte; the parser must fall back to
        cp1252 and preserve the character.
        """
        spec = _minimal_full_xer_spec()
        # Inject a smart quote into a task_name. We write the file as cp1252
        # bytes directly (bypassing UTF-8) to mimic Primavera's output.
        for i, (name, columns, rows) in enumerate(spec):
            if name == "TASK":
                idx = columns.index("task_name")
                rows[0][idx] = "Site walk’through"  # U+2019 right single quote
                spec[i] = (name, columns, rows)
                break
        xer_text = _make_synthetic_xer(spec)
        xer_bytes = xer_text.encode("cp1252")
        xer_path = tmp_path / "smart_quote.xer"
        xer_path.write_bytes(xer_bytes)

        tables = parse_xer(xer_path)
        validate_xer_tables(tables)
        assert tables["TASK"]["task_name"].iloc[0] == "Site walk’through"

    def test_zip_archive_raises_clear_error(self, tmp_path: Path) -> None:
        """SR-S3-Beta-10: feeding a .xlsx (or any ZIP) to parse_xer raises
        a ValueError with a clear, actionable message — not a cryptic
        UnicodeDecodeError. Catches the family of wiring bug that fed
        Stage 2.5's longest-path xlsx into the Stage 3 xer_path slot.
        """
        zip_path = tmp_path / "looks_like.xer"
        # Real-ish minimal ZIP archive — End-of-central-directory record only.
        # First 4 bytes are the local file header magic 50 4B 03 04.
        zip_path.write_bytes(
            b"PK\x03\x04"
            + b"\x14\x00\x00\x00\x08\x00"  # version + flags + compression
            + b"\x00" * 22                  # rest of header padding
            + b"PK\x05\x06" + b"\x00" * 18  # End-of-central-directory record
        )

        with pytest.raises(ValueError, match="ZIP archive"):
            parse_xer(zip_path)

        # Message also says what to point the binding at, so the operator
        # has somewhere to look.
        with pytest.raises(ValueError, match="schedule export"):
            parse_xer(zip_path)

    def test_undefined_cp1252_byte_falls_back_to_latin1(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """SR-S3-Beta-10: an XER containing a CP1252-undefined byte
        (one of 0x81, 0x8D, 0x8F, 0x90, 0x9D) decodes via the Latin-1
        final fallback rather than raising. The fallback emits a
        ``logger.warning`` so it is not silent.
        """
        spec = _minimal_full_xer_spec()
        # Inject a 0x81 byte into a task_name. 0x81 is a CP1252-undefined
        # slot — strict CP1252 decode raises here. We write the file as
        # raw bytes to bypass any encoder's own validation.
        for i, (name, columns, rows) in enumerate(spec):
            if name == "TASK":
                idx = columns.index("task_name")
                # Marker we'll find post-decode. The 0x81 lands inside the
                # task name to verify Latin-1 round-trips it (Latin-1 byte
                # 0x81 → Unicode U+0081, the HOP control character).
                rows[0][idx] = "MARKER_BEFORE\x81MARKER_AFTER"
                spec[i] = (name, columns, rows)
                break
        xer_text = _make_synthetic_xer(spec)
        # Write as Latin-1 so the 0x81 byte is preserved in the file.
        xer_path = tmp_path / "latin1_fallback.xer"
        xer_path.write_bytes(xer_text.encode("latin-1"))

        import logging as _logging
        with caplog.at_level(_logging.WARNING, logger="src.sra.cpm.xer_reader"):
            tables = parse_xer(xer_path)

        validate_xer_tables(tables)
        # Round-trip preserved the 0x81 byte as U+0081.
        assert (
            tables["TASK"]["task_name"].iloc[0]
            == "MARKER_BEFOREMARKER_AFTER"
        )
        # Warning was emitted, naming the file and the fallback path.
        assert any(
            "latin-1 fallback" in rec.getMessage()
            for rec in caplog.records
        ), f"Expected 'latin-1 fallback' in warnings; got {[r.getMessage() for r in caplog.records]}"
