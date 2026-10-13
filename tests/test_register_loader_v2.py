"""
Tests for load_from_register_v2() — master-register format loader.

Covers: format detection, CG map, probability fallback, negative costs,
old format delegation, missing file handling, zero-cost counting.
"""

import pytest

from src.register_loader import load_from_register_v2, load_from_register

# Paths to test registers
# CG map from Stage 1 brief (subset for testing)
# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# V2 loader — new format
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# V2 loader — old format delegation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestV2LoaderErrors:

    def test_missing_file_raises(self):
        """Missing file gives FileNotFoundError with clear message."""
        with pytest.raises(FileNotFoundError, match="not found"):
            load_from_register_v2("nonexistent_file.xlsx")

# ---------------------------------------------------------------------------
# Header detection helper
# ---------------------------------------------------------------------------
