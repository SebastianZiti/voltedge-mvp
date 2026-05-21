import tempfile
import unittest
from pathlib import Path

from app import create_app


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "app.db"
        self.app = create_app(self.db_path)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ready_endpoint_checks_database(self):
        response = self.client.get("/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "ready")

    def test_security_headers_are_added(self):
        response = self.client.get("/health")

        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-src", response.headers["Content-Security-Policy"])

    def test_analytics_contains_powerbi_embed_mount(self):
        response = self.client.get("/analytics")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Power BI iframe is ready", response.data)


if __name__ == "__main__":
    unittest.main()
