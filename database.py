import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "voltedge.db"


def get_connection(db_path=DEFAULT_DB_PATH):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path=DEFAULT_DB_PATH):
    with get_connection(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS chargers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                location TEXT NOT NULL,
                status TEXT NOT NULL,
                max_power_kw REAL NOT NULL,
                last_heartbeat TEXT
            );

            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                charger_id TEXT NOT NULL,
                power_kw REAL NOT NULL,
                voltage REAL NOT NULL,
                current REAL NOT NULL,
                status TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (charger_id) REFERENCES chargers(id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                charger_id TEXT NOT NULL,
                contract_id TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                energy_kwh REAL NOT NULL DEFAULT 0,
                price_dkk REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                FOREIGN KEY (charger_id) REFERENCES chargers(id)
            );

            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                charger_id TEXT NOT NULL,
                description TEXT NOT NULL,
                severity TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY (charger_id) REFERENCES chargers(id)
            );

            CREATE TABLE IF NOT EXISTS domain_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_name TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

        db.executemany(
            """
            INSERT OR IGNORE INTO chargers
            (id, name, location, status, max_power_kw, last_heartbeat)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            [
                ("CH-001", "Copenhagen City Hub", "Copenhagen", "available", 22.0),
                ("CH-002", "Aarhus Fleet Depot", "Aarhus", "available", 50.0),
                ("CH-003", "Odense Parking East", "Odense", "available", 22.0),
                ("CH-004", "Aalborg Housing Site", "Aalborg", "available", 11.0),
            ],
        )


def query_all(sql, params=(), db_path=DEFAULT_DB_PATH):
    with get_connection(db_path) as db:
        return [dict(row) for row in db.execute(sql, params).fetchall()]


def query_one(sql, params=(), db_path=DEFAULT_DB_PATH):
    with get_connection(db_path) as db:
        row = db.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql, params=(), db_path=DEFAULT_DB_PATH):
    with get_connection(db_path) as db:
        cursor = db.execute(sql, params)
        db.commit()
        return cursor.lastrowid
