"""
Session Context — Time-of-day awareness for ES futures agents.
Provides session classification, Al Brooks time guidance, and cooldown management.
All times are in US/Central (CT) — CME's native timezone.
"""
import logging
from datetime import datetime, time
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

CT = ZoneInfo("US/Central")
ET = ZoneInfo("US/Eastern")


@dataclass
class SessionInfo:
    """Current session context for agent prompts."""
    session_name: str          # e.g. "OPENING_30MIN", "MORNING", "LUNCH_LULL"
    time_et: str               # Human-readable time in ET
    minutes_since_rth_open: int
    bars_since_rth_open: int   # On 5m chart
    brooks_guidance: str       # What Al Brooks teaches about this time
    trade_aggressiveness: str  # "HIGH", "MODERATE", "LOW", "SKIP"
    volatility_regime: str     # "VERY_HIGH", "HIGH", "MODERATE", "LOW"
    vol_multiplier: float      # Scaling factor for stops/targets (1.0 = average)


def classify_session(dt: datetime, bar_interval_minutes: int = 5) -> SessionInfo:
    """
    Classify the current trading session based on time of day.
    Returns session context that gets injected into every agent prompt.

    Args:
        dt: Current datetime (timezone-aware, or UTC)
        bar_interval_minutes: Bar interval for calculating bars since open
    """
    # Convert to Eastern time
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    dt_et = dt.astimezone(ET)
    t = dt_et.time()

    # Calculate minutes since RTH open (9:30 AM ET)
    rth_open = dt_et.replace(hour=9, minute=30, second=0, microsecond=0)
    if dt_et < rth_open:
        mins_since_open = 0
    else:
        mins_since_open = int((dt_et - rth_open).total_seconds() / 60)

    bars_since_open = mins_since_open // bar_interval_minutes
    time_str = dt_et.strftime("%I:%M %p ET")

    # Session classification
    if t < time(9, 30):
        return SessionInfo(
            session_name="PRE_MARKET",
            time_et=time_str,
            minutes_since_rth_open=0,
            bars_since_rth_open=0,
            brooks_guidance=(
                "Pre-market / overnight session. Volume is low and spreads are wide. "
                "Al Brooks does not trade the 5-minute chart during extended hours. "
                "DO NOT TRADE. Observe only."
            ),
            trade_aggressiveness="SKIP",
            volatility_regime="LOW",
            vol_multiplier=0.5,
        )

    elif time(9, 30) <= t < time(10, 0):
        return SessionInfo(
            session_name="OPENING_30MIN",
            time_et=time_str,
            minutes_since_rth_open=mins_since_open,
            bars_since_rth_open=bars_since_open,
            brooks_guidance=(
                "First 30 minutes of RTH. CRITICAL: 80% of days open as a trading range "
                "with at least 2 reversals in the first 60-90 minutes. Only 20% produce a "
                "Trend From The Open (TFTO). Wait for 6 bars (30 min) before entering unless "
                "you see consecutive strong trend bars from Bar 1 — that signals a rare TFTO. "
                "Bar 3 (the close of the first 15 minutes) is always critical — it often "
                "produces a reversal. Do NOT chase the first move."
            ),
            trade_aggressiveness="LOW",
            volatility_regime="VERY_HIGH",
            vol_multiplier=2.5,
        )

    elif time(10, 0) <= t < time(10, 30):
        return SessionInfo(
            session_name="LATE_FIRST_HOUR",
            time_et=time_str,
            minutes_since_rth_open=mins_since_open,
            bars_since_rth_open=bars_since_open,
            brooks_guidance=(
                "Late first hour. The opening swing is developing. Look for H2/L2 pullback "
                "entries if a trend has established. If the opening reversal is underway, "
                "look for a Major Trend Reversal setup. The 18-bar opening range "
                "(first 90 minutes) will classify the day: if range < 30% of average daily "
                "range, expect a breakout. If > 50%, likely a trading range day."
            ),
            trade_aggressiveness="MODERATE",
            volatility_regime="HIGH",
            vol_multiplier=1.8,
        )

    elif time(10, 30) <= t < time(11, 30):
        return SessionInfo(
            session_name="MORNING",
            time_et=time_str,
            minutes_since_rth_open=mins_since_open,
            bars_since_rth_open=bars_since_open,
            brooks_guidance=(
                "Best trading window of the day. Trends are usually established by now. "
                "Follow the Always-In direction. This is where swing trades work best — "
                "the first pullback after the opening trend tends to produce a reliable "
                "second leg. High conviction entries here."
            ),
            trade_aggressiveness="HIGH",
            volatility_regime="MODERATE",
            vol_multiplier=1.3,
        )

    elif time(11, 30) <= t < time(13, 30):
        return SessionInfo(
            session_name="LUNCH_LULL",
            time_et=time_str,
            minutes_since_rth_open=mins_since_open,
            bars_since_rth_open=bars_since_open,
            brooks_guidance=(
                "Lunch hour — AVOID TRADING. Tight trading ranges dominate. Volume drops "
                "to half of morning levels. Most breakouts fail. Bars are small dojis with "
                "overlapping bodies. Al Brooks explicitly says 'most traders should not trade' "
                "during tight ranges. The only acceptable trade is a limit-order scalp at "
                "range extremes with very tight stops — but even that is marginal."
            ),
            trade_aggressiveness="SKIP",
            volatility_regime="LOW",
            vol_multiplier=0.7,
        )

    elif time(13, 30) <= t < time(15, 0):
        return SessionInfo(
            session_name="AFTERNOON",
            time_et=time_str,
            minutes_since_rth_open=mins_since_open,
            bars_since_rth_open=bars_since_open,
            brooks_guidance=(
                "Afternoon session — volume picking up. Watch for the lunch range breakout. "
                "Morning trends often resume here. If the lunch range was tight and broke "
                "out with a strong trend bar, enter in the breakout direction. "
                "2:00 PM ET is the common window for Fed announcements and macro news. "
                "Check if there are scheduled events before entering."
            ),
            trade_aggressiveness="MODERATE",
            volatility_regime="MODERATE",
            vol_multiplier=1.0,
        )

    elif time(15, 0) <= t < time(16, 0):
        return SessionInfo(
            session_name="CLOSING_HOUR",
            time_et=time_str,
            minutes_since_rth_open=mins_since_open,
            bars_since_rth_open=bars_since_open,
            brooks_guidance=(
                "Final hour — end-of-day dynamics. MOC (market on close) orders create "
                "institutional flow. The Open, High, and Low of the day are magnets. "
                "On trading range days near the high or low, expect a reversal toward "
                "the open. Strong breakouts in the final hour create swings lasting to "
                "the close. Watch for end-of-day traps — false breakouts designed to "
                "trap late entrants. Close all positions before 3:50 PM ET."
            ),
            trade_aggressiveness="MODERATE",
            volatility_regime="HIGH",
            vol_multiplier=1.5,
        )

    else:
        return SessionInfo(
            session_name="AFTER_HOURS",
            time_et=time_str,
            minutes_since_rth_open=mins_since_open,
            bars_since_rth_open=bars_since_open,
            brooks_guidance="After RTH close. DO NOT TRADE.",
            trade_aggressiveness="SKIP",
            volatility_regime="LOW",
            vol_multiplier=0.5,
        )


@dataclass
class CooldownManager:
    """
    Prevents rapid position flipping after exits.
    Separates closing decisions (always allowed) from opening decisions (gated).
    """
    min_bars_between_trades: int = 3      # Minimum 3 bars (15 min on 5m chart) between exit and next entry
    base_conviction_threshold: float = 60.0  # Minimum conviction to enter (0-100 scale)
    conviction_penalty_per_loss: float = 10.0  # Raise threshold by 10 per consecutive loss
    max_consecutive_losses: int = 3       # Pause trading after 3 consecutive losses

    # State
    consecutive_losses: int = 0
    last_exit_bar: int = -999
    trades_today: int = 0
    paused: bool = False

    def can_open_new_trade(self, current_bar: int, conviction_pct: float) -> tuple[bool, str]:
        """
        Check if agent is allowed to open a new position.
        Returns (allowed, reason_if_blocked).
        """
        if self.paused:
            return False, f"Trading paused after {self.max_consecutive_losses} consecutive losses"

        bars_since_exit = current_bar - self.last_exit_bar
        if bars_since_exit < self.min_bars_between_trades:
            return False, f"Cooldown: {self.min_bars_between_trades - bars_since_exit} bars remaining"

        required_conviction = min(
            self.base_conviction_threshold + (self.consecutive_losses * self.conviction_penalty_per_loss),
            95.0
        )
        if conviction_pct < required_conviction:
            return False, f"Conviction {conviction_pct:.0f}% below threshold {required_conviction:.0f}%"

        return True, ""

    def record_exit(self, bar_index: int, was_winner: bool):
        """Record a trade exit for cooldown tracking."""
        self.last_exit_bar = bar_index
        self.trades_today += 1
        if was_winner:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.paused = True
                logger.info(f"Trading PAUSED after {self.consecutive_losses} consecutive losses")

    def reset_daily(self):
        """Reset at the start of each trading day."""
        self.consecutive_losses = 0
        self.last_exit_bar = -999
        self.trades_today = 0
        self.paused = False
