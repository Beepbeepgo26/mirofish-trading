"""
Bar Builder — Aggregates 1-minute OHLCV bars into 5-minute bars.
Subscribes to ohlcv-1m from Databento and emits completed 5m bars.
"""
import logging
from typing import Optional, Callable
from app.models.order_book import Bar

logger = logging.getLogger(__name__)


class BarBuilder:
    """
    Accumulates N 1-minute bars into a single aggregated bar.
    Flushes a completed bar when the bucket is full.

    Usage:
        builder = BarBuilder(interval=5, on_bar=my_callback)
        for each 1m bar from Databento:
            builder.add_bar(bar_1m)
        # on_bar is called with the completed 5m bar every 5 minutes
    """

    def __init__(self, interval: int = 5, on_bar: Optional[Callable] = None):
        """
        Args:
            interval: Number of 1-minute bars to aggregate (default 5 for 5m bars)
            on_bar: Callback function called with each completed aggregated Bar
        """
        self.interval = interval
        self.on_bar = on_bar

        # Current bucket state
        self._bucket: list[Bar] = []
        self._bar_count = 0  # Total completed aggregated bars

        # Track all 1m bars for potential multi-timeframe use later
        self._all_1m_bars: list[Bar] = []

    def add_bar(self, bar_1m: Bar) -> Optional[Bar]:
        """
        Add a 1-minute bar to the current bucket.
        Returns the completed aggregated bar if the bucket is full, else None.
        """
        self._all_1m_bars.append(bar_1m)
        self._bucket.append(bar_1m)

        if len(self._bucket) >= self.interval:
            agg_bar = self._flush()
            return agg_bar

        return None

    def _flush(self) -> Bar:
        """Build an aggregated bar from the current bucket and reset."""
        bucket = self._bucket

        agg_bar = Bar(
            timestamp=self._bar_count,
            open=bucket[0].open,
            high=max(b.high for b in bucket),
            low=min(b.low for b in bucket),
            close=bucket[-1].close,
            volume=sum(b.volume for b in bucket),
            num_trades=sum(b.num_trades for b in bucket),
            buy_volume=sum(b.buy_volume for b in bucket),
            sell_volume=sum(b.sell_volume for b in bucket),
            ts_event=bucket[-1].ts_event,  # Use the last 1m bar's timestamp
        )

        self._bar_count += 1
        self._bucket = []

        logger.info(
            f"  [5m BAR {agg_bar.timestamp}] O={agg_bar.open:.2f} "
            f"H={agg_bar.high:.2f} L={agg_bar.low:.2f} C={agg_bar.close:.2f} "
            f"V={agg_bar.volume}"
        )

        if self.on_bar:
            self.on_bar(agg_bar)

        return agg_bar

    @property
    def bars_in_bucket(self) -> int:
        """How many 1m bars are in the current incomplete bucket."""
        return len(self._bucket)

    @property
    def completed_bar_count(self) -> int:
        """Total number of completed aggregated bars."""
        return self._bar_count

    def reset(self):
        """Clear the bucket and counter."""
        self._bucket = []
        self._bar_count = 0
        self._all_1m_bars = []


def resample_bars(bars_1m: list[dict], interval: int = 5) -> list[dict]:
    """
    Resample a list of 1-minute bar dicts into larger interval bars.
    Used for historical data (not live streaming).

    Args:
        bars_1m: List of 1-minute bar dicts with open, high, low, close, volume keys
        interval: Number of minutes per output bar (default 5)

    Returns:
        List of resampled bar dicts
    """
    if not bars_1m:
        return []

    resampled = []
    for i in range(0, len(bars_1m), interval):
        chunk = bars_1m[i:i + interval]
        if not chunk:
            break

        bar = {
            "open": chunk[0]["open"],
            "high": max(b["high"] for b in chunk),
            "low": min(b["low"] for b in chunk),
            "close": chunk[-1]["close"],
            "volume": sum(b.get("volume", 0) for b in chunk),
            "timestamp_utc": chunk[-1].get("timestamp_utc", ""),
        }
        resampled.append(bar)

    logger.info(f"Resampled {len(bars_1m)} 1m bars → {len(resampled)} {interval}m bars")
    return resampled
