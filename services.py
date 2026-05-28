import random
from datetime import datetime, timedelta

import numpy as np
from sklearn.linear_model import LinearRegression

import database
import price_service
from domain import (
    ChargerStatus,
    ChargingSession,
    DomainEvent,
    EnergyKwh,
    Incident,
    LoadForecast,
    MoneyDkk,
    PowerKw,
    SessionStatus,
    Socket,
    TelemetryReading,
)


DEMO_CONTRACT_ID = "CONTRACT-DEMO"
FORECAST_MIN_SAMPLES = 5
FORECAST_GROWTH_FACTOR = 1.08


def list_chargers(db_path=database.DEFAULT_DB_PATH):
    chargers = database.query_all(
        "SELECT * FROM chargers ORDER BY id",
        db_path=db_path,
    )
    sockets = database.query_all(
        "SELECT * FROM sockets ORDER BY charger_id, socket_number",
        db_path=db_path,
    )
    sockets_by_charger = {}
    for sock in sockets:
        sockets_by_charger.setdefault(sock["charger_id"], []).append(sock)
    for charger in chargers:
        charger["sockets"] = sockets_by_charger.get(charger["id"], [])
    return chargers


def add_charger(name, location, sockets, db_path=database.DEFAULT_DB_PATH, region="DK2"):
    charger_id = _next_charger_id(db_path)
    now = datetime.now().isoformat(timespec="seconds")

    with database.transaction(db_path) as db:
        db.execute(
            "INSERT INTO chargers (id, name, location, region) VALUES (?, ?, ?, ?)",
            (charger_id, name, location, region),
        )
        for i, sock in enumerate(sockets, 1):
            socket_id = f"{charger_id}-S{i}"
            db.execute(
                """
                INSERT INTO sockets
                (id, charger_id, socket_number, max_power_kw, status, connector_type, last_heartbeat)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    socket_id, charger_id, i,
                    float(sock["max_power_kw"]),
                    ChargerStatus.AVAILABLE.value,
                    sock.get("connector_type", "Type2"),
                    now,
                ),
            )
        db.execute(
            "INSERT INTO domain_events (event_name, entity_id, description, created_at) VALUES (?, ?, ?, ?)",
            (
                "ChargerAdded",
                charger_id,
                f"Charger '{name}' added at {location} with {len(sockets)} socket(s)",
                now,
            ),
        )

    return database.query_one(
        "SELECT * FROM chargers WHERE id = ?", (charger_id,), db_path=db_path
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
    sockets = database.query_all("SELECT * FROM sockets ORDER BY id", db_path=db_path)
    created = []

    for sock_row in sockets:
        socket = _socket_from_row(sock_row)
        status = ChargerStatus(
            random.choices(
                [s.value for s in ChargerStatus],
                weights=[45, 35, 12, 8],
                k=1,
            )[0]
        )
        max_power = float(socket.max_power_kw)
        power_kw = (
            0 if status in {ChargerStatus.AVAILABLE, ChargerStatus.FAULTED, ChargerStatus.OFFLINE}
            else round(random.uniform(4, max_power), 2)
        )
        voltage = 0 if status == ChargerStatus.OFFLINE else round(random.uniform(220, 240), 1)
        current = 0 if voltage == 0 else round((power_kw * 1000) / voltage, 1)
        timestamp = datetime.now()

        reading = TelemetryReading(
            socket_id=socket.id,
            power_kw=PowerKw(power_kw),
            voltage=voltage,
            current=current,
            status=status,
            timestamp=timestamp,
        )
        record = reading.to_record()

        with database.transaction(db_path) as db:
            db.execute(
                "INSERT INTO telemetry (socket_id, power_kw, voltage, current, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (record["socket_id"], record["power_kw"], record["voltage"], record["current"], record["status"], record["timestamp"]),
            )
            db.execute(
                "UPDATE sockets SET status = ?, last_heartbeat = ? WHERE id = ?",
                (status.value, record["timestamp"], socket.id),
            )
            db.execute(
                "INSERT INTO domain_events (event_name, entity_id, description, created_at) VALUES (?, ?, ?, ?)",
                (
                    "TelemetryReceived",
                    socket.id,
                    f"{socket.id} reported {status.value} at {reading.power_kw.to_float()} kW",
                    record["timestamp"],
                ),
            )
            if socket.status != status:
                db.execute(
                    "INSERT INTO domain_events (event_name, entity_id, description, created_at) VALUES (?, ?, ?, ?)",
                    (
                        "ChargerStatusChanged",
                        socket.id,
                        f"{socket.id} changed from {socket.status.value} to {status.value}",
                        record["timestamp"],
                    ),
                )
            if status == ChargerStatus.FAULTED:
                db.execute(
                    "INSERT INTO incidents (charger_id, description, severity, created_at) VALUES (?, ?, ?, ?)",
                    (socket.charger_id, f"Simulated fault on socket {socket.id}", "medium", record["timestamp"]),
                )
                db.execute(
                    "INSERT INTO domain_events (event_name, entity_id, description, created_at) VALUES (?, ?, ?, ?)",
                    ("IncidentOpened", socket.charger_id, f"Incident opened for {socket.charger_id}", record["timestamp"]),
                )

        created.append({"socket_id": socket.id, "status": status.value, "power_kw": reading.power_kw.to_float()})

    return created


def start_session(socket_id=None, db_path=database.DEFAULT_DB_PATH):
    now = datetime.now()
    heartbeat = now.isoformat(timespec="seconds")

    with database.transaction(db_path) as db:
        if socket_id:
            row = db.execute(
                "SELECT * FROM sockets WHERE id = ? AND status = 'available'",
                (socket_id,),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT * FROM sockets WHERE status = 'available' ORDER BY id LIMIT 1"
            ).fetchone()

        if not row:
            return None

        socket = _socket_from_row(row)
        if not socket.can_start_session():
            return None

        # Atomic claim: only update if socket is still 'available'.
        # Prevents two sessions starting on the same socket (race condition).
        claim = db.execute(
            "UPDATE sockets SET status = ?, last_heartbeat = ? WHERE id = ? AND status = 'available'",
            (ChargerStatus.OCCUPIED.value, heartbeat, socket.id),
        )
        if claim.rowcount == 0:
            return None

        session = ChargingSession.start(socket.id, DEMO_CONTRACT_ID, now)
        record = session.to_record()
        cursor = db.execute(
            "INSERT INTO sessions (socket_id, contract_id, start_time, status) VALUES (?, ?, ?, ?)",
            (record["socket_id"], record["contract_id"], record["start_time"], record["status"]),
        )
        session_id = cursor.lastrowid

        db.execute(
            "INSERT INTO domain_events (event_name, entity_id, description, created_at) VALUES (?, ?, ?, ?)",
            ("SessionStarted", str(session_id), f"Session {session_id} started on {socket.id}", heartbeat),
        )

    return database.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,), db_path=db_path)


def end_latest_session(db_path=database.DEFAULT_DB_PATH):
    now = datetime.now()
    completed_id = None

    with database.transaction(db_path) as db:
        row = db.execute(
            "SELECT * FROM sessions WHERE status = 'active' ORDER BY start_time DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None

        session = _session_from_row(row)

        socket_row = db.execute(
            """
            SELECT c.region
            FROM sockets s
            JOIN chargers c ON s.charger_id = c.id
            WHERE s.id = ?
            """,
            (session.socket_id,),
        ).fetchone()
        region = socket_row["region"] if socket_row else price_service.DEFAULT_REGION
        price_per_kwh = price_service.get_price_per_kwh(region, now)

        completed = session.complete(now, EnergyKwh(round(random.uniform(8, 38), 2)), price_per_kwh)
        record = completed.to_record()

        db.execute(
            "UPDATE sessions SET end_time = ?, energy_kwh = ?, price_dkk = ?, status = ? WHERE id = ?",
            (record["end_time"], record["energy_kwh"], record["price_dkk"], record["status"], completed.id),
        )
        db.execute(
            "UPDATE sockets SET status = ?, last_heartbeat = ? WHERE id = ?",
            (ChargerStatus.AVAILABLE.value, record["end_time"], completed.socket_id),
        )
        db.execute(
            "INSERT INTO domain_events (event_name, entity_id, description, created_at) VALUES (?, ?, ?, ?)",
            (
                "SessionEnded",
                str(completed.id),
                f"Session {completed.id} ended with {completed.energy_kwh.to_float()} kWh",
                now.isoformat(timespec="seconds"),
            ),
        )
        completed_id = completed.id

    return database.query_one("SELECT * FROM sessions WHERE id = ?", (completed_id,), db_path=db_path)


def seed_demo_sessions(db_path=database.DEFAULT_DB_PATH):
    chargers = {c["id"]: c for c in database.query_all("SELECT * FROM chargers", db_path=db_path)}
    sockets = {s["id"]: s for s in database.query_all("SELECT * FROM sockets", db_path=db_path)}

    base_time = datetime.now().replace(minute=0, second=0, microsecond=0)
    demo_plan = [
        ("CH-001-S1", 50, 18.4, 4),
        ("CH-001-S2", 65, 31.2, 4),
        ("CH-002-S1", 40, 26.8, 6),
        ("CH-002-S2", 55, 44.7, 6),
        ("CH-002-S3", 35, 39.5, 6),
        ("CH-003-S1", 28, 15.9, 7),
        ("CH-003-S1", 35, 21.6, 3),
        ("CH-004-S1", 55, 10.8, 9),
        ("CH-004-S2", 44, 12.4, 9),
    ]
    created = []

    for socket_id, duration_minutes, energy_kwh, hours_ago in demo_plan:
        if socket_id not in sockets:
            continue

        start_time = base_time - timedelta(hours=hours_ago)
        end_time = start_time + timedelta(minutes=duration_minutes)

        existing = database.query_one(
            "SELECT id FROM sessions WHERE socket_id = ? AND contract_id = ? AND start_time = ?",
            (socket_id, DEMO_CONTRACT_ID, start_time.isoformat(timespec="seconds")),
            db_path=db_path,
        )
        if existing is not None:
            continue

        charger_id = sockets[socket_id]["charger_id"]
        charger = chargers.get(charger_id)
        region = charger["region"] if charger else price_service.DEFAULT_REGION
        price_per_kwh = price_service.get_price_per_kwh(region, end_time)
        price_dkk = round(energy_kwh * price_per_kwh, 2)

        with database.transaction(db_path) as db:
            cursor = db.execute(
                """
                INSERT INTO sessions (socket_id, contract_id, start_time, end_time, energy_kwh, price_dkk, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    socket_id,
                    DEMO_CONTRACT_ID,
                    start_time.isoformat(timespec="seconds"),
                    end_time.isoformat(timespec="seconds"),
                    energy_kwh,
                    price_dkk,
                    SessionStatus.COMPLETED.value,
                ),
            )
            session_id = cursor.lastrowid
            db.execute(
                "INSERT INTO domain_events (event_name, entity_id, description, created_at) VALUES (?, ?, ?, ?)",
                (
                    "SessionEnded",
                    str(session_id),
                    f"Demo session {session_id} ended with {energy_kwh} kWh",
                    end_time.isoformat(timespec="seconds"),
                ),
            )
        created.append({"id": session_id, "socket_id": socket_id, "energy_kwh": energy_kwh, "price_dkk": price_dkk})

    return created


def calculate_kpis(db_path=database.DEFAULT_DB_PATH):
    chargers = list_chargers(db_path)
    all_sockets = database.query_all("SELECT * FROM sockets", db_path=db_path)
    sessions = list_sessions(db_path)
    telemetry = list_telemetry(500, db_path)
    incidents = database.query_all("SELECT * FROM incidents", db_path=db_path)

    total_energy = sum(float(row["energy_kwh"]) for row in sessions)
    active_sessions = len([row for row in all_sockets if row["status"] == "occupied"])
    faulted_sockets = len([row for row in all_sockets if row["status"] == "faulted"])
    operational_sockets = len([row for row in all_sockets if row["status"] in {"available", "occupied"}])
    uptime_percent = round((operational_sockets / len(all_sockets)) * 100, 1) if all_sockets else 0
    peak_load_kw = max([float(row["power_kw"]) for row in telemetry], default=0)

    return {
        "charger_count": len(chargers),
        "socket_count": len(all_sockets),
        "active_sessions": active_sessions,
        "total_energy_kwh": round(total_energy, 2),
        "faulted_sockets": faulted_sockets,
        "incident_count": len(incidents),
        "uptime_percent": uptime_percent,
        "peak_load_kw": round(peak_load_kw, 2),
        "forecast_next_hour_kw": forecast_load_next_hour(db_path).next_hour_kw,
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
        return 0.0
    average_load = sum(float(row["power_kw"]) for row in rows) / len(rows)
    return round(average_load * FORECAST_GROWTH_FACTOR, 2)


def forecast_load_next_hour(db_path=database.DEFAULT_DB_PATH):
    rows = database.query_all(
        """
        SELECT power_kw, timestamp
        FROM telemetry
        WHERE status = 'occupied'
        ORDER BY timestamp ASC
        """,
        db_path=db_path,
    )
    sample_size = len(rows)

    if sample_size < FORECAST_MIN_SAMPLES:
        return LoadForecast(
            next_hour_kw=forecast_next_hour(db_path),
            model="MeanBaseline",
            sample_size=sample_size,
        )

    feats = []
    targets = []
    for index, row in enumerate(rows):
        ts = datetime.fromisoformat(row["timestamp"])
        feats.append([index, ts.hour])
        targets.append(float(row["power_kw"]))

    X = np.array(feats, dtype=float)
    y = np.array(targets, dtype=float)
    model = LinearRegression().fit(X, y)

    last_ts = datetime.fromisoformat(rows[-1]["timestamp"])
    next_hour = (last_ts.hour + 1) % 24
    prediction = float(model.predict(np.array([[sample_size, next_hour]]))[0])
    r2 = float(model.score(X, y))

    return LoadForecast(
        next_hour_kw=round(max(prediction, 0.0), 2),
        model="LinearRegression",
        sample_size=sample_size,
        r2_score=round(r2, 3),
        feature_names=("time_index", "hour_of_day"),
        coefficients=tuple(round(float(c), 4) for c in model.coef_.tolist()),
        intercept=round(float(model.intercept_), 4),
    )


def publish_forecast_next_hour(db_path=database.DEFAULT_DB_PATH):
    forecast = forecast_load_next_hour(db_path)
    _record_domain_event(
        DomainEvent(
            "LoadForecastCalculated",
            "forecast-next-hour",
            f"{forecast.model} forecast={forecast.next_hour_kw} kW r2={forecast.r2_score} n={forecast.sample_size}",
            datetime.now(),
        ),
        db_path,
    )
    return forecast


def diagnose_incidents_by_charger(db_path=database.DEFAULT_DB_PATH):
    rows = database.query_all(
        """
        SELECT c.id AS charger_id,
               c.name,
               c.location,
               COUNT(DISTINCT i.id) AS incident_count,
               MAX(i.created_at) AS last_incident_at,
               (
                   SELECT description FROM incidents
                   WHERE charger_id = c.id
                   ORDER BY created_at DESC
                   LIMIT 1
               ) AS last_description,
               COALESCE(
                   (SELECT s.status FROM sockets s
                    WHERE s.charger_id = c.id
                    ORDER BY CASE s.status
                        WHEN 'faulted'  THEN 0
                        WHEN 'offline'  THEN 1
                        WHEN 'occupied' THEN 2
                        ELSE 3 END
                    LIMIT 1),
                   'unknown'
               ) AS status
        FROM chargers c
        LEFT JOIN incidents i ON i.charger_id = c.id
        GROUP BY c.id
        ORDER BY incident_count DESC, c.id ASC
        """,
        db_path=db_path,
    )
    return [dict(row) for row in rows]


def build_powerbi_report_rows(db_path=database.DEFAULT_DB_PATH):
    rows = []

    for sock in database.query_all(
        "SELECT s.*, c.location FROM sockets s JOIN chargers c ON s.charger_id = c.id",
        db_path=db_path,
    ):
        rows.append(
            {
                "dataset": "charger",
                "record_id": sock["id"],
                "charger_id": sock["id"],
                "location": sock["location"],
                "status": sock["status"],
                "metric": "max_power_kw",
                "value": sock["max_power_kw"],
                "timestamp": sock["last_heartbeat"],
                "description": f'{sock["connector_type"]} socket {sock["socket_number"]} on {sock["charger_id"]}',
            }
        )

    for telemetry in list_telemetry(500, db_path):
        rows.append(
            {
                "dataset": "telemetry",
                "record_id": telemetry["id"],
                "charger_id": telemetry["socket_id"],
                "location": "",
                "status": telemetry["status"],
                "metric": "power_kw",
                "value": telemetry["power_kw"],
                "timestamp": telemetry["timestamp"],
                "description": f"{telemetry['voltage']} V / {telemetry['current']} A",
            }
        )

    for session in list_sessions(db_path):
        rows.append(
            {
                "dataset": "session",
                "record_id": session["id"],
                "charger_id": session["socket_id"],
                "location": "",
                "status": session["status"],
                "metric": "energy_kwh",
                "value": session["energy_kwh"],
                "timestamp": session["end_time"] or session["start_time"],
                "description": f"{session['price_dkk']} DKK / {session['contract_id']}",
            }
        )

    for incident in database.query_all("SELECT * FROM incidents ORDER BY created_at DESC", db_path=db_path):
        rows.append(
            {
                "dataset": "incident",
                "record_id": incident["id"],
                "charger_id": incident["charger_id"],
                "location": "",
                "status": incident["severity"],
                "metric": "incident",
                "value": 1,
                "timestamp": incident["created_at"],
                "description": incident["description"],
            }
        )

    for event in list_domain_events(500, db_path):
        rows.append(
            {
                "dataset": "domain_event",
                "record_id": event["id"],
                "charger_id": event["entity_id"],
                "location": "",
                "status": event["event_name"],
                "metric": "event",
                "value": 1,
                "timestamp": event["created_at"],
                "description": event["description"],
            }
        )

    return rows


def build_powerbi_summary(db_path=database.DEFAULT_DB_PATH):
    kpis = calculate_kpis(db_path)
    sessions = list_sessions(db_path)
    telemetry = list_telemetry(500, db_path)
    completed_sessions = [row for row in sessions if row["status"] == SessionStatus.COMPLETED.value]
    active_sessions = [row for row in sessions if row["status"] == SessionStatus.ACTIVE.value]

    return {
        "charger_count": kpis["charger_count"],
        "socket_count": kpis["socket_count"],
        "active_sessions": len(active_sessions),
        "completed_sessions": len(completed_sessions),
        "total_sessions": len(sessions),
        "total_energy_kwh": kpis["total_energy_kwh"],
        "peak_load_kw": kpis["peak_load_kw"],
        "uptime_percent": kpis["uptime_percent"],
        "faulted_chargers": kpis["faulted_sockets"],
        "incident_count": kpis["incident_count"],
        "forecast_next_hour_kw": kpis["forecast_next_hour_kw"],
        "telemetry_readings": len(telemetry),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _next_charger_id(db_path):
    rows = database.query_all("SELECT id FROM chargers ORDER BY id", db_path=db_path)
    max_num = 0
    for row in rows:
        parts = row["id"].split("-")
        if len(parts) == 2 and parts[0] == "CH":
            try:
                max_num = max(max_num, int(parts[1]))
            except ValueError:
                pass
    return f"CH-{max_num + 1:03d}"


def _record_domain_event(event, db_path):
    record = event.to_record()
    database.execute(
        """
        INSERT INTO domain_events (event_name, entity_id, description, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (record["event_name"], record["entity_id"], record["description"], record["created_at"]),
        db_path=db_path,
    )


def _socket_from_row(row):
    return Socket(
        id=row["id"],
        charger_id=row["charger_id"],
        socket_number=int(row["socket_number"]),
        max_power_kw=float(row["max_power_kw"]),
        status=ChargerStatus(row["status"]),
        connector_type=row["connector_type"],
        last_heartbeat=row["last_heartbeat"],
    )


def _session_from_row(row):
    return ChargingSession(
        id=row["id"],
        socket_id=row["socket_id"],
        contract_id=row["contract_id"],
        start_time=datetime.fromisoformat(row["start_time"]),
        end_time=datetime.fromisoformat(row["end_time"]) if row["end_time"] else None,
        energy_kwh=EnergyKwh(float(row["energy_kwh"])),
        price_dkk=MoneyDkk(float(row["price_dkk"])),
        status=SessionStatus(row["status"]),
    )
