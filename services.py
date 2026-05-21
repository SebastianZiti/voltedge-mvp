import csv
import random
from datetime import datetime, timedelta
from io import StringIO

import database
from domain import (
    Charger,
    ChargerStatus,
    ChargingSession,
    DomainEvent,
    EnergyKwh,
    Incident,
    MoneyDkk,
    PowerKw,
    SessionStatus,
    TelemetryReading,
)


PRICE_PER_KWH_DKK = 3.25
DEMO_CONTRACT_ID = "CONTRACT-DEMO"


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
    chargers = [_charger_from_row(row) for row in list_chargers(db_path)]
    created = []

    for charger in chargers:
        status = ChargerStatus(
            random.choices(
                [status.value for status in ChargerStatus],
                weights=[45, 35, 12, 8],
                k=1,
            )[0]
        )
        max_power = float(charger.max_power_kw)
        power_kw = 0 if status in {ChargerStatus.AVAILABLE, ChargerStatus.FAULTED, ChargerStatus.OFFLINE} else round(random.uniform(4, max_power), 2)
        voltage = 0 if status == ChargerStatus.OFFLINE else round(random.uniform(220, 240), 1)
        current = 0 if voltage == 0 else round((power_kw * 1000) / voltage, 1)
        timestamp = datetime.now()
        reading = TelemetryReading(
            charger_id=charger.id,
            power_kw=PowerKw(power_kw),
            voltage=voltage,
            current=current,
            status=status,
            timestamp=timestamp,
        )
        reading_record = reading.to_record()

        database.execute(
            """
            INSERT INTO telemetry (charger_id, power_kw, voltage, current, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                reading_record["charger_id"],
                reading_record["power_kw"],
                reading_record["voltage"],
                reading_record["current"],
                reading_record["status"],
                reading_record["timestamp"],
            ),
            db_path=db_path,
        )
        updated_charger = charger.with_status(status, reading_record["timestamp"])
        database.execute(
            """
            UPDATE chargers
            SET status = ?, last_heartbeat = ?
            WHERE id = ?
            """,
            (updated_charger.status.value, updated_charger.last_heartbeat, updated_charger.id),
            db_path=db_path,
        )
        _record_domain_event(
            DomainEvent(
                "TelemetryReceived",
                charger.id,
                f"{charger.id} reported {status.value} at {reading.power_kw.to_float()} kW",
                timestamp,
            ),
            db_path,
        )

        if charger.status != status:
            _record_domain_event(
                DomainEvent(
                    "ChargerStatusChanged",
                    charger.id,
                    f"{charger.id} changed from {charger.status.value} to {status.value}",
                    timestamp,
                ),
                db_path,
            )

        if status == ChargerStatus.FAULTED:
            incident = Incident(
                charger_id=charger.id,
                description="Simulated charger fault from telemetry",
                severity="medium",
                created_at=timestamp,
            )
            incident_record = incident.to_record()
            database.execute(
                """
                INSERT INTO incidents (charger_id, description, severity, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    incident_record["charger_id"],
                    incident_record["description"],
                    incident_record["severity"],
                    incident_record["created_at"],
                ),
                db_path=db_path,
            )
            _record_domain_event(
                DomainEvent("IncidentOpened", charger.id, f"Incident opened for {charger.id}", timestamp),
                db_path,
            )

        created.append({"charger_id": charger.id, "status": status.value, "power_kw": reading.power_kw.to_float()})

    return created


def start_session(charger_id=None, db_path=database.DEFAULT_DB_PATH):
    charger_row = _select_available_charger(charger_id, db_path)
    charger = _charger_from_row(charger_row) if charger_row else None
    if not charger:
        return None
    if not charger.can_start_session():
        return None

    now = datetime.now()
    session = ChargingSession.start(charger.id, DEMO_CONTRACT_ID, now)
    session_record = session.to_record()
    session_id = database.execute(
        """
        INSERT INTO sessions (charger_id, contract_id, start_time, status)
        VALUES (?, ?, ?, ?)
        """,
        (
            session_record["charger_id"],
            session_record["contract_id"],
            session_record["start_time"],
            session_record["status"],
        ),
        db_path=db_path,
    )
    heartbeat = now.isoformat(timespec="seconds")
    database.execute(
        "UPDATE chargers SET status = ?, last_heartbeat = ? WHERE id = ?",
        (ChargerStatus.OCCUPIED.value, heartbeat, charger.id),
        db_path=db_path,
    )
    _record_domain_event(
        DomainEvent("SessionStarted", str(session_id), f"Session {session_id} started on {charger.id}", now),
        db_path,
    )
    return database.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,), db_path=db_path)


def end_latest_session(db_path=database.DEFAULT_DB_PATH):
    session_row = database.query_one(
        "SELECT * FROM sessions WHERE status = 'active' ORDER BY start_time DESC LIMIT 1",
        db_path=db_path,
    )
    if not session_row:
        return None

    session = _session_from_row(session_row)
    now = datetime.now()
    completed = session.complete(now, EnergyKwh(round(random.uniform(8, 38), 2)), PRICE_PER_KWH_DKK)
    completed_record = completed.to_record()

    database.execute(
        """
        UPDATE sessions
        SET end_time = ?, energy_kwh = ?, price_dkk = ?, status = ?
        WHERE id = ?
        """,
        (
            completed_record["end_time"],
            completed_record["energy_kwh"],
            completed_record["price_dkk"],
            completed_record["status"],
            completed.id,
        ),
        db_path=db_path,
    )
    database.execute(
        "UPDATE chargers SET status = ?, last_heartbeat = ? WHERE id = ?",
        (ChargerStatus.AVAILABLE.value, completed_record["end_time"], completed.charger_id),
        db_path=db_path,
    )
    _record_domain_event(
        DomainEvent(
            "SessionEnded",
            str(completed.id),
            f"Session {completed.id} ended with {completed.energy_kwh.to_float()} kWh",
            now,
        ),
        db_path,
    )
    return database.query_one("SELECT * FROM sessions WHERE id = ?", (completed.id,), db_path=db_path)


def seed_demo_sessions(db_path=database.DEFAULT_DB_PATH):
    chargers = [_charger_from_row(row) for row in list_chargers(db_path)]
    base_time = datetime.now().replace(minute=0, second=0, microsecond=0)
    demo_plan = [
        ("CH-001", 32, 18.4, 6),
        ("CH-001", 48, 31.2, 4),
        ("CH-002", 24, 26.8, 8),
        ("CH-002", 42, 44.7, 5),
        ("CH-002", 36, 39.5, 2),
        ("CH-003", 28, 15.9, 7),
        ("CH-003", 35, 21.6, 3),
        ("CH-004", 55, 10.8, 9),
        ("CH-004", 44, 12.4, 1),
    ]
    created = []

    charger_ids = {charger.id for charger in chargers}
    for charger_id, duration_minutes, energy_kwh, hours_ago in demo_plan:
        if charger_id not in charger_ids:
            continue
        start_time = base_time - timedelta(hours=hours_ago)
        end_time = start_time + timedelta(minutes=duration_minutes)
        price_dkk = round(energy_kwh * PRICE_PER_KWH_DKK, 2)

        session_id = database.execute(
            """
            INSERT INTO sessions (charger_id, contract_id, start_time, end_time, energy_kwh, price_dkk, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                charger_id,
                DEMO_CONTRACT_ID,
                start_time.isoformat(timespec="seconds"),
                end_time.isoformat(timespec="seconds"),
                energy_kwh,
                price_dkk,
                SessionStatus.COMPLETED.value,
            ),
            db_path=db_path,
        )
        _record_domain_event(
            DomainEvent(
                "SessionEnded",
                str(session_id),
                f"Demo session {session_id} ended with {energy_kwh} kWh",
                end_time,
            ),
            db_path,
        )
        created.append({"id": session_id, "charger_id": charger_id, "energy_kwh": energy_kwh, "price_dkk": price_dkk})

    return created


def calculate_kpis(db_path=database.DEFAULT_DB_PATH):
    chargers = list_chargers(db_path)
    sessions = list_sessions(db_path)
    telemetry = list_telemetry(500, db_path)
    incidents = database.query_all("SELECT * FROM incidents", db_path=db_path)

    total_energy = sum(float(row["energy_kwh"]) for row in sessions)
    active_sessions = len([row for row in sessions if row["status"] == "active"])
    faulted_chargers = len([row for row in chargers if row["status"] == "faulted"])
    operational_chargers = len([row for row in chargers if row["status"] in {"available", "occupied"}])
    uptime_percent = round((operational_chargers / len(chargers)) * 100, 1) if chargers else 0
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


def export_latest_report_csv(db_path=database.DEFAULT_DB_PATH):
    rows = []

    for charger in list_chargers(db_path):
        rows.append(
            {
                "dataset": "charger",
                "record_id": charger["id"],
                "charger_id": charger["id"],
                "location": charger["location"],
                "status": charger["status"],
                "metric": "max_power_kw",
                "value": charger["max_power_kw"],
                "timestamp": charger["last_heartbeat"],
                "description": charger["name"],
            }
        )

    for telemetry in list_telemetry(500, db_path):
        rows.append(
            {
                "dataset": "telemetry",
                "record_id": telemetry["id"],
                "charger_id": telemetry["charger_id"],
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
                "charger_id": session["charger_id"],
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

    output = StringIO()
    fieldnames = ["dataset", "record_id", "charger_id", "location", "status", "metric", "value", "timestamp", "description"]
    writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter=";")
    writer.writeheader()
    writer.writerows([_format_powerbi_row(row) for row in rows])
    return output.getvalue()


def _format_powerbi_row(row):
    formatted = dict(row)
    formatted["value"] = _format_decimal_for_powerbi(row["value"])
    return formatted


def _format_decimal_for_powerbi(value):
    if value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".replace(".", ",")


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


def _record_domain_event(event, db_path):
    record = event.to_record()
    _record_event(record["event_name"], record["entity_id"], record["description"], record["created_at"], db_path)


def _charger_from_row(row):
    return Charger(
        id=row["id"],
        name=row["name"],
        location=row["location"],
        status=ChargerStatus(row["status"]),
        max_power_kw=float(row["max_power_kw"]),
        last_heartbeat=row["last_heartbeat"],
    )


def _session_from_row(row):
    return ChargingSession(
        id=row["id"],
        charger_id=row["charger_id"],
        contract_id=row["contract_id"],
        start_time=datetime.fromisoformat(row["start_time"]),
        end_time=datetime.fromisoformat(row["end_time"]) if row["end_time"] else None,
        energy_kwh=EnergyKwh(float(row["energy_kwh"])),
        price_dkk=MoneyDkk(float(row["price_dkk"])),
        status=SessionStatus(row["status"]),
    )
