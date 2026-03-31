"""
Live Streaming Session — Real-time ES futures simulation.
Connects to Databento Live, receives 1-min OHLCV bars,
runs agent decisions on each bar, and pushes results via callback.
"""
import asyncio
import json
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable
from functools import singledispatch

import databento as db

from app.config import AppConfig
from app.models.order_book import OrderBook, Bar, Side, snap_to_tick
from app.models.market_state import BrooksStateMachine, MarketState
from app.agents.profiles import (
    create_institutional_profiles, create_retail_profiles,
    create_mm_profiles, create_noise_profiles,
    AL_BROOKS_FULL_METHODOLOGY,
)
from app.agents.llm_agent import LLMTradingAgent, NoiseAgent, AgentDecision
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)


class SessionState(Enum):
    INITIALIZING = "initializing"
    WAITING_FOR_DATA = "waiting_for_data"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class LiveSessionConfig:
    """Configuration for a live streaming session."""
    dataset: str = "GLBX.MDP3"
    schema: str = "ohlcv-1m"
    symbol: str = "ES.c.0"
    stype: str = "continuous"
    seed_bars: int = 5           # Wait for N bars before agents start trading
    max_bars: int = 120          # Auto-stop after N bars (2 hours at 1-min)
    agent_institutional: int = 3
    agent_retail: int = 5
    agent_market_maker: int = 1
    agent_noise: int = 5


class LiveSession:
    """
    Manages a single live streaming simulation session.

    Lifecycle:
      1. start() → connects to Databento Live, creates agents
      2. Databento pushes OHLCV bars via callback
      3. Each bar triggers: state machine update → agent decisions → order book
      4. Results pushed to frontend via on_update callback
      5. stop() → disconnects, compiles final results
    """

    def __init__(self, config: AppConfig, session_config: LiveSessionConfig,
                 session_id: Optional[str] = None,
                 on_update: Optional[Callable] = None):
        self.config = config
        self.session_config = session_config
        self.session_id = session_id or datetime.now().strftime("live_%Y%m%d_%H%M%S")
        self.on_update = on_update  # Callback: fn(event_type, data) → pushed to WebSocket

        # State
        self.state = SessionState.INITIALIZING
        self.bars: list[Bar] = []
        self.all_decisions: list[AgentDecision] = []
        self.bar_count = 0
        self.started_at: Optional[datetime] = None
        self.error: Optional[str] = None

        # Core components
        self.book = OrderBook()
        self.state_machine = BrooksStateMachine()

        # LLM clients
        self.llm_primary = LLMClient(
            config.llm_primary, concurrency=config.sim.concurrency, name="primary"
        )
        self.llm_boost = LLMClient(
            config.llm_boost, concurrency=config.sim.concurrency, name="boost"
        )

        # Agents (created in start)
        self.agents: list = []

        # Databento live client
        self._live_client: Optional[db.Live] = None
        self._live_thread: Optional[threading.Thread] = None
        self._agent_loop: Optional[asyncio.AbstractEventLoop] = None
        self._agent_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Price scaling — Databento returns prices as fixed-point integers
        # For GLBX.MDP3 ohlcv-1m, prices are in 1e-9 scale
        self.PX_SCALE = 1e-9

    def start(self):
        """Start the live session — connects to Databento and initializes agents."""
        logger.info(f"[{self.session_id}] Starting live session...")
        self.started_at = datetime.utcnow()

        # Validate Databento key
        if not self.config.databento_api_key:
            self.state = SessionState.ERROR
            self.error = "DATABENTO_API_KEY not configured"
            raise RuntimeError(self.error)

        # Create agents
        self._create_agents()

        # Seed initial order book liquidity at a reasonable price
        # We'll update this when the first bar arrives
        self._seed_initial_book(5500.0)  # Placeholder — updated on first bar

        # Start the async agent loop in a background thread
        self._agent_loop = asyncio.new_event_loop()
        self._agent_thread = threading.Thread(
            target=self._run_agent_loop, daemon=True
        )
        self._agent_thread.start()

        # Start Databento live stream in a background thread
        self._live_thread = threading.Thread(
            target=self._run_databento_stream, daemon=True
        )
        self._live_thread.start()

        self.state = SessionState.WAITING_FOR_DATA
        self._emit("session_started", {
            "session_id": self.session_id,
            "config": {
                "symbol": self.session_config.symbol,
                "seed_bars": self.session_config.seed_bars,
                "max_bars": self.session_config.max_bars,
                "agents": {
                    "institutional": self.session_config.agent_institutional,
                    "retail": self.session_config.agent_retail,
                    "market_maker": self.session_config.agent_market_maker,
                    "noise": self.session_config.agent_noise,
                },
            }
        })

    def stop(self):
        """Stop the live session gracefully."""
        logger.info(f"[{self.session_id}] Stopping live session...")
        self._stop_event.set()
        self.state = SessionState.STOPPED

        # Close Databento connection
        if self._live_client:
            try:
                self._live_client.stop()
            except Exception as e:
                logger.warning(f"Error stopping Databento client: {e}")

        # Stop agent loop
        if self._agent_loop and self._agent_loop.is_running():
            self._agent_loop.call_soon_threadsafe(self._agent_loop.stop)

        # Compile and emit final results
        results = self._compile_results()
        self._emit("session_stopped", results)

        return results

    def get_status(self) -> dict:
        """Get current session status."""
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "bars_received": self.bar_count,
            "total_decisions": len(self.all_decisions),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "error": self.error,
            "current_price": self.book.last_price,
            "market_state": self.state_machine.get_state_summary() if self.bars else None,
            "llm_stats": {
                "primary": self.llm_primary.stats(),
                "boost": self.llm_boost.stats(),
            },
        }

    # ─── Private: Databento Stream ───

    def _run_databento_stream(self):
        """Run the Databento Live client in a blocking thread."""
        try:
            self._live_client = db.Live(key=self.config.databento_api_key)

            self._live_client.subscribe(
                dataset=self.session_config.dataset,
                schema=self.session_config.schema,
                symbols=[self.session_config.symbol],
                stype_in=self.session_config.stype,
            )

            # Register callback using singledispatch pattern
            @singledispatch
            def handler(_: db.DBNRecord):
                pass  # Ignore unknown record types

            @handler.register
            def _(msg: db.OHLCVMsg):
                if self._stop_event.is_set():
                    return
                self._on_ohlcv_bar(msg)

            @handler.register
            def _(msg: db.SymbolMappingMsg):
                logger.info(f"[{self.session_id}] Symbol mapping: "
                           f"{msg.stype_in_symbol} → instrument_id={msg.instrument_id}")

            @handler.register
            def _(msg: db.ErrorMsg):
                logger.error(f"[{self.session_id}] Databento error: {msg.err}")
                self.error = f"Databento: {msg.err}"
                self._emit("error", {"message": msg.err})

            self._live_client.add_callback(handler)

            logger.info(f"[{self.session_id}] Databento Live connected. "
                       f"Waiting for {self.session_config.symbol} bars...")

            # Start the session — required in databento >= 0.43
            self._live_client.start()

            # This blocks until the stream ends or stop() is called
            self._live_client.block_for_close()

        except Exception as e:
            logger.error(f"[{self.session_id}] Databento stream error: {e}")
            self.state = SessionState.ERROR
            self.error = str(e)
            self._emit("error", {"message": str(e)})

    def _on_ohlcv_bar(self, msg: db.OHLCVMsg):
        """Handle an incoming OHLCV bar from Databento Live."""
        self.bar_count += 1

        # Convert Databento fixed-point prices to float
        # Extract real timestamp: ts_event is nanoseconds since epoch
        ts_seconds = int(msg.ts_event / 1e9) if hasattr(msg, 'ts_event') and msg.ts_event else 0

        bar = Bar(
            timestamp=self.bar_count - 1,
            open=msg.open * self.PX_SCALE,
            high=msg.high * self.PX_SCALE,
            low=msg.low * self.PX_SCALE,
            close=msg.close * self.PX_SCALE,
            volume=msg.volume,
            num_trades=0,  # Not available in OHLCV schema
            ts_event=ts_seconds,
        )

        self.bars.append(bar)
        self.book.last_price = bar.close

        logger.info(f"[{self.session_id}] Bar {bar.timestamp}: "
                    f"O={bar.open:.2f} H={bar.high:.2f} L={bar.low:.2f} "
                    f"C={bar.close:.2f} V={bar.volume}")

        # Update state machine
        market_state = self.state_machine.process_bar(bar)

        # Emit bar to frontend
        self._emit("bar", bar.to_dict())

        # Seeding phase: collect bars but don't trade yet
        if self.bar_count <= self.session_config.seed_bars:
            self.state = SessionState.WAITING_FOR_DATA
            self._emit("seeding", {
                "bars_received": self.bar_count,
                "bars_needed": self.session_config.seed_bars,
                "market_state": self.state_machine.get_state_summary(),
            })

            # Re-seed order book around the actual price on first bar
            if self.bar_count == 1:
                self._seed_initial_book(bar.close)

            return

        # Trading phase: run agents
        self.state = SessionState.RUNNING

        # Replenish MM liquidity
        self._replenish_liquidity(bar.close, bar.timestamp)

        # Schedule agent decisions on the async loop
        if self._agent_loop and self._agent_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self._run_agent_round(market_state, bar.close, bar.timestamp),
                self._agent_loop,
            )
            try:
                # Wait up to 30 seconds for agents to decide
                future.result(timeout=30)
            except Exception as e:
                logger.error(f"[{self.session_id}] Agent round error: {e}")

        # Auto-stop if max bars reached
        if self.bar_count >= self.session_config.max_bars:
            logger.info(f"[{self.session_id}] Max bars ({self.session_config.max_bars}) reached. Auto-stopping.")
            self.stop()

    # ─── Private: Agent Execution ───

    def _run_agent_loop(self):
        """Run the asyncio event loop for agent decisions in a background thread."""
        asyncio.set_event_loop(self._agent_loop)
        self._agent_loop.run_forever()

    async def _run_agent_round(self, market_state: MarketState,
                                current_price: float, timestamp: int):
        """Run all agents concurrently for this bar."""
        random.shuffle(self.agents)

        batch_size = self.config.sim.concurrency
        bar_decisions = []

        for i in range(0, len(self.agents), batch_size):
            batch = self.agents[i:i + batch_size]
            tasks = [
                agent.decide(market_state, current_price,
                             self.book, self.bars, timestamp)
                for agent in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for d in results:
                if isinstance(d, AgentDecision):
                    self.all_decisions.append(d)
                    bar_decisions.append(d)
                elif isinstance(d, Exception):
                    logger.error(f"Agent decision error: {d}")

        # Emit decisions for this bar to frontend
        active_decisions = [d.to_dict() for d in bar_decisions if d.action != "HOLD"]
        self._emit("decisions", {
            "timestamp": timestamp,
            "total": len(bar_decisions),
            "active": len(active_decisions),
            "decisions": active_decisions[:20],  # Limit to top 20 for WebSocket
            "market_state": self.state_machine.get_state_summary(),
        })

        # Emit updated P&L
        pnl_summary = self._get_pnl_summary()
        self._emit("pnl", pnl_summary)

    def _create_agents(self):
        """Initialize all trading agents."""
        sc = self.session_config

        for p in create_institutional_profiles(sc.agent_institutional):
            self.agents.append(LLMTradingAgent(p, self.llm_primary))
        for p in create_mm_profiles(sc.agent_market_maker):
            self.agents.append(LLMTradingAgent(p, self.llm_primary))
        for p in create_retail_profiles(sc.agent_retail):
            self.agents.append(LLMTradingAgent(p, self.llm_boost))
        for p in create_noise_profiles(sc.agent_noise):
            self.agents.append(NoiseAgent(p.agent_id))

        logger.info(f"[{self.session_id}] Created {len(self.agents)} agents "
                    f"({sc.agent_institutional} inst, {sc.agent_retail} retail, "
                    f"{sc.agent_market_maker} mm, {sc.agent_noise} noise)")

    def _seed_initial_book(self, price: float):
        """Seed the order book with initial two-sided liquidity."""
        for offset in [0.25, 0.50, 0.75, 1.00, 1.50, 2.00]:
            self.book.submit_limit_order("SEED", Side.BUY,
                                          snap_to_tick(price - offset), 100, 0)
            self.book.submit_limit_order("SEED", Side.SELL,
                                          snap_to_tick(price + offset), 100, 0)

    def _replenish_liquidity(self, price: float, timestamp: int):
        """Keep background liquidity available."""
        for offset in [0.25, 0.50, 1.00]:
            self.book.submit_limit_order("SEED_MM", Side.BUY,
                                          snap_to_tick(price - offset), 30, timestamp)
            self.book.submit_limit_order("SEED_MM", Side.SELL,
                                          snap_to_tick(price + offset), 30, timestamp)

    # ─── Private: Helpers ───

    def _emit(self, event_type: str, data: dict):
        """Emit an event to the frontend via the callback."""
        if self.on_update:
            try:
                self.on_update(event_type, data)
            except Exception as e:
                logger.error(f"[{self.session_id}] Emit error: {e}")

    def _get_pnl_summary(self) -> dict:
        """Get current P&L by agent type."""
        pnl: dict = {}
        for agent in self.agents:
            t = agent.agent_type
            if t not in pnl:
                pnl[t] = {"agents": 0, "total_realized": 0, "total_unrealized": 0,
                           "winners": 0, "losers": 0}
            pnl[t]["agents"] += 1
            pnl[t]["total_realized"] += agent.realized_pnl
            if hasattr(agent, 'position'):
                agent.position.update_pnl(self.book.last_price or 0)
                pnl[t]["total_unrealized"] += agent.position.unrealized_pnl
            if agent.realized_pnl > 0:
                pnl[t]["winners"] += 1
            elif agent.realized_pnl < 0:
                pnl[t]["losers"] += 1
        return pnl

    def _compile_results(self) -> dict:
        """Compile final results after session ends."""
        return {
            "session_id": self.session_id,
            "source": "live",
            "state": self.state.value,
            "bars": [b.to_dict() for b in self.bars],
            "total_bars": len(self.bars),
            "total_decisions": len(self.all_decisions),
            "pnl_by_type": self._get_pnl_summary(),
            "llm_stats": {
                "primary": self.llm_primary.stats(),
                "boost": self.llm_boost.stats(),
            },
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "duration_seconds": (datetime.utcnow() - self.started_at).total_seconds()
                                if self.started_at else 0,
        }
