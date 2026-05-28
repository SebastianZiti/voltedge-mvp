import logging
import os
import time
from pathlib import Path

from flask import g, jsonify, Flask, redirect, render_template, request, Response, url_for

import database
import observability
import services


DEFAULT_DEV_SECRET_KEY = "dev-only-change-me"

KNOWN_PLACEHOLDER_SECRET_KEYS = frozenset({
    DEFAULT_DEV_SECRET_KEY,
    "local-compose-change-before-production",
})


def create_app(db_path=None):
    observability.reset_metrics()
    app = Flask(__name__)
    if db_path is None:
        db_path = Path(os.getenv("DB_PATH", database.DEFAULT_DB_PATH))
    app.config["DB_PATH"] = db_path
    service_env = os.getenv("SERVICE_ENV", "development")
    app.config["SERVICE_ENV"] = service_env

    secret_key = os.getenv("SECRET_KEY")
    if service_env != "development":
        if not secret_key or secret_key in KNOWN_PLACEHOLDER_SECRET_KEYS:
            raise RuntimeError(
                "SECRET_KEY skal sættes til en stærk værdi udenfor 'development'. "
                "Sæt miljøvariablen SECRET_KEY før appen startes."
            )
    app.config["SECRET_KEY"] = secret_key or DEFAULT_DEV_SECRET_KEY
    database.init_db(db_path)
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    app.logger.propagate = False

    def db_path_from_config():
        return app.config["DB_PATH"]

    @app.before_request
    def start_request_timer():
        g.request_start_time = time.perf_counter()

    @app.after_request
    def record_observability_metrics(response):
        duration = time.perf_counter() - getattr(g, "request_start_time", time.perf_counter())
        route = request.url_rule.rule if request.url_rule else request.path
        observability.record_http_request(request.method, route, response.status_code, duration)
        return response

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'"
        )
        return response

    @app.after_request
    def log_request(response):
        app.logger.info(
            "request method=%s path=%s status=%s",
            request.method,
            request.path,
            response.status_code,
        )
        return response

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(_error):
        app.logger.exception("Unhandled application error")
        return jsonify({"error": "Internal server error"}), 500

    @app.get("/")
    def dashboard():
        return render_template(
            "dashboard.html",
            kpis=services.calculate_kpis(db_path_from_config()),
            chargers=services.list_chargers(db_path_from_config()),
            telemetry=services.list_telemetry(8, db_path_from_config()),
            events=services.list_domain_events(8, db_path_from_config()),
        )

    @app.get("/chargers")
    def chargers_page():
        return render_template(
            "chargers.html",
            chargers=services.list_chargers(db_path_from_config()),
        )

    @app.post("/chargers/add")
    def add_charger_form():
        name = request.form.get("name", "").strip()
        location = request.form.get("location", "").strip()
        region = request.form.get("region", "DK2").strip()
        powers = request.form.getlist("socket_max_power[]")
        connectors = request.form.getlist("socket_connector_type[]")
        if not name or not location or not powers:
            return redirect(url_for("chargers_page"))
        sockets = [
            {"max_power_kw": float(p), "connector_type": c}
            for p, c in zip(powers, connectors)
            if p and float(p) > 0
        ]
        if sockets:
            services.add_charger(name, location, sockets, db_path_from_config(), region=region)
        return redirect(url_for("chargers_page"))

    @app.get("/sessions")
    def sessions_page():
        return render_template("sessions.html", sessions=services.list_sessions(db_path_from_config()))

    @app.get("/analytics")
    def analytics_page():
        return render_template(
            "analytics.html",
            kpis=services.calculate_kpis(db_path_from_config()),
            forecast=services.forecast_load_next_hour(db_path_from_config()).to_record(),
            diagnostics=services.diagnose_incidents_by_charger(db_path_from_config()),
        )

    @app.post("/simulate")
    def simulate():
        services.simulate_telemetry(db_path_from_config())
        return redirect(url_for("dashboard"))

    @app.post("/sessions/start")
    def start_session_form():
        services.start_session(request.form.get("socket_id"), db_path_from_config())
        return redirect(url_for("sessions_page"))

    @app.post("/sessions/end")
    def end_session_form():
        services.end_latest_session(db_path_from_config())
        return redirect(url_for("sessions_page"))

    def _block_seed_demo_in_production():
        return app.config["SERVICE_ENV"] == "production"

    @app.post("/sessions/seed-demo")
    def seed_demo_sessions_form():
        if _block_seed_demo_in_production():
            return jsonify({"error": "Not found"}), 404
        services.seed_demo_sessions(db_path_from_config())
        return redirect(url_for("sessions_page"))

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    @app.get("/health")
    def health():
        return jsonify({"status": "healthy", "service": "voltedge-mvp"})

    @app.get("/ready")
    def ready():
        try:
            database.query_one("SELECT COUNT(*) AS count FROM chargers", db_path=db_path_from_config())
        except Exception:
            app.logger.exception("Readiness check failed")
            return jsonify({"status": "not_ready"}), 503
        return jsonify({"status": "ready", "service": "voltedge-mvp", "environment": app.config["SERVICE_ENV"]})

    @app.get("/metrics")
    def metrics():
        db_ready = True
        try:
            database.query_one("SELECT COUNT(*) AS count FROM chargers", db_path=db_path_from_config())
        except Exception:
            db_ready = False
        return Response(
            observability.render_prometheus_metrics(db_path_from_config(), db_ready),
            mimetype="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/api/chargers")
    def api_chargers():
        return jsonify(services.list_chargers(db_path_from_config()))

    @app.post("/api/chargers")
    def api_add_charger():
        payload = request.get_json(silent=True) or {}
        name = payload.get("name", "").strip()
        location = payload.get("location", "").strip()
        region = payload.get("region", "DK2").strip()
        sockets = payload.get("sockets", [])
        if not name or not location or not sockets:
            return jsonify({"error": "name, location and sockets are required"}), 400
        charger = services.add_charger(name, location, sockets, db_path_from_config(), region=region)
        return jsonify(charger), 201

    @app.post("/api/telemetry/simulate")
    def api_simulate_telemetry():
        return jsonify({"created": services.simulate_telemetry(db_path_from_config())})

    @app.get("/api/sessions")
    def api_sessions():
        return jsonify(services.list_sessions(db_path_from_config()))

    @app.post("/api/sessions/start")
    def api_start_session():
        payload = request.get_json(silent=True) or {}
        session = services.start_session(payload.get("socket_id"), db_path_from_config())
        if not session:
            return jsonify({"error": "No available socket found"}), 409
        return jsonify(session), 201

    @app.post("/api/sessions/end")
    def api_end_session():
        session = services.end_latest_session(db_path_from_config())
        if not session:
            return jsonify({"error": "No active session found"}), 404
        return jsonify(session)

    @app.post("/api/sessions/seed-demo")
    def api_seed_demo_sessions():
        if _block_seed_demo_in_production():
            return jsonify({"error": "Not found"}), 404
        return jsonify({"created": services.seed_demo_sessions(db_path_from_config())}), 201

    @app.get("/api/analytics/kpis")
    def api_kpis():
        return jsonify(services.calculate_kpis(db_path_from_config()))

    @app.get("/api/analytics/forecast")
    def api_forecast():
        return jsonify(services.forecast_load_next_hour(db_path_from_config()).to_record())

    @app.get("/api/analytics/diagnostics")
    def api_diagnostics():
        return jsonify(services.diagnose_incidents_by_charger(db_path_from_config()))

    @app.post("/api/analytics/forecast/publish")
    def api_publish_forecast():
        return jsonify(services.publish_forecast_next_hour(db_path_from_config()).to_record()), 201

    @app.get("/api/events")
    def api_events():
        return jsonify(services.list_domain_events(db_path=db_path_from_config()))

    @app.get("/api/powerbi/summary")
    def api_powerbi_summary():
        return jsonify(services.build_powerbi_summary(db_path_from_config()))

    @app.get("/api/powerbi/report-data")
    def api_powerbi_report_data():
        return jsonify(services.build_powerbi_report_rows(db_path_from_config()))

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5001, debug=os.getenv("FLASK_DEBUG", "0") == "1")
