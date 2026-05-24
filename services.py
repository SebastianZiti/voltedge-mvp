import random
from datetime import datetime, timedelta

import numpy as np
from sklearn.linear_model import LinearRegression

import database
from domain import (
    Charger,
    ChargerStatus,
    ChargingSession,
    DomainEvent,
    EnergyKwh,
    Incident,
    LoadForecast,
    MoneyDkk,
    PowerKw,
    SessionStatus,
    TelemetryReading,
)


PRICE_PER_KWH_DKK = 3.25
DEMO_CONTRACT_ID = "CONTRACT-DEMO"
FORECAST_MIN_SAMPLES = 5
FORECAST_GROWTH_FACTOR = 1.08


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
                [s.value for s in ChargerStatus],
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
        record = reading.to_record()

        with database.transaction(db_path) as db:
            db.execute(
                "INSERT INTO telemetry (charger_id, power_kw, voltage, current, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (record["charger_id"], record["power_kw"], record["voltage"], record["current"], record["status"], record["timestamp"]),
            )
            db.execute(
                "UPDATE chargers SET status = ?, last_heartbeat = ? WHERE id = ?",
                (status.value, record["timestamp"], charger.id),
            )
            db.execute(
                "INSERT INTO domain_events (event_name, entity_id, description, created_at) VALUES (?, ?, ?, ?)",
                (
                    "TelemetryReceived",
                    charger.id,
                    f"{charger.id} reported {status.value} at {reading.power_kw.to_float()} kW",
                    record["timestamp"],
                ),
            )
            if charger.status != status:
                db.execute(
                    "INSERT INTO domain_events (event_name, entity_id, description, created_at) VALUES (?, ?, ?, ?)",
                    (
                        "ChargerStatusChanged",
                        charger.id,
                        f"{charger.id} changed from {charger.status.value} to {status.value}",
                        record["timestamp"],
                    ),
                )
            if status == ChargerStatus.FAULTED:
                db.execute(
                    "INSERT INTO incidents (charger_id, description, severity, created_at) VALUES (?, ?, ?, ?)",
                    (charger.id, "Simulated charger fault from telemetry", "medium", record["timestamp"]),
                )
                db.execute(
                    "INSERT INTO domain_events (event_name, entity_id, description, created_at) VALUES (?, ?, ?, ?)",
                    ("IncidentOpened", charger.id, f"Incident opened for {charger.id}", record["timestamp"]),
                )

        created.append({"charger_id": charger.id, "status": status.value, "power_kw": reading.power_kw.to_float()})

    return created


def start_session(charger_id=None, db_path=database.DEFAULT_DB_PATH):
    now = datetime.now()
    heartbeat = now.isoformat(timespec="seconds")

    with database.transaction(db_path) as db:
        if charger_id:
            row = db.execute(
                "SELECT * FROM chargers WHERE id = ? AND status = 'available'",
                (charger_id,),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT * FROM chargers WHERE status = 'available' ORDER BY id LIMIT 1"
            ).fetchone()

        if not row:
            return None

        charger = _charger_from_row(row)
        if not charger.can_start_session():
            return None

        # Atomic claim: vi opdaterer KUN hvis chargeren stadig er 'available'.
        # Hvis en anden bruger nåede at booke den først, opdateres 0 rækker, og
        # vi giver op. Forhindrer at to sessions kan starte på samme charger.
        claim = db.execute(
            "UPDATE chargers SET status = ?, last_heartbeat = ? WHERE id = ? AND status = 'available'",
            (ChargerStatus.OCCUPIED.value, heartbeat, charger.id),
        )
        if claim.rowcount == 0:
            return None  # En anden tog chargeren imens

        session = ChargingSession.start(charger.id, DEMO_CONTRACT_ID, now)
        record = session.to_record()
        cursor = db.execute(
            "INSERT INTO sessions (charger_id, contract_id, start_time, status) VALUES (?, ?, ?, ?)",
            (record["charger_id"], record["contract_id"], record["start_time"], record["status"]),
        )
        session_id = cursor.lastrowid

        db.execute(
            "INSERT INTO domain_events (event_name, entity_id, description, created_at) VALUES (?, ?, ?, ?)",
            ("SessionStarted", str(session_id), f"Session {session_id} started on {charger.id}", heartbeat),
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
        completed = session.complete(now, EnergyKwh(round(random.uniform(8, 38), 2)), PRICE_PER_KWH_DKK)
        record = completed.to_record()

        db.execute(
            "UPDATE sessions SET end_time = ?, energy_kwh = ?, price_dkk = ?, status = ? WHERE id = ?",
            (record["end_time"], record["energy_kwh"], record["price_dkk"], record["status"], completed.id),
        )
        db.execute(
            "UPDATE chargers SET status = ?, last_heartbeat = ? WHERE id = ?",
            (ChargerStatus.AVAILABLE.value, record["end_time"], completed.charger_id),
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
    return round(average_load * FORECAST_GROWTH_FACTOR, 2)


def forecast_load_next_hour(db_path=database.DEFAULT_DB_PATH):
    # ML domain service: forudsiger næste times belastning.
    # Henter alle telemetri-aflæsninger hvor chargeren faktisk ladede (status = 'occupied').
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

    # Cold-start: hvis der er for få datapunkter falder vi tilbage til
    # et simpelt gennemsnit. Det giver ingen mening at træne en model på 2 målinger.
    if sample_size < FORECAST_MIN_SAMPLES:
        return LoadForecast(
            next_hour_kw=forecast_next_hour(db_path),
            model="MeanBaseline",
            sample_size=sample_size,
        )

    # Feature engineering: for hver måling laver vi 2 features.
    # feats = [[time_index, hour_of_day], ...]   <- input til modellen (X)
    # targets = [power_kw, ...]                   <- det vi vil forudsige (y)
    feats = []
    targets = []
    for index, row in enumerate(rows):
        ts = datetime.fromisoformat(row["timestamp"])
        feats.append([index, ts.hour])  # time_index = trend, hour = døgnmønster
        targets.append(float(row["power_kw"]))

    # Træning: sklearn lærer en linje gennem datapunkterne.
    # Modellen kan derefter forudsige y for nye X-værdier.
    X = np.array(feats, dtype=float)
    y = np.array(targets, dtype=float)
    model = LinearRegression().fit(X, y)

    # Prediction: hvad ville modellen forudsige for "næste måling, næste time"?
    last_ts = datetime.fromisoformat(rows[-1]["timestamp"])
    next_hour = (last_ts.hour + 1) % 24
    prediction = float(model.predict(np.array([[sample_size, next_hour]]))[0])

    # R²: kvalitetsmål (0-1). Tæt på 1 = modellen forklarer dataene godt.
    r2 = float(model.score(X, y))

    return LoadForecast(
        next_hour_kw=round(max(prediction, 0.0), 2),  # kan ikke være negativ
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


def build_powerbi_report_rows(db_path=database.DEFAULT_DB_PATH):
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

    return rows


def build_powerbi_summary(db_path=database.DEFAULT_DB_PATH):
    kpis = calculate_kpis(db_path)
    sessions = list_sessions(db_path)
    telemetry = list_telemetry(500, db_path)
    completed_sessions = [row for row in sessions if row["status"] == SessionStatus.COMPLETED.value]
    active_sessions = [row for row in sessions if row["status"] == SessionStatus.ACTIVE.value]

    return {
        "charger_count": kpis["charger_count"],
        "active_sessions": len(active_sessions),
        "completed_sessions": len(completed_sessions),
        "total_sessions": len(sessions),
        "total_energy_kwh": kpis["total_energy_kwh"],
        "peak_load_kw": kpis["peak_load_kw"],
        "uptime_percent": kpis["uptime_percent"],
        "faulted_chargers": kpis["faulted_chargers"],
        "incident_count": kpis["incident_count"],
        "forecast_next_hour_kw": kpis["forecast_next_hour_kw"],
        "telemetry_readings": len(telemetry),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


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
