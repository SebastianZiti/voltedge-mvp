import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from time import perf_counter

import observability


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "voltedge.db"


def get_connection(db_path=DEFAULT_DB_PATH):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path=DEFAULT_DB_PATH):
    with closing(get_connection(db_path)) as db:
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
        db.commit()


def query_all(sql, params=(), db_path=DEFAULT_DB_PATH):
    start = perf_counter()
    try:
        with closing(get_connection(db_path)) as db:
            rows = [dict(row) for row in db.execute(sql, params).fetchall()]
        observability.record_db_query("select_many", perf_counter() - start)
        return rows
    except Exception:
        observability.record_db_query("select_many", perf_counter() - start, error=True)
        raise


def query_one(sql, params=(), db_path=DEFAULT_DB_PATH):
    start = perf_counter()
    try:
        with closing(get_connection(db_path)) as db:
            row = db.execute(sql, params).fetchone()
            result = dict(row) if row else None
        observability.record_db_query("select_one", perf_counter() - start)
        return result
    except Exception:
        observability.record_db_query("select_one", perf_counter() - start, error=True)
        raise


def execute(sql, params=(), db_path=DEFAULT_DB_PATH):
    start = perf_counter()
    try:
        with closing(get_connection(db_path)) as db:
            cursor = db.execute(sql, params)
            db.commit()
            lastrowid = cursor.lastrowid
        observability.record_db_query("write", perf_counter() - start)
        return lastrowid
    except Exception:
        observability.record_db_query("write", perf_counter() - start, error=True)
        raise


@contextmanager
def transaction(db_path=DEFAULT_DB_PATH):
    # Bruges som "with database.transaction(...) as db:" i services.py.
    # Alt der sker mellem yield og db.commit() bliver gemt SAMMEN i databasen.
    # Hvis noget fejler undervejs, rulles ALLE ændringer tilbage (rollback).
    # Det sikrer aggregat-konsistens: enten gennemføres hele forretningshandlingen,
    # eller også sker der ingenting. Forhindrer "halv-skrevne" tilstande.
    db = get_connection(db_path)
    start = perf_counter()
    try:
        db.execute("BEGIN IMMEDIATE")  # tager skrive-lås nu, så ingen andre kan skrive imens
        yield db
        db.commit()  # alt gik godt -> gem ændringer
        observability.record_db_query("transaction", perf_counter() - start)
    except Exception:
        db.rollback()  # noget fejlede -> annullér alle ændringer
        observability.record_db_query("transaction", perf_counter() - start, error=True)
        raise
    finally:
        db.close()
