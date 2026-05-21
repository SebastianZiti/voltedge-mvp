# VoltEdge Smart Charging Operations Intelligence MVP

Dette er en simpel Python MVP til eksamen i Design og implementering af digitale løsninger.
Den viser, hvordan VoltEdge Mobility A/S kan samle telemetri, ladesessioner, KPI'er,
forecast og BI-eksport i en lille realistisk operations-løsning.

MVP'en er bevidst lavet enkel, så den kan forklares af et team uden stærk kodebaggrund.
Der bruges Python, Flask, HTML, CSS og SQLite. Der bruges ikke TypeScript eller frontend framework.

## Hvad løsningen demonstrerer

- Et fungerende web-dashboard.
- Et fungerende API.
- Simuleret telemetri fra ladestandere.
- Ladesessioner der kan startes og afsluttes.
- Data gemt i SQLite.
- Analytics som Python domain service.
- Simpelt load forecast.
- CSV-eksport til Power BI.
- Docker-baseret kørsel.
- GitHub Actions CI med test og Docker build.

## Domænekobling

Rapportens problemfelt er fragmenteret datamodel og begrænset analyseevne hos VoltEdge.
MVP'en viser en lille samlet datamodel, hvor telemetri, charger-status, sessioner,
incidents og domain events kan spores samlet.

DDD-begreber i MVP'en:

- Bounded context: Charging Operations.
- Entities: Charger, ChargingSession, TelemetryReading, Incident.
- Value objects: PowerKw, EnergyKwh, MoneyDkk, ChargerStatus.
- Domain service: ForecastService, implementeret som `forecast_next_hour`.
- Domain events: TelemetryReceived, ChargerStatusChanged, SessionStarted, SessionEnded, LoadForecastCalculated.

## Start lokalt

```bash
cd "/Users/sebastian/Desktop/Eksamens MVP/voltedge_mvp"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Åbn derefter:

```text
http://127.0.0.1:5001
```

## Start med Docker

```bash
cd "/Users/sebastian/Desktop/Eksamens MVP/voltedge_mvp"
docker build -t voltedge-mvp .
docker run --rm -p 5001:5001 voltedge-mvp
```

## Docker i afleveringen

Man skal ikke aflevere en kørende Docker-container. Man afleverer projektet med
kode, `Dockerfile`, `requirements.txt` og denne README. Dockerfilen fungerer som
opskriften på, hvordan appen bygges og køres.

Censor eller underviser kan selv bygge og starte MVP'en med Docker:

```bash
docker build -t voltedge-mvp .
docker run --rm -p 5001:5001 voltedge-mvp
```

Når containeren kører, kan appen åbnes her:

```text
http://127.0.0.1:5001
```

Dette opfylder eksamenskravet om anvendelse af container service, fordi MVP'en
kan pakkes og afvikles som en Docker-container.

## Demo-flow til eksamen

1. Åbn dashboardet.
2. Klik på `Generate telemetry`.
3. Vis at charger-status, seneste telemetri og domain events opdateres.
4. Gå til `Sessions`.
5. Klik `Start test session`.
6. Klik `End latest session`.
7. Gå til `Analytics` og vis KPI'er og forecast.
8. Download CSV-filer og vis dem i Power BI.
9. Forklar Docker, tests og CI/CD.

## API endpoints

```text
GET  /health
GET  /api/chargers
POST /api/telemetry/simulate
GET  /api/sessions
POST /api/sessions/start
POST /api/sessions/end
GET  /api/analytics/kpis
GET  /api/analytics/forecast
GET  /api/events
GET  /export/chargers.csv
GET  /export/telemetry.csv
GET  /export/sessions.csv
GET  /export/incidents.csv
GET  /export/domain_events.csv
```

## Test

```bash
python -m unittest discover -s tests
```

Testene dækker:

- database seed med demo-ladestandere.
- simulering af telemetri.
- start og afslutning af session.
- KPI-beregning.
- CSV-eksport.

## Power BI

Brug CSV-eksporterne som datakilder:

- `telemetry.csv`: effekt, status og tidspunkt.
- `sessions.csv`: energi, pris og session-status.
- `chargers.csv`: lokation og max effekt.
- `incidents.csv`: fejl og severity.
- `domain_events.csv`: sporbarhed fra hændelser i systemet.

Foreslåede visuals:

- Cards: total kWh, active sessions, uptime, faulted chargers.
- Bar chart: kWh pr. charger.
- Line chart: power_kw over tid.
- Table: incidents og domain events.

## Hvorfor løsningen er realistisk men simpel

I en større enterprise-løsning ville VoltEdge sandsynligvis bruge Azure, PostgreSQL,
Service Bus, API Gateway og flere microservices. I denne MVP er det samlet i én Python-app,
fordi eksamensproduktet skal være forståeligt, demonstrerbart og realistisk at bygge.

Arkitekturen kan stadig forklares som første trin mod en større platform:

- SQLite kan erstattes af PostgreSQL.
- Python domain events kan erstattes af Azure Service Bus.
- Flask-app'en kan deles op i microservices.
- CSV-eksport kan erstattes af et data warehouse.
