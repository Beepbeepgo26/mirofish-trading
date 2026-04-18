"""
Live Streaming API — REST endpoints + WebSocket for real-time simulation.
"""
import logging
import threading
from collections import deque
from flask import Blueprint, jsonify, request
from app.config import config
from app.services.live_session import LiveSession, LiveSessionConfig, SessionState

logger = logging.getLogger(__name__)
live_api = Blueprint("live_api", __name__, url_prefix="/api/live")

# Active live sessions (only one at a time for now)
_active_session: LiveSession | None = None
_session_lock = threading.Lock()

# Event buffer — (seq_id, event_dict) tuples. deque with maxlen auto-drops oldest.
# Sequence IDs are monotonic across the session lifetime, so SSE consumers
# can resume by tracking the last seen seq_id even after truncation.
_ws_buffers: dict[str, deque] = {}
_ws_seq_counters: dict[str, int] = {}
_ws_lock = threading.Lock()

BUFFER_MAXLEN = 500


def _broadcast(event_type: str, data: dict):
    """Broadcast an event to all WebSocket/SSE subscribers. Thread-safe."""
    if not _active_session:
        return
    sid = _active_session.session_id
    with _ws_lock:
        if sid not in _ws_buffers:
            _ws_buffers[sid] = deque(maxlen=BUFFER_MAXLEN)
            _ws_seq_counters[sid] = 0
        _ws_seq_counters[sid] += 1
        _ws_buffers[sid].append((
            _ws_seq_counters[sid],
            {"type": event_type, "data": data},
        ))


@live_api.route("/start", methods=["POST"])
def start_live():
    """
    Start a live streaming simulation.

    Body (all optional):
    {
        "seed_bars": 5,
        "max_bars": 120,
        "agents": {
            "institutional": 3,
            "retail": 5,
            "market_maker": 1,
            "noise": 5
        }
    }
    """
    global _active_session

    with _session_lock:
        if _active_session and _active_session.state in (
            SessionState.RUNNING, SessionState.WAITING_FOR_DATA
        ):
            return jsonify({
                "error": "A live session is already running",
                "session_id": _active_session.session_id,
                "state": _active_session.state.value,
            }), 409

        data = request.get_json() or {}
        agents = data.get("agents", {})

        session_config = LiveSessionConfig(
            seed_bars=data.get("seed_bars", 5),
            max_bars=data.get("max_bars", 120),
            agent_institutional=agents.get("institutional", 3),
            agent_retail=agents.get("retail", 5),
            agent_market_maker=agents.get("market_maker", 1),
            agent_noise=agents.get("noise", 5),
        )

        try:
            _active_session = LiveSession(
                config=config,
                session_config=session_config,
                on_update=_broadcast,
            )
            _active_session.start()

            return jsonify({
                "session_id": _active_session.session_id,
                "state": _active_session.state.value,
                "message": "Live session started. Connect to WebSocket for updates.",
                "websocket": f"/ws/live/{_active_session.session_id}",
            })
        except Exception as e:
            logger.error(f"Failed to start live session: {e}")
            return jsonify({"error": str(e)}), 500


@live_api.route("/stop", methods=["POST"])
def stop_live():
    """Stop the active live session."""
    global _active_session

    with _session_lock:
        if not _active_session:
            return jsonify({"error": "No active live session"}), 404

        results = _active_session.stop()
        session_id = _active_session.session_id
        _active_session = None

        # Persist results using storage service
        from app.services.storage import StorageService
        storage = StorageService(bucket_name=config.gcs_bucket)
        paths = storage.save_results(session_id, results)

    # Clean up the ws buffer AFTER persisting, so any lingering pollers
    # can still pull the final events before truncation.
    # Delay by one poll cycle (~2s) to give the SSE generator a chance
    # to emit session_ended.
    def _cleanup():
        import time as _time
        _time.sleep(5)
        with _ws_lock:
            _ws_buffers.pop(session_id, None)
            _ws_seq_counters.pop(session_id, None)
        logger.debug(f"Cleaned up ws buffers for session {session_id}")

    threading.Thread(target=_cleanup, daemon=True).start()

    return jsonify({
        "session_id": session_id,
        "state": "stopped",
        "results": results,
        "storage": paths,
    })


@live_api.route("/status", methods=["GET"])
def live_status():
    """Get current live session status."""
    if not _active_session:
        return jsonify({"active": False, "message": "No active live session"})

    return jsonify({
        "active": True,
        **_active_session.get_status(),
    })


@live_api.route("/events", methods=["GET"])
def live_events():
    """
    Poll for recent events. Clients send `after=<last_seen_seq_id>` and
    receive only events with seq_id > after.
    """
    if not _active_session:
        return jsonify({"events": [], "active": False, "last_seq": 0})

    sid = _active_session.session_id
    after = request.args.get("after", 0, type=int)

    with _ws_lock:
        buf = _ws_buffers.get(sid)
        if not buf:
            return jsonify({"events": [], "active": True, "last_seq": 0})
        # Filter while holding the lock
        new_events = [
            {"seq": seq, **event}
            for seq, event in buf
            if seq > after
        ]
        last_seq = _ws_seq_counters.get(sid, 0)

    return jsonify({
        "events": new_events[:50],
        "total": last_seq,
        "last_seq": last_seq,
        "active": _active_session.state in (
            SessionState.RUNNING, SessionState.WAITING_FOR_DATA
        ),
    })
