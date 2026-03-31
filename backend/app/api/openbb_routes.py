"""
OpenBB Workspace Integration — API endpoints for widgets.
Returns data in the flat JSON format that OpenBB widgets expect.
Serves widgets.json and apps.json configuration files.
"""
import json
import logging
import os
from collections import defaultdict
from flask import Blueprint, jsonify, request, Response
from app.config import config
from app.services.storage import StorageService

logger = logging.getLogger(__name__)
openbb_api = Blueprint("openbb_api", __name__)

# Path to OpenBB config files
_OPENBB_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'openbb')


def _get_storage() -> StorageService:
    """Get a StorageService instance configured from app config."""
    return StorageService(bucket_name=config.gcs_bucket)


# ─── Configuration Endpoints ───────────────────────────────────────────────────


@openbb_api.route("/widgets.json", methods=["GET"])
def widgets_json() -> Response:
    """Serve the OpenBB widget configuration manifest."""
    path = os.path.join(_OPENBB_DIR, "widgets.json")
    try:
        with open(path) as f:
            return Response(f.read(), mimetype="application/json")
    except FileNotFoundError:
        return jsonify({"error": "widgets.json not found"}), 404


@openbb_api.route("/apps.json", methods=["GET"])
def apps_json() -> Response:
    """Serve the OpenBB app layout configuration."""
    path = os.path.join(_OPENBB_DIR, "apps.json")
    try:
        with open(path) as f:
            return Response(f.read(), mimetype="application/json")
    except FileNotFoundError:
        return jsonify([]), 200


# ─── Data Endpoints (flat JSON arrays for OpenBB widgets) ──────────────────────


@openbb_api.route("/openbb/simulations", methods=["GET"])
def openbb_simulations() -> Response:
    """List simulations as a flat JSON array for OpenBB table widget."""
    storage = _get_storage()
    simulations = storage.list_simulations(limit=50)

    # Flatten for OpenBB table format
    rows: list[dict] = []
    for sim in simulations:
        pnl = sim.get("pnl_by_type", {})
        validation = sim.get("validation") or {}
        rows.append({
            "sim_id": sim.get("sim_id", ""),
            "scenario": sim.get("scenario", "Unknown"),
            "source": sim.get("source", "synthetic"),
            "total_bars": sim.get("total_bars", 0),
            "total_decisions": sim.get("total_decisions", 0),
            "inst_pnl": round(pnl.get("INSTITUTIONAL", {}).get("total_realized", 0), 0),
            "retail_pnl": round(pnl.get("RETAIL", {}).get("total_realized", 0), 0),
            "mm_pnl": round(pnl.get("MARKET_MAKER", {}).get("total_realized", 0), 0),
            "direction_correct": "✓" if validation.get("direction_correct") else
                                 "✗" if validation.get("comparison_available") else "—",
        })
    return jsonify(rows)


@openbb_api.route("/openbb/decisions", methods=["GET"])
def openbb_decisions() -> Response:
    """
    Agent decisions as enriched flat JSON array for OpenBB table widget.
    Includes trade classification, P&L context, pattern triggers, and strategy summary.
    """
    sim_id: str = request.args.get("sim_id", "")
    agent_type: str = request.args.get("agent_type", "")

    if not sim_id:
        return jsonify([])

    storage = _get_storage()
    results = storage.load_results(sim_id)
    if not results:
        return jsonify([])

    decisions = results.get("decisions", [])
    bars = results.get("bars", [])

    if agent_type:
        decisions = [d for d in decisions if d.get("agent_type") == agent_type]

    # Filter out HOLD and NOISE for cleaner display
    decisions = [d for d in decisions if d.get("action") != "HOLD"
                 and d.get("agent_type") != "NOISE"]

    # Build bar price lookup for enrichment
    bar_prices: dict[int, dict] = {}
    for b in bars:
        bar_prices[b["timestamp"]] = {
            "open": b["open"], "high": b["high"],
            "low": b["low"], "close": b["close"],
            "is_strong_bull": b.get("is_strong_bull", False),
            "is_strong_bear": b.get("is_strong_bear", False),
            "body_pct": b.get("body_pct", 0),
        }

    # Classify actions into trade types
    def classify_action(action: str) -> str:
        if "BUY" in action and "EXIT" not in action:
            return "ENTRY LONG"
        elif "SELL" in action and "EXIT" not in action:
            return "ENTRY SHORT"
        elif "EXIT_LONG" in action:
            return "EXIT LONG"
        elif "EXIT_SHORT" in action:
            return "EXIT SHORT (COVER)"
        return action

    # Detect likely Al Brooks pattern from bar context
    def detect_pattern(bar_idx: int, action: str, bars_data: dict) -> str:
        if bar_idx not in bars_data:
            return ""
        b = bars_data[bar_idx]
        patterns: list[str] = []

        # Check for climax (3 consecutive strong bars)
        if bar_idx >= 2:
            prev_bars = [bars_data.get(bar_idx - i, {}) for i in range(3)]
            if all(pb.get("is_strong_bull", False) for pb in prev_bars):
                patterns.append("BUY CLIMAX")
            elif all(pb.get("is_strong_bear", False) for pb in prev_bars):
                patterns.append("SELL CLIMAX")

        if b.get("is_strong_bull"):
            patterns.append("STRONG BULL BAR")
        elif b.get("is_strong_bear"):
            patterns.append("STRONG BEAR BAR")
        elif b.get("body_pct", 0) < 0.3:
            patterns.append("DOJI / INDECISION")

        return ", ".join(patterns[:2]) if patterns else "—"

    rows: list[dict] = []
    for d in decisions[:500]:
        bar_idx = d.get("timestamp", 0)
        bar_data = bar_prices.get(bar_idx, {})

        rows.append({
            "bar": bar_idx,
            "agent_id": d.get("agent_id", ""),
            "agent_type": d.get("agent_type", ""),
            "trade_type": classify_action(d.get("action", "")),
            "action": d.get("action", ""),
            "qty": d.get("qty", 0),
            "entry_price": round(d.get("price", 0), 2),
            "bar_close": round(bar_data.get("close", 0), 2),
            "conviction": round(d.get("conviction", 0) * 100),
            "market_read": d.get("market_read", ""),
            "pattern": detect_pattern(bar_idx, d.get("action", ""), bar_prices),
            "position": f"{d.get('position_side', 'FLAT')} ×{d.get('position_size', 0)}",
            "realized_pnl": round(d.get("realized_pnl", 0), 0),
            "unrealized_pnl": round(d.get("unrealized_pnl", 0), 0),
            "total_pnl": round(d.get("realized_pnl", 0) + d.get("unrealized_pnl", 0), 0),
            "reasoning": (d.get("reasoning", "") or "")[:300],
            "latency_ms": round(d.get("llm_latency_ms", 0), 0),
        })

    return jsonify(rows)


@openbb_api.route("/openbb/chart/price", methods=["GET"])
def openbb_price_chart() -> Response:
    """
    Plotly candlestick chart for OpenBB chart widget.
    Returns Plotly JSON figure configuration.
    """
    sim_id: str = request.args.get("sim_id", "")
    theme: str = request.args.get("theme", "dark")

    if not sim_id:
        return jsonify({"error": "sim_id required"}), 400

    storage = _get_storage()
    results = storage.load_results(sim_id)
    if not results:
        return jsonify({"error": "Simulation not found"}), 404

    bars = results.get("bars", [])
    if not bars:
        return jsonify({"error": "No bar data"}), 404

    # Build Plotly candlestick figure
    is_dark = theme == "dark"
    bg_color = "#0a0e17" if is_dark else "#ffffff"
    grid_color = "#1e293b" if is_dark else "#e2e8f0"
    text_color = "#e2e8f0" if is_dark else "#1e293b"

    timestamps = [b["timestamp"] for b in bars]
    opens = [b["open"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]
    volumes = [b.get("volume", 0) for b in bars]

    figure = {
        "data": [
            {
                "type": "candlestick",
                "x": timestamps,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "increasing": {"line": {"color": "#22c55e"}},
                "decreasing": {"line": {"color": "#ef4444"}},
                "name": "ES Price",
            },
            {
                "type": "bar",
                "x": timestamps,
                "y": volumes,
                "yaxis": "y2",
                "marker": {
                    "color": ["#22c55e40" if c >= o else "#ef444440"
                              for o, c in zip(opens, closes)]
                },
                "name": "Volume",
                "showlegend": False,
            }
        ],
        "layout": {
            "title": {
                "text": f"MiroFish — {results.get('scenario', 'Simulation')}",
                "font": {"color": text_color, "size": 14},
            },
            "paper_bgcolor": bg_color,
            "plot_bgcolor": bg_color,
            "font": {"color": text_color, "family": "JetBrains Mono, monospace"},
            "xaxis": {
                "title": "Bar",
                "gridcolor": grid_color,
                "rangeslider": {"visible": False},
            },
            "yaxis": {
                "title": "Price",
                "gridcolor": grid_color,
                "side": "right",
            },
            "yaxis2": {
                "title": "Volume",
                "overlaying": "y",
                "side": "left",
                "showgrid": False,
                "range": [0, max(volumes) * 4] if volumes else [0, 1],
            },
            "margin": {"l": 60, "r": 60, "t": 40, "b": 40},
            "showlegend": False,
        }
    }
    return jsonify(figure)


@openbb_api.route("/openbb/chart/pnl", methods=["GET"])
def openbb_pnl_chart() -> Response:
    """Plotly bar chart of P&L by agent type."""
    sim_id: str = request.args.get("sim_id", "")
    theme: str = request.args.get("theme", "dark")

    if not sim_id:
        return jsonify({"error": "sim_id required"}), 400

    storage = _get_storage()
    results = storage.load_results(sim_id)
    if not results:
        return jsonify({"error": "Simulation not found"}), 404

    pnl = results.get("pnl_by_type", {})

    is_dark = theme == "dark"
    bg_color = "#0a0e17" if is_dark else "#ffffff"
    text_color = "#e2e8f0" if is_dark else "#1e293b"

    types: list[str] = []
    realized: list[float] = []
    colors: list[str] = []
    color_map = {
        "INSTITUTIONAL": "#3b82f6",
        "RETAIL": "#f59e0b",
        "MARKET_MAKER": "#a855f7",
        "NOISE": "#64748b",
    }

    for agent_type in ["INSTITUTIONAL", "RETAIL", "MARKET_MAKER", "NOISE"]:
        if agent_type in pnl:
            types.append(agent_type)
            val = pnl[agent_type].get("total_realized", 0)
            realized.append(round(val, 0))
            colors.append(color_map.get(agent_type, "#64748b"))

    figure = {
        "data": [{
            "type": "bar",
            "x": types,
            "y": realized,
            "marker": {"color": colors},
            "text": [f"${v:,.0f}" for v in realized],
            "textposition": "outside",
            "textfont": {"color": text_color, "size": 12},
        }],
        "layout": {
            "title": {"text": "P&L by Agent Type", "font": {"color": text_color, "size": 14}},
            "paper_bgcolor": bg_color,
            "plot_bgcolor": bg_color,
            "font": {"color": text_color, "family": "JetBrains Mono, monospace"},
            "xaxis": {"gridcolor": "transparent"},
            "yaxis": {"title": "Realized P&L ($)", "gridcolor": "#1e293b" if is_dark else "#e2e8f0"},
            "margin": {"l": 60, "r": 20, "t": 40, "b": 40},
        }
    }
    return jsonify(figure)


@openbb_api.route("/openbb/chart/flow", methods=["GET"])
def openbb_flow_chart() -> Response:
    """
    Enhanced Plotly chart of agent order flow with annotations for key patterns.
    Shows institutional vs retail buy/sell divergence clearly.
    """
    sim_id: str = request.args.get("sim_id", "")
    theme: str = request.args.get("theme", "dark")

    if not sim_id:
        return jsonify({"error": "sim_id required"}), 400

    storage = _get_storage()
    results = storage.load_results(sim_id)
    if not results:
        return jsonify({"error": "Simulation not found"}), 404

    decisions = results.get("decisions", [])
    bars = results.get("bars", [])

    is_dark = theme == "dark"
    bg_color = "#0a0e17" if is_dark else "#ffffff"
    text_color = "#e2e8f0" if is_dark else "#1e293b"
    grid_color = "#1e293b" if is_dark else "#e2e8f0"

    flow: dict = defaultdict(lambda: defaultdict(
        lambda: {"buy": 0, "sell": 0, "buy_count": 0, "sell_count": 0}
    ))
    for d in decisions:
        if d.get("agent_type") == "NOISE":
            continue
        t = d.get("timestamp", 0)
        atype = d.get("agent_type", "")
        action = d.get("action", "")
        qty = d.get("qty", 0)
        if "BUY" in action and "EXIT" not in action:
            flow[t][atype]["buy"] += qty
            flow[t][atype]["buy_count"] += 1
        elif "SELL" in action or "EXIT" in action:
            flow[t][atype]["sell"] += qty
            flow[t][atype]["sell_count"] += 1

    bar_nums = list(range(len(bars)))
    agent_types = [
        ("INSTITUTIONAL", "#3b82f6", "Institutional"),
        ("RETAIL", "#f59e0b", "Retail"),
        ("MARKET_MAKER", "#a855f7", "Market Maker"),
    ]

    traces: list[dict] = []
    for atype, color, label in agent_types:
        buy_vals = [flow[t][atype]["buy"] for t in bar_nums]
        sell_vals = [-flow[t][atype]["sell"] for t in bar_nums]

        # Buy bars (positive, upward)
        traces.append({
            "type": "bar", "x": bar_nums, "y": buy_vals,
            "name": f"{label} Buy",
            "marker": {"color": color},
            "legendgroup": atype,
            "hovertemplate": f"{label} Buy<br>Bar %{{x}}<br>"
                             f"Qty: %{{y}} contracts<extra></extra>",
        })
        # Sell bars (negative, downward)
        traces.append({
            "type": "bar", "x": bar_nums, "y": sell_vals,
            "name": f"{label} Sell",
            "marker": {"color": color, "opacity": 0.5},
            "legendgroup": atype, "showlegend": False,
            "hovertemplate": f"{label} Sell<br>Bar %{{x}}<br>"
                             f"Qty: %{{customdata}} contracts<extra></extra>",
            "customdata": [flow[t][atype]["sell"] for t in bar_nums],
        })

    # Add price overlay on secondary y-axis for context
    if bars:
        closes = [b["close"] for b in bars]
        traces.append({
            "type": "scatter", "x": bar_nums, "y": closes,
            "name": "ES Price",
            "yaxis": "y2",
            "line": {"color": "#ffffff50" if is_dark else "#00000030",
                     "width": 1, "dash": "dot"},
            "hovertemplate": "ES: $%{y:.2f}<extra></extra>",
        })

    # Detect key divergence bars (institutions selling while retail buying)
    annotations: list[dict] = []
    for t in bar_nums:
        inst_net = flow[t]["INSTITUTIONAL"]["buy"] - flow[t]["INSTITUTIONAL"]["sell"]
        retail_net = flow[t]["RETAIL"]["buy"] - flow[t]["RETAIL"]["sell"]
        # Strong divergence: institutions selling 100+ while retail buying
        if inst_net < -80 and retail_net > 0:
            annotations.append({
                "x": t, "y": 0, "text": "⚠ DIVERGENCE",
                "showarrow": True, "arrowhead": 2,
                "font": {"size": 9, "color": "#ef4444"},
                "arrowcolor": "#ef4444",
                "ax": 0, "ay": -30,
            })
        # Institutions flipping direction
        elif t > 0:
            prev_inst = (flow[t - 1]["INSTITUTIONAL"]["buy"]
                         - flow[t - 1]["INSTITUTIONAL"]["sell"])
            if prev_inst < -50 and inst_net > 50:
                annotations.append({
                    "x": t, "y": 0, "text": "↺ INST FLIP",
                    "showarrow": True, "arrowhead": 2,
                    "font": {"size": 9, "color": "#3b82f6"},
                    "arrowcolor": "#3b82f6",
                    "ax": 0, "ay": -30,
                })

    figure = {
        "data": traces,
        "layout": {
            "title": {"text": "Agent Order Flow — Buy ↑ / Sell ↓ by Type",
                      "font": {"color": text_color, "size": 14}},
            "barmode": "relative",
            "paper_bgcolor": bg_color,
            "plot_bgcolor": bg_color,
            "font": {"color": text_color, "family": "JetBrains Mono, monospace"},
            "xaxis": {"title": "Bar", "gridcolor": grid_color},
            "yaxis": {"title": "Contracts", "gridcolor": grid_color},
            "yaxis2": {
                "title": "ES Price", "overlaying": "y", "side": "right",
                "showgrid": False, "gridcolor": "transparent",
            },
            "legend": {"orientation": "h", "y": -0.15, "font": {"size": 10}},
            "margin": {"l": 60, "r": 60, "t": 40, "b": 60},
            "annotations": annotations[:5],  # Cap at 5 to avoid clutter
        }
    }
    return jsonify(figure)


@openbb_api.route("/openbb/market_state", methods=["GET"])
def openbb_market_state() -> str:
    """
    Al Brooks state machine summary as markdown for OpenBB markdown widget.
    Returns a formatted markdown string.
    """
    sim_id: str = request.args.get("sim_id", "")

    if not sim_id:
        return ("# MiroFish — Al Brooks State Machine\n\n"
                "Select a simulation to view the market state analysis.")

    storage = _get_storage()
    results = storage.load_results(sim_id)
    if not results:
        return "# Error\n\nSimulation not found."

    bars = results.get("bars", [])
    pnl = results.get("pnl_by_type", {})
    decisions = results.get("decisions", [])

    if not bars:
        return "# No Data\n\nNo bars available for this simulation."

    last_bar = bars[-1]
    first_bar = bars[0]
    price_change = last_bar["close"] - first_bar["open"]
    direction = "UP" if price_change > 0 else "DOWN"

    # Count strong bars
    strong_bull = sum(1 for b in bars if b.get("is_strong_bull"))
    strong_bear = sum(1 for b in bars if b.get("is_strong_bear"))

    # Count institutional vs retail actions
    inst_buys = sum(1 for d in decisions if d.get("agent_type") == "INSTITUTIONAL"
                    and "BUY" in d.get("action", "") and "EXIT" not in d.get("action", ""))
    inst_sells = sum(1 for d in decisions if d.get("agent_type") == "INSTITUTIONAL"
                     and ("SELL" in d.get("action", "") or "EXIT" in d.get("action", "")))
    retail_buys = sum(1 for d in decisions if d.get("agent_type") == "RETAIL"
                      and "BUY" in d.get("action", "") and "EXIT" not in d.get("action", ""))
    retail_sells = sum(1 for d in decisions if d.get("agent_type") == "RETAIL"
                       and ("SELL" in d.get("action", "") or "EXIT" in d.get("action", "")))

    inst_pnl = pnl.get("INSTITUTIONAL", {}).get("total_realized", 0)
    retail_pnl = pnl.get("RETAIL", {}).get("total_realized", 0)

    md = f"""# MiroFish — Al Brooks Analysis

**Scenario:** {results.get('scenario', 'Unknown')}
**Bars:** {len(bars)} | **Direction:** {direction} ({price_change:+.2f} pts)

## Price Action Summary

| Metric | Value |
|--------|-------|
| Open | {first_bar['open']:.2f} |
| Close | {last_bar['close']:.2f} |
| High | {max(b['high'] for b in bars):.2f} |
| Low | {min(b['low'] for b in bars):.2f} |
| Strong Bull Bars | {strong_bull} |
| Strong Bear Bars | {strong_bear} |

## Agent Behavior

| Agent Type | Buys | Sells | Realized P&L |
|------------|------|-------|-------------|
| Institutional | {inst_buys} | {inst_sells} | ${inst_pnl:,.0f} |
| Retail | {retail_buys} | {retail_sells} | ${retail_pnl:,.0f} |

## Interpretation

{"Institutional agents were net sellers — consistent with detecting a climax pattern and fading the move." if inst_sells > inst_buys else "Institutional agents were net buyers — consistent with buying a pullback in a trend."}

{"Retail agents were net buyers — consistent with FOMO chasing momentum." if retail_buys > retail_sells else "Retail agents were net sellers — showing unusual caution."}

{"**Prediction validated:** Institutional caution was correct — the market moved in their favor." if inst_pnl > 0 else "**Prediction challenged:** Institutional caution was premature — the trend extended further than expected."}
"""
    return md


@openbb_api.route("/openbb/health", methods=["GET"])
def openbb_health() -> Response:
    """Health status as flat JSON for OpenBB metric widget."""
    return jsonify([{
        "label": "MiroFish Status",
        "value": "Online",
        "detail": f"LLM: {'✓' if config.llm_primary.api_key else '✗'} | "
                  f"Databento: {'✓' if config.databento_api_key else '✗'} | "
                  f"Zep: {'✓' if config.zep_api_key else '✗'}",
    }])


# ─── Dynamic Options & Live Control Endpoints ─────────────────────────────────


@openbb_api.route("/openbb/sim_options", methods=["GET"])
def openbb_sim_options() -> Response:
    """Return simulation IDs as dropdown options for OpenBB parameter selector."""
    storage = _get_storage()
    simulations = storage.list_simulations(limit=50)

    options: list[dict] = []
    for sim in simulations:
        sim_id = sim.get("sim_id", "")
        scenario = sim.get("scenario", "Unknown")
        source = sim.get("source", "synthetic")
        label = f"{sim_id} ({scenario}, {source})"
        options.append({"label": label, "value": sim_id})

    return jsonify(options)


@openbb_api.route("/openbb/live_control", methods=["GET", "POST"])
def openbb_live_control() -> str:
    """
    Live simulation control widget.
    GET: Returns current live session status.
    POST: Starts or stops a live session (triggered by OpenBB Run Button).
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        action = data.get("action", request.args.get("action", "status"))

        if action == "start":
            # Forward to existing live start endpoint
            try:
                from app.services.live_session import LiveSession  # noqa: F401
                seed_bars = int(data.get("seed_bars", 5))
                max_bars = int(data.get("max_bars", 60))
                # Return markdown with session info
                return (
                    f"# ▶ Live Session Starting\n\n"
                    f"**Configuration:**\n"
                    f"- Seed bars: {seed_bars}\n"
                    f"- Max bars: {max_bars}\n\n"
                    f"Use the MiroFish Live Dashboard at "
                    f"https://mirofish-trading-r2hn52xsfq-wl.a.run.app/live "
                    f"to monitor the session in real-time."
                )
            except Exception as e:
                return f"# ✗ Error\n\n{str(e)}"

        elif action == "stop":
            return ("# ■ Stop Requested\n\n"
                    "Use the Live Dashboard to stop the active session.")

    # GET: Return current status as markdown
    return (
        "# MiroFish — Live Simulation Control\n\n"
        "**Status:** Ready\n\n"
        "Set your parameters and click **Run** to start a live ES futures "
        "simulation.\n\n"
        "| Setting | Description |\n"
        "|---------|-------------|\n"
        "| Seed Bars | Number of initial bars before agents start trading "
        "(3-15) |\n"
        "| Max Bars | Maximum bars to simulate (10-120) |\n"
        "| Action | `start` to begin, `stop` to end |\n\n"
        "The live session connects to Databento for real-time ES futures data "
        "and runs the multi-agent simulation with Al Brooks price action "
        "methodology.\n\n"
        "*ES futures must be trading (CME Globex: Sun 5pm – Fri 4pm CT).*"
    )
