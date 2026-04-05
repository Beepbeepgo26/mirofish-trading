"""
LLM Trading Agent — The core agent class.
Wraps Al Brooks state machine context + agent personality into an LLM prompt,
gets structured JSON decision, and executes against the order book.
"""
import random
import logging
from dataclasses import dataclass

from app.models.order_book import OrderBook, Side, Bar, snap_to_tick
from app.models.market_state import MarketState, MarketCycle
from app.agents.profiles import TraderProfile
from app.services.llm_client import LLMClient
from app.services.session_context import SessionInfo, CooldownManager

logger = logging.getLogger(__name__)


@dataclass
class Position:
    side: str = "FLAT"
    size: int = 0
    avg_entry: float = 0.0
    unrealized_pnl: float = 0.0

    def update_pnl(self, current_price: float):
        if self.side == "LONG":
            self.unrealized_pnl = (current_price - self.avg_entry) * self.size * 50
        elif self.side == "SHORT":
            self.unrealized_pnl = (self.avg_entry - current_price) * self.size * 50
        else:
            self.unrealized_pnl = 0.0


@dataclass
class AgentDecision:
    timestamp: int
    agent_id: str
    agent_type: str
    current_price: float
    action: str
    qty: int = 0
    price: float = 0.0
    reasoning: str = ""
    conviction: float = 0.0
    market_read: str = ""
    position_side: str = "FLAT"
    position_size: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    llm_latency_ms: float = 0.0
    fill_price: float = 0.0      # Actual price the order was filled at
    exit_price: float = 0.0      # Price when position was closed (for EXIT actions)
    entry_price: float = 0.0     # Average entry price of the position at time of decision
    session_name: str = ""       # Current session (MORNING, LUNCH_LULL, etc.)
    cooldown_blocked: bool = False  # Whether the trade was blocked by cooldown

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    def to_log_str(self) -> str:
        return (f"{self.agent_id} [{self.agent_type}] | {self.action} "
                f"qty={self.qty} @{self.price:.2f} | "
                f"conviction={self.conviction:.0%} | {self.market_read} | "
                f"pos={self.position_side}x{self.position_size} | "
                f"pnl=R${self.realized_pnl:.0f}/U${self.unrealized_pnl:.0f} | "
                f"latency={self.llm_latency_ms:.0f}ms | {self.reasoning[:80]}")


class LLMTradingAgent:
    """
    LLM-powered trading agent. Each agent has:
    - A personality profile (system prompt)
    - Access to market state (user prompt context)
    - Structured JSON output → order execution
    """

    def __init__(self, profile: TraderProfile, llm_client: LLMClient, memory=None):
        self.profile = profile
        self.llm = llm_client
        self.memory = memory
        self.position = Position()
        self.realized_pnl = 0.0
        self.decisions: list[AgentDecision] = []
        self._system_prompt = profile.to_system_prompt()
        self._recent_bars_context: list[str] = []
        self.cooldown = CooldownManager()

    @property
    def agent_id(self):
        return self.profile.agent_id

    @property
    def agent_type(self):
        return self.profile.agent_type

    def _build_user_prompt(self, state: MarketState, current_price: float,
                           book: OrderBook, bars: list[Bar],
                           session_info: SessionInfo = None) -> str:
        """Build the user prompt with full market context."""
        # Recent bars (last 10)
        recent_bars = bars[-10:] if len(bars) > 10 else bars
        bars_str = "\n".join(b.to_prompt_str() for b in recent_bars)

        # Market state from Brooks state machine
        patterns = ", ".join(p.value for p in state.active_patterns) if state.active_patterns else "none"

        # Position context
        self.position.update_pnl(current_price)
        pos_str = (f"Side={self.position.side}, Size={self.position.size}, "
                   f"AvgEntry={self.position.avg_entry:.2f}, "
                   f"UnrealizedPnL=${self.position.unrealized_pnl:,.0f}")

        # Order book
        book_str = book.get_book_summary()

        # Session context
        session_str = ""
        if session_info:
            session_str = f"""
SESSION CONTEXT:
- Current Time: {session_info.time_et}
- Session: {session_info.session_name}
- Minutes Since RTH Open: {session_info.minutes_since_rth_open}
- Bars Since RTH Open (5m): {session_info.bars_since_rth_open}
- Trade Aggressiveness: {session_info.trade_aggressiveness}
- Volatility Regime: {session_info.volatility_regime}

AL BROOKS TIME-OF-DAY GUIDANCE:
{session_info.brooks_guidance}
"""

        # Cooldown status
        cooldown_str = ""
        if self.cooldown.consecutive_losses > 0:
            cooldown_str = f"\nCOOLDOWN STATUS: {self.cooldown.consecutive_losses} consecutive losses. "
            if self.cooldown.paused:
                cooldown_str += "TRADING PAUSED — do not enter new positions."

        return f"""CURRENT MARKET STATE (Bar {len(bars)-1}):
Price: {current_price:.2f}
Order Book: {book_str}
{session_str}
RECENT PRICE ACTION (5-MINUTE BARS):
{bars_str}

AL BROOKS STATE MACHINE ASSESSMENT:
- Market Cycle: {state.cycle.value}
- Always-In Direction: {state.always_in.direction} (confidence: {state.always_in.confidence:.0%})
- Active Patterns: [{patterns}]
- Consecutive Bull Bars: {state.consecutive_bull_bars}
- Consecutive Bear Bars: {state.consecutive_bear_bars}
- TBTL Expected: {"YES (" + str(state.tbtl_bars_remaining) + " bars remaining)" if state.tbtl_expected else "No"}
- Trend Extending: {"YES — DO NOT fade until confirmed reversal bar" if state.trend_extending else "No"}
- Confirmed Reversal: {"YES — safe to fade" if state.confirmed_reversal else "No"}
- Fade Attempts This Trend: {state.fade_attempts}
- Support Levels: {[f"{s:.2f}" for s in state.support_levels[:3]]}
- Resistance Levels: {[f"{r:.2f}" for r in state.resistance_levels[:3]]}

YOUR CURRENT POSITION:
{pos_str}
Entry Price: {self.position.avg_entry:.2f}
Realized P&L (session): ${self.realized_pnl:,.0f}
{cooldown_str}
DECISION REQUIRED:
Given the price action, session context, your methodology, and your personality — what is your next action?
Respond with JSON only."""

    async def decide(self, state: MarketState, current_price: float,
                     book: OrderBook, bars: list[Bar], timestamp: int,
                     session_info: SessionInfo = None) -> AgentDecision:
        """Get LLM decision and execute it."""
        user_prompt = self._build_user_prompt(state, current_price, book, bars,
                                              session_info=session_info)

        # Query Zep knowledge graph for relevant context
        memory_context = ""
        if self.memory:
            try:
                # Build a query based on current market state
                query_parts = []
                if state.active_patterns:
                    patterns = ", ".join(p.value for p in state.active_patterns)
                    query_parts.append(patterns)
                query_parts.append(state.cycle.value)
                query_parts.append(f"ES futures {state.always_in.direction}")
                query = " ".join(query_parts)

                memories = await self.memory.query_graph(query, limit=3)
                if memories:
                    memory_context = "\n\nKNOWLEDGE GRAPH CONTEXT (from prior simulations):\n"
                    for m in memories:
                        memory_context += f"- {m[:200]}\n"
                    user_prompt += memory_context
            except Exception:
                pass  # Memory is optional — don't break decisions if it fails

        # Call LLM
        result = await self.llm.complete_json(
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            temperature=0.6 if self.agent_type == "INSTITUTIONAL" else 0.8,
            max_tokens=300,
        )

        # Parse decision
        action = result.get("action", "HOLD")
        qty = min(int(result.get("qty", 0)), self.profile.max_position)
        price = float(result.get("price", current_price))
        reasoning = result.get("reasoning", "No reasoning provided.")
        conviction = float(result.get("conviction", 0.5))
        market_read = result.get("market_read", "UNKNOWN")

        # Execute action
        if conviction < 0.3:
            action = "HOLD"
            qty = 0

        # Session gating: if session says SKIP, force HOLD
        if session_info and session_info.trade_aggressiveness == "SKIP":
            if action not in ("HOLD", "EXIT_LONG", "EXIT_SHORT"):
                action = "HOLD"
                qty = 0
                reasoning += " [SESSION: Trading not recommended during this period]"

        # Cooldown gating: check if we can open a new position
        if action not in ("HOLD", "EXIT_LONG", "EXIT_SHORT"):
            can_trade, block_reason = self.cooldown.can_open_new_trade(
                timestamp, conviction * 100
            )
            if not can_trade:
                action = "HOLD"
                qty = 0
                reasoning += f" [COOLDOWN: {block_reason}]"

        # Guard: Block counter-trend entries during trend extension
        if state.trend_extending and not state.confirmed_reversal:
            is_counter_trend = False
            if state.cycle in (MarketCycle.STRONG_BULL, MarketCycle.WEAK_BULL):
                if action in ('SELL_LIMIT', 'SELL_MARKET'):
                    is_counter_trend = True
            elif state.cycle in (MarketCycle.STRONG_BEAR, MarketCycle.WEAK_BEAR):
                if action in ('BUY_LIMIT', 'BUY_MARKET'):
                    is_counter_trend = True

            if is_counter_trend and self.agent_type == 'INSTITUTIONAL':
                logger.info(f'  [{self.agent_id}] Blocked counter-trend {action} '
                            f'— trend extending, no confirmed reversal')
                action = 'HOLD'
                qty = 0
                reasoning += ' [BLOCKED: trend extending without reversal confirmation]'
                state.fade_attempts += 1

        fill_price, exit_price = self._execute(action, qty, price, book, current_price, timestamp)

        decision = AgentDecision(
            timestamp=timestamp,
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            current_price=current_price,
            action=action,
            qty=qty,
            price=price,
            reasoning=reasoning,
            conviction=conviction,
            market_read=market_read,
            position_side=self.position.side,
            position_size=self.position.size,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=self.position.unrealized_pnl,
            fill_price=fill_price,
            exit_price=exit_price,
            entry_price=self.position.avg_entry,
            session_name=session_info.session_name if session_info else "",
            cooldown_blocked=(action == "HOLD" and "[COOLDOWN:" in reasoning),
        )
        self.decisions.append(decision)
        return decision

    def _execute(self, action: str, qty: int, price: float,
                 book: OrderBook, current_price: float, timestamp: int) -> tuple[float, float]:
        """
        Execute the trading action against the order book.
        Returns (fill_price, exit_price) — 0.0 if not applicable.
        """
        fill_price = 0.0
        exit_price = 0.0

        if qty <= 0 and action not in ('HOLD', 'EXIT_LONG', 'EXIT_SHORT'):
            return fill_price, exit_price

        if action == 'BUY_LIMIT':
            limit_price = snap_to_tick(min(price, current_price))
            order = book.submit_limit_order(
                self.agent_id, Side.BUY, limit_price, qty, timestamp)
            if order.filled_qty > 0:
                fill_price = limit_price
                self._add_to_position('LONG', order.filled_qty, limit_price)

        elif action == 'SELL_LIMIT':
            limit_price = snap_to_tick(max(price, current_price))
            order = book.submit_limit_order(
                self.agent_id, Side.SELL, limit_price, qty, timestamp)
            if order.filled_qty > 0:
                fill_price = limit_price
                self._add_to_position('SHORT', order.filled_qty, limit_price)

        elif action == 'BUY_MARKET':
            trades = book.submit_market_order(
                self.agent_id, Side.BUY, qty, timestamp)
            if trades:
                total_qty = sum(t.qty for t in trades)
                vwap = sum(t.price * t.qty for t in trades) / total_qty
                fill_price = round(vwap, 2)
                self._add_to_position('LONG', total_qty, vwap)

        elif action == 'SELL_MARKET':
            trades = book.submit_market_order(
                self.agent_id, Side.SELL, qty, timestamp)
            if trades:
                total_qty = sum(t.qty for t in trades)
                vwap = sum(t.price * t.qty for t in trades) / total_qty
                fill_price = round(vwap, 2)
                self._add_to_position('SHORT', total_qty, vwap)

        elif action == 'EXIT_LONG' and self.position.side == 'LONG':
            exit_qty = self.position.size
            trades = book.submit_market_order(
                self.agent_id, Side.SELL, exit_qty, timestamp)
            if trades:
                total_qty = sum(t.qty for t in trades)
                vwap = sum(t.price * t.qty for t in trades) / total_qty
                exit_price = round(vwap, 2)
                was_winner = self.position.unrealized_pnl > 0
                self.realized_pnl += self.position.unrealized_pnl
                self.position = Position()
                self.cooldown.record_exit(timestamp, was_winner)

        elif action == 'EXIT_SHORT' and self.position.side == 'SHORT':
            exit_qty = self.position.size
            trades = book.submit_market_order(
                self.agent_id, Side.BUY, exit_qty, timestamp)
            if trades:
                total_qty = sum(t.qty for t in trades)
                vwap = sum(t.price * t.qty for t in trades) / total_qty
                exit_price = round(vwap, 2)
                was_winner = self.position.unrealized_pnl > 0
                self.realized_pnl += self.position.unrealized_pnl
                self.position = Position()
                self.cooldown.record_exit(timestamp, was_winner)

        return fill_price, exit_price

    def _add_to_position(self, side: str, qty: int, price: float):
        if self.position.side == side or self.position.side == "FLAT":
            if self.position.size == 0:
                self.position.avg_entry = price
            else:
                total_cost = self.position.avg_entry * self.position.size + price * qty
                self.position.avg_entry = total_cost / (self.position.size + qty)
            self.position.side = side
            self.position.size += qty
        else:
            # Reducing opposite position
            if qty >= self.position.size:
                self.realized_pnl += self.position.unrealized_pnl
                remaining = qty - self.position.size
                self.position = Position()
                if remaining > 0:
                    self.position.side = side
                    self.position.size = remaining
                    self.position.avg_entry = price
            else:
                self.position.size -= qty


class NoiseAgent:
    """Rule-based noise agent — no LLM needed, saves tokens."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.agent_type = "NOISE"
        self.position = Position()
        self.realized_pnl = 0.0
        self.decisions: list[AgentDecision] = []
        self.profile = TraderProfile(
            agent_id=agent_id, agent_type="NOISE", name=f"Bot_{agent_id}",
            capital=10000, max_position=3, methodology="random",
            risk_level="random", behavioral_rules="random"
        )

    async def decide(self, state: MarketState, current_price: float,
                     book: OrderBook, bars: list[Bar], timestamp: int,
                     session_info: SessionInfo = None) -> AgentDecision:
        action = "HOLD"
        qty = 0
        price = 0.0

        if random.random() < 0.15:
            side = random.choice([Side.BUY, Side.SELL])
            qty = random.randint(1, 2)
            if random.random() < 0.6:
                book.submit_market_order(self.agent_id, side, qty, timestamp)
                action = f"{side.value}_MARKET"
            else:
                offset = random.uniform(-1.0, 1.0)
                price = snap_to_tick(current_price + offset)
                book.submit_limit_order(self.agent_id, side, price, qty, timestamp)
                action = f"{side.value}_LIMIT"

        decision = AgentDecision(
            timestamp=timestamp, agent_id=self.agent_id, agent_type="NOISE",
            current_price=current_price, action=action, qty=qty, price=price,
            reasoning="Random noise.", conviction=0.0, market_read="N/A",
            position_side=self.position.side, position_size=self.position.size,
            realized_pnl=self.realized_pnl, unrealized_pnl=0.0,
        )
        self.decisions.append(decision)
        return decision
