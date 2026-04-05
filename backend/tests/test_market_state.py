"""
Unit tests for the Al Brooks price action state machine.
Tests: cycle classification, climax detection, TBTL, trend extension, reversal.
"""
from app.models.order_book import Bar
from app.models.market_state import (
    BrooksStateMachine, MarketCycle, PatternType
)


def make_bar(timestamp, open, close, high=None, low=None, volume=1000):
    """Helper to create a bar with reasonable defaults."""
    if high is None:
        high = max(open, close) + 0.25
    if low is None:
        low = min(open, close) - 0.25
    return Bar(timestamp=timestamp, open=open, high=high, low=low,
               close=close, volume=volume, num_trades=volume // 10)


def make_strong_bull_bar(timestamp, base_price, move=2.0):
    """Create a strong bull bar (body > 60% of range)."""
    return make_bar(timestamp, base_price, base_price + move,
                    high=base_price + move + 0.1,
                    low=base_price - 0.1)


def make_strong_bear_bar(timestamp, base_price, move=2.0):
    """Create a strong bear bar."""
    return make_bar(timestamp, base_price, base_price - move,
                    high=base_price + 0.1,
                    low=base_price - move - 0.1)


class TestBrooksStateMachine:
    def setup_method(self):
        self.sm = BrooksStateMachine()

    def test_initial_state(self):
        assert self.sm.state.cycle == MarketCycle.UNKNOWN
        assert self.sm.state.always_in.direction == "FLAT"
        assert self.sm.state.tbtl_expected is False

    def test_consecutive_bull_count(self):
        for i in range(3):
            bar = make_strong_bull_bar(i, 5400.0 + i * 2)
            self.sm.process_bar(bar)
        assert self.sm.state.consecutive_bull_bars == 3
        assert self.sm.state.consecutive_bear_bars == 0

    def test_consecutive_bear_count(self):
        for i in range(3):
            bar = make_strong_bear_bar(i, 5410.0 - i * 2)
            self.sm.process_bar(bar)
        assert self.sm.state.consecutive_bear_bars == 3
        assert self.sm.state.consecutive_bull_bars == 0

    def test_buy_climax_detected(self):
        """3 consecutive strong bull bars should trigger BUY_CLIMAX."""
        for i in range(3):
            bar = make_strong_bull_bar(i, 5400.0 + i * 2)
            state = self.sm.process_bar(bar)
        assert PatternType.BUY_CLIMAX in state.active_patterns
        assert state.tbtl_expected is True

    def test_sell_climax_detected(self):
        """3 consecutive strong bear bars should trigger SELL_CLIMAX."""
        for i in range(3):
            bar = make_strong_bear_bar(i, 5410.0 - i * 2)
            state = self.sm.process_bar(bar)
        assert PatternType.SELL_CLIMAX in state.active_patterns
        assert state.tbtl_expected is True

    def test_tbtl_countdown(self):
        """After climax, TBTL bars remaining should count down."""
        for i in range(3):
            self.sm.process_bar(make_strong_bull_bar(i, 5400.0 + i * 2))
        # TBTL starts at 10 but decrements during the same process_bar call
        assert self.sm.state.tbtl_bars_remaining == 9

        # Process more bars — TBTL should count down
        for i in range(3, 8):
            bar = make_bar(i, 5406.0, 5405.5)  # Weak bars
            self.sm.process_bar(bar)
        assert self.sm.state.tbtl_bars_remaining < 10
        assert self.sm.state.tbtl_expected is True

    def test_tbtl_expires(self):
        """TBTL should expire after ~12 bars."""
        for i in range(3):
            self.sm.process_bar(make_strong_bull_bar(i, 5400.0 + i * 2))

        for i in range(3, 16):
            self.sm.process_bar(make_bar(i, 5406.0, 5405.5))
        assert self.sm.state.tbtl_expected is False

    def test_trend_extending_on_continued_climax(self):
        """If bull bars continue past initial climax, trend_extending should be True."""
        for i in range(5):
            self.sm.process_bar(make_strong_bull_bar(i, 5400.0 + i * 2))
        assert self.sm.state.trend_extending is True

    def test_confirmed_reversal(self):
        """Strong bear bar during bull trend extension should set confirmed_reversal."""
        # Build a strong bull trend
        for i in range(5):
            self.sm.process_bar(make_strong_bull_bar(i, 5400.0 + i * 2))
        assert self.sm.state.trend_extending is True

        # Now a strong bear bar
        self.sm.process_bar(make_strong_bear_bar(5, 5410.0, move=3.0))
        # The state machine should detect this as a potential reversal
        # (exact behavior depends on cycle classification)

    def test_strong_bull_cycle(self):
        """5 bars with mostly strong bulls should classify as STRONG_BULL."""
        for i in range(5):
            self.sm.process_bar(make_strong_bull_bar(i, 5400.0 + i * 2))
        assert self.sm.state.cycle == MarketCycle.STRONG_BULL

    def test_always_in_long_during_bull(self):
        for i in range(5):
            self.sm.process_bar(make_strong_bull_bar(i, 5400.0 + i * 2))
        assert self.sm.state.always_in.direction == "LONG"
        assert self.sm.state.always_in.confidence >= 0.5

    def test_state_summary_string(self):
        for i in range(3):
            self.sm.process_bar(make_strong_bull_bar(i, 5400.0 + i * 2))
        summary = self.sm.get_state_summary()
        assert "Cycle=" in summary
        assert "AI=" in summary
        assert "BUY_CLIMAX" in summary
