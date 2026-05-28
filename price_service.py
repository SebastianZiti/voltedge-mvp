import json
import logging
import urllib.request
from datetime import datetime


FALLBACK_PRICE_PER_KWH_DKK = 3.25
VAT_MULTIPLIER = 1.25

LOCATION_TO_REGION = {
    "Copenhagen": "DK2",
    "Aarhus": "DK1",
    "Odense": "DK1",
    "Aalborg": "DK1",
}
DEFAULT_REGION = "DK2"

_price_cache: dict = {}

_logger = logging.getLogger(__name__)


def get_region_for_location(location):
    return LOCATION_TO_REGION.get(location, DEFAULT_REGION)


def get_price_per_kwh(region, at=None):
    if at is None:
        at = datetime.now()

    date_key = at.strftime("%Y-%m-%d")
    cache_key = (date_key, region)

    if cache_key not in _price_cache:
        try:
            _price_cache[cache_key] = _fetch_prices(at, region)
        except (OSError, ValueError, KeyError) as exc:
            _logger.warning("Kunne ikke hente el-pris fra elprisenligenu.dk (%s) - bruger fallback %.2f DKK/kWh", exc, FALLBACK_PRICE_PER_KWH_DKK)
            return FALLBACK_PRICE_PER_KWH_DKK

    entries = _price_cache[cache_key]
    spot_price = _find_price_for_hour(entries, at.hour)
    if spot_price is None:
        _logger.warning("Ingen pris-entry for time %d - bruger fallback", at.hour)
        return FALLBACK_PRICE_PER_KWH_DKK

    consumer_price = max(spot_price * VAT_MULTIPLIER, 0.0)
    return round(consumer_price, 4)


def reset_cache():
    _price_cache.clear()


def _fetch_prices(date, region):
    url = (
        f"https://www.elprisenligenu.dk/api/v1/prices/"
        f"{date.year}/{date.month:02d}-{date.day:02d}_{region}.json"
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "VoltEdge-MVP/1.0"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _find_price_for_hour(entries, hour):
    for entry in entries:
        time_start = entry.get("time_start", "")
        try:
            entry_hour = int(time_start[11:13])
        except (IndexError, ValueError):
            continue
        if entry_hour == hour:
            return float(entry["DKK_per_kWh"])
    return None
