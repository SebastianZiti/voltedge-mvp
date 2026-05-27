"""
Pris-service: henter danske el-priser fra elprisenligenu.dk's API.

Hvorfor en separat fil?
-----------------------
Det her er infrastructure layer — kode der taler med et EKSTERNT system
(elprisenligenu.dk). Vi holder det adskilt fra domain og services, saa
forretningslogikken i services.py ikke skal vide noget om HTTP eller JSON.

Hvorfor urllib og ikke requests?
--------------------------------
urllib er en del af Pythons standard-bibliotek, saa vi undgaar at tilfoeje
en ny dependency. For et enkelt GET-kald er det helt fint.

Strategi:
- Spot-pris hentes fra API'et og ganges med 1.25 (25% dansk moms)
- Vi cacher pr. dag og region for at undgaa at spamme API'et
- Hvis API'et er nede (fx offline demo) bruges en fallback-pris
- Region vaelges per charger-lokation: Koebenhavn = DK2 (oest),
  Aarhus/Odense/Aalborg = DK1 (vest) - det matcher Danmarks
  el-prisomraader (Storebaelt deler landet i to)
"""
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime


# Fallback hvis API'et er utilgaengeligt - holder MVP'en koerende
# selv hvis demo'en koerer offline eller serveren er nede.
FALLBACK_PRICE_PER_KWH_DKK = 3.25

# Dansk moms paa 25% laegges oven i spot-prisen,
# saa tallet matcher hvad en EV-ejer faktisk betaler.
VAT_MULTIPLIER = 1.25

# Vores fire chargere ligger i de byer der staar i database.py.
# Storebaelt deler Danmark i to el-prisomraader: DK1 (Jylland/Fyn) og DK2 (Sjaelland).
LOCATION_TO_REGION = {
    "Copenhagen": "DK2",
    "Aarhus": "DK1",
    "Odense": "DK1",
    "Aalborg": "DK1",
}
DEFAULT_REGION = "DK2"

# In-memory cache: noegle = (dato, region), vaerdi = liste af 24 pris-entries fra API'et.
# Foerste kald rammer API'et; efterfoelgende kald samme dag/region rammer cachen.
_price_cache: dict = {}

_logger = logging.getLogger(__name__)


def get_region_for_location(location):
    """Mapper en charger-lokation til DK1 eller DK2. Default DK2."""
    return LOCATION_TO_REGION.get(location, DEFAULT_REGION)


def get_price_per_kwh(region, at=None):
    """
    Returnerer el-pris per kWh (inkl. 25% moms) for given region og tidspunkt.
    Falder tilbage til FALLBACK_PRICE_PER_KWH_DKK hvis API'et ikke svarer.
    """
    if at is None:
        at = datetime.now()

    date_key = at.strftime("%Y-%m-%d")
    cache_key = (date_key, region)

    if cache_key not in _price_cache:
        try:
            _price_cache[cache_key] = _fetch_prices(at, region)
        # OSError daekker URLError, HTTPError, TimeoutError og ConnectionError;
        # ValueError daekker JSONDecodeError; KeyError fanger uventet JSON-struktur.
        except (OSError, ValueError, KeyError) as exc:
            _logger.warning(
                "Kunne ikke hente el-pris fra elprisenligenu.dk (%s) - bruger fallback %.2f DKK/kWh",
                exc,
                FALLBACK_PRICE_PER_KWH_DKK,
            )
            return FALLBACK_PRICE_PER_KWH_DKK

    entries = _price_cache[cache_key]
    spot_price = _find_price_for_hour(entries, at.hour)
    if spot_price is None:
        _logger.warning("Ingen pris-entry for time %d - bruger fallback", at.hour)
        return FALLBACK_PRICE_PER_KWH_DKK

    # Floor til 0: i Danmark kan spot-prisen blive NEGATIV midt paa dagen naar
    # solceller producerer mere end forbruget (forekommer regelmaessigt i 2026).
    # Vi modellerer ikke "du faar penge for at lade" i denne MVP, saa vi
    # nuller-clipper. Negativ pris er et reelt fanomen - god demo-pointe til censor.
    consumer_price = max(spot_price * VAT_MULTIPLIER, 0.0)
    return round(consumer_price, 4)


def reset_cache():
    """Roemmer cachen. Bruges af tests og kan kaldes manuelt hvis dagen skifter."""
    _price_cache.clear()


def _fetch_prices(date, region):
    """Kalder elprisenligenu.dk API og parser JSON-svaret."""
    url = (
        f"https://www.elprisenligenu.dk/api/v1/prices/"
        f"{date.year}/{date.month:02d}-{date.day:02d}_{region}.json"
    )
    # User-Agent er paakraevet af API'et (ellers 403 Forbidden).
    # Vi identificerer os som VoltEdge MVP - god opfoersel paa et offentligt API.
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "VoltEdge-MVP/1.0 (eksamens-projekt)"},
    )
    # timeout=5: hvis API'et er langsomt, falder vi hellere tilbage end at fryse appen.
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _find_price_for_hour(entries, hour):
    """
    Finder DKK_per_kWh for given time-of-day i API-svaret.
    API'et returnerer 24 entries (en per time), hver med et 'time_start' felt
    som ser saadan ud: "2026-05-27T08:00:00+02:00".
    """
    for entry in entries:
        time_start = entry.get("time_start", "")
        try:
            entry_hour = int(time_start[11:13])
        except (IndexError, ValueError):
            continue
        if entry_hour == hour:
            return float(entry["DKK_per_kWh"])
    return None
