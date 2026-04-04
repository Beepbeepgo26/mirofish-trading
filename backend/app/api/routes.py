"""
REST API — Simulation management endpoints.
Supports synthetic scenarios AND real Databento ES futures data.
Results persist to Google Cloud Storage (or local disk as fallback).
"""
import asyncio
import logging
from flask import Blueprint, jsonify, request
from app.config import config
from app.services.simulation_manager import SimulationManager
from app.services.databento_client import DatabentoClient
from app.services.storage import StorageService
from app.scenarios.market_scenarios import generate_scenario_a, generate_scenario_b

logger = logging.getLogger(__name__)
api = Blueprint("api", __name__, url_prefix="/api")

# Active simulations (in-memory cache — GCS is the durable store)
_active_sims: dict[str, SimulationManager] = {}
_sim_results: dict[str, dict] = {}

# Shared services
_databento: DatabentoClient | None = None
_storage: StorageService | None = None


def _get_databento() -> DatabentoClient:
    global _databento
    if _databento is None:
        _databento = DatabentoClient(config.databento_api_key)
    return _databento


def _get_storage() -> StorageService:
    global _storage
    if _storage is None:
        _storage = StorageService(bucket_name=config.gcs_bucket)
    return _storage


def _run_async(coro):
    """Run async coroutine from sync Flask context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@api.route("/health", methods=["GET"])
def health():
    storage = _get_storage()
    return jsonify({
        "status": "ok",
        "llm_configured": bool(config.llm_primary.api_key),
        "databento_configured": bool(config.databento_api_key),
        "storage": "gcs" if storage._enabled else "local",
        "gcs_bucket": config.gcs_bucket or None,
    })


@api.route("/scenarios", methods=["GET"])
def list_scenarios():
    return jsonify({
        "scenarios": [
            {"id": "scenario_a", "name": "Bull Trend + 3-Bar Buy Climax",
             "description": "Synthetic — tests TBTL correction prediction"},
            {"id": "scenario_b", "name": "Gap-Up Open + Overnight Divergence",
             "description": "Synthetic — tests 50/50 gap resolution prediction"},
            {"id": "databento", "name": "Real ES Futures Data (Databento)",
             "description": "Pull actual 1-minute bars from any date. Requires DATABENTO_API_KEY."},
        ]
    })


@api.route("/databento/cost", methods=["POST"])
def databento_cost():
    """Estimate cost before pulling data."""
    data = request.get_json() or {}
    date = data.get("date")
    start_time = data.get("start_time", "09:30")
    end_time = data.get("end_time", "11:00")
    timezone = data.get("timezone", "US/Eastern")

    if not date:
        return jsonify({"error": "date is required (YYYY-MM-DD)"}), 400

    try:
        dbn = _get_databento()
        cost = dbn.get_cost_estimate(date, start_time, end_time, timezone)
        return jsonify({"estimated_cost_usd": cost, "date": date,
                        "range": f"{start_time}-{end_time} {timezone}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/databento/bars", methods=["POST"])
def databento_bars():
    """Pull ES bars from Databento without running a simulation. Preview the data."""
    data = request.get_json() or {}
    date = data.get("date")
    start_time = data.get("start_time", "09:30")
    end_time = data.get("end_time", "11:00")
    timezone = data.get("timezone", "US/Eastern")
    max_bars = data.get("max_bars", 60)
    bar_interval = data.get("bar_interval", 5)

    if not date:
        return jsonify({"error": "date is required (YYYY-MM-DD)"}), 400

    try:
        dbn = _get_databento()
        bars = dbn.pull_bars(date, start_time, end_time, timezone, max_bars=max_bars, bar_interval=bar_interval)
        return jsonify({
            "bars": bars,
            "count": len(bars),
            "date": date,
            "range": f"{start_time}-{end_time} {timezone}",
            "price_range": {
                "high": max(b["high"] for b in bars) if bars else None,
                "low": min(b["low"] for b in bars) if bars else None,
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/simulations", methods=["POST"])
def create_simulation():
    """
    Start a new simulation.

    Supports two sources:
    1. Synthetic: {"scenario": "scenario_a"} or {"scenario": "scenario_b"}
    2. Databento: {"source": "databento", "date": "2026-03-06", ...}
    """
    data = request.get_json() or {}
    source = data.get("source", "synthetic")

    # Override agent counts if provided (with validation)
    if "agents" in data:
        MAX_AGENTS = {"institutional": 20, "retail": 100, "market_maker": 10, "noise": 50}
        for key, val in data["agents"].items():
            attr_name = f"agents_{key}"
            if not hasattr(config.sim, attr_name):
                return jsonify({"error": f"Unknown agent type: {key}"}), 400
            count = int(val)
            if count < 0:
                return jsonify({"error": f"Agent count for {key} cannot be negative"}), 400
            max_count = MAX_AGENTS.get(key, 50)
            if count > max_count:
                return jsonify({
                    "error": f"Agent count for {key} exceeds maximum of {max_count} (got {count}). "
                             f"Estimated cost: ~${count * 30 * 0.003:.0f} per simulation."
                }), 400
            setattr(config.sim, attr_name, count)

    try:
        if source == "databento":
            scenario = _build_databento_scenario(data)
        else:
            scenario_id = data.get("scenario", "scenario_a")
            seed = data.get("seed", 42)
            if scenario_id == "scenario_a":
                scenario = generate_scenario_a(seed=seed)
            elif scenario_id == "scenario_b":
                scenario = generate_scenario_b(seed=seed)
            else:
                return jsonify({"error": f"Unknown scenario: {scenario_id}"}), 400

        # Create and run simulation
        sim = SimulationManager(config, scenario)
        _active_sims[sim.sim_id] = sim

        _run_async(sim.setup())
        results = _run_async(sim.run())

        # If Databento source, add validation comparison
        if source == "databento" and "validation_bars" in scenario:
            results["validation"] = _compare_prediction_vs_actual(
                results, scenario["validation_bars"]
            )

        _sim_results[sim.sim_id] = results
        results["source"] = source

        # Persist to GCS (or local disk)
        storage = _get_storage()
        storage_paths = storage.save_results(sim.sim_id, results)
        logger.info(f"Simulation {sim.sim_id} persisted: {storage_paths}")

        return jsonify({
            "sim_id": sim.sim_id,
            "status": "completed",
            "source": source,
            "total_bars": results["total_bars"],
            "total_decisions": results["total_decisions"],
            "pnl_by_type": results["pnl_by_type"],
            "llm_stats": results["llm_stats"],
            "validation": results.get("validation"),
            "storage": {k: v for k, v in storage_paths.items()},
        })

    except Exception as e:
        logger.error(f"Simulation failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def _build_databento_scenario(data: dict) -> dict:
    """Build a simulation scenario from Databento real data."""
    date = data.get("date")
    start_time = data.get("start_time", "09:30")
    end_time = data.get("end_time", "11:00")
    timezone = data.get("timezone", "US/Eastern")
    seed_bar_count = data.get("seed_bars", 15)
    total_bars = data.get("total_bars", 30)
    free_run = data.get("free_run_bars", 12)

    if not date:
        raise ValueError("date is required for Databento source (YYYY-MM-DD)")

    dbn = _get_databento()

    if date == "recent":
        # Pull most recent session
        all_bars = dbn.pull_recent_session(bars_back=total_bars)
        session_data = {
            "seed_bars": all_bars[:seed_bar_count],
            "validation_bars": all_bars[seed_bar_count:],
            "all_bars": all_bars,
            "metadata": {"date": "recent", "total_bars_retrieved": len(all_bars)},
        }
    else:
        session_data = dbn.pull_session_with_context(
            date=date,
            start_time=start_time,
            end_time=end_time,
            timezone=timezone,
            seed_bars=seed_bar_count,
            total_bars=total_bars,
        )

    meta = session_data["metadata"]

    return {
        "name": f"Databento ES: {date} {start_time}-{end_time} {timezone}",
        "description": (
            f"Real ES futures 5-minute bars from {date}. "
            f"Agents see first {len(session_data['seed_bars'])} bars (5m), "
            f"then predict the next {free_run}. "
            f"Actual outcome available for comparison."
        ),
        "seed_bars": session_data["seed_bars"],
        "seed_bar_count": len(session_data["seed_bars"]),
        "bar_interval": "5m",
        "free_run_bars": free_run,
        "validation_bars": session_data["validation_bars"],
        "expected_outcomes": {
            "actual_direction": meta.get("actual_direction"),
            "actual_final_close": meta.get("actual_final_close"),
            "seed_close": meta.get("seed_close"),
        },
    }


def _compare_prediction_vs_actual(results: dict, validation_bars: list) -> dict:
    """Compare what agents predicted vs what actually happened."""
    if not validation_bars:
        return {"comparison_available": False}

    sim_bars = results.get("bars", [])
    # Free-run bars start after the seed bars
    seed_count = results.get("seed_bar_count", 0)
    free_run_bars = sim_bars[seed_count:] if len(sim_bars) > seed_count else []

    if not free_run_bars or not validation_bars:
        return {"comparison_available": False}

    # Predicted direction vs actual
    last_seed_close = sim_bars[seed_count - 1]["close"] if seed_count > 0 and seed_count <= len(sim_bars) else None
    predicted_close = free_run_bars[-1]["close"] if free_run_bars else None
    actual_close = validation_bars[-1]["close"] if validation_bars else None

    predicted_direction = "UP" if predicted_close and last_seed_close and predicted_close > last_seed_close else "DOWN"
    actual_direction = "UP" if actual_close and last_seed_close and actual_close > last_seed_close else "DOWN"

    # Price accuracy
    price_error = abs(predicted_close - actual_close) if predicted_close and actual_close else None

    # Institutional consensus
    inst_decisions = [d for d in results.get("decisions", [])
                      if d.get("agent_type") == "INSTITUTIONAL" and d.get("action") != "HOLD"]
    inst_bullish = sum(1 for d in inst_decisions if "BUY" in d.get("action", ""))
    inst_bearish = sum(1 for d in inst_decisions if "SELL" in d.get("action", ""))
    inst_consensus = "BULLISH" if inst_bullish > inst_bearish else "BEARISH" if inst_bearish > inst_bullish else "NEUTRAL"

    return {
        "comparison_available": True,
        "predicted_direction": predicted_direction,
        "actual_direction": actual_direction,
        "direction_correct": predicted_direction == actual_direction,
        "predicted_close": predicted_close,
        "actual_close": actual_close,
        "price_error_points": round(price_error, 2) if price_error else None,
        "institutional_consensus": inst_consensus,
        "institutional_bullish_actions": inst_bullish,
        "institutional_bearish_actions": inst_bearish,
        "validation_bars_available": len(validation_bars),
    }


@api.route("/simulations/<sim_id>", methods=["GET"])
def get_simulation(sim_id: str):
    """Get simulation results. Checks memory first, then GCS."""
    # Try in-memory cache first
    if sim_id in _sim_results:
        return jsonify(_sim_results[sim_id])

    # Try persistent storage
    storage = _get_storage()
    results = storage.load_results(sim_id)
    if results:
        _sim_results[sim_id] = results  # Re-cache
        return jsonify(results)

    return jsonify({"error": "Simulation not found"}), 404


@api.route("/simulations/<sim_id>/decisions", methods=["GET"])
def get_decisions(sim_id: str):
    """Get all decisions for a simulation, optionally filtered."""
    # Try in-memory first
    if sim_id in _sim_results:
        decisions = _sim_results[sim_id].get("decisions", [])
    else:
        # Try persistent storage
        storage = _get_storage()
        decisions = storage.load_decisions(sim_id)
        if not decisions:
            return jsonify({"error": "Simulation not found"}), 404

    agent_type = request.args.get("agent_type")
    bar = request.args.get("bar", type=int)

    if agent_type:
        decisions = [d for d in decisions if d.get("agent_type") == agent_type]
    if bar is not None:
        decisions = [d for d in decisions if d.get("timestamp") == bar]

    return jsonify({"decisions": decisions, "count": len(decisions)})


@api.route("/simulations/<sim_id>/bars", methods=["GET"])
def get_bars(sim_id: str):
    """Get price bars for a simulation."""
    if sim_id in _sim_results:
        return jsonify({"bars": _sim_results[sim_id].get("bars", [])})

    storage = _get_storage()
    results = storage.load_results(sim_id)
    if results:
        return jsonify({"bars": results.get("bars", [])})

    return jsonify({"error": "Simulation not found"}), 404


@api.route("/simulations/<sim_id>/validation", methods=["GET"])
def get_validation(sim_id: str):
    """Get prediction vs actual comparison (Databento source only)."""
    if sim_id in _sim_results:
        validation = _sim_results[sim_id].get("validation")
    else:
        storage = _get_storage()
        results = storage.load_results(sim_id)
        validation = results.get("validation") if results else None

    if not validation:
        return jsonify({"error": "No validation data (only available for Databento-sourced simulations)"}), 404
    return jsonify(validation)


@api.route("/simulations/<sim_id>/summary", methods=["GET"])
def get_summary(sim_id: str):
    """Get human-readable summary text."""
    storage = _get_storage()
    summary = storage.load_summary(sim_id)
    if summary:
        return summary, 200, {"Content-Type": "text/plain"}
    return jsonify({"error": "Summary not found"}), 404


@api.route("/simulations", methods=["GET"])
def list_simulations():
    """List all saved simulations."""
    limit = request.args.get("limit", 50, type=int)
    storage = _get_storage()
    simulations = storage.list_simulations(limit=limit)
    return jsonify({"simulations": simulations, "count": len(simulations)})


@api.route("/simulations/<sim_id>", methods=["DELETE"])
def delete_simulation(sim_id: str):
    """Delete a simulation from storage."""
    storage = _get_storage()
    deleted = storage.delete_simulation(sim_id)
    if sim_id in _sim_results:
        del _sim_results[sim_id]
    return jsonify({"deleted": deleted, "sim_id": sim_id})
