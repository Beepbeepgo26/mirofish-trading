# MiroFish Trading — Repo Identity

**This is the TRADING SIMULATION app. NOT mirofish-forecast.**

## Repo Identification
- Local path: `/Users/sam/Desktop/mirofish-trading/`
- Cloud Run service: `mirofish-trading` (us-west2)
- Revision tracking: `00041-wq2` and later
- Live URL: `https://mirofish-trading-r2hn52xsfq-wl.a.run.app`
- GCS bucket: `total-now-339022-mirofish-results`

## What This App Does
Multi-agent LLM simulation engine incorporating Al Brooks price action methodology. Runs trading simulations with agent decision-making, NOT a forecasting service.

## Key Technologies
- Flask + Vue.js
- GPT-4o / 4o-mini (agents)
- Zep Cloud (memory layer)
- Databento GLBX.MDP3 ES.c.0 (live data)
- Websocket streaming

## What This Repo Does NOT Contain
- LightGBM fast path models (that's mirofish-forecast)
- CQR/ACI calibration layer (that's mirofish-forecast)
- Natural language forecast synthesis (that's mirofish-forecast)
- Probability distribution outputs (that's mirofish-forecast)

## Before Making Changes
Confirm you are working in this repo by checking:
1. Path starts with `/Users/sam/Desktop/mirofish-trading/`
2. Cloud Run service target is `mirofish-trading`
3. Zep Cloud imports are present

If ANY of these don't match, STOP — you may be in the wrong repo.
