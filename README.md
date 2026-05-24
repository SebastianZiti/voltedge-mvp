# VoltEdge Smart Charging Operations Intelligence MVP

Python/Flask MVP til eksamen i Design og implementering af digitale løsninger.
Løsningen demonstrerer en lille operations-platform for VoltEdge Mobility A/S, hvor telemetri,
ladesessioner, domain events, KPI'er, forecast og Power BI API-data hænger sammen.

## Hvad programmet demonstrerer

- Web-dashboard med charger-status, KPI'er, telemetry og domain events.
- API til chargers, sessions, telemetry simulation, analytics og Power BI data.
- DDD-inspireret domænemodel med entities, value objects, domain events og domain services.
- SQLite som operational database.
- Simpelt load forecast som analytics/domain service.
- Demo sessions på tværs af alle ladestandere, så Power BI har data at arbejde med.
- Power BI-venlige JSON-endpoints til ekstern BI-rapportering.
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
6. Importer `/api/powerbi/report-data` i Power BI Desktop via Web connector.
7. Klik `Refresh` i Power BI Desktop efter nye demo-data.
8. Gå til `Analytics` og vis KPI'er og forecast i webappen.

## Power BI data endpoints

Power BI læser ikke direkte fra SQLite-filen. Power BI bruger appens HTTP-endpoints som datakilde, og appen fungerer som API-lag foran den operationelle database:

```text
Power BI Desktop / Power BI Service
  -> GET /api/powerbi/report-data
  -> Flask route i app.py
  -> services.build_powerbi_report_rows()
  -> database.query_all()
  -> voltedge.db
```

Det betyder, at databasen ikke eksponeres direkte. Power BI får et kontrolleret BI-dataset fra applikationen.

Brug disse endpoints i Power BI Desktop:

```text
GET /api/powerbi/report-data
GET /api/powerbi/summary
```

`/api/powerbi/report-data` returnerer et normaliseret datasæt med chargers, telemetry, sessions, incidents og domain events.
`/api/powerbi/summary` returnerer færdige KPI-tal som JSON.

Datasættet fra `/api/powerbi/report-data` har disse felter:

```text
dataset, record_id, charger_id, location, status, metric, value, timestamp, description
```

`metric` forklarer hvad `value` betyder:

```text
- max_power_kw: ladestanderens maksimale kapacitet.
- power_kw: aktuel effekt fra telemetry.
- energy_kwh: energi leveret i afsluttede sessions.
- incident: tællefelt for incidents.
- event: tællefelt for domain events.
```

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

Den tilhørende Power BI Desktop-rapport ligger i repoet som:

```text
powerbi-eksamen.pbix
```

Rapporten er bygget mod det lokale endpoint:

```text
http://127.0.0.1:5001/api/powerbi/report-data
```

Når appen kører lokalt og data ændres, kan rapporten opdateres med `Refresh` i Power BI Desktop.

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
GET  /api/powerbi/summary
GET  /api/powerbi/report-data
```

## DDD-kobling i koden

- Bounded context: Charging Operations Intelligence.
- Entities: `Charger`, `ChargingSession`, `TelemetryReading`, `Incident`.
- Value objects: `PowerKw`, `EnergyKwh`, `MoneyDkk`, `ChargerStatus`, `SessionStatus`, `LoadForecast` (frozen).
- Domain events: `TelemetryReceived`, `ChargerStatusChanged`, `SessionStarted`, `SessionEnded`, `IncidentOpened`, `LoadForecastCalculated`.
- Domain service: `forecast_load_next_hour` (scikit-learn lineær regression, med `forecast_next_hour` som cold-start fallback).
- Persistens: SQLite-tabellerne `chargers`, `telemetry`, `sessions`, `incidents`, `domain_events`.

Domæneobjekterne ligger i `domain.py`, og service-laget mapper mellem domæneobjekter og SQLite-records i `services.py`.

Se også:

- `docs/ARCHITECTURE.md` for bounded context, ubiquitous language, DDD-mapping, dataflow og drift.
- `docs/POWERBI.md` for den eksterne Power BI-integration og dashboard-data contract.

## DevSecOps og drift

Programmet indeholder:

- Unit tests i `tests/`.
- GitHub Actions CI med test og Docker build.
- GitHub Actions CD i `.github/workflows/CD.yml`, som publicerer Docker image til GitHub Packages.
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

## Miljøer (dev / test / prod)

Appen styres via miljøvariablen `SERVICE_ENV`. Værdien påvirker både hvilke
endpoints der er åbne, og om appen overhovedet starter:

| `SERVICE_ENV` | `SECRET_KEY` påkrævet? | `/sessions/seed-demo` | Tilsigtet brug |
| --- | --- | --- | --- |
| `development` | Nej (default-værdi tilladt) | Tilladt (201) | Lokal udvikling på egen maskine |
| `test` | **Ja** — appen fejler ved opstart hvis mangler eller default | Tilladt (201) | CI / staging — tester en realistisk konfiguration |
| `production` | **Ja** — appen fejler ved opstart hvis mangler eller default | **Blokeret (404)** | Live drift |

Eksempel — start i production:

```bash
docker run --rm -p 5001:5001 \
  -e SERVICE_ENV=production \
  -e SECRET_KEY="$(openssl rand -hex 32)" \
  ghcr.io/<github-owner>/voltedge-mvp:latest
```

Hvis `SECRET_KEY` glemmes i test eller production, stopper appen med
`RuntimeError` — den nægter at starte med den offentligt kendte default-nøgle.

## Deployment

Repoet indeholder en CD-workflow, der bygger Docker-imaget og publicerer det til GitHub Packages / GitHub Container Registry:

```text
.github/workflows/CD.yml
```

Workflowet kører ved push til `main` og kan også startes manuelt fra GitHub Actions.
CI-workflowet tester appen og bygger Docker-imaget som validering. CD-workflowet publicerer Docker-imaget til:

```text
ghcr.io/<github-owner>/voltedge-mvp:latest
ghcr.io/<github-owner>/voltedge-mvp:<commit-sha>
```

Workflowet bruger GitHubs indbyggede `GITHUB_TOKEN`, så der skal ikke oprettes en separat Azure secret til CD.
I GitHub-repoets package settings skal container package være synlig for den målgruppe, der skal kunne hente imaget.

Kør published image lokalt:

```text
docker pull ghcr.io/<github-owner>/voltedge-mvp:latest
docker run --rm -p 5001:5001 ghcr.io/<github-owner>/voltedge-mvp:latest
```

Kør published image lokalt uden pull:

```text
docker run --rm -p 5001:5001 ghcr.io/<github-owner>/voltedge-mvp:latest
```

Dette opfylder CD-delen som container-publicering: hver godkendt ændring på `main` bliver testet, bygget og gjort tilgængelig som versioneret Docker image i GitHub Packages.

## Rollback-strategi

CD publicerer **to tags** for hvert build:

- `:latest` — peger altid på seneste main-commit.
- `:<commit-sha>` — uforanderlig version, ét per commit.

Det betyder at hver tidligere version stadig ligger i GitHub Container Registry.
Hvis et nyt deploy viser sig at være fejlbehæftet, ruller man tilbage ved at
deploye den **forrige** SHA-tag:

```bash
# 1. Find den seneste kendte gode commit-sha (fx fra GitHub Actions-historik).
# 2. Deploy den specifikke version i stedet for :latest:
docker pull ghcr.io/<github-owner>/voltedge-mvp:<previous-sha>
docker run --rm -p 5001:5001 \
  -e SERVICE_ENV=production \
  -e SECRET_KEY="$SECRET_KEY" \
  ghcr.io/<github-owner>/voltedge-mvp:<previous-sha>
```

For at gøre en rollback **permanent** (så `:latest` igen peger på den gamle
version) kan man enten:

1. **Revert-commit på `main`** — `git revert <bad-sha>` + push. CD bygger
   automatisk en ny `:latest` der svarer til den gamle adfærd. Anbefalet
   fordi git-historikken bliver eksplicit om hvad der skete.
2. **Re-tag manuelt** i Container Registry — hurtig nødløsning, men efterlader
   ingen spor i git-historikken.

Databasen er bevidst **uafhængig af container-versionen** (SQLite-filen ligger
på værten/volume), så rollback af koden påvirker ikke data. Ved skema-ændringer
i fremtidige versioner skal migrationer designes så de er bagudkompatible — en
ny kolonne skal være nullable/default, så en ældre container stadig kan læse
tabellen.

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
- Power BI JSON-endpoints.
- `/ready` og security headers.

## Docker

Build:

```bash
docker build -t voltedge-mvp .
```

Run:

```bash
docker run --rm -p 5001:5001 voltedge-mvp
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
- Data warehouse i stedet for direkte API-baseret BI-export.
- Power BI semantic model med separate tabeller og relationer.
- Produktions-WSGI server og central log/monitorering.
