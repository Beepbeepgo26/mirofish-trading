"""
Tests for session_context — session classification and CooldownManager.
Tests: all 7 session periods, boundary times, cooldown gating, loss tracking, daily reset.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from app.services.session_context import classify_session, CooldownManager


ET = ZoneInfo("America/New_York")


class TestClassifySession:
    def _dt(self, hour: int, minute: int = 0) -> datetime:
        """Create a timezone-aware datetime in ET for testing."""
        return datetime(2026, 4, 7, hour, minute, 0, tzinfo=ET)

    def test_pre_market(self):
        info = classify_session(self._dt(8, 0))
        assert info.session_name == "PRE_MARKET"
        assert info.trade_aggressiveness == "SKIP"

    def test_opening_30min(self):
        info = classify_session(self._dt(9, 30))
        assert info.session_name == "OPENING_30MIN"
        assert info.trade_aggressiveness == "LOW"
        assert info.volatility_regime == "VERY_HIGH"

    def test_opening_boundary_exact_930(self):
        info = classify_session(self._dt(9, 30))
        assert info.session_name == "OPENING_30MIN"

    def test_late_first_hour(self):
        info = classify_session(self._dt(10, 15))
        assert info.session_name == "LATE_FIRST_HOUR"
        assert info.trade_aggressiveness == "MODERATE"

    def test_morning(self):
        info = classify_session(self._dt(11, 0))
        assert info.session_name == "MORNING"
        assert info.trade_aggressiveness == "HIGH"

    def test_lunch_lull(self):
        info = classify_session(self._dt(12, 0))
        assert info.session_name == "LUNCH_LULL"
        assert info.trade_aggressiveness == "SKIP"

    def test_lunch_lull_boundary_1130(self):
        info = classify_session(self._dt(11, 30))
        assert info.session_name == "LUNCH_LULL"

    def test_afternoon(self):
        info = classify_session(self._dt(14, 0))
        assert info.session_name == "AFTERNOON"
        assert info.trade_aggressiveness == "MODERATE"

    def test_closing_hour(self):
        info = classify_session(self._dt(15, 30))
        assert info.session_name == "CLOSING_HOUR"
        assert info.volatility_regime == "HIGH"

    def test_after_hours(self):
        info = classify_session(self._dt(16, 30))
        assert info.session_name == "AFTER_HOURS"
        assert info.trade_aggressiveness == "SKIP"

    def test_minutes_since_open(self):
        info = classify_session(self._dt(10, 0))
        assert info.minutes_since_rth_open == 30

    def test_bars_since_open_5m(self):
        info = classify_session(self._dt(10, 0), bar_interval_minutes=5)
        assert info.bars_since_rth_open == 6  # 30 min / 5 = 6 bars

    def test_utc_input_converted(self):
        """UTC time that maps to 10:00 AM ET should be LATE_FIRST_HOUR."""
        utc = ZoneInfo("UTC")
        dt = datetime(2026, 4, 7, 14, 0, 0, tzinfo=utc)  # 14:00 UTC = 10:00 ET
        info = classify_session(dt)
        assert info.session_name == "LATE_FIRST_HOUR"


class TestCooldownManager:
    def test_can_open_fresh(self):
        cm = CooldownManager()
        allowed, reason = cm.can_open_new_trade(100, 75.0)
        assert allowed is True
        assert reason == ""

    def test_blocked_by_cooldown(self):
        cm = CooldownManager()
        cm.record_exit(10, was_winner=True)
        allowed, reason = cm.can_open_new_trade(11, 80.0)
        assert allowed is False
        assert "Cooldown" in reason

    def test_passes_after_cooldown(self):
        cm = CooldownManager()
        cm.record_exit(10, was_winner=True)
        allowed, _ = cm.can_open_new_trade(14, 80.0)  # 4 bars later > min 3
        assert allowed is True

    def test_conviction_below_threshold(self):
        cm = CooldownManager()
        allowed, reason = cm.can_open_new_trade(100, 50.0)  # below 60% default
        assert allowed is False
        assert "Conviction" in reason

    def test_conviction_escalation_after_loss(self):
        cm = CooldownManager()
        cm.record_exit(5, was_winner=False)
        # Threshold: 60 + 10*1 = 70
        allowed, reason = cm.can_open_new_trade(20, 65.0)
        assert allowed is False
        assert "70" in reason

    def test_pause_after_3_losses(self):
        cm = CooldownManager()
        cm.record_exit(1, was_winner=False)
        cm.record_exit(5, was_winner=False)
        cm.record_exit(9, was_winner=False)
        assert cm.paused is True
        allowed, reason = cm.can_open_new_trade(100, 99.0)
        assert allowed is False
        assert "paused" in reason.lower()

    def test_win_resets_consecutive_losses(self):
        cm = CooldownManager()
        cm.record_exit(1, was_winner=False)
        cm.record_exit(5, was_winner=False)
        cm.record_exit(9, was_winner=True)  # resets
        assert cm.consecutive_losses == 0
        allowed, _ = cm.can_open_new_trade(20, 65.0)
        assert allowed is True  # threshold back to 60

    def test_reset_daily(self):
        cm = CooldownManager()
        cm.record_exit(1, was_winner=False)
        cm.record_exit(5, was_winner=False)
        cm.record_exit(9, was_winner=False)
        assert cm.paused is True
        cm.reset_daily()
        assert cm.paused is False
        assert cm.consecutive_losses == 0
        assert cm.trades_today == 0
        assert cm.last_exit_bar == -999
