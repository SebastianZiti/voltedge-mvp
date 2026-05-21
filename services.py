import csv
import random
from datetime import datetime
from io import StringIO

import database


PRICE_PER_KWH_DKK = 3.25


def list_chargers(db_path=database.DEFAULT_DB_PATH):
    return database.query_all(
        "SELECT * FROM chargers ORDER BY id",
        db_path=db_path,
    )


def list_sessions(db_path=database.DEFAULT_DB_PATH):
    return database.query_all(
        "SELECT * FROM sessions ORDER BY start_time DESC",
        db_path=db_path,
    )


def list_telemetry(limit=100, db_path=database.DEFAULT_DB_PATH):
    return database.query_all(
        "SELECT * FROM telemetry ORDER BY timestamp DESC LIMIT ?",
        (limit,),
        db_path=db_path,
    )


def list_domain_events(limit=25, db_path=database.DEFAULT_DB_PATH):
    return database.query_all(
        "SELECT * FROM domain_events ORDER BY created_at DESC LIMIT ?",
        (limit,),
        db_path=db_path,
    )


def simulate_telemetry(db_path=database.DEFAULT_DB_PATH):
    chargers = list_chargers(db_path)
    created = []

    for charger in chargers:
        status = random.choices(
            ["available", "occupied", "faulted", "offline"],
            weights=[45, 35, 12, 8],
            k=1,
        )[0]
        max_power = float(charger["max_power_kw"])
        power_kw = 0 if status in ["available", "faulted", "offline"] else round(random.uniform(4, max_power), 2)
        voltage = 0 if status == "offline" else round(random.uniform(220, 240), 1)
        current = 0 if voltage == 0 else round((power_kw * 1000) / voltage, 1)
        timestamp = datetime.now().isoformat(timespec="seconds")

        database.execute(
            """
            INSERT INTO telemetry (charger_id, power_kw, voltage, current, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (charger["id"], power_kw, voltage, current, status, timestamp),
            db_path=db_path,
        )
        database.execute(
            """
            UPDATE chargers
            SET status = ?, last_heartbeat = ?
            WHERE id = ?
            """,
            (status, timestamp, charger["id"]),
            db_path=db_path,
        )
        _record_event(
            "TelemetryReceived",
            charger["id"],
            f"{charger['id']} reported {status} at {power_kw} kW",
            timestamp,
            db_path,
        )

        if charger["status"] != status:
            _record_event(
                "ChargerStatusChanged",
                charger["id"],
                f"{charger['id']} changed from {charger['status']} to {status}",
                timestamp,
                db_path,
            )

        if status == "faulted":
            database.execute(
                """
                INSERT INTO incidents (charger_id, description, severity, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (charger["id"], "Simulated charger fault from telemetry", "medium", timestamp),
                db_path=db_path,
            )
            _record_event(
                "IncidentOpened",
                charger["id"],
                f"Incident opened for {charger['id']}",
                timestamp,
                db_path,
            )

        created.append({"charger_id": charger["id"], "status": status, "power_kw": power_kw})

    return created


def start_session(charger_id=None, db_path=database.DEFAULT_DB_PATH):
    charger = _select_available_charger(charger_id, db_path)
    if not charger:
        return None

    now = datetime.now().isoformat(timespec="seconds")
    session_id = database.execute(
        """
        INSERT INTO sessions (charger_id, contract_id, start_time, status)
        VALUES (?, ?, ?, ?)
        """,
        (charger["id"], "CONTRACT-DEMO", now, "active"),
        db_path=db_path,
    )
    database.execute(
        "UPDATE chargers SET status = ?, last_heartbeat = ? WHERE id = ?",
        ("occupied", now, charger["id"]),
        db_path=db_path,
    )
    _record_event("SessionStarted", str(session_id), f"Session {session_id} started on {charger['id']}", now, db_path)
    return database.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,), db_path=db_path)


def end_latest_session(db_path=database.DEFAULT_DB_PATH):
    session = database.query_one(
        "SELECT * FROM sessions WHERE status = 'active' ORDER BY start_time DESC LIMIT 1",
        db_path=db_path,
    )
    if not session:
        return None

    energy_kwh = round(random.uniform(8, 38), 2)
    price_dkk = round(energy_kwh * PRICE_PER_KWH_DKK, 2)
    now = datetime.now().isoformat(timespec="seconds")

    database.execute(
        """
        UPDATE sessions
        SET end_time = ?, energy_kwh = ?, price_dkk = ?, status = ?
        WHERE id = ?
        """,
        (now, energy_kwh, price_dkk, "completed", session["id"]),
        db_path=db_path,
    )
    database.execute(
        "UPDATE chargers SET status = ?, last_heartbeat = ? WHERE id = ?",
        ("available", now, session["charger_id"]),
        db_path=db_path,
    )
    _record_event(
        "SessionEnded",
        str(session["id"]),
        f"Session {session['id']} ended with {energy_kwh} kWh",
        now,
        db_path,
    )
    return database.query_one("SELECT * FROM sessions WHERE id = ?", (session["id"],), db_path=db_path)


def calculate_kpis(db_path=database.DEFAULT_DB_PATH):
    chargers = list_chargers(db_path)
    sessions = list_sessions(db_path)
    telemetry = list_telemetry(500, db_path)
    incidents = database.query_all("SELECT * FROM incidents", db_path=db_path)

    total_energy = sum(float(row["energy_kwh"]) for row in sessions)
    active_sessions = len([row for row in sessions if row["status"] == "active"])
    faulted_chargers = len([row for row in chargers if row["status"] == "faulted"])
    online_chargers = len([row for row in chargers if row["status"] != "offline"])
    uptime_percent = round((online_chargers / len(chargers)) * 100, 1) if chargers else 0
    peak_load_kw = max([float(row["power_kw"]) for row in telemetry], default=0)

    return {
        "charger_count": len(chargers),
        "active_sessions": active_sessions,
        "total_energy_kwh": round(total_energy, 2),
        "faulted_chargers": faulted_chargers,
        "incident_count": len(incidents),
        "uptime_percent": uptime_percent,
        "peak_load_kw": round(peak_load_kw, 2),
        "forecast_next_hour_kw": forecast_next_hour(db_path),
    }


def forecast_next_hour(db_path=database.DEFAULT_DB_PATH):
    rows = database.query_all(
        """
        SELECT power_kw
        FROM telemetry
        WHERE status = 'occupied'
        ORDER BY timestamp DESC
        LIMIT 20
        """,
        db_path=db_path,
    )
    if not rows:
        return 0
    average_load = sum(float(row["power_kw"]) for row in rows) / len(rows)
    business_growth_factor = 1.08
    forecast = round(average_load * business_growth_factor, 2)
    _record_event(
        "LoadForecastCalculated",
        "forecast-next-hour",
        f"Forecast calculated as {forecast} kW",
        datetime.now().isoformat(timespec="seconds"),
        db_path,
    )
    return forecast


def export_csv(table_name, db_path=database.DEFAULT_DB_PATH):
    allowed_tables = {"sessions", "telemetry", "chargers", "incidents", "domain_events"}
    if table_name not in allowed_tables:
        raise ValueError("Unknown export table")

    rows = database.query_all(f"SELECT * FROM {table_name}", db_path=db_path)
    output = StringIO()
    if not rows:
        return ""

    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _select_available_charger(charger_id, db_path):
    if charger_id:
        return database.query_one(
            "SELECT * FROM chargers WHERE id = ? AND status != 'offline' AND status != 'faulted'",
            (charger_id,),
            db_path=db_path,
        )
    return database.query_one(
        "SELECT * FROM chargers WHERE status = 'available' ORDER BY id LIMIT 1",
        db_path=db_path,
    )


def _record_event(event_name, entity_id, description, created_at, db_path):
    database.execute(
        """
        INSERT INTO domain_events (event_name, entity_id, description, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (event_name, entity_id, description, created_at),
        db_path=db_path,
    )
