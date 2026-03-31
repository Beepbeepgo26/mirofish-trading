#!/usr/bin/env python3
"""
MiroFish Trading Simulation — CLI Runner
Run simulations directly from the command line.

Usage:
    python scripts/run_simulation.py --scenario a --seed 42
    python scripts/run_simulation.py --scenario b --seed 123
    python scripts/run_simulation.py --scenario both
"""
import asyncio
import argparse
import logging
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.config import AppConfig
from app.services.simulation_manager import SimulationManager
from app.scenarios.market_scenarios import generate_scenario_a, generate_scenario_b


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )


async def run_scenario(config: AppConfig, scenario: dict) -> dict:
    sim = SimulationManager(config, scenario)
    await sim.setup()
    results = await sim.run()
    return results


async def main_async(args):
    config = AppConfig.load()

    # Validate LLM config
    if not config.llm_primary.api_key:
        print("\n❌ ERROR: LLM_API_KEY not set in .env file.")
        print("   Copy .env.example to .env and fill in your API keys.")
        print("   See README.md for setup instructions.\n")
        sys.exit(1)

    print("\n" + "█" * 70)
    print("  MIROFISH TRADING SIMULATION — LLM AGENT MODE")
    print("  ES Futures · Institutional vs Retail · Al Brooks PA")
    print("█" * 70)
    print(f"\n  Primary LLM: {config.llm_primary.model_name} @ {config.llm_primary.base_url}")
    print(f"  Boost LLM:   {config.llm_boost.model_name} @ {config.llm_boost.base_url}")
    print(f"  Zep Memory:  {'✓ configured' if config.zep_api_key else '✗ disabled'}")
    print(f"  Concurrency: {config.sim.concurrency}")
    print()

    # Override config from CLI args
    if args.institutional:
        config.sim.agents_institutional = args.institutional
    if args.retail:
        config.sim.agents_retail = args.retail
    if args.rounds:
        config.sim.max_rounds = args.rounds

    results = []

    if args.scenario in ("a", "both"):
        scenario_a = generate_scenario_a(seed=args.seed)
        if args.rounds:
            scenario_a["free_run_bars"] = args.rounds
        r = await run_scenario(config, scenario_a)
        results.append(r)

    if args.scenario in ("b", "both"):
        scenario_b = generate_scenario_b(seed=args.seed + 81)
        if args.rounds:
            scenario_b["free_run_bars"] = args.rounds
        r = await run_scenario(config, scenario_b)
        results.append(r)

    # Print summary
    print("\n" + "=" * 70)
    print("  SIMULATION COMPLETE")
    print("=" * 70)
    for r in results:
        print(f"\n  Scenario: {r['scenario']}")
        print(f"  Bars: {r['total_bars']} | Decisions: {r['total_decisions']}")
        print(f"  LLM calls: primary={r['llm_stats']['primary']['total_calls']}, "
              f"boost={r['llm_stats']['boost']['total_calls']}")
        print(f"  Total tokens: {r['llm_stats']['primary']['total_tokens'] + r['llm_stats']['boost']['total_tokens']}")
        print(f"\n  P&L:")
        for atype, stats in sorted(r["pnl_by_type"].items()):
            total = stats["total_realized"] + stats["total_unrealized"]
            print(f"    {atype:<15} ${total:>10,.0f}  (W:{stats['winners']} L:{stats['losers']})")
        print(f"\n  Output: output/{r['sim_id']}/")


def main():
    parser = argparse.ArgumentParser(description="MiroFish Trading Simulation CLI")
    parser.add_argument("--scenario", choices=["a", "b", "both"], default="both",
                        help="Which scenario to run")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--institutional", type=int, help="Number of institutional agents")
    parser.add_argument("--retail", type=int, help="Number of retail agents")
    parser.add_argument("--rounds", type=int, help="Number of free-run bars")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    setup_logging(args.log_level)
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
