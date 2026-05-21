from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

import database
import services


def create_app(db_path=database.DEFAULT_DB_PATH):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path
    database.init_db(db_path)

    def db_path_from_config():
        return app.config["DB_PATH"]

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
        return render_template("chargers.html", chargers=services.list_chargers(db_path_from_config()))

    @app.get("/sessions")
    def sessions_page():
        return render_template("sessions.html", sessions=services.list_sessions(db_path_from_config()))

    @app.get("/analytics")
    def analytics_page():
        return render_template(
            "analytics.html",
            kpis=services.calculate_kpis(db_path_from_config()),
            forecast=services.forecast_next_hour(db_path_from_config()),
        )

    @app.post("/simulate")
    def simulate():
        services.simulate_telemetry(db_path_from_config())
        return redirect(url_for("dashboard"))

    @app.post("/sessions/start")
    def start_session_form():
        services.start_session(request.form.get("charger_id"), db_path_from_config())
        return redirect(url_for("sessions_page"))

    @app.post("/sessions/end")
    def end_session_form():
        services.end_latest_session(db_path_from_config())
        return redirect(url_for("sessions_page"))

    @app.get("/health")
    def health():
        return jsonify({"status": "healthy", "service": "voltedge-mvp"})

    @app.get("/api/chargers")
    def api_chargers():
        return jsonify(services.list_chargers(db_path_from_config()))

    @app.post("/api/telemetry/simulate")
    def api_simulate_telemetry():
        return jsonify({"created": services.simulate_telemetry(db_path_from_config())})

    @app.get("/api/sessions")
    def api_sessions():
        return jsonify(services.list_sessions(db_path_from_config()))

    @app.post("/api/sessions/start")
    def api_start_session():
        payload = request.get_json(silent=True) or {}
        session = services.start_session(payload.get("charger_id"), db_path_from_config())
        if not session:
            return jsonify({"error": "No available charger found"}), 409
        return jsonify(session), 201

    @app.post("/api/sessions/end")
    def api_end_session():
        session = services.end_latest_session(db_path_from_config())
        if not session:
            return jsonify({"error": "No active session found"}), 404
        return jsonify(session)

    @app.get("/api/analytics/kpis")
    def api_kpis():
        return jsonify(services.calculate_kpis(db_path_from_config()))

    @app.get("/api/analytics/forecast")
    def api_forecast():
        return jsonify({"next_hour_kw": services.forecast_next_hour(db_path_from_config())})

    @app.get("/api/events")
    def api_events():
        return jsonify(services.list_domain_events(db_path=db_path_from_config()))

    @app.get("/export/<table_name>.csv")
    def export_table(table_name):
        try:
            csv_data = services.export_csv(table_name, db_path_from_config())
        except ValueError:
            return jsonify({"error": "Unknown export"}), 404

        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={table_name}.csv"},
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
