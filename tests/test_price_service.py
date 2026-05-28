import unittest
from datetime import datetime
from unittest import mock

import price_service


class PriceServiceTests(unittest.TestCase):
    def setUp(self):
        price_service.reset_cache()

    def test_region_mapping_copenhagen_is_dk2(self):
        self.assertEqual(price_service.get_region_for_location("Copenhagen"), "DK2")

    def test_region_mapping_jutland_cities_are_dk1(self):
        self.assertEqual(price_service.get_region_for_location("Aarhus"), "DK1")
        self.assertEqual(price_service.get_region_for_location("Odense"), "DK1")
        self.assertEqual(price_service.get_region_for_location("Aalborg"), "DK1")

    def test_unknown_location_falls_back_to_default_region(self):
        self.assertEqual(price_service.get_region_for_location("Berlin"), price_service.DEFAULT_REGION)

    def test_price_includes_25_percent_vat(self):
        fake_response = [
            {"DKK_per_kWh": 2.00, "time_start": "2026-05-27T08:00:00+02:00"},
        ]
        with mock.patch("price_service._fetch_prices", return_value=fake_response):
            price = price_service.get_price_per_kwh("DK2", datetime(2026, 5, 27, 8))

        self.assertAlmostEqual(price, 2.50, places=2)

    def test_price_uses_correct_hour_from_api(self):
        fake_response = [
            {"DKK_per_kWh": 1.00, "time_start": "2026-05-27T13:00:00+02:00"},
            {"DKK_per_kWh": 3.00, "time_start": "2026-05-27T14:00:00+02:00"},
            {"DKK_per_kWh": 5.00, "time_start": "2026-05-27T15:00:00+02:00"},
        ]
        with mock.patch("price_service._fetch_prices", return_value=fake_response):
            price = price_service.get_price_per_kwh("DK1", datetime(2026, 5, 27, 14))

        self.assertAlmostEqual(price, 3.75, places=2)

    def test_fallback_when_api_fails(self):
        with mock.patch(
            "price_service._fetch_prices",
            side_effect=ConnectionError("no internet"),
        ):
            price = price_service.get_price_per_kwh("DK2", datetime(2026, 5, 27, 8))

        self.assertEqual(price, price_service.FALLBACK_PRICE_PER_KWH_DKK)

    def test_negative_spot_price_is_floored_to_zero(self):
        fake_response = [
            {"DKK_per_kWh": -0.05, "time_start": "2026-05-27T12:00:00+02:00"},
        ]
        with mock.patch("price_service._fetch_prices", return_value=fake_response):
            price = price_service.get_price_per_kwh("DK2", datetime(2026, 5, 27, 12))

        self.assertEqual(price, 0.0)

    def test_cache_prevents_repeated_api_calls(self):
        fake_response = [
            {"DKK_per_kWh": 1.00, "time_start": "2026-05-27T08:00:00+02:00"},
        ]
        mock_fetch = mock.MagicMock(return_value=fake_response)
        with mock.patch("price_service._fetch_prices", mock_fetch):
            price_service.get_price_per_kwh("DK2", datetime(2026, 5, 27, 8))
            price_service.get_price_per_kwh("DK2", datetime(2026, 5, 27, 8))
            price_service.get_price_per_kwh("DK2", datetime(2026, 5, 27, 8))

        self.assertEqual(mock_fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
