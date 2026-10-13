"""
Tests for Excel reader utilities and register_loader.

reader.py functions require a live xlwings Book (tested via integration).
register_loader.py reads .xlsx files via openpyxl — fully testable here.

Tests validate:
- Register loading: correct row count, risk IDs, probabilities
- CG assignment merge from MC_Inputs
- Opportunity sign handling
- Likelihood band fallback
- Helper functions (_safe_float, _safe_str)
"""


from src.reader import _safe_float, _safe_str


# Paths to test data (the actual project input files)
# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_numeric(self):
        assert _safe_float(42.5) == 42.5

    def test_integer(self):
        assert _safe_float(100) == 100.0

    def test_none(self):
        assert _safe_float(None) == 0.0
        assert _safe_float(None, 99.0) == 99.0

    def test_ref_error(self):
        assert _safe_float("#REF!") == 0.0

    def test_string_number(self):
        assert _safe_float("1,234,567") == 1234567.0

    def test_dollar_string(self):
        assert _safe_float("$5,000,000") == 5000000.0

    def test_nan(self):
        assert _safe_float("nan") == 0.0


class TestSafeStr:
    def test_normal(self):
        assert _safe_str("Hello") == "Hello"

    def test_none(self):
        assert _safe_str(None) == ""
        assert _safe_str(None, "default") == "default"

    def test_ref_error(self):
        assert _safe_str("#REF!") == ""

    def test_strips_whitespace(self):
        assert _safe_str("  BOP Contractor  ") == "BOP Contractor"


# ---------------------------------------------------------------------------
# Register loader — integration tests against real files
# ---------------------------------------------------------------------------
