# Sprog-brug (Ubiquitous Language)

> "Ubiquitous Language" er et DDD-begreb: domæne-eksperter, udviklere og kode
> skal bruge **samme ord** for de samme ting. Hvis forretningen siger
> "ladesession", må koden ikke kalde det `record_x_42`. Ellers opstår der
> oversættelses-fejl mellem forretning og kode.
>
> Dette dokument er den fælles ordbog for VoltEdge MVP'en. Alle termer her
> findes præcis sådan i koden — så når censor spørger "hvad er en
> ChargingSession?", kan jeg pege på `domain.py` og forklare det samme begreb.

## Bounded Context

| Term | Betydning |
|---|---|
| **Charging Operations Intelligence** | Det afgrænsede område MVP'en dækker: status, telemetri, sessioner, hændelser, KPI'er og forecast for ladeinfrastrukturen. Billing, partner-onboarding og hardware-adaptere ligger **udenfor** dette context og er bevidst ikke implementeret. |

## Entities (har identitet over tid)

Entities har et **id** og kan ændre tilstand. To chargers med samme navn er stadig forskellige entities.

| Engelsk navn (i koden) | Dansk forklaring | Kode-placering |
|---|---|---|
| `Charger` | En fysisk ladestander. Har id, navn, lokation, status og max effekt. | `domain.py`, tabel `chargers` |
| `ChargingSession` | En ladesession — perioden hvor en bil oplades. Har start, slut, energi, pris og status. | `domain.py`, tabel `sessions` |
| `TelemetryReading` | Én måling fra en charger på et bestemt tidspunkt (effekt, spænding, strøm, status). | `domain.py`, tabel `telemetry` |
| `Incident` | En fejl-hændelse oprettet når en charger melder `faulted`. Har beskrivelse, alvorlighed og oprettelses-tid. | `domain.py`, tabel `incidents` |

## Value Objects (har ingen identitet — kun værdi)

Value objects sammenlignes på **værdi**, ikke id. To `PowerKw(22.0)` er ens. De er **immutable** — man kan ikke ændre dem efter de er skabt; man laver bare en ny.

| Engelsk navn | Dansk forklaring | Hvorfor det er et VO |
|---|---|---|
| `PowerKw` | Effekt i kilowatt. | Validerer at effekt ≥ 0. To målinger med samme tal er ens. |
| `EnergyKwh` | Energi i kilowatt-timer. | Samme idé — kan ikke være negativ. |
| `MoneyDkk` | Pris i danske kroner. | Domain-rule: ingen negative penge. Skiller "tal" fra "tal med betydning". |
| `ChargerStatus` (enum) | Stationens drift-tilstand: `available`, `occupied`, `faulted`, `offline`. | Fast lukket værdimængde — kun disse fire tilstande er gyldige. |
| `SessionStatus` (enum) | Session-tilstand: `active` eller `completed`. | Samme princip. |
| `LoadForecast` (frozen) | Resultatet af en forecast-beregning: forudsagt kW + model-info + R². | `frozen=True` betyder at man **ikke** kan ændre tallet bagefter — så ingen kan manipulere et forecast efter det er udregnet. |

## Aggregater

Et aggregat samler entities/VOs der **skal være konsistente på samme tid**. Vi tager skrive-lås på hele aggregatet for ikke at få halv-skrevne tilstande.

| Aggregat | Hvad det indeholder | Hvorfor det er ét aggregat |
|---|---|---|
| **Charger-aggregat** | `Charger` + dens åbne `ChargingSession` + dens seneste `TelemetryReading` + eventuelle åbne `Incident`. | Når en session starter, skal chargerens status ændres atomart (ellers kunne to brugere booke samme stander). Det håndteres af `database.transaction()` i `start_session`. |

## Domain Events (forretningsmæssige kendsgerninger der er sket)

Domain events beskriver hændelser som **forretningen interesserer sig for** — ting drift, billing eller analytics vil reagere på. De skrives til `domain_events`-tabellen som en uændrelig log.

| Event-navn (i DB) | Hvornår oprettes det | Forretningsmæssig betydning |
|---|---|---|
| `ChargerStatusChanged` | Når en chargers status går fra X til Y. | Operationelt skift drift skal vide — fx fra `available` til `occupied`. |
| `SessionStarted` | Ved start af en ladesession. | En kunde er begyndt at lade — billing-relevant. |
| `SessionEnded` | Ved afslutning af en session (inkl. demo-seed). | Session-data er færdig og kan faktureres. |
| `IncidentOpened` | Når en charger melder `faulted`. | En fejl er åbnet — drift skal reagere. |
| `LoadForecastCalculated` | Når `publish_forecast_next_hour` køres. | Et forecast er publiceret som forretningsfaktum (CQRS — den **eneste** skriveoperation for forecast). |

## Integration Events (tekniske hændelser fra eksterne contexts)

Et **integration event** kommer udefra (her: simuleret OCPP-telemetri fra ladestander-hardware). Det er en teknisk hændelse, ikke en forretningsbeslutning. I MVP'en gemmer vi det i **samme `domain_events`-tabel** som de rigtige domain events for at holde infrastrukturen simpel — men begrebsmæssigt er det noget andet.

| Event-navn (i DB) | Hvornår oprettes det | Hvorfor det er et integration event |
|---|---|---|
| `TelemetryReceived` | Hver gang `simulate_telemetry` skaber en måling. | "Der kom data ind fra hardware" — en teknisk integration mellem OCPP-context og vores Charging Operations Intelligence-context. Forretningen reagerer ikke på hver enkelt måling; den reagerer på de **udledte** domain events (`ChargerStatusChanged`, `IncidentOpened`) som måling kan udløse. |

> **Hvis censor spørger:** "Er `TelemetryReceived` ikke et domain event når det ligger i `domain_events`-tabellen?"
>
> Svar: *I koden er det behandlet ensartet for at simplificere persistens og Power BI-eksport. Men begrebsmæssigt er det et **integration event** fra OCPP-konteksten. I et produktionssystem ville man typisk skille de to logs (én for tekniske integrationer, én for forretningsmæssige fakta), så analytikere ikke skal filtrere telemetri-støj fra session-events.*

## Domain Services (logik der ikke hører til ét objekt)

| Service | Analyse-type | Hvad den svarer på |
|---|---|---|
| `calculate_kpis` | Deskriptiv | **Hvad sker der?** — antal chargers, aktive sessions, total energi, uptime, peak load, forecast. |
| `diagnose_incidents_by_charger` | Diagnostisk | **Hvorfor er uptime ikke 100%?** — bryder incidents ned per charger. |
| `forecast_load_next_hour` | Predictive (ML) | **Hvad vil ske næste time?** — træner scikit-learn `LinearRegression` på (time-index, hour-of-day) → power_kw. |
| `forecast_next_hour` | Cold-start fallback | Simpel gennemsnit × 1.08 — bruges kun når der er færre end 5 målinger (så ML giver ingen mening). |

## Application Services (orkestrerer flows)

Disse er flows på tværs af domain-objekter — typisk én pr. forretnings-handling.

| Service | Hvad den gør |
|---|---|
| `simulate_telemetry` | Genererer en måling for hver charger + opdaterer status + opretter events (alt i én transaction). |
| `start_session` | "Atomic claim" på en charger via `UPDATE ... WHERE status='available'` — forhindrer at to brugere booker samme stander. |
| `end_latest_session` | Afslutter seneste aktive session, henter aktuel el-pris via `price_service`, opdaterer charger til `available`, skriver `SessionEnded`. |
| `seed_demo_sessions` | Idempotent demo-data: skipper rækker der allerede findes (samme charger + start_time). Henter historisk el-pris per session via `price_service`. |
| `publish_forecast_next_hour` | Kører forecastet **og** skriver `LoadForecastCalculated`-event. Den eneste forecast-funktion der ændrer DB (CQRS). |

## Pris-service (infrastructure layer — kalder eksternt API)

`price_service.py` er kode der taler med et **eksternt system** (elprisenligenu.dk). Den ligger som infrastructure layer fordi den oversætter mellem den eksterne pris-context og vores domain.

| Funktion | Hvad den gør |
|---|---|
| `get_price_per_kwh(region, at)` | Henter dansk spot-pris per kWh for given region og tidspunkt. Lægger 25% moms på. Floor til 0 hvis spot-prisen er negativ (kan ske ved sol-overskud i Danmark). |
| `get_region_for_location(location)` | Mapper en charger-by til DK1 (Jylland/Fyn) eller DK2 (Sjælland). |
| `_fetch_prices(date, region)` | Kalder elprisenligenu.dk's REST-API via `urllib`. Sender User-Agent header (krævet af API'et). |
| `reset_cache()` | Tømmer in-memory cache. Bruges i tests for isolation. |

| Konstant | Værdi | Hvorfor |
|---|---|---|
| `FALLBACK_PRICE_PER_KWH_DKK` | `3.25` | Bruges hvis API'et ikke kan nås — sikrer at MVP'en fortsætter offline. |
| `VAT_MULTIPLIER` | `1.25` | 25% dansk moms oven på spot-prisen. |
| `LOCATION_TO_REGION` | dict | Copenhagen→DK2, Aarhus/Odense/Aalborg→DK1. Matcher Danmarks faktiske el-prisområder (Storebælt deler landet). |

## Infrastruktur-termer (ikke domain — men vigtige at forklare)

| Term | Hvad det betyder her |
|---|---|
| `database.transaction()` | Context manager der starter `BEGIN IMMEDIATE`, committer ved succes, rollback'er ved fejl. Sikrer at fx session-INSERT og event-INSERT lykkes **sammen** eller slet ikke. |
| **Atomic claim** | At "booke" et delt resource via betinget `UPDATE`. Hvis `rowcount == 0`, var en anden hurtigere. Forhindrer TOCTOU-race. |
| **Idempotency** | Samme handling kan gentages uden dubletter. `seed_demo_sessions` tjekker for eksisterende række før INSERT. |
| **CQRS** | Command/Query Responsibility Segregation — GET (queries) må aldrig ændre tilstand; kun explicit POST (commands) skriver. Derfor er `forecast_load_next_hour` ren beregning, mens `publish_forecast_next_hour` er kommando-versionen. |
| **Cold-start** | Når der er for lidt data til at træne ML — vi falder tilbage til en simpel baseline-beregning. |
| **Anti-corruption layer** | `/api/powerbi/*`-endpoints. Power BI læser **ikke** SQLite direkte; den får en stabil JSON-kontrakt, så vi kan ændre DB-skemaet uden at bryde rapporten. |
| **Bounded Context Map** | Diagrammet i `ARCHITECTURE.md` der viser hvilke andre contexts MVP'en taler med (OCPP + elprisenligenu.dk upstream, Billing/Partner downstream, Power BI som ACL-konsument). |
| **Negativ spot-pris** | Reelt dansk fænomen: når solceller producerer mere end forbruget, kan timeprisen blive negativ. Vi flooor til 0 så MVP'en ikke modellerer "appen betaler kunden" — men det er en god demo-pointe at det forekommer. |
| **Fallback-strategi** | Hvis `elprisenligenu.dk` ikke svarer, returnerer `price_service` konstanten 3.25 DKK/kWh. Vi logger en warning, men appen fortsætter. Det gør MVP'en **resilient** — censor-demo virker også uden internet. |
| **Cache pr. (dato, region)** | `price_service` gemmer API-svaret i en in-memory dict. Forhindrer at vi spammer API'et — én cache-entry dækker alle 24 timer for dagen for én region. |

## Sådan bruges denne ordbog mundtligt

Når censor spørger om et begreb, kan jeg:

1. **Pege på koden** ("`ChargingSession` ligger i `domain.py` linje 100"),
2. **Forklare med min egen analogi** ("Det er som en kvittering — den får et id når kunden starter, og lukkes når kunden går"),
3. **Vise hvor det bruges** ("Den oprettes af `start_session` og lukkes af `end_latest_session`").

Det er det Ubiquitous Language gør for et eksamens-forsvar: **én term, ét sted, én forklaring**.
