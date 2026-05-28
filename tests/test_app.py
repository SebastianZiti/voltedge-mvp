import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import price_service
from app import create_app


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "app.db"
        self.app = create_app(self.db_path)
        self.client = self.app.test_client()

        self._price_patcher = mock.patch(
            "price_service._fetch_prices",
            side_effect=ConnectionError("test environment - no real API call"),
        )
        self._price_patcher.start()
        price_service.reset_cache()

    def tearDown(self):
        self._price_patcher.stop()
        self.temp_dir.cleanup()

    def test_ready_endpoint_checks_database(self):
        response = self.client.get("/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "ready")

    def test_security_headers_are_added(self):
        response = self.client.get("/health")

        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

    def test_analytics_does_not_embed_powerbi(self):
        response = self.client.get("/analytics")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"iframe", response.data)
        self.assertNotIn(b"Power BI", response.data)

    def test_powerbi_summary_endpoint_returns_kpis(self):
        response = self.client.get("/api/powerbi/summary")

        self.assertEqual(response.status_code, 200)
        self.assertIn("charger_count", response.json)
        self.assertIn("forecast_next_hour_kw", response.json)

    def test_powerbi_report_data_endpoint_returns_rows(self):
        response = self.client.get("/api/powerbi/report-data")

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json), 4)
        self.assertEqual(response.json[0]["dataset"], "charger")

    def test_metrics_endpoint_exposes_prometheus_metrics(self):
        self.client.get("/health")
        self.client.get("/api/chargers")
        response = self.client.get("/metrics")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.content_type)
        self.assertIn("# TYPE flask_http_request_total counter", body)
        self.assertIn('flask_http_request_total{method="GET",path="/health",status="200"}', body)
        self.assertIn("flask_http_request_duration_seconds_bucket", body)
        self.assertIn("voltedge_db_queries_total", body)
        self.assertIn("voltedge_db_query_duration_seconds_bucket", body)

    def test_csv_download_routes_are_not_public(self):
        latest_report = self.client.get("/export/latest_report.csv")
        telemetry_export = self.client.get("/export/telemetry.csv")

        self.assertEqual(latest_report.status_code, 404)
        self.assertEqual(telemetry_export.status_code, 404)

    def test_ready_does_not_leak_error_details(self):
        with mock.patch("app.database.query_one", side_effect=RuntimeError("hemmelig DB-detalje")):
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json, {"status": "not_ready"})
        self.assertNotIn("hemmelig", response.get_data(as_text=True))


class SecretKeyHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "app.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_production_without_secret_key_raises(self):
        with mock.patch.dict(os.environ, {"SERVICE_ENV": "production"}, clear=False):
            os.environ.pop("SECRET_KEY", None)
            with self.assertRaises(RuntimeError):
                create_app(self.db_path)

    def test_production_with_default_secret_key_raises(self):
        with mock.patch.dict(
            os.environ,
            {"SERVICE_ENV": "production", "SECRET_KEY": "dev-only-change-me"},
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                create_app(self.db_path)

    def test_production_with_compose_placeholder_secret_key_raises(self):
        with mock.patch.dict(
            os.environ,
            {
                "SERVICE_ENV": "production",
                "SECRET_KEY": "local-compose-change-before-production",
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                create_app(self.db_path)

    def test_production_with_strong_secret_key_starts(self):
        with mock.patch.dict(
            os.environ,
            {"SERVICE_ENV": "production", "SECRET_KEY": "en-laang-tilfaeldig-noegle-1234567890"},
            clear=False,
        ):
            app = create_app(self.db_path)
            self.assertEqual(app.config["SERVICE_ENV"], "production")


class SeedDemoGateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "app.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_seed_demo_blocked_in_production(self):
        with mock.patch.dict(
            os.environ,
            {"SERVICE_ENV": "production", "SECRET_KEY": "en-laang-tilfaeldig-noegle-1234567890"},
            clear=False,
        ):
            app = create_app(self.db_path)
            client = app.test_client()

            api_response = client.post("/api/sessions/seed-demo")
            form_response = client.post("/sessions/seed-demo")

            self.assertEqual(api_response.status_code, 404)
            self.assertEqual(form_response.status_code, 404)

    def test_seed_demo_allowed_in_development(self):
        response = self.client_for_dev().post("/api/sessions/seed-demo")
        self.assertEqual(response.status_code, 201)

    def client_for_dev(self):
        app = create_app(self.db_path)
        return app.test_client()


if __name__ == "__main__":
    unittest.main()
