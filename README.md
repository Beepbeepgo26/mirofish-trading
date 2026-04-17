# MiroFish Trading Simulation

> ⚠️ **Repo Identity Check:** This is `mirofish-trading` — the trading simulation app.
> For the standalone forecasting app, see `mirofish-forecast` repo.
> See `AGENT_CONTEXT.md` for full disambiguation.

**ES Futures Multi-Agent Simulation — Institutional vs Retail — Al Brooks Price Action**

Adapted from [MiroFish](https://github.com/666ghj/MiroFish) swarm intelligence engine. Uses LLM-powered agents with distinct personalities, trading methodologies, and cognitive biases to simulate ES futures order flow dynamics.

## What This Does

Spawns 70+ AI trading agents (institutional desks, retail traders, market makers, noise bots) into a continuous double-auction order book. Each agent receives:
- The current market state via an Al Brooks price action state machine
- A personality profile (MBTI, risk tolerance, methodology depth, cognitive biases)
- Recent price bars and order book context

The LLM generates a structured trading decision (action, quantity, price, reasoning, conviction). The order book matches fills, and emergent price action develops from the aggregate order flow.

Two scenarios test core Al Brooks predictions:
- **Scenario A**: Bull trend → 3-bar buy climax → does the TBTL correction materialize?
- **Scenario B**: Gap-up open against overnight trend → continuation or reversal?

## Quick Start

### 1. Clone and configure

```bash
git clone <this-repo>
cd mirofish-trading
cp .env.example .env
# Edit .env with your API keys
```

### 2. Set API keys in `.env`

```env
# Primary LLM — used for institutional agents and market makers
# Recommended: GPT-4o, Claude (via OpenRouter), Qwen-Plus
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o

# Boost LLM — used for retail agents (cheaper model works fine)
LLM_BOOST_API_KEY=sk-your-key
LLM_BOOST_BASE_URL=https://api.openai.com/v1
LLM_BOOST_MODEL_NAME=gpt-4o-mini

# Optional: Zep Cloud for knowledge graph memory
ZEP_API_KEY=z_your-zep-key
```

### 3. Run with Docker (recommended)

```bash
# Start the API server
docker compose up backend

# Or run a one-shot simulation from CLI
docker compose --profile cli run sim-runner --scenario both --seed 42
```

### 4. Run without Docker

```bash
cd backend
pip install -e .
# or: uv pip install -r pyproject.toml

# Start API server
python -m app.main

# Or run CLI directly
cd ..
python scripts/run_simulation.py --scenario both --seed 42
```

## CLI Options

```
python scripts/run_simulation.py [options]

Options:
  --scenario {a,b,both}    Which scenario to run (default: both)
  --seed INT               Random seed (default: 42)
  --institutional INT      Number of institutional agents
  --retail INT             Number of retail agents
  --rounds INT             Number of free-run bars (agents drive price)
  --log-level {DEBUG,INFO,WARNING,ERROR}
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Service health check |
| GET | `/api/scenarios` | List available scenarios |
| POST | `/api/simulations` | Start a new simulation |
| GET | `/api/simulations/<id>` | Get full results |
| GET | `/api/simulations/<id>/decisions` | Agent decisions (filterable) |
| GET | `/api/simulations/<id>/bars` | Price bars |

### Start a simulation via API

```bash
curl -X POST http://localhost:5001/api/simulations \
  -H "Content-Type: application/json" \
  -d '{"scenario": "scenario_a", "seed": 42}'
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Flask API (5001)                   │
├─────────────────────────────────────────────────────┤
│              Simulation Manager                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ Order    │  │ Brooks   │  │   Zep Memory     │  │
│  │ Book     │  │ State    │  │   (Knowledge     │  │
│  │ Engine   │  │ Machine  │  │    Graph)        │  │
│  └──────────┘  └──────────┘  └──────────────────┘  │
├─────────────────────────────────────────────────────┤
│                   Agent Pool                         │
│  ┌────────────┐  ┌──────────┐  ┌────┐  ┌───────┐  │
│  │Institutional│  │  Retail  │  │ MM │  │ Noise │  │
│  │ (GPT-4o)   │  │(4o-mini) │  │(4o)│  │(rules)│  │
│  │ 7 agents   │  │40 agents │  │ 3  │  │  20   │  │
│  └────────────┘  └──────────┘  └────┘  └───────┘  │
├─────────────────────────────────────────────────────┤
│              LLM Client (Async + Rate Limited)       │
│  Primary: GPT-4o / Claude    Boost: GPT-4o-mini     │
└─────────────────────────────────────────────────────┘
```

## Agent Profiles

**Institutional** (7 agents, primary LLM): Full Al Brooks state machine methodology. Use limit orders, TWAP execution, scale into positions. Detect climaxes and fade them. Wide stops, large size. Named after real fund archetypes (Apex Capital, Bridgewater, Citadel, etc.) with distinct MBTI personalities.

**Retail** (40 agents, boost LLM): Simplified price action + cognitive biases. Use market orders, chase momentum (FOMO), place stops at obvious levels, panic exit on adverse bars. 60% novice, 40% intermediate. Each has randomized biases (loss aversion, disposition effect, herding, etc.).

**Market Maker** (3 agents, primary LLM): Two-sided quoting with inventory skew. Widen spreads during climaxes. No directional bias.

**Noise** (20 agents, rule-based): Random orders at ~15% activity rate. No LLM cost. Provides background liquidity.

## Output

Each simulation produces:
- `output/<sim_id>/results.json` — Full structured results
- `output/<sim_id>/decision_log.jsonl` — Every agent decision with reasoning
- `output/<sim_id>/summary.txt` — Human-readable P&L and notable trades

## Cost Estimation

Per simulation run (30 bars, 70 LLM agents):
- Primary LLM calls: ~300 (10 agents × 30 bars)
- Boost LLM calls: ~1,200 (40 agents × 30 bars)
- Estimated tokens: ~500K–1M total
- Estimated cost with GPT-4o + 4o-mini: ~$2–5 per run

To reduce cost: lower `--retail` count, use cheaper boost model, or reduce `--rounds`.

## Extending

**Add custom scenarios**: Create new functions in `backend/app/scenarios/market_scenarios.py` returning the same dict structure.

**Add agent archetypes**: Add new profiles in `backend/app/agents/profiles.py`. The `TraderProfile.to_system_prompt()` method builds the full system prompt.

**Connect real data**: Replace seed bars with actual ES futures OHLC from Databento or other sources. The system accepts any list of `{open, high, low, close, volume}` dicts.

**Integrate with existing dashboard**: The Flask API endpoints mirror the data shapes needed for your Databento/React dashboard. Price bars from `/api/simulations/<id>/bars` can feed directly into TradingView Lightweight Charts.

## License

AGPL-3.0 (following MiroFish upstream license)
