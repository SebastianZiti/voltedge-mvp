# VoltEdge Smart Charging Operations Intelligence MVP

Python/Flask MVP til eksamen i Design og implementering af digitale løsninger.
Løsningen demonstrerer en lille operations-platform for VoltEdge Mobility A/S, hvor telemetri,
ladesessioner, domain events, KPI'er, forecast og Power BI-eksport hænger sammen.

## Hvad programmet demonstrerer

- Web-dashboard med charger-status, KPI'er, telemetry og domain events.
- API til chargers, sessions, telemetry simulation, analytics og CSV-export.
- DDD-inspireret domænemodel med entities, value objects, domain events og domain services.
- SQLite som operational database.
- Simpelt load forecast som analytics/domain service.
- Demo sessions på tværs af alle ladestandere, så Power BI har data at arbejde med.
- Power BI-venlig samlet CSV-rapport med dansk decimalformat.
- Power BI iframe-slot på Analytics-siden.
- DevSecOps-elementer: tests, CI, Docker, `/health`, `/ready`, security headers og logging.

## Start lokalt

```bash
cd "/Users/sebastian/Desktop/Eksamens MVP/voltedge_mvp"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Åbn:

```text
http://127.0.0.1:5001
```

## Demo-flow

1. Åbn dashboardet.
2. Klik `Generate telemetry` et par gange.
3. Gå til `Sessions`.
4. Klik `Generate demo sessions`.
5. Gå tilbage til dashboardet.
6. Klik `Download CSV report`.
7. Importer CSV-filen i Power BI.
8. Gå til `Analytics` og vis KPI'er, forecast, separate CSV-exports og Power BI iframe-området.

## Power BI CSV

Dashboard-knappen `Download CSV report` downloader:

```text
voltedge_latest_report.csv
```

Endpoint:

```text
GET /export/latest_report.csv
```

Filen bruger semikolon og dansk decimalformat, så Power BI ikke læser `31,27` som `3127`.
Ved import i Power BI bør du vælge:

```text
Separator: Semicolon / Semikolon
Locale: Danish / Denmark
```

Den samlede CSV har disse kolonner:

```text
dataset;record_id;charger_id;location;status;metric;value;timestamp;description
```

`metric` forklarer hvad `value` betyder:

- `max_power_kw`: ladestanderens maksimale kapacitet.
- `power_kw`: aktuel effekt fra telemetry.
- `energy_kwh`: energi leveret i afsluttede sessions.
- `incident`: tællefelt for incidents.
- `event`: tællefelt for domain events.

Til Power BI-graf for energiforbrug:

```text
X-akse: charger_id
Y-akse: Sum af value
Filter: dataset = session
Filter: metric = energy_kwh
```

Til graf for aktuel ladeeffekt:

```text
X-akse: charger_id
Y-akse: Sum eller Average af value
Filter: dataset = telemetry
Filter: metric = power_kw
```

Separate CSV'er findes stadig:

```text
GET /export/chargers.csv
GET /export/telemetry.csv
GET /export/sessions.csv
GET /export/incidents.csv
GET /export/domain_events.csv
```

## Power BI iframe

Analytics-siden har et iframe-slot til en publiceret Power BI-rapport.
Start appen med en embed-URL:

```bash
POWERBI_EMBED_URL="https://app.powerbi.com/reportEmbed?reportId=..." python app.py
```

URL'en valideres, så kun `https://app.powerbi.com/...` accepteres.
Selve Power BI-rapporten bygges i Power BI Desktop eller Power BI Service.

## API endpoints

```text
GET  /health
GET  /ready
GET  /api/chargers
POST /api/telemetry/simulate
GET  /api/sessions
POST /api/sessions/start
POST /api/sessions/end
POST /api/sessions/seed-demo
GET  /api/analytics/kpis
GET  /api/analytics/forecast
GET  /api/events
GET  /export/latest_report.csv
GET  /export/chargers.csv
GET  /export/telemetry.csv
GET  /export/sessions.csv
GET  /export/incidents.csv
GET  /export/domain_events.csv
```

## DDD-kobling i koden

- Bounded context: Charging Operations.
- Entities: `Charger`, `ChargingSession`, `TelemetryReading`, `Incident`.
- Value objects: `PowerKw`, `EnergyKwh`, `MoneyDkk`, `ChargerStatus`, `SessionStatus`.
- Domain events: `TelemetryReceived`, `ChargerStatusChanged`, `SessionStarted`, `SessionEnded`, `IncidentOpened`, `LoadForecastCalculated`.
- Domain service: `forecast_next_hour`.
- Persistens: SQLite-tabellerne `chargers`, `telemetry`, `sessions`, `incidents`, `domain_events`.

Domæneobjekterne ligger i `domain.py`, og service-laget mapper mellem domæneobjekter og SQLite-records i `services.py`.

## DevSecOps og drift

Programmet indeholder:

- Unit tests i `tests/`.
- GitHub Actions CI med test og Docker build.
- Dockerfile med healthcheck mod `/ready`.
- `/health` til simpel liveness.
- `/ready` til database-readiness.
- Security headers: CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`.
- Request logging via Flask logger.
- Miljøvariabler:
  - `SERVICE_ENV`
  - `LOG_LEVEL`
  - `FLASK_DEBUG`
  - `SECRET_KEY`
  - `POWERBI_EMBED_URL`

## Test

```bash
python3 -m unittest discover -s tests
```

Testene dækker:

- database seed med demo-ladestandere.
- telemetry simulation.
- start og afslutning af sessions.
- demo sessions på alle chargers.
- KPI-beregning, inkl. uptime hvor `faulted` ikke tæller som drift.
- CSV-export.
- `/ready`, security headers og Power BI iframe mount.

## Docker

Build:

```bash
docker build -t voltedge-mvp .
```

Run:

```bash
docker run --rm -p 5001:5001 voltedge-mvp
```

Run med Power BI iframe:

```bash
docker run --rm -p 5001:5001 \
  -e POWERBI_EMBED_URL="https://app.powerbi.com/reportEmbed?reportId=..." \
  voltedge-mvp
```

Tjek container readiness:

```bash
curl http://127.0.0.1:5001/ready
```

## Realistisk videreudvikling

I en enterprise-version kunne MVP'en udvides med:

- PostgreSQL i stedet for SQLite.
- Azure Service Bus i stedet for lokale domain events.
- API Gateway foran Flask API'et.
- Data warehouse i stedet for CSV-export.
- Power BI semantic model med separate tabeller og relationer.
- Produktions-WSGI server og central log/monitorering.
