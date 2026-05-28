# VoltEdge — Smart Charging Operations Intelligence

Operations-platform for VoltEdge Mobility A/S. Systemet håndterer ladestandere, sessioner, telemetri, KPI'er, load forecast og Power BI-rapportering via et Flask-baseret web-interface og REST API.

## Krav

- Python 3.12+
- Docker og Docker Compose (valgfrit, men anbefalet)

## Start

### Med Docker Compose (anbefalet)

Kører app, Prometheus og Grafana samlet:

```bash
docker compose up --build
```

### Direkte med Python

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

### Adresser

| Service    | URL                            | Note                                              |
|------------|--------------------------------|---------------------------------------------------|
| Webapp     | http://127.0.0.1:5001          |                                                   | 
| Prometheus | http://127.0.0.1:9090          | Kun via Docker Compose                            | 
| Grafana    | http://127.0.0.1:3000          | Kun via Docker Compose — login: `admin` / `admin` |
| Metrics    | http://127.0.0.1:5001/metrics  | Prometheus-format, kan ses direkte i browser      |

## Demo-flow

1. Åbn dashboardet på `http://127.0.0.1:5001`.
2. Klik **Generate telemetry** et par gange — simulerer målinger fra alle ladestandere.
3. Gå til **Sessions** og klik **Generate demo sessions** — opretter historiske ladesessioner på tværs af alle stik.
4. Gå tilbage til dashboardet og se KPI'er og load forecast opdatere sig.
5. Gå til **Analytics** for ML-baseret load forecast med R²-score.
6. Åbn Power BI Desktop, brug **Web connector** mod `http://127.0.0.1:5001/api/powerbi/report-data`, og klik **Refresh**.

## Miljøvariabler

Kopiér `.env.example` til `.env` og udfyld til eget miljø:

```bash
cp .env.example .env
```

Til lokal udvikling er ingen `.env` nødvendig — `docker-compose.yml` har dev-defaults inline.

| Variabel       | Standard (dev)                          | Krævet i prod? |
|----------------|-----------------------------------------|----------------|
| `SERVICE_ENV`  | `development`                           | Nej            |
| `SECRET_KEY`   | `dev-only-change-me`                    | Ja             |
| `LOG_LEVEL`    | `INFO`                                  | Nej            |
| `FLASK_DEBUG`  | `0`                                     | Nej            |
| `DB_PATH`      | `voltedge.db` (ved siden af `app.py`)   | Nej            |

I `test`- og `production`-miljø afviser appen at starte uden en stærk `SECRET_KEY`.  
`/sessions/seed-demo`-endpointet er blokeret i `production` (returnerer 404).

## Tests

```bash
python -m unittest discover -s tests
```

44 tests fordelt på tre filer:

- `tests/test_services.py` — domæne- og servicelag: sessioner, telemetri, KPI-beregning, ML-forecast, incident-analyse, Power BI-eksport, transaction rollback.
- `tests/test_app.py` — Flask-integration: security headers, `/health`, `/ready`, `/metrics`, `SECRET_KEY`-validering, production-blokering af seed-endpoint.
- `tests/test_price_service.py` — el-pris-integration (mocket, virker offline): region-mapping, moms, fallback, negativ pris, caching.

## API endpoints

```
GET  /health
GET  /ready
GET  /metrics                          # Prometheus-format
GET  /api/chargers
POST /api/chargers
POST /api/telemetry/simulate
GET  /api/sessions
POST /api/sessions/start
POST /api/sessions/end
POST /api/sessions/seed-demo
GET  /api/analytics/kpis
GET  /api/analytics/forecast
GET  /api/analytics/diagnostics
POST /api/analytics/forecast/publish
GET  /api/events
GET  /api/powerbi/summary
GET  /api/powerbi/report-data
```

## Power BI

Power BI læser fra appens HTTP-endpoints — ikke direkte fra databasen.

```
GET /api/powerbi/report-data   — normaliseret datasæt: chargers, telemetry, sessions, incidents, domain events
GET /api/powerbi/summary       — færdige KPI-tal som JSON
```

Felter i `/api/powerbi/report-data`:

```
dataset, record_id, charger_id, location, status, metric, value, timestamp, description
```

Eksempel-filter i Power BI for energiforbrug per ladestandere:

```
X-akse: charger_id
Y-akse: Sum af value
Filter: dataset = session, metric = energy_kwh
```

Den medfølgende Power BI-rapport ligger i `PowerBI/powerbi-eksamen.pbix` og peger mod `http://127.0.0.1:5001/api/powerbi/report-data`.

## Arkitektur

- **Domænemodel** (`domain.py`): Charger (aggregate root), Socket, ChargingSession, TelemetryReading, Incident — med value objects `PowerKw`, `EnergyKwh`, `MoneyDkk`, `LoadForecast`.
- **Domain events**: ChargerAdded, ChargerStatusChanged, SessionStarted, SessionEnded, IncidentOpened, LoadForecastCalculated — gemt i `domain_events`-tabellen.
- **Domain services** (`services.py`):
  - Deskriptiv: `calculate_kpis`
  - Diagnostisk: `diagnose_incidents_by_charger`
  - Predictive: `forecast_load_next_hour` — scikit-learn `LinearRegression` med cold-start fallback til simpelt gennemsnit
- **Infrastructure**: SQLite (`database.py`), el-priser fra elprisenligenu.dk med dag/region-cache og offline-fallback (`price_service.py`), Prometheus-metrics (`observability.py`).
- **Observability**: `/metrics`-endpoint med HTTP- og database-histogrammer, Prometheus-scraping og Grafana-dashboard i `infra/`.

## Docker

```bash
docker build -t voltedge-mvp .
docker run --rm -p 5001:5001 voltedge-mvp
```

## CI/CD

`.github/workflows/cicd.yml` kører to jobs:

- `ci`: tests, pip-audit (dependency scanning) og Docker build — kører ved alle push og PRs.
- `cd`: publicerer Docker-image til GitHub Container Registry — kører kun på `main` og kun hvis `ci` er grøn.

Images tagges som `:latest` og `:<commit-sha>`, så rollback til en specifik version altid er mulig:

```bash
docker run --rm -p 5001:5001 \
  -e SERVICE_ENV=production \
  -e SECRET_KEY="$(openssl rand -hex 32)" \
  ghcr.io/<github-owner>/voltedge-mvp:<commit-sha>
```
