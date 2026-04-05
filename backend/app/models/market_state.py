"""
Al Brooks Price Action State Machine
Classifies market cycles, detects patterns (climaxes, breakouts, measured moves),
and generates probabilistic assessments for agent decision-making.
"""
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
from app.models.order_book import Bar

logger = logging.getLogger(__name__)


class MarketCycle(Enum):
    STRONG_BULL = "STRONG_BULL"
    WEAK_BULL = "WEAK_BULL"
    TRADING_RANGE = "TRADING_RANGE"
    WEAK_BEAR = "WEAK_BEAR"
    STRONG_BEAR = "STRONG_BEAR"
    UNKNOWN = "UNKNOWN"


class PatternType(Enum):
    BUY_CLIMAX = "BUY_CLIMAX"
    SELL_CLIMAX = "SELL_CLIMAX"
    BREAKOUT_BULL = "BREAKOUT_BULL"
    BREAKOUT_BEAR = "BREAKOUT_BEAR"
    FALSE_BREAKOUT_BULL = "FALSE_BREAKOUT_BULL"
    FALSE_BREAKOUT_BEAR = "FALSE_BREAKOUT_BEAR"
    TBTL_CORRECTION = "TBTL_CORRECTION"
    MEASURED_MOVE_TARGET = "MEASURED_MOVE_TARGET"
    HIGH_2 = "HIGH_2"
    LOW_2 = "LOW_2"
    WEDGE_TOP = "WEDGE_TOP"
    WEDGE_BOTTOM = "WEDGE_BOTTOM"
    CHANNEL_OVERSHOOT = "CHANNEL_OVERSHOOT"
    GAP_OPEN = "GAP_OPEN"
    NONE = "NONE"


@dataclass
class AlwaysInState:
    """Al Brooks 'Always In' direction — if forced to be in the market, which side."""
    direction: str = "FLAT"  # "LONG", "SHORT", "FLAT"
    confidence: float = 0.5  # 0-1
    bars_in_state: int = 0


@dataclass
class MarketState:
    """Complete market state assessment from Al Brooks perspective."""
    cycle: MarketCycle = MarketCycle.UNKNOWN
    always_in: AlwaysInState = field(default_factory=AlwaysInState)
    active_patterns: list = field(default_factory=list)
    support_levels: list = field(default_factory=list)
    resistance_levels: list = field(default_factory=list)
    measured_move_targets: list = field(default_factory=list)
    tbtl_expected: bool = False
    tbtl_bars_remaining: int = 0
    consecutive_bull_bars: int = 0
    consecutive_bear_bars: int = 0
    range_high: Optional[float] = None
    range_low: Optional[float] = None
    trend_start_price: Optional[float] = None
    bars_since_climax: int = 0
    climax_price: Optional[float] = None
    # Trend extension guard fields
    trend_extending: bool = False
    bars_since_last_fade: int = 0
    fade_attempts: int = 0
    confirmed_reversal: bool = False


class BrooksStateMachine:
    """
    Implements the Al Brooks price action state machine.
    Processes bars sequentially and maintains full market state.
    """

    def __init__(self):
        self.bars: list[Bar] = []
        self.state = MarketState()
        self._swing_highs: list[tuple[int, float]] = []  # (bar_index, price)
        self._swing_lows: list[tuple[int, float]] = []

    def process_bar(self, bar: Bar) -> MarketState:
        """Process a new bar and update all state."""
        self.bars.append(bar)
        idx = len(self.bars) - 1

        self._update_consecutive_counts(bar)
        self._detect_swings(idx)
        self._classify_cycle()
        self._detect_patterns(idx)
        self._update_always_in()
        self._update_support_resistance()
        self._update_tbtl()

        return self.state

    def _update_consecutive_counts(self, bar: Bar):
        if bar.is_strong_bull:
            self.state.consecutive_bull_bars += 1
            self.state.consecutive_bear_bars = 0
        elif bar.is_strong_bear:
            self.state.consecutive_bear_bars += 1
            self.state.consecutive_bull_bars = 0
        else:
            # Weak bar or doji — reset counts if direction changes
            if bar.is_bull:
                self.state.consecutive_bear_bars = 0
            elif bar.is_bear:
                self.state.consecutive_bull_bars = 0

    def _detect_swings(self, idx: int):
        if idx < 2:
            return
        bars = self.bars
        # Swing high: higher high than both neighbors
        if bars[idx - 1].high > bars[idx - 2].high and bars[idx - 1].high > bars[idx].high:
            self._swing_highs.append((idx - 1, bars[idx - 1].high))
        # Swing low
        if bars[idx - 1].low < bars[idx - 2].low and bars[idx - 1].low < bars[idx].low:
            self._swing_lows.append((idx - 1, bars[idx - 1].low))

    def _classify_cycle(self):
        """Classify current market cycle based on recent bar behavior."""
        if len(self.bars) < 5:
            self.state.cycle = MarketCycle.UNKNOWN
            return

        recent = self.bars[-5:]
        bull_count = sum(1 for b in recent if b.is_bull)
        strong_bull = sum(1 for b in recent if b.is_strong_bull)
        bear_count = sum(1 for b in recent if b.is_bear)
        strong_bear = sum(1 for b in recent if b.is_strong_bear)

        # Strong trends: 4+ of 5 bars in one direction, or 3+ strong bars
        if strong_bull >= 3 or (bull_count >= 4 and strong_bull >= 2):
            self.state.cycle = MarketCycle.STRONG_BULL
        elif strong_bear >= 3 or (bear_count >= 4 and strong_bear >= 2):
            self.state.cycle = MarketCycle.STRONG_BEAR
        elif bull_count >= 3 and strong_bull >= 1:
            self.state.cycle = MarketCycle.WEAK_BULL
        elif bear_count >= 3 and strong_bear >= 1:
            self.state.cycle = MarketCycle.WEAK_BEAR
        else:
            # Check for trading range: overlapping bars, mixed direction
            avg_body_pct = sum(b.body_pct for b in recent) / 5
            if avg_body_pct < 0.4 or (bull_count >= 2 and bear_count >= 2):
                self.state.cycle = MarketCycle.TRADING_RANGE
            else:
                self.state.cycle = MarketCycle.TRADING_RANGE

    def _detect_patterns(self, idx: int):
        """Detect Al Brooks patterns in current bar context."""
        self.state.active_patterns = []

        # Buy Climax: 3+ consecutive strong bull bars
        if self.state.consecutive_bull_bars >= 3:
            self.state.active_patterns.append(PatternType.BUY_CLIMAX)

            # First detection: set up TBTL expectation
            if not self.state.tbtl_expected:
                self.state.tbtl_expected = True
                self.state.tbtl_bars_remaining = 10
                self.state.bars_since_climax = 0
                self.state.climax_price = self.bars[-1].high
                self.state.fade_attempts = 0
                if self.state.trend_start_price:
                    move = self.bars[-1].high - self.state.trend_start_price
                    self.state.measured_move_targets = [self.bars[-1].high - move]
            else:
                # Trend is EXTENDING past the initial climax
                self.state.trend_extending = True
                self.state.confirmed_reversal = False

        # Sell Climax: mirror logic
        if self.state.consecutive_bear_bars >= 3:
            self.state.active_patterns.append(PatternType.SELL_CLIMAX)
            if not self.state.tbtl_expected:
                self.state.tbtl_expected = True
                self.state.tbtl_bars_remaining = 10
                self.state.bars_since_climax = 0
                self.state.climax_price = self.bars[-1].low
                self.state.fade_attempts = 0
            else:
                self.state.trend_extending = True
                self.state.confirmed_reversal = False

        # Detect confirmed reversal (strong bar against the trend)
        if self.state.trend_extending:
            curr = self.bars[-1]
            if self.state.cycle in (MarketCycle.STRONG_BULL, MarketCycle.WEAK_BULL):
                if curr.is_strong_bear:
                    self.state.confirmed_reversal = True
                    self.state.trend_extending = False
                    logger.info(f'  [STATE] Confirmed bearish reversal bar at index {idx}')
            elif self.state.cycle in (MarketCycle.STRONG_BEAR, MarketCycle.WEAK_BEAR):
                if curr.is_strong_bull:
                    self.state.confirmed_reversal = True
                    self.state.trend_extending = False
                    logger.info(f'  [STATE] Confirmed bullish reversal bar at index {idx}')

        # Track trend start
        if self.state.cycle in (MarketCycle.STRONG_BULL, MarketCycle.STRONG_BEAR):
            if self.state.trend_start_price is None:
                self.state.trend_start_price = self.bars[-1].open

        if self.state.cycle == MarketCycle.TRADING_RANGE:
            self.state.trend_start_price = None

        # Gap detection (for scenario B)
        if idx >= 1:
            gap = self.bars[idx].open - self.bars[idx - 1].close
            if abs(gap) > 2.0:  # > 2 points gap on ES
                self.state.active_patterns.append(PatternType.GAP_OPEN)

        # High-2 / Low-2 (pullback entries)
        if idx >= 4 and self.state.cycle in (MarketCycle.STRONG_BULL, MarketCycle.WEAK_BULL):
            # High-2: second attempt to go above prior bar's high in a bull trend
            pullback_lows = 0
            for i in range(max(0, idx - 4), idx):
                if self.bars[i].low < self.bars[i - 1].low if i > 0 else False:
                    pullback_lows += 1
            if pullback_lows >= 2 and self.bars[idx].is_bull:
                self.state.active_patterns.append(PatternType.HIGH_2)

        if idx >= 4 and self.state.cycle in (MarketCycle.STRONG_BEAR, MarketCycle.WEAK_BEAR):
            pullback_highs = 0
            for i in range(max(0, idx - 4), idx):
                if self.bars[i].high > self.bars[i - 1].high if i > 0 else False:
                    pullback_highs += 1
            if pullback_highs >= 2 and self.bars[idx].is_bear:
                self.state.active_patterns.append(PatternType.LOW_2)

        # False breakout detection at range boundaries
        if self.state.range_high and self.state.range_low:
            curr = self.bars[-1]
            if curr.high > self.state.range_high and curr.close < self.state.range_high:
                self.state.active_patterns.append(PatternType.FALSE_BREAKOUT_BULL)
            if curr.low < self.state.range_low and curr.close > self.state.range_low:
                self.state.active_patterns.append(PatternType.FALSE_BREAKOUT_BEAR)

    def _update_always_in(self):
        """Update Always-In direction based on market cycle and recent bars."""
        cycle = self.state.cycle
        ai = self.state.always_in

        if cycle == MarketCycle.STRONG_BULL:
            ai.direction = "LONG"
            ai.confidence = 0.8
        elif cycle == MarketCycle.WEAK_BULL:
            ai.direction = "LONG"
            ai.confidence = 0.6
        elif cycle == MarketCycle.STRONG_BEAR:
            ai.direction = "SHORT"
            ai.confidence = 0.8
        elif cycle == MarketCycle.WEAK_BEAR:
            ai.direction = "SHORT"
            ai.confidence = 0.6
        elif cycle == MarketCycle.TRADING_RANGE:
            ai.direction = "FLAT"
            ai.confidence = 0.5
        else:
            ai.direction = "FLAT"
            ai.confidence = 0.3

        # Reduce confidence if TBTL expected
        if self.state.tbtl_expected:
            ai.confidence *= 0.7

        ai.bars_in_state += 1

    def _update_support_resistance(self):
        """Update S/R levels from swing points."""
        if self._swing_highs:
            self.state.resistance_levels = sorted(
                set(p for _, p in self._swing_highs[-10:]), reverse=True
            )[:5]
        if self._swing_lows:
            self.state.support_levels = sorted(
                set(p for _, p in self._swing_lows[-10:])
            )[:5]

        # Update range boundaries
        if len(self.bars) >= 20 and self.state.cycle == MarketCycle.TRADING_RANGE:
            recent = self.bars[-20:]
            self.state.range_high = max(b.high for b in recent)
            self.state.range_low = min(b.low for b in recent)

    def _update_tbtl(self):
        """Track TBTL (Ten Bars, Two Legs) correction countdown."""
        if self.state.tbtl_expected:
            self.state.bars_since_climax += 1
            self.state.tbtl_bars_remaining = max(0, 10 - self.state.bars_since_climax)
            if self.state.bars_since_climax >= 12:
                self.state.tbtl_expected = False
                self.state.bars_since_climax = 0

    def get_state_summary(self) -> str:
        """Human-readable state summary for logging."""
        s = self.state
        patterns = ", ".join(p.value for p in s.active_patterns) if s.active_patterns else "none"
        return (
            f"Cycle={s.cycle.value} | AI={s.always_in.direction}@{s.always_in.confidence:.0%} | "
            f"Patterns=[{patterns}] | ConsecBull={s.consecutive_bull_bars} ConsecBear={s.consecutive_bear_bars} | "
            f"TBTL={'YES(' + str(s.tbtl_bars_remaining) + ' bars left)' if s.tbtl_expected else 'no'}"
        )
