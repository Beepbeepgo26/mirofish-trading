"""
Continuous Double Auction Order Book — Enhanced for closed-loop simulation.
Agent orders drive price discovery. Supports ES futures tick size (0.25).
"""
import uuid
import heapq
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Order:
    agent_id: str
    side: Side
    price: float
    qty: int
    timestamp: int
    order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    filled_qty: int = 0

    @property
    def remaining(self):
        return self.qty - self.filled_qty

    @property
    def is_filled(self):
        return self.remaining <= 0

    def __lt__(self, other):
        return self.timestamp < other.timestamp

    def __le__(self, other):
        return self.timestamp <= other.timestamp


@dataclass
class Trade:
    timestamp: int
    price: float
    qty: int
    buyer_id: str
    seller_id: str
    aggressor_side: Side


@dataclass
class Bar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    num_trades: int
    buy_volume: int = 0
    sell_volume: int = 0
    ts_event: int = 0  # Unix timestamp in seconds (from Databento ts_event)

    @property
    def body_size(self):
        return abs(self.close - self.open)

    @property
    def range_size(self):
        return self.high - self.low

    @property
    def is_bull(self):
        return self.close > self.open

    @property
    def is_bear(self):
        return self.close < self.open

    @property
    def body_pct(self):
        if self.range_size == 0:
            return 0
        return self.body_size / self.range_size

    @property
    def is_strong_bull(self):
        return self.is_bull and self.body_pct > 0.6 and self.body_size > 0.5

    @property
    def is_strong_bear(self):
        return self.is_bear and self.body_pct > 0.6 and self.body_size > 0.5

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp, "open": round(self.open, 2),
            "high": round(self.high, 2), "low": round(self.low, 2),
            "close": round(self.close, 2), "volume": self.volume,
            "time": self.ts_event if self.ts_event else self.timestamp,
            "buy_volume": self.buy_volume, "sell_volume": self.sell_volume,
            "body_pct": round(self.body_pct, 2),
            "is_bull": self.is_bull, "is_strong_bull": self.is_strong_bull,
            "is_strong_bear": self.is_strong_bear,
        }

    def to_prompt_str(self) -> str:
        """Compact string for LLM context."""
        direction = "BULL" if self.is_bull else "BEAR" if self.is_bear else "DOJI"
        strength = "STRONG" if (self.is_strong_bull or self.is_strong_bear) else "weak"
        return (f"Bar{self.timestamp}: O={self.open:.2f} H={self.high:.2f} "
                f"L={self.low:.2f} C={self.close:.2f} Vol={self.volume} "
                f"[{strength} {direction}, body={self.body_pct:.0%}]")


ES_TICK = 0.25


def snap_to_tick(price: float) -> float:
    return round(price / ES_TICK) * ES_TICK


class OrderBook:
    def __init__(self):
        self._bids: list = []
        self._asks: list = []
        self._orders: dict[str, Order] = {}
        self.trades: list[Trade] = []
        self.last_price: Optional[float] = None
        self._trade_buffer: list[Trade] = []

    @property
    def best_bid(self) -> Optional[float]:
        self._clean_bids()
        return -self._bids[0][0] if self._bids else None

    @property
    def best_ask(self) -> Optional[float]:
        self._clean_asks()
        return self._asks[0][0] if self._asks else None

    @property
    def mid_price(self) -> Optional[float]:
        bb, ba = self.best_bid, self.best_ask
        if bb is not None and ba is not None:
            return (bb + ba) / 2
        return self.last_price

    @property
    def spread(self) -> Optional[float]:
        bb, ba = self.best_bid, self.best_ask
        if bb is not None and ba is not None:
            return ba - bb
        return None

    def _clean_bids(self):
        while self._bids and self._bids[0][2].is_filled:
            heapq.heappop(self._bids)

    def _clean_asks(self):
        while self._asks and self._asks[0][2].is_filled:
            heapq.heappop(self._asks)

    def submit_limit_order(self, agent_id: str, side: Side, price: float,
                           qty: int, timestamp: int) -> Order:
        order = Order(agent_id=agent_id, side=side, price=snap_to_tick(price),
                      qty=qty, timestamp=timestamp)
        self._orders[order.order_id] = order

        if side == Side.BUY:
            self._match_buy(order, timestamp)
            if not order.is_filled:
                heapq.heappush(self._bids, (-order.price, order.timestamp, order))
        else:
            self._match_sell(order, timestamp)
            if not order.is_filled:
                heapq.heappush(self._asks, (order.price, order.timestamp, order))
        return order

    def submit_market_order(self, agent_id: str, side: Side, qty: int,
                            timestamp: int) -> list[Trade]:
        trades_before = len(self._trade_buffer)
        if side == Side.BUY:
            order = Order(agent_id=agent_id, side=Side.BUY, price=99999,
                          qty=qty, timestamp=timestamp)
            self._match_buy(order, timestamp)
        else:
            order = Order(agent_id=agent_id, side=Side.SELL, price=0.01,
                          qty=qty, timestamp=timestamp)
            self._match_sell(order, timestamp)
        return self._trade_buffer[trades_before:]

    def _match_buy(self, buy_order: Order, timestamp: int):
        self._clean_asks()
        while not buy_order.is_filled and self._asks and self._asks[0][0] <= buy_order.price:
            _, _, sell_order = self._asks[0]
            fill_qty = min(buy_order.remaining, sell_order.remaining)
            fill_price = sell_order.price
            buy_order.filled_qty += fill_qty
            sell_order.filled_qty += fill_qty
            self.last_price = fill_price
            trade = Trade(timestamp=timestamp, price=fill_price, qty=fill_qty,
                          buyer_id=buy_order.agent_id, seller_id=sell_order.agent_id,
                          aggressor_side=Side.BUY)
            self.trades.append(trade)
            self._trade_buffer.append(trade)
            if sell_order.is_filled:
                heapq.heappop(self._asks)
            self._clean_asks()

    def _match_sell(self, sell_order: Order, timestamp: int):
        self._clean_bids()
        while not sell_order.is_filled and self._bids and (-self._bids[0][0]) >= sell_order.price:
            _, _, buy_order = self._bids[0]
            fill_qty = min(sell_order.remaining, buy_order.remaining)
            fill_price = buy_order.price
            sell_order.filled_qty += fill_qty
            buy_order.filled_qty += fill_qty
            self.last_price = fill_price
            trade = Trade(timestamp=timestamp, price=fill_price, qty=fill_qty,
                          buyer_id=buy_order.agent_id, seller_id=sell_order.agent_id,
                          aggressor_side=Side.SELL)
            self.trades.append(trade)
            self._trade_buffer.append(trade)
            if buy_order.is_filled:
                heapq.heappop(self._bids)
            self._clean_bids()

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self._orders:
            self._orders[order_id].filled_qty = self._orders[order_id].qty
            return True
        return False

    def build_bar(self, timestamp: int, prev_close: Optional[float] = None) -> Optional[Bar]:
        if not self._trade_buffer:
            p = self.last_price or prev_close or 5000.0
            bar = Bar(timestamp=timestamp, open=p, high=p, low=p, close=p,
                      volume=0, num_trades=0)
            self._trade_buffer = []
            return bar
        prices = [t.price for t in self._trade_buffer]
        buy_vol = sum(t.qty for t in self._trade_buffer if t.aggressor_side == Side.BUY)
        sell_vol = sum(t.qty for t in self._trade_buffer if t.aggressor_side == Side.SELL)
        bar = Bar(timestamp=timestamp, open=prices[0], high=max(prices),
                  low=min(prices), close=prices[-1],
                  volume=sum(t.qty for t in self._trade_buffer),
                  num_trades=len(self._trade_buffer),
                  buy_volume=buy_vol, sell_volume=sell_vol)
        self._trade_buffer = []
        return bar

    def get_book_summary(self, levels: int = 3) -> str:
        """Compact book summary for LLM context."""
        bb, ba = self.best_bid, self.best_ask
        spread = self.spread
        bid_str = f"{bb:.2f}" if bb is not None else "empty"
        ask_str = f"{ba:.2f}" if ba is not None else "empty"
        spread_str = f"{spread:.2f}" if spread is not None else "N/A"
        last_str = f"{self.last_price:.2f}" if self.last_price is not None else "N/A"
        return f"Bid={bid_str} Ask={ask_str} Spread={spread_str} Last={last_str}"
