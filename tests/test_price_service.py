import unittest
from datetime import datetime
from unittest import mock

import price_service


class PriceServiceTests(unittest.TestCase):
    def setUp(self):
        # Hver test starter med tom cache saa de ikke paavirker hinanden.
        price_service.reset_cache()

    def test_region_mapping_copenhagen_is_dk2(self):
        self.assertEqual(price_service.get_region_for_location("Copenhagen"), "DK2")

    def test_region_mapping_jutland_cities_are_dk1(self):
        self.assertEqual(price_service.get_region_for_location("Aarhus"), "DK1")
        self.assertEqual(price_service.get_region_for_location("Odense"), "DK1")
        self.assertEqual(price_service.get_region_for_location("Aalborg"), "DK1")

    def test_unknown_location_falls_back_to_default_region(self):
        # Ukendt by skal ikke crashe - returnerer default-regionen.
        self.assertEqual(price_service.get_region_for_location("Berlin"), price_service.DEFAULT_REGION)

    def test_price_includes_25_percent_vat(self):
        # Vi mocker API'et til at returnere en kendt spot-pris paa 2.00 DKK
        # for klokken 08. Forventet output: 2.00 * 1.25 = 2.50 DKK.
        fake_response = [
            {"DKK_per_kWh": 2.00, "time_start": "2026-05-27T08:00:00+02:00"},
        ]
        with mock.patch("price_service._fetch_prices", return_value=fake_response):
            price = price_service.get_price_per_kwh("DK2", datetime(2026, 5, 27, 8))

        self.assertAlmostEqual(price, 2.50, places=2)

    def test_price_uses_correct_hour_from_api(self):
        # API'et returnerer 3 timer; vi spoerger om time 14 og forventer den entry.
        fake_response = [
            {"DKK_per_kWh": 1.00, "time_start": "2026-05-27T13:00:00+02:00"},
            {"DKK_per_kWh": 3.00, "time_start": "2026-05-27T14:00:00+02:00"},
            {"DKK_per_kWh": 5.00, "time_start": "2026-05-27T15:00:00+02:00"},
        ]
        with mock.patch("price_service._fetch_prices", return_value=fake_response):
            price = price_service.get_price_per_kwh("DK1", datetime(2026, 5, 27, 14))

        # 3.00 * 1.25 = 3.75
        self.assertAlmostEqual(price, 3.75, places=2)

    def test_fallback_when_api_fails(self):
        # Hvis _fetch_prices kaster en netvaerksfejl skal vi faa fallback-prisen.
        with mock.patch(
            "price_service._fetch_prices",
            side_effect=ConnectionError("no internet"),
        ):
            price = price_service.get_price_per_kwh("DK2", datetime(2026, 5, 27, 8))

        self.assertEqual(price, price_service.FALLBACK_PRICE_PER_KWH_DKK)

    def test_negative_spot_price_is_floored_to_zero(self):
        # I Danmark kan spot-prisen blive negativ ved hoej sol-produktion.
        # Vi modellerer ikke negativ slutbruger-pris, saa vi forventer 0.
        fake_response = [
            {"DKK_per_kWh": -0.05, "time_start": "2026-05-27T12:00:00+02:00"},
        ]
        with mock.patch("price_service._fetch_prices", return_value=fake_response):
            price = price_service.get_price_per_kwh("DK2", datetime(2026, 5, 27, 12))

        self.assertEqual(price, 0.0)

    def test_cache_prevents_repeated_api_calls(self):
        # Foerste kald rammer API'et, andet kald (samme dag+region) skal komme fra cachen.
        fake_response = [
            {"DKK_per_kWh": 1.00, "time_start": "2026-05-27T08:00:00+02:00"},
        ]
        mock_fetch = mock.MagicMock(return_value=fake_response)
        with mock.patch("price_service._fetch_prices", mock_fetch):
            price_service.get_price_per_kwh("DK2", datetime(2026, 5, 27, 8))
            price_service.get_price_per_kwh("DK2", datetime(2026, 5, 27, 8))
            price_service.get_price_per_kwh("DK2", datetime(2026, 5, 27, 8))

        # Tre kald, men kun ÉN faktisk API-anmodning takket vaere cachen.
        self.assertEqual(mock_fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
