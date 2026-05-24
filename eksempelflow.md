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
    N --> O["Gemmer DomainEvent<br/>TelemetryReceived / ChargerStatusChanged"]
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
    AL --> AM["POST /sessions/seed-demo"]
    AM --> AN["services.seed_demo_sessions()"]
    AN --> AO["Opretter demo sessions<br/>på flere chargers"]
    AO --> AP["Gemmer SessionEnded events"]
    AP --> H

    I --> AQ["Gå til Analytics"]
    AQ --> AR["GET /analytics"]
    AR --> AS["services.calculate_kpis()"]
    AR --> AT["services.forecast_next_hour()"]
    AS --> H
    AT --> AU["Gemmer DomainEvent<br/>LoadForecastCalculated"]
    AU --> H
    H --> AV["Analytics-side viser KPI'er<br/>og forecast"]

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
6. Hvis ja, oprettes en `ChargingSession`.
7. Sessionen gemmes i databasen.
8. Chargeren sættes til `occupied`.
9. Der gemmes et domain event: `SessionStarted`.
