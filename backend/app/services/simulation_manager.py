"""
Simulation Manager — The core orchestrator.
Manages the full simulation lifecycle:
  1. Initialize agents with LLM clients
  2. Seed knowledge graph
  3. Run simulation loop (seed bars → free-run bars)
  4. Collect and compile results
"""
import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime
from typing import Optional

import numpy as np

from app.config import AppConfig
from app.models.order_book import OrderBook, Side, Bar, snap_to_tick
from app.models.market_state import BrooksStateMachine, MarketState
from app.agents.profiles import (
    create_institutional_profiles, create_retail_profiles,
    create_mm_profiles, create_noise_profiles,
    AL_BROOKS_FULL_METHODOLOGY,
)
from app.agents.llm_agent import LLMTradingAgent, NoiseAgent, AgentDecision, Position
from app.services.llm_client import LLMClient
from app.services.zep_memory import ZepMemoryService

logger = logging.getLogger(__name__)


class SimulationManager:
    """
    Orchestrates a complete trading simulation run.
    """

    def __init__(self, config: AppConfig, scenario: dict, sim_id: Optional[str] = None):
        self.config = config
        self.scenario = scenario
        self.sim_id = sim_id or datetime.now().strftime("%Y%m%d_%H%M%S")

        # Core components
        self.book = OrderBook()
        self.state_machine = BrooksStateMachine()
        self.bars: list[Bar] = []
        self.all_decisions: list[AgentDecision] = []

        # LLM clients
        self.llm_primary = LLMClient(
            config.llm_primary,
            concurrency=config.sim.concurrency,
            name="primary"
        )
        self.llm_boost = LLMClient(
            config.llm_boost,
            concurrency=config.sim.concurrency,
            name="boost"
        )

        # Zep memory
        self.memory = ZepMemoryService(
            api_key=config.zep_api_key,
            group_id=f"mirofish_{self.sim_id}"
        )

        # Agents (initialized in setup)
        self.agents: list = []
        self._output_dir = os.path.join("output", self.sim_id)

    async def setup(self):
        """Initialize all agents and memory."""
        os.makedirs(self._output_dir, exist_ok=True)
        logger.info(f"Setting up simulation {self.sim_id}...")

        # Initialize Zep and seed methodology
        await self.memory.initialize()
        await self.memory.seed_methodology(AL_BROOKS_FULL_METHODOLOGY)

        # Create agent profiles
        inst_profiles = create_institutional_profiles(self.config.sim.agents_institutional)
        retail_profiles = create_retail_profiles(self.config.sim.agents_retail)
        mm_profiles = create_mm_profiles(self.config.sim.agents_market_maker)
        noise_profiles = create_noise_profiles(self.config.sim.agents_noise)

        # Instantiate LLM agents
        # Institutional → primary LLM (smartest model)
        for p in inst_profiles:
            self.agents.append(LLMTradingAgent(p, self.llm_primary, memory=self.memory))

        # Market makers → primary LLM (need good judgment)
        for p in mm_profiles:
            self.agents.append(LLMTradingAgent(p, self.llm_primary, memory=self.memory))

        # Retail → boost LLM (cheaper model, personality does the heavy lifting)
        for p in retail_profiles:
            self.agents.append(LLMTradingAgent(p, self.llm_boost, memory=self.memory))

        # Noise → rule-based (no LLM cost)
        for p in noise_profiles:
            self.agents.append(NoiseAgent(p.agent_id))

        logger.info(f"Agents created: {len(self.agents)} total "
                     f"({self.config.sim.agents_institutional} inst, "
                     f"{self.config.sim.agents_retail} retail, "
                     f"{self.config.sim.agents_market_maker} mm, "
                     f"{self.config.sim.agents_noise} noise)")

    async def run(self) -> dict:
        """Execute the full simulation."""
        logger.info(f"\n{'='*70}")
        logger.info(f"  RUNNING: {self.scenario['name']}")
        logger.info(f"  Agents: {len(self.agents)}")
        logger.info(f"  Seed bars: {self.scenario['seed_bar_count']}")
        logger.info(f"  Free-run bars: {self.scenario['free_run_bars']}")
        logger.info(f"{'='*70}\n")

        seed_bars = self.scenario["seed_bars"]
        free_run_count = self.scenario["free_run_bars"]
        total_bars = len(seed_bars) + free_run_count

        # Initialize order book with first price
        first_price = seed_bars[0]["open"]
        self.book.last_price = first_price

        # Seed initial MM liquidity
        self._seed_initial_liquidity(first_price)

        # ─── Phase 1: Seed bars (price determined by scenario) ───
        for t, seed_bar in enumerate(seed_bars):
            logger.info(f"  [SEED] Bar {t}: O={seed_bar['open']:.2f} "
                         f"H={seed_bar['high']:.2f} L={seed_bar['low']:.2f} "
                         f"C={seed_bar['close']:.2f}")

            # Inject seed liquidity to establish price levels
            self._inject_seed_liquidity(seed_bar, t)

            # Build bar from seed data
            bar = Bar(timestamp=t, open=seed_bar["open"], high=seed_bar["high"],
                      low=seed_bar["low"], close=seed_bar["close"],
                      volume=seed_bar["volume"], num_trades=seed_bar["volume"] // 10)
            self.bars.append(bar)

            # Update state machine
            market_state = self.state_machine.process_bar(bar)

            # Agent decisions (concurrent LLM calls)
            await self._run_agent_round(market_state, bar.close, t)

            # Process order book
            self.book.build_bar(t)

            # Record to Zep
            bar_decisions = [d.to_dict() for d in self.all_decisions if d.timestamp == t]
            await self.memory.record_bar_event(
                bar.to_dict(),
                {"cycle": market_state.cycle.value,
                 "always_in_dir": market_state.always_in.direction},
                bar_decisions
            )

        # ─── Phase 2: Free-run bars (agents drive price) ───
        logger.info(f"\n  ─── FREE RUN: Agents now drive price discovery ───\n")
        prev_close = self.bars[-1].close if self.bars else first_price
        catalysts = []

        for t_offset in range(free_run_count):
            t = len(seed_bars) + t_offset

            # Check for liquidity death and inject catalyst if needed
            free_run_bars_so_far = [b for b in self.bars if b.timestamp >= len(seed_bars)]
            if not self._check_liquidity_health(free_run_bars_so_far):
                catalyst = self._inject_catalyst(prev_close, t)
                catalysts.append(catalyst)

            # Replenish MM liquidity
            self._replenish_mm_liquidity(prev_close, t)

            # Get market state from last bar
            market_state = self.state_machine.state

            # Agent decisions drive all order flow
            await self._run_agent_round(market_state, prev_close, t)

            # Build bar from actual trades
            bar = self.book.build_bar(t, prev_close)
            if bar:
                self.bars.append(bar)
                self.state_machine.process_bar(bar)
                prev_close = bar.close
                vol_status = 'LOW' if bar.volume < 50 else 'OK'
                logger.info(f'  [FREE] Bar {t}: O={bar.open:.2f} H={bar.high:.2f} '
                             f'L={bar.low:.2f} C={bar.close:.2f} V={bar.volume} '
                             f'[{vol_status}] | '
                             f'{self.state_machine.get_state_summary()}')

        # Compile results
        results = self._compile_results()

        # Save outputs
        await self._save_outputs(results)

        # Log LLM stats
        logger.info(f"\n  LLM Stats:")
        logger.info(f"    Primary: {self.llm_primary.stats()}")
        logger.info(f"    Boost:   {self.llm_boost.stats()}")

        await self.memory.close()
        return results

    async def _run_agent_round(self, market_state: MarketState,
                                current_price: float, timestamp: int):
        """Run all agents concurrently with rate limiting."""
        random.shuffle(self.agents)

        # Split into batches to respect concurrency limits
        batch_size = self.config.sim.concurrency
        for i in range(0, len(self.agents), batch_size):
            batch = self.agents[i:i + batch_size]
            tasks = []
            for agent in batch:
                tasks.append(
                    agent.decide(market_state, current_price,
                                 self.book, self.bars, timestamp)
                )
            decisions = await asyncio.gather(*tasks, return_exceptions=True)

            for d in decisions:
                if isinstance(d, AgentDecision):
                    self.all_decisions.append(d)
                elif isinstance(d, Exception):
                    logger.error(f"Agent decision error: {d}")

    def _seed_initial_liquidity(self, price: float):
        """Seed order book with initial two-sided liquidity."""
        for offset in [0.25, 0.50, 0.75, 1.00, 1.50, 2.00]:
            self.book.submit_limit_order("SEED", Side.BUY,
                                          snap_to_tick(price - offset), 100, 0)
            self.book.submit_limit_order("SEED", Side.SELL,
                                          snap_to_tick(price + offset), 100, 0)

    def _inject_seed_liquidity(self, seed_bar: dict, timestamp: int):
        """Inject orders across seed bar's price range."""
        mid = (seed_bar["open"] + seed_bar["close"]) / 2
        for price in np.linspace(seed_bar["low"], seed_bar["high"], 8):
            price = snap_to_tick(price)
            qty = random.randint(10, 30)
            side = Side.BUY if price < mid else Side.SELL
            self.book.submit_limit_order("SEED", side, price, qty, timestamp)

    def _replenish_mm_liquidity(self, price: float, timestamp: int):
        """Keep background liquidity available during free-run."""
        for offset in [0.25, 0.50, 1.00]:
            self.book.submit_limit_order("SEED_MM", Side.BUY,
                                          snap_to_tick(price - offset), 30, timestamp)
            self.book.submit_limit_order("SEED_MM", Side.SELL,
                                          snap_to_tick(price + offset), 30, timestamp)

    def _check_liquidity_health(self, recent_bars: list, threshold: int = 50) -> bool:
        """Detect liquidity death: 3+ consecutive bars with volume < threshold."""
        if len(recent_bars) < 3:
            return True  # Healthy (not enough data)
        last_3 = recent_bars[-3:]
        dead_bars = sum(1 for b in last_3 if b.volume < threshold)
        return dead_bars < 3  # Healthy if fewer than 3 dead bars

    def _inject_catalyst(self, current_price: float, timestamp: int,
                         direction: str = 'random') -> dict:
        """Inject a news catalyst event that forces agents to re-evaluate."""
        if direction == 'random':
            direction = random.choice(['bullish', 'bearish'])

        # Create an order flow shock
        shock_size = random.uniform(1.0, 3.0)  # 1-3 point move
        if direction == 'bearish':
            shock_size = -shock_size

        # Inject aggressive orders to move price
        target = snap_to_tick(current_price + shock_size)
        qty = random.randint(50, 150)
        if shock_size > 0:
            self.book.submit_market_order('CATALYST', Side.BUY, qty, timestamp)
            # Replenish asks above new price
            for offset in [0.25, 0.50, 0.75, 1.0]:
                self.book.submit_limit_order('CATALYST', Side.SELL,
                    snap_to_tick(target + offset), 40, timestamp)
        else:
            self.book.submit_market_order('CATALYST', Side.SELL, qty, timestamp)
            for offset in [0.25, 0.50, 0.75, 1.0]:
                self.book.submit_limit_order('CATALYST', Side.BUY,
                    snap_to_tick(target - offset), 40, timestamp)

        catalyst = {
            'type': 'NEWS_CATALYST',
            'direction': direction,
            'shock_points': round(shock_size, 2),
            'timestamp': timestamp,
        }
        logger.info(f'  [CATALYST] Injected {direction} catalyst: '
                   f'{shock_size:+.2f} pts at bar {timestamp}')
        return catalyst

    def _compile_results(self) -> dict:
        """Compile all simulation results."""
        pnl_by_type = {}
        for agent in self.agents:
            t = agent.agent_type
            if t not in pnl_by_type:
                pnl_by_type[t] = {"agents": 0, "total_realized": 0,
                                  "total_unrealized": 0, "winners": 0, "losers": 0}
            pnl_by_type[t]["agents"] += 1
            pnl_by_type[t]["total_realized"] += agent.realized_pnl
            unrealized = agent.position.unrealized_pnl if hasattr(agent.position, 'unrealized_pnl') else 0
            pnl_by_type[t]["total_unrealized"] += unrealized
            if agent.realized_pnl > 0:
                pnl_by_type[t]["winners"] += 1
            elif agent.realized_pnl < 0:
                pnl_by_type[t]["losers"] += 1

        return {
            "sim_id": self.sim_id,
            "scenario": self.scenario["name"],
            "seed_bar_count": self.scenario.get("seed_bar_count", 0),
            "bars": [b.to_dict() for b in self.bars],
            "decisions": [d.to_dict() for d in self.all_decisions],
            "pnl_by_type": pnl_by_type,
            "total_bars": len(self.bars),
            "total_decisions": len(self.all_decisions),
            "llm_stats": {
                "primary": self.llm_primary.stats(),
                "boost": self.llm_boost.stats(),
            },
        }

    async def _save_outputs(self, results: dict):
        """Save all outputs to disk."""
        # Results JSON
        results_path = os.path.join(self._output_dir, "results.json")
        with open(results_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"  Results saved: {results_path}")

        # Decision log
        log_path = os.path.join(self._output_dir, "decision_log.jsonl")
        with open(log_path, "w") as f:
            for d in self.all_decisions:
                f.write(json.dumps(d.to_dict(), default=str) + "\n")
        logger.info(f"  Decision log saved: {log_path}")

        # Human-readable summary
        summary_path = os.path.join(self._output_dir, "summary.txt")
        with open(summary_path, "w") as f:
            f.write(f"{'='*70}\n")
            f.write(f"  SIMULATION SUMMARY: {results['scenario']}\n")
            f.write(f"  ID: {results['sim_id']}\n")
            f.write(f"{'='*70}\n\n")

            f.write(f"  Total bars: {results['total_bars']}\n")
            f.write(f"  Total decisions: {results['total_decisions']}\n\n")

            f.write(f"  P&L BY AGENT TYPE:\n")
            f.write(f"  {'Type':<15} {'N':>5} {'Realized':>12} {'Unrealized':>12} {'W':>4} {'L':>4}\n")
            f.write(f"  {'-'*55}\n")
            for atype, stats in sorted(results["pnl_by_type"].items()):
                f.write(f"  {atype:<15} {stats['agents']:>5} "
                        f"${stats['total_realized']:>10,.0f} "
                        f"${stats['total_unrealized']:>10,.0f} "
                        f"{stats['winners']:>4} {stats['losers']:>4}\n")

            f.write(f"\n  LLM Usage:\n")
            for tier, stats in results["llm_stats"].items():
                f.write(f"    {tier}: {stats['total_calls']} calls, "
                        f"{stats['total_tokens']} tokens, "
                        f"{stats['errors']} errors\n")

            # Notable decisions
            f.write(f"\n  NOTABLE DECISIONS:\n")
            f.write(f"  {'-'*55}\n")
            notable = [d for d in self.all_decisions
                       if d.action not in ("HOLD", "N/A") and d.conviction > 0.5]
            for d in notable[:30]:
                f.write(f"  Bar {d.timestamp:2d} | {d.to_log_str()}\n")

        logger.info(f"  Summary saved: {summary_path}")
