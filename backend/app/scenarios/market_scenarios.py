"""
Market Scenario Seed Generators
Produce the initial price bars that establish the market context
before agents begin driving price through order flow.
"""
import random


def generate_scenario_a(seed: int = 42) -> dict:
    """
    Scenario A: Strong bull trend → 3-bar buy climax → TBTL test zone.

    Phase 1 (bars 0-4): Gradual institutional accumulation
    Phase 2 (bars 5-7): Parabolic acceleration — BUY CLIMAX
    Phase 3 (bars 8-14): Indecision — seed bars thin out, agents take over
    """
    random.seed(seed)
    bars = []
    price = 5400.00

    # Phase 1: Orderly bull trend
    for i in range(5):
        move = random.uniform(0.5, 2.0)
        o, c = price, price + move
        h = c + random.uniform(0.0, 0.75)
        low = o - random.uniform(0.0, 0.5)
        bars.append({"open": o, "high": h, "low": low, "close": c,
                      "volume": random.randint(800, 1500)})
        price = c

    # Phase 2: Buy climax — 3 strong bull bars with expanding ranges
    for i in range(3):
        expansion = 1.5 + i * 0.5
        move = random.uniform(2.0, 3.5) * expansion / 1.5
        o, c = price, price + move
        h = c + random.uniform(0.0, 0.5)
        low = o - random.uniform(0.0, 0.25)
        bars.append({"open": o, "high": h, "low": low, "close": c,
                      "volume": random.randint(2000, 4000)})
        price = c

    # Phase 3: Indecision — thinner seed bars, agents drive discovery
    for i in range(7):
        move = random.uniform(-0.3, 0.3)  # Minimal seed influence
        o, c = price, price + move
        h = max(o, c) + random.uniform(0.1, 0.5)
        low = min(o, c) - random.uniform(0.1, 0.5)
        bars.append({"open": o, "high": h, "low": low, "close": c,
                      "volume": random.randint(200, 500)})
        price = c

    return {
        "name": "Scenario A: Bull Trend + 3-Bar Buy Climax",
        "description": (
            "Strong bull trend accelerates into a 3-bar buy climax. "
            "Al Brooks predicts: institutional profit-taking → TBTL correction "
            "(10 bars, 2 legs). Retail FOMO entries provide exit liquidity."
        ),
        "seed_bars": bars,
        "seed_bar_count": len(bars),
        "free_run_bars": 15,  # Additional bars where agents fully drive price
        "expected_outcomes": {
            "tbtl_correction": True,
            "institutional_exits_at_climax": True,
            "retail_fomo_at_climax": True,
            "correction_target_estimate": bars[4]["close"],
        },
    }


def generate_scenario_b(seed: int = 123) -> dict:
    """
    Scenario B: Overnight bear trend → gap-up RTH open → 50/50 resolution.

    Phase 1 (bars 0-4): Overnight (Globex) bear trend
    Phase 2 (bar 5): GAP UP open against overnight direction
    Phase 3 (bars 6-11): Opening range — institutional directional tests
    Phase 4 (bars 12+): Free run — agents determine resolution
    """
    random.seed(seed)
    bars = []
    price = 5420.00

    # Phase 1: Overnight bear trend
    for i in range(5):
        move = random.uniform(-1.5, -0.5)
        o, c = price, price + move
        h = o + random.uniform(0.0, 0.5)
        low = c - random.uniform(0.0, 0.75)
        bars.append({"open": o, "high": h, "low": low, "close": c,
                      "volume": random.randint(300, 600)})
        price = c

    overnight_close = price

    # Phase 2: Gap UP
    gap = random.uniform(3.0, 6.0)
    price = overnight_close + gap
    o = price
    c = price + random.uniform(-0.5, 1.5)
    h = max(o, c) + random.uniform(0.5, 1.5)
    low = min(o, c) - random.uniform(0.5, 1.5)
    bars.append({"open": o, "high": h, "low": low, "close": c,
                  "volume": random.randint(2000, 4000)})
    price = c

    # Phase 3: Opening range tests
    for i in range(6):
        direction = 1 if i % 2 == 0 else -1
        move = direction * random.uniform(0.5, 1.5)
        o, c = price, price + move
        h = max(o, c) + random.uniform(0.0, 0.75)
        low = min(o, c) - random.uniform(0.0, 0.75)
        bars.append({"open": o, "high": h, "low": low, "close": c,
                      "volume": random.randint(800, 2000)})
        price = c

    return {
        "name": "Scenario B: Gap-Up Open + Overnight Divergence",
        "description": (
            "Overnight Globex session bears down, but RTH opens with gap UP. "
            "Al Brooks: 50% probability of gap continuation vs reversal. "
            "Institutional agents probe both directions; retail chases gap direction."
        ),
        "seed_bars": bars,
        "seed_bar_count": len(bars),
        "free_run_bars": 18,
        "expected_outcomes": {
            "gap_direction": "UP",
            "overnight_direction": "DOWN",
            "resolution_probability": 0.5,
        },
        "overnight_close": overnight_close,
    }
