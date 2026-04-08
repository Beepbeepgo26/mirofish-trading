"""
Tests for BarBuilder — 1m→5m aggregation for live and historical data.
Tests: incomplete bucket, complete bucket, OHLCV, reset, resample with remainders.
"""
from app.models.order_book import Bar
from app.services.bar_builder import BarBuilder, resample_bars


class TestBarBuilder:
    """BarBuilder.add_bar() accepts Bar objects (not dicts)."""

    def _make_bar(self, o: float, h: float, low: float, c: float,
                  v: int = 100, ts: int = 0) -> Bar:
        return Bar(timestamp=ts, open=o, high=h, low=low, close=c,
                   volume=v, num_trades=10)

    def test_incomplete_bucket_returns_none(self):
        bb = BarBuilder(interval=5)
        result = bb.add_bar(self._make_bar(100, 101, 99, 100.5))
        assert result is None
        result = bb.add_bar(self._make_bar(100.5, 102, 99.5, 101))
        assert result is None

    def test_complete_bucket_returns_bar(self):
        bb = BarBuilder(interval=5)
        bars = [
            self._make_bar(100, 102, 99, 101, 200),
            self._make_bar(101, 103, 100, 102, 150),
            self._make_bar(102, 104, 101, 103, 300),
            self._make_bar(103, 105, 100, 104, 250),
            self._make_bar(104, 106, 102, 105, 100),
        ]
        result = None
        for bar in bars:
            result = bb.add_bar(bar)
        assert result is not None
        assert isinstance(result, Bar)

    def test_ohlcv_aggregation(self):
        bb = BarBuilder(interval=5)
        bars = [
            self._make_bar(100, 102, 99, 101, 200),
            self._make_bar(101, 103, 98, 102, 150),   # lowest low
            self._make_bar(102, 107, 101, 103, 300),   # highest high
            self._make_bar(103, 105, 100, 104, 250),
            self._make_bar(104, 106, 102, 105, 100),   # last close
        ]
        result = None
        for bar in bars:
            result = bb.add_bar(bar)
        assert result.open == 100           # first bar's open
        assert result.high == 107           # max high
        assert result.low == 98             # min low
        assert result.close == 105          # last bar's close
        assert result.volume == 1000        # sum of volumes

    def test_reset_clears_state(self):
        bb = BarBuilder(interval=5)
        bb.add_bar(self._make_bar(100, 101, 99, 100.5))
        bb.add_bar(self._make_bar(100.5, 102, 99.5, 101))
        assert bb.bars_in_bucket == 2
        bb.reset()
        assert bb.bars_in_bucket == 0
        assert bb.completed_bar_count == 0

    def test_second_bucket_starts_fresh(self):
        bb = BarBuilder(interval=5)
        # Fill first bucket
        for i in range(5):
            bb.add_bar(self._make_bar(100 + i, 102 + i, 99 + i, 101 + i))
        assert bb.completed_bar_count == 1
        # Second bucket needs 5 new bars
        for i in range(4):
            assert bb.add_bar(self._make_bar(200 + i, 202 + i, 199 + i, 201 + i)) is None
        result = bb.add_bar(self._make_bar(204, 206, 203, 205))
        assert result is not None
        assert result.open == 200  # first bar of second bucket
        assert bb.completed_bar_count == 2


class TestResampleBars:
    """resample_bars() works on dicts and includes partial final chunks."""

    def _make_bar(self, o: float, h: float, low: float, c: float, v: int = 100) -> dict:
        return {"open": o, "high": h, "low": low, "close": c, "volume": v}

    def test_exact_divisible(self):
        bars = [self._make_bar(100 + i, 102 + i, 99 + i, 101 + i) for i in range(10)]
        result = resample_bars(bars, interval=5)
        assert len(result) == 2

    def test_non_divisible_includes_partial(self):
        """resample_bars includes partial final chunks (7 bars → 2 resampled)."""
        bars = [self._make_bar(100 + i, 102 + i, 99 + i, 101 + i) for i in range(7)]
        result = resample_bars(bars, interval=5)
        assert len(result) == 2  # 5 bars + 2 bars = 2 resampled

    def test_single_bar_returns_one(self):
        """A single bar is a valid partial chunk."""
        bars = [self._make_bar(100, 102, 99, 101)]
        result = resample_bars(bars, interval=5)
        assert len(result) == 1

    def test_empty_input(self):
        result = resample_bars([], interval=5)
        assert len(result) == 0

    def test_resampled_ohlcv_correct(self):
        bars = [
            self._make_bar(100, 105, 95, 101, 100),
            self._make_bar(101, 110, 96, 102, 200),
            self._make_bar(102, 108, 97, 103, 150),
            self._make_bar(103, 106, 94, 104, 250),   # lowest low
            self._make_bar(104, 112, 99, 105, 300),    # highest high
        ]
        result = resample_bars(bars, interval=5)
        assert len(result) == 1
        assert result[0]["open"] == 100
        assert result[0]["high"] == 112
        assert result[0]["low"] == 94
        assert result[0]["close"] == 105
        assert result[0]["volume"] == 1000
