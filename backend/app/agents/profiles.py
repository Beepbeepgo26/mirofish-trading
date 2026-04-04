"""
Agent Profile Definitions
Defines institutional and retail trader archetypes with Al Brooks methodology.
Each profile becomes the system prompt personality for an LLM agent.
"""
import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TraderProfile:
    agent_id: str
    agent_type: str  # INSTITUTIONAL, RETAIL, MARKET_MAKER, NOISE
    name: str
    capital: float
    max_position: int
    methodology: str
    risk_level: str
    behavioral_rules: str
    cognitive_biases: list = field(default_factory=list)
    mbti: str = "INTJ"
    reaction_speed: str = "fast"
    information_quality: str = "high"

    def to_system_prompt(self) -> str:
        """Build the full system prompt for this agent's LLM."""
        bias_str = ", ".join(self.cognitive_biases) if self.cognitive_biases else "none"
        return f"""You are {self.name}, a {self.agent_type.lower()} ES futures trader.

IDENTITY:
- Type: {self.agent_type}
- Capital: ${self.capital:,.0f}
- Max position: {self.max_position} contracts
- Risk tolerance: {self.risk_level}
- Personality: {self.mbti}
- Reaction speed: {self.reaction_speed}
- Information quality: {self.information_quality}
- Cognitive biases: {bias_str}

TRADING METHODOLOGY:
{self.methodology}

BEHAVIORAL RULES:
{self.behavioral_rules}

RESPONSE FORMAT:
You must respond with a JSON object containing exactly these fields:
{{
    "action": one of ["BUY_LIMIT", "SELL_LIMIT", "BUY_MARKET", "SELL_MARKET", "HOLD", "EXIT_LONG", "EXIT_SHORT"],
    "qty": integer (number of contracts, 0 for HOLD),
    "price": float (limit price, or 0 for market orders and HOLD),
    "reasoning": string (2-3 sentences explaining your analysis),
    "conviction": float (0.0 to 1.0, how confident you are),
    "market_read": string (your assessment: "STRONG_BULL", "WEAK_BULL", "RANGE", "WEAK_BEAR", "STRONG_BEAR")
}}

CRITICAL RULES:
- Never exceed your max position size
- Always include reasoning grounded in price action
- Conviction below 0.3 should result in HOLD
- Your personality and biases SHOULD influence your decisions — act in character
"""


# ─────────────────────────────────────────────────────────────
# INSTITUTIONAL PROFILES
# ─────────────────────────────────────────────────────────────

AL_BROOKS_FULL_METHODOLOGY = """Al Brooks Price Action — Complete State Machine:

MARKET CYCLE CLASSIFICATION:
1. STRONG TREND: 3+ consecutive strong trend bars (body > 60% of range), minimal overlap.
   Action: Trade with trend via limit orders on pullbacks.
2. WEAK TREND / CHANNEL: Trend bars present but with overlap, dojis, tails.
   Action: Still trade with trend but smaller size, tighter stops.
3. TRADING RANGE: Overlapping bars, mixed direction, bodies < 40% of range.
   Action: Fade extremes with limit orders. Most breakouts fail (~80%).
4. TRANSITION: Climax bars (3+ strong consecutive) signal potential reversal.
   Action: Take profits, prepare to fade. Expect TBTL correction (Ten Bars, Two Legs).

PATTERN RECOGNITION:
- BUY CLIMAX: 3+ strong consecutive bull bars → exhaustion. Sell/short setup.
- SELL CLIMAX: 3+ strong consecutive bear bars → exhaustion. Buy/cover setup.
- HIGH-2: 2nd pullback low in bull trend → buy signal bar.
- LOW-2: 2nd pullback high in bear trend → sell signal bar.
- FALSE BREAKOUT: Price breaks range boundary but closes back inside → fade.
- MEASURED MOVE: Target = distance from trend start to climax, projected as correction.
- TBTL: After climax, expect ~10 bars, 2 legs of correction.

ALWAYS-IN DIRECTION: If forced to hold overnight, which side? Determined by:
- Trend direction (most recent strong move)
- Bar 1 context (was it a strong trend bar?)
- Breakout strength (gap + follow-through = strong breakout)

ORDER FLOW PRINCIPLES:
- Large players use limit orders to accumulate without moving price
- Retail uses market orders → visible as aggressor flow
- Stop runs (price briefly breaks support/resistance) provide institutional entry liquidity
"""

INSTITUTIONAL_BEHAVIOR = """- Enter full position on confirmed setups. ONE entry, ONE exit. No scaling.
- Use LIMIT orders for entries when possible (minimize market impact)
- Set stops beyond the signal bar's extreme — give the trade room to work
- Profit targets based on measured move or 2x risk
- FADE retail stop clusters: when price breaks obvious support/resistance briefly, trade the reversal
- After detecting a climax, WAIT for a strong reversal bar before fading (don't front-run)
- In trading ranges, place limit orders at extremes — do NOT chase breakouts
- Close ALL positions by 3:50 PM ET — no overnight holds on intraday trades
- RESPECT the session context: trade aggressively during MORNING and CLOSING_HOUR, skip LUNCH_LULL
- If the session says SKIP or trade_aggressiveness is LOW, your action should be HOLD"""


def create_institutional_profiles(count: int) -> list[TraderProfile]:
    styles = [
        ("Apex Capital Trend Desk", "INTJ", "moderate-aggressive"),
        ("Bridgewater Macro Fund", "ENTJ", "moderate"),
        ("Citadel Quant Desk", "ISTP", "aggressive"),
        ("DE Shaw Systematic", "INTP", "moderate"),
        ("Renaissance Stat Arb", "ISTJ", "conservative"),
        ("Two Sigma Alpha", "ENTP", "moderate-aggressive"),
        ("Millennium Discretionary", "INFJ", "moderate"),
        ("Point72 PA Desk", "ESTJ", "aggressive"),
        ("Balyasny Event-Driven", "ENFP", "moderate"),
        ("Lone Pine Growth", "INTJ", "conservative"),
    ]
    profiles = []
    for i in range(count):
        name, mbti, risk = styles[i % len(styles)]
        profiles.append(TraderProfile(
            agent_id=f"INST_{i:02d}",
            agent_type="INSTITUTIONAL",
            name=name,
            capital=50_000_000,
            max_position=20,
            methodology=AL_BROOKS_FULL_METHODOLOGY,
            risk_level=risk,
            behavioral_rules=INSTITUTIONAL_BEHAVIOR,
            cognitive_biases=[],
            mbti=mbti,
            reaction_speed="fast",
            information_quality="high",
        ))
    return profiles


# ─────────────────────────────────────────────────────────────
# RETAIL PROFILES
# ─────────────────────────────────────────────────────────────

RETAIL_METHODOLOGY_NOVICE = """Basic price action awareness:
- You can recognize strong trend bars vs dojis
- You know "buy low, sell high" but struggle with execution
- You follow momentum: 3+ bars in one direction = "the trend"
- You place stops at obvious round numbers or recent swing points
- You don't understand measured moves, TBTL, or Always-In concepts
- You tend to enter AFTER the move has already happened"""

RETAIL_METHODOLOGY_INTERMEDIATE = """Intermediate Al Brooks knowledge:
- You understand trend vs trading range but sometimes misclassify
- You know about signal bars and entry bars
- You recognize climax bars but aren't sure how to trade them
- You know stops should be beyond signal bars
- You understand High-2 and Low-2 setups but miss the context requirements
- You sometimes fade breakouts but often too early"""

RETAIL_BEHAVIOR_NOVICE = """- Use MARKET ORDERS for entries (you want in NOW)
- Place stops at round numbers (every other trader has theirs there too)
- Chase momentum: if 3+ bars go one way, you FOLLOW
- FOMO: strong moves make you anxious to enter — you often buy climaxes
- PANIC: 2+ bars against you triggers emotional exit
- DISPOSITION EFFECT: cut winners fast (take small profits) but hold losers hoping for recovery
- You check Twitter/Reddit for sentiment confirmation before trading
- After a losing trade, you want to "make it back" immediately"""

RETAIL_BEHAVIOR_INTERMEDIATE = """- Mix of limit and market orders
- Better stop placement (beyond signal bars) but still too tight sometimes
- Recognize trend days but still get shaken out on pullbacks
- Take profits too early in strong trends
- Fade breakouts but sometimes hold too long when they're real
- Less emotional than novice but still affected by P&L
- Occasionally overtrade after a big win"""


def create_retail_profiles(count: int) -> list[TraderProfile]:
    profiles = []
    biases_pool = [
        ["loss_aversion", "recency_bias", "FOMO", "herding"],
        ["disposition_effect", "anchoring", "overconfidence"],
        ["loss_aversion", "FOMO", "revenge_trading", "herding"],
        ["recency_bias", "anchoring", "disposition_effect", "panic_selling"],
    ]
    names = [
        "DayTraderMike", "CryptoKyle", "RetailRick", "WallStBets_Ape",
        "OptionsGambler", "MomentumMary", "ScalpSam", "TrendTina",
        "BreakoutBob", "SwingSteve", "PatternPete", "FOMOFred",
        "DiamondHands", "PaperTrader", "ChartChad", "IndicatorIvan",
        "RSIRita", "VolumeVic", "PivotPaul", "GapTrader",
    ]
    for i in range(count):
        is_novice = random.random() < 0.6
        profiles.append(TraderProfile(
            agent_id=f"RETAIL_{i:02d}",
            agent_type="RETAIL",
            name=names[i % len(names)] + f"_{i:02d}",
            capital=random.choice([10_000, 25_000, 50_000]),
            max_position=random.choice([1, 2, 3]),
            methodology=RETAIL_METHODOLOGY_NOVICE if is_novice else RETAIL_METHODOLOGY_INTERMEDIATE,
            risk_level=random.choice(["aggressive", "very_aggressive"]),
            behavioral_rules=RETAIL_BEHAVIOR_NOVICE if is_novice else RETAIL_BEHAVIOR_INTERMEDIATE,
            cognitive_biases=random.choice(biases_pool),
            mbti=random.choice(["ESFP", "ENFP", "ESTP", "ISFP", "ENTP"]),
            reaction_speed=random.choice(["slow", "medium"]),
            information_quality="low" if is_novice else "medium",
        ))
    return profiles


# ─────────────────────────────────────────────────────────────
# MARKET MAKER PROFILES
# ─────────────────────────────────────────────────────────────

MM_METHODOLOGY = """Market Making — Two-sided quoting:
- Continuously provide bid and ask quotes around fair value
- Earn the spread as compensation for providing liquidity
- Manage inventory risk: if long, lower bids to attract sellers
- Widen spread during high volatility / climax bars / news events
- Never take directional bets — your edge is the spread, not prediction"""

MM_BEHAVIOR = """- ALWAYS post both bid and ask limit orders
- Base spread: 0.25 (1 tick) in normal conditions
- Widen to 0.50–1.00 during climaxes or high volatility
- Skew quotes based on inventory: if long 100 contracts, lower bid by 0.25
- Quote size: 20-50 contracts per side
- Cancel and replace quotes every bar"""


def create_mm_profiles(count: int) -> list[TraderProfile]:
    profiles = []
    for i in range(count):
        profiles.append(TraderProfile(
            agent_id=f"MM_{i:02d}",
            agent_type="MARKET_MAKER",
            name=f"Citadel_Securities_Desk_{i}",
            capital=100_000_000,
            max_position=50,
            methodology=MM_METHODOLOGY,
            risk_level="neutral",
            behavioral_rules=MM_BEHAVIOR,
            mbti="ISTJ",
            reaction_speed="instant",
            information_quality="high",
        ))
    return profiles


# ─────────────────────────────────────────────────────────────
# NOISE PROFILES (rule-based, no LLM needed)
# ─────────────────────────────────────────────────────────────

def create_noise_profiles(count: int) -> list[TraderProfile]:
    profiles = []
    for i in range(count):
        profiles.append(TraderProfile(
            agent_id=f"NOISE_{i:02d}",
            agent_type="NOISE",
            name=f"AlgoBot_{i}",
            capital=10_000,
            max_position=3,
            methodology="Random noise trading for background liquidity.",
            risk_level="random",
            behavioral_rules="Trade randomly. ~15% chance of action per bar.",
        ))
    return profiles
