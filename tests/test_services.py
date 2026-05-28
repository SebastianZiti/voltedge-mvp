import tempfile
import unittest
from pathlib import Path
from unittest import mock

import database
import price_service
import services


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        database.init_db(self.db_path)

        self._price_patcher = mock.patch(
            "price_service._fetch_prices",
            side_effect=ConnectionError("test environment - no real API call"),
        )
        self._price_patcher.start()
        price_service.reset_cache()

    def tearDown(self):
        self._price_patcher.stop()
        self.temp_dir.cleanup()

    def test_database_starts_with_demo_stations(self):
        stations = services.list_chargers(self.db_path)

        self.assertEqual(len(stations), 4)
        self.assertEqual(stations[0]["id"], "CH-001")

    def test_demo_stations_have_correct_socket_counts(self):
        stations = services.list_chargers(self.db_path)
        by_id = {s["id"]: s for s in stations}

        self.assertEqual(len(by_id["CH-001"]["sockets"]), 2)  # 2 stik
        self.assertEqual(len(by_id["CH-002"]["sockets"]), 3)  # 3 stik
        self.assertEqual(len(by_id["CH-003"]["sockets"]), 1)  # 1 stik
        self.assertEqual(len(by_id["CH-004"]["sockets"]), 2)  # 2 stik

    def test_can_add_station_with_multiple_sockets(self):
        station = services.add_charger(
            name="Test Station",
            location="Testby",
            sockets=[
                {"max_power_kw": 22.0, "connector_type": "Type2"},
                {"max_power_kw": 50.0, "connector_type": "CCS"},
                {"max_power_kw": 50.0, "connector_type": "CCS"},
            ],
            db_path=self.db_path,
        )

        self.assertIsNotNone(station)
        self.assertEqual(station["name"], "Test Station")

        stations = services.list_chargers(self.db_path)
        new_station = next(s for s in stations if s["name"] == "Test Station")
        self.assertEqual(len(new_station["sockets"]), 3)

    def test_can_simulate_telemetry_and_create_events(self):
        created = services.simulate_telemetry(self.db_path)
        telemetry = services.list_telemetry(db_path=self.db_path)
        events = services.list_domain_events(db_path=self.db_path)

        # 8 stik i alt (2+3+1+2), én telemetri-aflæsning per stik
        self.assertEqual(len(created), 8)
        self.assertEqual(len(telemetry), 8)
        self.assertTrue(any(event["event_name"] == "TelemetryReceived" for event in events))

    def test_can_start_and_end_session(self):
        started = services.start_session(db_path=self.db_path)
        ended = services.end_latest_session(self.db_path)

        self.assertEqual(started["status"], "active")
        self.assertEqual(ended["status"], "completed")
        self.assertGreater(ended["energy_kwh"], 0)
        self.assertGreater(ended["price_dkk"], 0)

    def test_kpis_have_expected_fields(self):
        services.simulate_telemetry(self.db_path)

        kpis = services.calculate_kpis(self.db_path)

        self.assertEqual(kpis["charger_count"], 4)
        self.assertEqual(kpis["socket_count"], 8)
        self.assertIn("forecast_next_hour_kw", kpis)
        self.assertIn("uptime_percent", kpis)

    def test_faulted_socket_reduces_uptime(self):
        # 1 ud af 8 stik er faulted → 7/8 = 87.5%
        database.execute(
            "UPDATE sockets SET status = ? WHERE id = ?",
            ("faulted", "CH-001-S1"),
            db_path=self.db_path,
        )

        kpis = services.calculate_kpis(self.db_path)

        self.assertEqual(kpis["uptime_percent"], 87.5)

    def test_powerbi_report_rows_contain_all_datasets(self):
        services.simulate_telemetry(self.db_path)
        services.seed_demo_sessions(self.db_path)

        rows = services.build_powerbi_report_rows(self.db_path)
        datasets = {row["dataset"] for row in rows}
        metrics = {row["metric"] for row in rows}

        self.assertIn("charger", datasets)
        self.assertIn("telemetry", datasets)
        self.assertIn("session", datasets)
        self.assertIn("domain_event", datasets)
        self.assertIn("energy_kwh", metrics)
        self.assertIn("power_kw", metrics)

    def test_powerbi_summary_contains_dashboard_metrics(self):
        services.simulate_telemetry(self.db_path)
        services.seed_demo_sessions(self.db_path)

        summary = services.build_powerbi_summary(self.db_path)

        # charger_count bevarer sit navn for PowerBI bagudkompatibilitet
        self.assertEqual(summary["charger_count"], 4)
        self.assertEqual(summary["completed_sessions"], 9)
        self.assertGreater(summary["total_energy_kwh"], 0)
        self.assertIn("generated_at", summary)

    def test_can_seed_demo_sessions_for_all_sockets(self):
        created = services.seed_demo_sessions(self.db_path)
        sessions = services.list_sessions(self.db_path)

        self.assertEqual(len(created), 9)
        # Alle 8 stik er repræsenteret (CH-003-S1 optræder i to sessioner)
        socket_ids_in_sessions = {session["socket_id"] for session in sessions}
        self.assertIn("CH-001-S1", socket_ids_in_sessions)
        self.assertIn("CH-001-S2", socket_ids_in_sessions)
        self.assertIn("CH-002-S1", socket_ids_in_sessions)
        self.assertIn("CH-002-S2", socket_ids_in_sessions)
        self.assertIn("CH-002-S3", socket_ids_in_sessions)
        self.assertIn("CH-003-S1", socket_ids_in_sessions)
        self.assertIn("CH-004-S1", socket_ids_in_sessions)
        self.assertIn("CH-004-S2", socket_ids_in_sessions)
        self.assertTrue(all(session["status"] == "completed" for session in sessions))

    def test_seed_demo_sessions_is_idempotent(self):
        first_call = services.seed_demo_sessions(self.db_path)
        second_call = services.seed_demo_sessions(self.db_path)
        sessions = services.list_sessions(self.db_path)

        self.assertEqual(len(first_call), 9)
        self.assertEqual(len(second_call), 0)
        self.assertEqual(len(sessions), 9)

    def test_cannot_start_second_session_on_occupied_socket(self):
        first = services.start_session("CH-001-S1", db_path=self.db_path)
        second = services.start_session("CH-001-S1", db_path=self.db_path)

        self.assertIsNotNone(first)
        self.assertEqual(first["status"], "active")
        self.assertIsNone(second)

    def test_two_sockets_on_same_station_can_run_simultaneously(self):
        # Kerneforretningsregel: to stik på SAMME standere kan lade på samme tid.
        # Det var ikke muligt i den gamle model med én Charger per enhed.
        first = services.start_session("CH-001-S1", db_path=self.db_path)
        second = services.start_session("CH-001-S2", db_path=self.db_path)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first["status"], "active")
        self.assertEqual(second["status"], "active")

    def test_cannot_start_session_on_faulted_socket(self):
        database.execute(
            "UPDATE sockets SET status = ? WHERE id = ?",
            ("faulted", "CH-002-S1"),
            db_path=self.db_path,
        )

        result = services.start_session("CH-002-S1", db_path=self.db_path)

        self.assertIsNone(result)

    def test_forecast_query_does_not_write_domain_events(self):
        services.simulate_telemetry(self.db_path)
        events_before = len(services.list_domain_events(500, self.db_path))

        services.forecast_next_hour(self.db_path)
        services.forecast_next_hour(self.db_path)
        services.forecast_next_hour(self.db_path)

        events_after = len(services.list_domain_events(500, self.db_path))
        self.assertEqual(events_before, events_after)

    def test_publish_forecast_records_domain_event(self):
        services.simulate_telemetry(self.db_path)

        services.publish_forecast_next_hour(self.db_path)

        events = services.list_domain_events(500, self.db_path)
        self.assertTrue(any(event["event_name"] == "LoadForecastCalculated" for event in events))

    def test_forecast_falls_back_to_baseline_when_insufficient_data(self):
        forecast = services.forecast_load_next_hour(self.db_path)

        self.assertEqual(forecast.model, "MeanBaseline")
        self.assertIsNone(forecast.r2_score)
        self.assertGreaterEqual(forecast.sample_size, 0)

    def test_forecast_uses_linear_regression_with_enough_occupied_telemetry(self):
        for index in range(8):
            ts = f"2026-05-23T{10 + index:02d}:00:00"
            database.execute(
                "INSERT INTO telemetry (socket_id, power_kw, voltage, current, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                ("CH-001-S1", 10.0 + index * 2.0, 230.0, 10.0, "occupied", ts),
                db_path=self.db_path,
            )

        forecast = services.forecast_load_next_hour(self.db_path)

        self.assertEqual(forecast.model, "LinearRegression")
        self.assertEqual(forecast.sample_size, 8)
        self.assertIsNotNone(forecast.r2_score)
        self.assertEqual(forecast.feature_names, ("time_index", "hour_of_day"))
        self.assertEqual(len(forecast.coefficients), 2)
        self.assertGreater(forecast.next_hour_kw, 0)

    def test_load_forecast_is_frozen_value_object(self):
        from dataclasses import FrozenInstanceError

        from domain import LoadForecast

        forecast = LoadForecast(next_hour_kw=12.5, model="LinearRegression", sample_size=10)
        with self.assertRaises(FrozenInstanceError):
            forecast.model = "Tampered"

    def test_diagnose_incidents_returns_all_stations_with_zero_when_no_incidents(self):
        diagnostics = services.diagnose_incidents_by_charger(self.db_path)

        self.assertEqual(len(diagnostics), 4)
        self.assertTrue(all(row["incident_count"] == 0 for row in diagnostics))
        self.assertTrue(all(row["last_incident_at"] is None for row in diagnostics))

    def test_diagnose_incidents_attributes_counts_to_correct_station(self):
        database.execute(
            "INSERT INTO incidents (charger_id, description, severity, created_at) VALUES (?, ?, ?, ?)",
            ("CH-002", "first fault", "high", "2026-05-20T10:00:00"),
            db_path=self.db_path,
        )
        database.execute(
            "INSERT INTO incidents (charger_id, description, severity, created_at) VALUES (?, ?, ?, ?)",
            ("CH-002", "second fault", "high", "2026-05-21T10:00:00"),
            db_path=self.db_path,
        )
        database.execute(
            "INSERT INTO incidents (charger_id, description, severity, created_at) VALUES (?, ?, ?, ?)",
            ("CH-003", "single fault", "medium", "2026-05-22T10:00:00"),
            db_path=self.db_path,
        )

        diagnostics = services.diagnose_incidents_by_charger(self.db_path)
        by_id = {row["charger_id"]: row for row in diagnostics}

        self.assertEqual(by_id["CH-002"]["incident_count"], 2)
        self.assertEqual(by_id["CH-002"]["last_description"], "second fault")
        self.assertEqual(by_id["CH-003"]["incident_count"], 1)
        self.assertEqual(by_id["CH-001"]["incident_count"], 0)
        # Sorteret efter incident_count DESC, så CH-002 skal være først
        self.assertEqual(diagnostics[0]["charger_id"], "CH-002")

    def test_transaction_rolls_back_on_error(self):
        sessions_before = len(services.list_sessions(self.db_path))
        events_before = len(services.list_domain_events(500, self.db_path))

        try:
            with database.transaction(self.db_path) as db:
                db.execute(
                    "INSERT INTO sessions (socket_id, contract_id, start_time, status) VALUES (?, ?, ?, ?)",
                    ("CH-001-S1", "TEST", "2026-01-01T00:00:00", "active"),
                )
                db.execute(
                    "INSERT INTO domain_events (event_name, entity_id, description, created_at) VALUES (?, ?, ?, ?)",
                    ("TestEvent", "x", "test", "2026-01-01T00:00:00"),
                )
                raise RuntimeError("forced failure")
        except RuntimeError:
            pass

        self.assertEqual(len(services.list_sessions(self.db_path)), sessions_before)
        self.assertEqual(len(services.list_domain_events(500, self.db_path)), events_before)


if __name__ == "__main__":
    unittest.main()
