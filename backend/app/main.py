"""
MiroFish Trading Simulation — Flask Backend
"""
import json
import logging
import os
import time
from flask import Flask
from flask_cors import CORS
from app.config import config

def create_app() -> Flask:
    # Serve Vue frontend from static/ directory (built by Vite)
    static_dir = os.path.join(os.path.dirname(__file__), '..', 'static')
    app = Flask(__name__, static_folder=static_dir, static_url_path='')
    CORS(app, origins=[
        "https://pro.openbb.co",
        "https://excel.openbb.co",
        "http://localhost:3000",
        "http://localhost:5001",
    ], supports_credentials=True)

    # Logging — file handler optional (Cloud Run may have read-only filesystem)
    handlers = [logging.StreamHandler()]
    try:
        os.makedirs(config.log_dir, exist_ok=True)
        handlers.append(logging.FileHandler(os.path.join(config.log_dir, "server.log")))
    except OSError:
        pass  # Cloud Run: skip file logging, stdout goes to Cloud Logging
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=handlers,
    )

    # Validate configuration at startup — fail fast on critical issues
    try:
        config.validate()
    except ValueError as e:
        logging.error(f"Configuration error: {e}")
        logging.error("Fix your .env file and restart.")
        # Don't crash — let health endpoint still work for debugging
        # But log the error prominently

    # Register API routes
    from app.api.routes import api
    app.register_blueprint(api)

    from app.api.live_routes import live_api
    app.register_blueprint(live_api)

    from app.api.openbb_routes import openbb_api
    app.register_blueprint(openbb_api)

    @app.route("/")
    def index():
        return app.send_static_file("index.html")

    # Catch-all for Vue SPA routing — serve index.html for all non-API paths
    @app.errorhandler(404)
    def not_found(e):
        # If it's an API route, return JSON 404
        from flask import request
        if request.path.startswith('/api/'):
            return {"error": "Not found"}, 404
        # Otherwise serve the Vue app (handles its own routing)
        try:
            return app.send_static_file("index.html")
        except Exception:
            return {"name": "MiroFish Trading Simulation", "version": "0.1.0",
                    "note": "Frontend not built. Run: cd frontend && npm run build"}

    @app.route("/ws/live/<session_id>")
    def live_websocket(session_id):
        """
        SSE endpoint for live session updates.
        Uses Server-Sent Events (text/event-stream) which works on Cloud Run
        without any additional dependencies.
        """
        from app.api.live_routes import _ws_buffers, _active_session

        def event_stream():
            idx = 0
            while True:
                events = _ws_buffers.get(session_id, [])
                while idx < len(events):
                    event = events[idx]
                    yield f"data: {json.dumps(event)}\n\n"
                    idx += 1
                # Check if session is still active
                if _active_session is None or _active_session.state.value in ("stopped", "error"):
                    yield f"data: {json.dumps({'type': 'session_ended'})}\n\n"
                    break
                time.sleep(0.5)  # Poll interval

        return app.response_class(
            event_stream(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',
            }
        )

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", config.flask_port))
    app.run(host="0.0.0.0", port=port, debug=False)
