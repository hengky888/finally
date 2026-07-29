"""Tests for symbol normalization and validation."""

import pytest

from app.market.symbols import (
    SIMULATED_UNIVERSE,
    InvalidSymbolFormatError,
    is_simulated,
    normalize_symbol,
)


class TestNormalizeSymbol:
    """Unit tests for normalize_symbol."""

    def test_uppercases(self):
        """Lowercase input is uppercased."""
        assert normalize_symbol("aapl") == "AAPL"

    def test_strips_whitespace(self):
        """Leading/trailing whitespace is stripped."""
        assert normalize_symbol("  aapl  ") == "AAPL"

    def test_already_normalized(self):
        """Already-normalized input passes through unchanged."""
        assert normalize_symbol("AAPL") == "AAPL"

    def test_dotted_suffix(self):
        """Dotted share-class suffixes (e.g. BRK.B) are supported."""
        assert normalize_symbol("brk.b") == "BRK.B"

    def test_single_letter_symbol(self):
        """A single-letter ticker (e.g. F) is valid."""
        assert normalize_symbol("f") == "F"

    def test_five_letter_symbol(self):
        """A five-letter ticker (the max) is valid."""
        assert normalize_symbol("googl") == "GOOGL"

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "TOOLONG",  # 7 letters, over the 5-letter cap
            "123",  # digits are not letters
            "AA PL",  # embedded whitespace
            "AAPL.",  # dot with no suffix letters
            "AAPL.ABC",  # 3-letter suffix, max is 2
            "AAPL!",  # punctuation
        ],
    )
    def test_rejects_invalid_shapes(self, raw):
        """Anything that isn't plausibly a ticker raises InvalidSymbolFormatError."""
        with pytest.raises(InvalidSymbolFormatError):
            normalize_symbol(raw)

    def test_none_like_input_rejected(self):
        """A falsy, non-string input is treated as empty and rejected."""
        with pytest.raises(InvalidSymbolFormatError):
            normalize_symbol(None)

    def test_error_message_includes_original_input(self):
        """The raised error should reference the original (un-normalized) input."""
        with pytest.raises(InvalidSymbolFormatError, match=r"nope!"):
            normalize_symbol("nope!")


class TestIsSimulated:
    """Unit tests for is_simulated."""

    def test_default_watchlist_tickers_are_simulated(self):
        """All ten default watchlist tickers must be priceable by the simulator."""
        defaults = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]
        for ticker in defaults:
            assert is_simulated(ticker) is True

    def test_dotted_symbol_is_simulated(self):
        """A dotted share-class ticker in the universe is recognized."""
        assert is_simulated("BRK.B") is True

    def test_unknown_symbol_is_not_simulated(self):
        """A ticker outside the curated universe is rejected."""
        assert is_simulated("ZZZZ") is False

    def test_lowercase_is_not_simulated(self):
        """is_simulated does exact matching; callers must normalize first."""
        assert is_simulated("aapl") is False

    def test_universe_is_a_frozenset(self):
        """SIMULATED_UNIVERSE should be immutable."""
        assert isinstance(SIMULATED_UNIVERSE, frozenset)

    def test_universe_is_nonempty(self):
        """Sanity check that the universe was actually populated."""
        assert len(SIMULATED_UNIVERSE) > 10
