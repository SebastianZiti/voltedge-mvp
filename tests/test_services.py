import tempfile
import unittest
from pathlib import Path

import database
import services


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        database.init_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_database_starts_with_demo_chargers(self):
        chargers = services.list_chargers(self.db_path)

        self.assertEqual(len(chargers), 4)
        self.assertEqual(chargers[0]["id"], "CH-001")

    def test_can_simulate_telemetry_and_create_events(self):
        created = services.simulate_telemetry(self.db_path)
        telemetry = services.list_telemetry(db_path=self.db_path)
        events = services.list_domain_events(db_path=self.db_path)

        self.assertEqual(len(created), 4)
        self.assertEqual(len(telemetry), 4)
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
        self.assertIn("forecast_next_hour_kw", kpis)
        self.assertIn("uptime_percent", kpis)

    def test_faulted_charger_reduces_uptime(self):
        database.execute("UPDATE chargers SET status = ? WHERE id = ?", ("faulted", "CH-001"), db_path=self.db_path)

        kpis = services.calculate_kpis(self.db_path)

        self.assertEqual(kpis["uptime_percent"], 75.0)

    def test_csv_export_contains_header(self):
        csv_data = services.export_csv("chargers", self.db_path)

        self.assertIn("id,name,location,status,max_power_kw,last_heartbeat", csv_data)

    def test_latest_report_csv_contains_powerbi_friendly_header(self):
        services.simulate_telemetry(self.db_path)

        csv_data = services.export_latest_report_csv(self.db_path)

        self.assertIn("dataset;record_id;charger_id;location;status;metric;value;timestamp;description", csv_data)
        self.assertIn("telemetry", csv_data)

    def test_can_seed_demo_sessions_for_all_chargers(self):
        created = services.seed_demo_sessions(self.db_path)
        sessions = services.list_sessions(self.db_path)

        self.assertEqual(len(created), 9)
        self.assertEqual({session["charger_id"] for session in sessions}, {"CH-001", "CH-002", "CH-003", "CH-004"})
        self.assertTrue(all(session["status"] == "completed" for session in sessions))


if __name__ == "__main__":
    unittest.main()
