"""
Databento Client — Historical and Live ES futures data.
Pulls 1-minute OHLCV bars from GLBX.MDP3 (CME Globex) and converts
them into seed bar format for the simulation engine.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from app.services.bar_builder import resample_bars

logger = logging.getLogger(__name__)

# Databento import with graceful fallback
try:
    import databento as db
    DATABENTO_AVAILABLE = True
except ImportError:
    DATABENTO_AVAILABLE = False
    logger.warning("databento not installed. Run: pip install databento")


# Constants
DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1m"
SYMBOL = "ES.c.0"
STYPE = "continuous"

try:
    ET = ZoneInfo("US/Eastern")
    UTC = ZoneInfo("UTC")
except Exception:
    # Fallback for environments without tzdata (Docker will have it)
    ET = None
    UTC = None


class DatabentoClient:
    """
    Pulls ES futures 1-minute bars from Databento.
    Supports historical (any date) and recent sessions.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("DATABENTO_API_KEY", "")
        self._client = None
        self._enabled = bool(self.api_key) and DATABENTO_AVAILABLE

        if not DATABENTO_AVAILABLE:
            logger.warning("Databento SDK not available. Install with: pip install databento")
        elif not self.api_key:
            logger.warning("DATABENTO_API_KEY not set. Databento features disabled.")

    def _get_client(self):
        if self._client is None:
            self._client = db.Historical(self.api_key)
        return self._client

    def get_cost_estimate(self, date: str, start_time: str = "09:30",
                          end_time: str = "11:00", timezone: str = "US/Eastern") -> float:
        """
        Get the estimated cost in USD for a data request before pulling it.
        Returns 0.0 if Databento is unavailable.
        """
        if not self._enabled:
            return 0.0

        start_dt, end_dt = self._build_timestamps(date, start_time, end_time, timezone)

        try:
            client = self._get_client()
            cost = client.metadata.get_cost(
                dataset=DATASET,
                symbols=[SYMBOL],
                stype_in=STYPE,
                schema=SCHEMA,
                start=start_dt.isoformat(),
                end=end_dt.isoformat(),
            )
            logger.info(f"Databento cost estimate: ${cost:.4f}")
            return cost
        except Exception as e:
            logger.error(f"Cost estimate failed: {e}")
            return -1.0

    def pull_bars(self, date: str, start_time: str = "09:30",
                  end_time: str = "11:00", timezone: str = "US/Eastern",
                  max_bars: Optional[int] = None,
                  bar_interval: int = 5) -> list[dict]:
        """
        Pull 1-minute ES bars for a specific date and time window.

        Args:
            date: Date string "YYYY-MM-DD"
            start_time: Start time "HH:MM" in the specified timezone
            end_time: End time "HH:MM" in the specified timezone
            timezone: Timezone string (default "US/Eastern")
            max_bars: Optional limit on number of bars returned

        Returns:
            List of bar dicts: [{"open": float, "high": float, "low": float,
                                  "close": float, "volume": int, "timestamp_utc": str}, ...]
        """
        if not self._enabled:
            raise RuntimeError("Databento not available. Set DATABENTO_API_KEY or install databento.")

        start_dt, end_dt = self._build_timestamps(date, start_time, end_time, timezone)

        logger.info(f"Pulling ES bars: {date} {start_time}-{end_time} {timezone}")
        logger.info(f"  UTC range: {start_dt.isoformat()} → {end_dt.isoformat()}")

        try:
            client = self._get_client()
            data = client.timeseries.get_range(
                dataset=DATASET,
                schema=SCHEMA,
                symbols=[SYMBOL],
                stype_in=STYPE,
                start=start_dt.isoformat(),
                end=end_dt.isoformat(),
            )

            # Convert to DataFrame for easy handling
            df = data.to_df()

            if df.empty:
                logger.warning("No bars returned from Databento.")
                return []

            # Convert to our seed bar format
            bars = []
            for idx, row in df.iterrows():
                bar = {
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"]),
                    "timestamp_utc": idx.isoformat() if hasattr(idx, 'isoformat') else str(idx),
                }
                bars.append(bar)

            # Resample 1-minute bars to the requested interval
            if bar_interval > 1:
                bars = resample_bars(bars, interval=bar_interval)
                logger.info(f"  Resampled to {bar_interval}m: {len(bars)} bars")

            if max_bars and len(bars) > max_bars:
                bars = bars[:max_bars]

            logger.info(f"  Retrieved {len(bars)} bars. "
                        f"Price range: {min(b['low'] for b in bars):.2f} - "
                        f"{max(b['high'] for b in bars):.2f}")

            return bars

        except Exception as e:
            logger.error(f"Databento pull failed: {e}")
            raise

    def pull_recent_session(self, bars_back: int = 30) -> list[dict]:
        """
        Pull bars from the most recent RTH session.
        Tries last business day, skipping weekends.
        """
        today = datetime.now(ET or ZoneInfo("UTC"))

        # Find last business day
        if today.weekday() == 0:  # Monday
            target = today - timedelta(days=3)  # Friday
        elif today.weekday() == 6:  # Sunday
            target = today - timedelta(days=2)  # Friday
        elif today.weekday() == 5:  # Saturday
            target = today - timedelta(days=1)  # Friday
        else:
            # If before market open (9:30 ET), use yesterday
            market_open = today.replace(hour=9, minute=30, second=0)
            if today < market_open:
                target = today - timedelta(days=1)
                # Skip weekends
                while target.weekday() >= 5:
                    target -= timedelta(days=1)
            else:
                target = today

        date_str = target.strftime("%Y-%m-%d")

        # Calculate end time based on bars needed
        # 30 bars from 9:30 = 10:00 AM, 60 bars = 10:30 AM, etc.
        # Multiply by bar interval because pull_bars resamples 1m → 5m
        # To get 30 five-minute bars, we need 150 one-minute bars (150 minutes of data)
        bar_interval = 5
        minutes_needed = bars_back * bar_interval
        end_hour = 9 + (30 + minutes_needed) // 60
        end_minute = (30 + minutes_needed) % 60
        end_time = f"{end_hour:02d}:{end_minute:02d}"

        # Cap at market close
        if end_hour >= 16:
            end_time = "16:00"

        logger.info(f"Pulling recent session: {date_str} 09:30-{end_time} ET")
        return self.pull_bars(date_str, "09:30", end_time, max_bars=bars_back)

    def pull_session_with_context(self, date: str, start_time: str = "09:30",
                                   end_time: str = "11:00",
                                   timezone: str = "US/Eastern",
                                   seed_bars: int = 15,
                                   total_bars: int = 30) -> dict:
        """
        Pull bars and split into seed (known) and validation (hidden) sets.
        This is the key method for backtesting agent predictions:
        - Agents see the first `seed_bars` bars
        - We compare their predictions against the remaining bars

        Returns:
            {
                "seed_bars": [...],       # Bars agents will see
                "validation_bars": [...], # Bars to compare predictions against
                "all_bars": [...],        # Full bar sequence
                "metadata": {...}         # Session info
            }
        """
        all_bars = self.pull_bars(date, start_time, end_time, timezone,
                                  max_bars=total_bars, bar_interval=5)

        if len(all_bars) < seed_bars:
            raise ValueError(f"Only got {len(all_bars)} bars, need at least {seed_bars} for seeding.")

        seed = all_bars[:seed_bars]
        validation = all_bars[seed_bars:]

        # Compute session metadata
        metadata = {
            "date": date,
            "start_time": start_time,
            "end_time": end_time,
            "timezone": timezone,
            "total_bars_retrieved": len(all_bars),
            "seed_bar_count": len(seed),
            "validation_bar_count": len(validation),
            "session_open": seed[0]["open"],
            "session_range_high": max(b["high"] for b in all_bars),
            "session_range_low": min(b["low"] for b in all_bars),
            "seed_close": seed[-1]["close"],
            "actual_final_close": all_bars[-1]["close"] if all_bars else None,
            "actual_direction": "UP" if all_bars[-1]["close"] > seed[-1]["close"] else "DOWN"
                                if all_bars else "UNKNOWN",
        }

        return {
            "seed_bars": seed,
            "validation_bars": validation,
            "all_bars": all_bars,
            "metadata": metadata,
        }

    def _build_timestamps(self, date: str, start_time: str, end_time: str,
                          timezone: str) -> tuple:
        """Convert local date/time strings to UTC datetime objects."""
        tz = ZoneInfo(timezone)
        start_local = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        end_local = datetime.strptime(f"{date} {end_time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)
