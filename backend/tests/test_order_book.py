"""
Unit tests for the continuous double-auction order book.
Tests: limit orders, market orders, matching, bar building, tick snapping.
"""
from app.models.order_book import OrderBook, Side, Bar, snap_to_tick


class TestSnapToTick:
    def test_exact_tick(self):
        assert snap_to_tick(5400.00) == 5400.00
        assert snap_to_tick(5400.25) == 5400.25
        assert snap_to_tick(5400.50) == 5400.50
        assert snap_to_tick(5400.75) == 5400.75

    def test_rounds_to_nearest_tick(self):
        assert snap_to_tick(5400.10) == 5400.00
        assert snap_to_tick(5400.13) == 5400.25
        assert snap_to_tick(5400.30) == 5400.25
        assert snap_to_tick(5400.40) == 5400.50
        assert snap_to_tick(5400.60) == 5400.50
        assert snap_to_tick(5400.90) == 5401.00


class TestOrderBook:
    def setup_method(self):
        self.book = OrderBook()

    def test_empty_book(self):
        assert self.book.best_bid is None
        assert self.book.best_ask is None
        assert self.book.mid_price is None
        assert self.book.spread is None

    def test_limit_buy_rests_on_book(self):
        self.book.submit_limit_order("A", Side.BUY, 5400.00, 10, 0)
        assert self.book.best_bid == 5400.00
        assert self.book.best_ask is None

    def test_limit_sell_rests_on_book(self):
        self.book.submit_limit_order("A", Side.SELL, 5401.00, 10, 0)
        assert self.book.best_ask == 5401.00
        assert self.book.best_bid is None

    def test_spread_calculation(self):
        self.book.submit_limit_order("A", Side.BUY, 5400.00, 10, 0)
        self.book.submit_limit_order("B", Side.SELL, 5400.50, 10, 0)
        assert self.book.spread == 0.50
        assert self.book.mid_price == 5400.25

    def test_limit_order_matching(self):
        """Buy limit at or above best ask should match immediately."""
        self.book.submit_limit_order("A", Side.SELL, 5400.00, 10, 0)
        order = self.book.submit_limit_order("B", Side.BUY, 5400.00, 5, 1)
        assert order.filled_qty == 5
        assert len(self.book.trades) == 1
        assert self.book.trades[0].price == 5400.00
        assert self.book.trades[0].qty == 5
        assert self.book.trades[0].buyer_id == "B"
        assert self.book.trades[0].seller_id == "A"

    def test_market_buy_fills_against_asks(self):
        self.book.submit_limit_order("A", Side.SELL, 5400.00, 10, 0)
        self.book.submit_limit_order("B", Side.SELL, 5400.25, 10, 0)
        trades = self.book.submit_market_order("C", Side.BUY, 15, 1)
        assert len(trades) == 2
        assert trades[0].price == 5400.00
        assert trades[0].qty == 10
        assert trades[1].price == 5400.25
        assert trades[1].qty == 5
        assert self.book.last_price == 5400.25

    def test_market_sell_fills_against_bids(self):
        self.book.submit_limit_order("A", Side.BUY, 5400.25, 10, 0)
        self.book.submit_limit_order("B", Side.BUY, 5400.00, 10, 0)
        trades = self.book.submit_market_order("C", Side.SELL, 15, 1)
        assert len(trades) == 2
        assert trades[0].price == 5400.25
        assert trades[0].qty == 10
        assert trades[1].price == 5400.00
        assert trades[1].qty == 5

    def test_partial_fill(self):
        self.book.submit_limit_order("A", Side.SELL, 5400.00, 5, 0)
        trades = self.book.submit_market_order("B", Side.BUY, 10, 1)
        # Only 5 available, should fill 5
        assert len(trades) == 1
        assert trades[0].qty == 5

    def test_no_self_matching(self):
        """Orders from same agent shouldn't self-match in a real exchange,
        but our simple book doesn't prevent it — document this behavior."""
        self.book.submit_limit_order("A", Side.SELL, 5400.00, 10, 0)
        trades = self.book.submit_market_order("A", Side.BUY, 5, 1)
        # Our book DOES allow self-matching (simple implementation)
        assert len(trades) == 1

    def test_price_time_priority(self):
        """Better price fills first; same price, earlier order fills first."""
        self.book.submit_limit_order("A", Side.SELL, 5400.50, 10, 0)
        self.book.submit_limit_order("B", Side.SELL, 5400.25, 10, 1)
        self.book.submit_limit_order("C", Side.SELL, 5400.25, 10, 2)
        trades = self.book.submit_market_order("D", Side.BUY, 15, 3)
        # Should fill B first (better price, earlier), then C
        assert trades[0].seller_id == "B"
        assert trades[0].price == 5400.25
        assert trades[1].seller_id == "C"
        assert trades[1].price == 5400.25

    def test_build_bar_from_trades(self):
        self.book.submit_limit_order("A", Side.SELL, 5400.00, 10, 0)
        self.book.submit_limit_order("B", Side.SELL, 5401.00, 10, 0)
        self.book.submit_market_order("C", Side.BUY, 5, 0)
        self.book.submit_market_order("D", Side.BUY, 8, 0)
        bar = self.book.build_bar(0)
        assert bar is not None
        assert bar.open == 5400.00
        assert bar.high == 5401.00
        assert bar.low == 5400.00
        assert bar.close == 5401.00
        assert bar.volume == 13

    def test_build_bar_no_trades(self):
        """Bar with no trades should return a flat bar at last price."""
        self.book.last_price = 5400.00
        bar = self.book.build_bar(0)
        assert bar is not None
        assert bar.open == 5400.00
        assert bar.close == 5400.00
        assert bar.volume == 0

    def test_cancel_order(self):
        order = self.book.submit_limit_order("A", Side.BUY, 5400.00, 10, 0)
        assert self.book.cancel_order(order.order_id) is True
        assert order.is_filled  # Cancel marks as fully filled
        # New sell shouldn't match the cancelled buy
        trades = self.book.submit_market_order("B", Side.SELL, 5, 1)
        assert len(trades) == 0


class TestBar:
    def test_bull_bar(self):
        bar = Bar(timestamp=0, open=5400.0, high=5401.5, low=5399.5,
                  close=5401.0, volume=100, num_trades=10)
        assert bar.is_bull is True
        assert bar.is_bear is False
        assert bar.body_size == 1.0
        assert bar.range_size == 2.0
        assert bar.body_pct == 0.5

    def test_strong_bull_bar(self):
        bar = Bar(timestamp=0, open=5400.0, high=5402.0, low=5399.8,
                  close=5401.8, volume=100, num_trades=10)
        assert bar.is_strong_bull is True
        assert bar.is_strong_bear is False

    def test_strong_bear_bar(self):
        bar = Bar(timestamp=0, open=5401.8, high=5402.0, low=5399.8,
                  close=5400.0, volume=100, num_trades=10)
        assert bar.is_strong_bear is True
        assert bar.is_strong_bull is False

    def test_doji(self):
        bar = Bar(timestamp=0, open=5400.0, high=5401.0, low=5399.0,
                  close=5400.0, volume=100, num_trades=10)
        assert bar.body_pct == 0.0
        assert bar.is_strong_bull is False
        assert bar.is_strong_bear is False

    def test_to_dict(self):
        bar = Bar(timestamp=0, open=5400.0, high=5401.0, low=5399.0,
                  close=5400.5, volume=100, num_trades=10)
        d = bar.to_dict()
        assert d["timestamp"] == 0
        assert d["open"] == 5400.0
        assert d["is_bull"] is True
        assert "body_pct" in d

    def test_to_prompt_str(self):
        bar = Bar(timestamp=3, open=5400.0, high=5402.0, low=5399.8,
                  close=5401.8, volume=500, num_trades=50)
        s = bar.to_prompt_str()
        assert "Bar3" in s
        assert "BULL" in s
        assert "STRONG" in s
