# Eksempelflow: VoltEdge MVP

Dette flowchart viser det typiske bruger- og systemflow i programmet.

```mermaid
flowchart TD
    A["Bruger åbner webapp<br/>http://127.0.0.1:5001"] --> B["Flask app.py modtager request"]
    B --> C["Dashboard vises"]

    C --> D["services.calculate_kpis()"]
    C --> E["services.list_chargers()"]
    C --> F["services.list_telemetry()"]
    C --> G["services.list_domain_events()"]

    D --> H["SQLite database<br/>voltedge.db"]
    E --> H
    F --> H
    G --> H

    C --> I{"Bruger vælger handling"}

    I --> J["Generate telemetry"]
    J --> K["POST /simulate"]
    K --> L["services.simulate_telemetry()"]
    L --> M["Opretter TelemetryReading"]
    M --> N["Opdaterer Charger status"]
    N --> O["Gemmer event i domain_events-tabel<br/>TelemetryReceived (integration event)<br/>ChargerStatusChanged (domain event)"]
    O --> H
    H --> C

    I --> P["Gå til Sessions"]
    P --> Q["GET /sessions"]
    Q --> R["services.list_sessions()"]
    R --> H
    H --> S["Sessions-side vises"]

    S --> T{"Session handling"}
    T --> U["Start session"]
    U --> V["POST /sessions/start"]
    V --> W["services.start_session()"]
    W --> X["Charger.can_start_session()"]
    X --> Y{"Charger er ikke<br/>offline/faulted?"}
    Y -->|"Ja"| Z["ChargingSession.start()"]
    Z --> AA["Gem session som ACTIVE"]
    AA --> AB["Sæt charger til OCCUPIED"]
    AB --> AC["Gem DomainEvent<br/>SessionStarted"]
    AC --> H
    Y -->|"Nej"| S

    T --> AD["End session"]
    AD --> AE["POST /sessions/end"]
    AE --> AF["services.end_latest_session()"]
    AF --> AG["ChargingSession.complete()"]
    AG --> AH["Beregner energy_kwh og price_dkk"]
    AH --> AI["Gem session som COMPLETED"]
    AI --> AJ["Sæt charger til AVAILABLE"]
    AJ --> AK["Gem DomainEvent<br/>SessionEnded"]
    AK --> H

    T --> AL["Generate demo sessions"]
    AL --> AM["POST /sessions/seed-demo<br/>(blokeret 404 i production)"]
    AM --> AN["services.seed_demo_sessions()"]
    AN --> ANC{"Findes denne demo-session<br/>allerede? (idempotency)"}
    ANC -->|"Nej"| AO["Opretter demo sessions<br/>på flere chargers"]
    ANC -->|"Ja"| ANS["Springer INSERT over"]
    AO --> AP["Gemmer SessionEnded events"]
    AP --> H
    ANS --> H

    I --> AQ["Gå til Analytics"]
    AQ --> AR["GET /analytics"]
    AR --> AS["services.calculate_kpis()"]
    AR --> AT["services.forecast_load_next_hour()<br/>(sklearn LinearRegression eller<br/>MeanBaseline fallback)"]
    AR --> ATD["services.diagnose_incidents_by_charger()<br/>(diagnostisk domain service)"]
    AS --> H
    AT --> H
    ATD --> H
    H --> AV["Analytics-side viser KPI'er,<br/>forecast (model, R², samples)<br/>og diagnostics-tabel"]

    I --> APUB["Publicer forecast som event"]
    APUB --> APUBM["POST /api/analytics/forecast/publish"]
    APUBM --> APUBS["services.publish_forecast_next_hour()<br/>(eneste sted forecast skriver til DB —<br/>CQRS: GET er pure queries)"]
    APUBS --> APUBE["Gemmer DomainEvent<br/>LoadForecastCalculated"]
    APUBE --> H

    I --> AW["Power BI Desktop henter data"]
    AW --> AX["GET /api/powerbi/report-data"]
    AX --> AY["services.build_powerbi_report_rows()"]
    AY --> H
    H --> AZ["JSON-data bruges<br/>i Power BI dashboard"]
```

## Kort forklaring

Programmet starter i `app.py`, hvor Flask-routes tager imod brugerens handlinger.
Selve forretningslogikken ligger især i `services.py`, mens domæneobjekterne ligger i `domain.py`.
Data gemmes i SQLite-databasen `voltedge.db`.

Et centralt eksempel er start af en session:

1. Brugeren klikker start session.
2. `app.py` kalder `services.start_session()`.
3. `services.py` finder en charger i databasen.
4. Chargeren laves til et `Charger`-domæneobjekt.
5. `Charger.can_start_session()` tjekker om den må starte en session.
6. Hvis ja, oprettes en `ChargingSession` — alt inden for én `database.transaction()`-context manager.
7. Sessionen gemmes i databasen.
8. Chargeren sættes til `occupied` via **atomic claim** (`UPDATE … WHERE status='available'`), så to samtidige requests ikke kan starte en session på samme charger.
9. Der gemmes et domain event: `SessionStarted`.

## CI/CD-flow (DevSecOps)

```mermaid
flowchart LR
    DEV["Sebas pusher kode"] --> GH["GitHub modtager push"]
    GH --> CI["Job: ci"]
    CI --> CIT["Tests<br/>python -m unittest"]
    CI --> CIA["Sikkerhed:<br/>pip-audit<br/>(CVE-scan)"]
    CI --> CIB["Build Docker image"]
    CIT --> CIG{"Alt grønt?"}
    CIA --> CIG
    CIB --> CIG
    CIG -->|"Nej"| FAIL["Workflow fejler<br/>(ingen publish)"]
    CIG -->|"Ja, og main-branch"| CD["Job: cd<br/>(needs: ci)"]
    CD --> CDL["Log ind på GHCR"]
    CDL --> CDB["Build + push image<br/>med OCI source label"]
    CDB --> REG["ghcr.io/sebastianziti/<br/>voltedge-mvp:latest +<br/>:&lt;commit-sha&gt;"]
    REG --> ROLL["Rollback-mulighed:<br/>deploy en tidligere SHA"]
```

## Observability-flow (runtime)

```mermaid
flowchart LR
    APP["Flask app.py"] --> METRIC["GET /metrics endpoint"]
    APP --> HOOK["after_request hook<br/>(observability.py)"]
    HOOK --> RECORD["Optæller HTTP requests<br/>+ latency histogram"]
    DB["database.py"] --> DBREC["Optæller DB queries<br/>+ latency histogram"]
    METRIC --> PROM["Prometheus scraper<br/>(hvert 10. sekund)"]
    RECORD --> METRIC
    DBREC --> METRIC
    PROM --> TSDB["Prometheus TSDB"]
    TSDB --> GRAF["Grafana dashboard<br/>(VoltEdge-overview)"]
```
