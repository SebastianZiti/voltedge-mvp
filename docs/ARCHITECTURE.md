# VoltEdge MVP Architecture

## Purpose

The technical MVP implements a narrow but central part of the VoltEdge case:
standardized operational insight across chargers, telemetry, sessions, events,
KPIs and load forecasting.

The chosen bounded context is:

```text
Charging Operations Intelligence
```

This bounded context owns the operational language and data needed to answer:

- Which chargers are available, occupied, faulted or offline?
- Which charging sessions are active or completed?
- What telemetry has been received from chargers?
- Which operational events and incidents have happened?
- What is the current operational performance?
- What load is expected in the next hour?

The MVP intentionally keeps billing, partner onboarding, roaming settlement and
hardware-specific OCPP adapters outside the bounded context. Those areas are
important in the full VoltEdge landscape, but they would make the exam MVP too
broad.

### Bounded Context Map

The MVP context interacts with several surrounding contexts that are part of
the wider VoltEdge landscape but deliberately out of scope. The diagram below
shows the relationships using DDD terminology (U = upstream / supplier,
D = downstream / consumer, ACL = anti-corruption layer):

```text
            +-----------------------+
            |   OCPP Adapters       |
            |   (charger hardware)  |
            +----------+------------+
                       | U  (upstream — pushes telemetry)
                       v D
       +----------------------------------+        U   +---------------------+
       |                                  |----------->|     Power BI        |
       |   Charging Operations            |   (ACL via |   (analytics /      |
       |   Intelligence  (MVP)            |    JSON    |    reporting)       |
       |                                  |    API)    +---------------------+
       +---+--------------+---------------+
           | D            | D
           v U            v U
   +---------------+   +-----------------------+
   |   Billing &   |   |  Partner Onboarding   |
   |   Settlement  |   |  & Roaming            |
   +---------------+   +-----------------------+
```

Legend:

- **Charging Operations Intelligence** owns operational truth: charger status,
  telemetry, sessions, incidents, domain events, KPIs and load forecasts.
- **OCPP Adapters** is the upstream supplier of raw telemetry. In the MVP this
  is simulated via `services.simulate_telemetry`.
- **Billing & Settlement** and **Partner Onboarding & Roaming** are downstream
  consumers of session data. They are deliberately out of MVP scope.
- **Power BI** consumes operational data via the `/api/powerbi/*` JSON
  endpoints, which act as an **anti-corruption layer**: Power BI never reads
  SQLite directly, so internal schema changes do not break the BI model.

## Ubiquitous Language

| Term | Meaning in this MVP | Code location |
| --- | --- | --- |
| `Charger` | A charging station managed by VoltEdge. | `domain.py`, `chargers` table |
| `ChargerStatus` | Operational charger state: available, occupied, faulted or offline. | `domain.py` |
| `TelemetryReading` | A point-in-time charger measurement with power, voltage, current and status. | `domain.py`, `telemetry` table |
| `ChargingSession` | A charging session with contract, start/end time, energy and price. | `domain.py`, `sessions` table |
| `SessionStatus` | Session state: active or completed. | `domain.py` |
| `Incident` | Operational problem created from a faulted charger state. | `domain.py`, `incidents` table |
| `DomainEvent` | Business event persisted for traceability and analytics. | `domain.py`, `domain_events` table |
| `LoadForecast` | Predicted next-hour load based on recent occupied charger telemetry. | `services.forecast_next_hour` |

## DDD Mapping

### Entities

- `Charger`
- `ChargingSession`
- `TelemetryReading`
- `Incident`

These objects have identity over time and are persisted in SQLite. `DomainEvent`
is **not** listed here — it is covered separately under *Domain Events* below,
because it represents a *fact that happened*, not an entity in the business
model.

### Value Objects

- `PowerKw`
- `EnergyKwh`
- `MoneyDkk`
- `ChargerStatus`
- `SessionStatus`
- `LoadForecast` (frozen — immutable result of a forecast computation)

The value objects validate simple domain rules, for example that power, energy
and money cannot be negative. `LoadForecast` is declared with `frozen=True` so
the prediction result cannot be mutated after it is produced.

### Domain Events

The MVP records domain events whenever important operational facts occur:

- `TelemetryReceived`
- `ChargerStatusChanged`
- `SessionStarted`
- `SessionEnded`
- `IncidentOpened`
- `LoadForecastCalculated`

The events are stored in the `domain_events` table and exposed to Power BI as
part of the operational analytics dataset.

### Domain Service

`services.forecast_load_next_hour` is the MVP's predictive domain service. It
reads recent occupied charger telemetry and trains a **scikit-learn linear
regression** on two features — `time_index` (overall trend) and `hour_of_day`
(daily pattern) — to predict next-hour load. The result is returned as a frozen
`LoadForecast` value object including the R² quality score.

If fewer than five occupied-status readings exist, the service falls back to a
simple mean baseline (`services.forecast_next_hour`). This cold-start fallback
keeps the system useful before enough data has been collected to train a model.

## Component Structure

```text
templates/ + static/
        |
        v
app.py                  Flask routes, API, security headers, health checks
        |
        v
services.py             Application/domain services and BI data logic
        |
        v
domain.py               Entities, value objects and domain events
        |
        v
database.py             SQLite schema, seed data and query helpers
        |
        v
voltedge.db             Operational database
```

## Persistence Model

The database mirrors the bounded context:

- `chargers`
- `telemetry`
- `sessions`
- `incidents`
- `domain_events`

This gives traceability from operational telemetry to session data, incidents,
domain events, KPIs and Power BI API data.

### ER Diagram

`chargers` is the root entity. Telemetry, sessions and incidents each reference
a single charger. `domain_events` is intentionally decoupled — it stores a flat
audit log keyed by `entity_id` (a string), so any domain object can publish an
event without forcing a foreign-key relationship.

```text
            +---------------------+
            |      chargers       |
            |---------------------|
            | id (PK)             |
            | name                |
            | location            |
            | status              |
            | max_power_kw        |
            | last_heartbeat      |
            +----------+----------+
                       |
        +--------------+--------------+
        |              |              |
        | 1:N          | 1:N          | 1:N
        v              v              v
+---------------+ +-----------+ +---------------+
|   telemetry   | | sessions  | |  incidents    |
|---------------| |-----------| |---------------|
| id (PK)       | | id (PK)   | | id (PK)       |
| charger_id FK | | charger_id| | charger_id FK |
| power_kw      | |   FK      | | description   |
| voltage       | | contract  | | severity      |
| current       | | start/end | | created_at    |
| status        | | energy    | | resolved_at   |
| timestamp     | | price     | +---------------+
+---------------+ | status    |
                  +-----------+

       +---------------------+
       |    domain_events    |   (audit log — no FK,
       |---------------------|    keyed loosely by
       | id (PK)             |    entity_id string)
       | event_name          |
       | entity_id           |
       | description         |
       | created_at          |
       +---------------------+
```

## Data Flow

```text
User/API action
  -> Flask route in app.py
  -> Service function in services.py
  -> Domain object/value object in domain.py
  -> SQLite persistence in database.py
  -> Domain event persisted in domain_events
  -> Dashboard/API/Power BI endpoints
```

For example, telemetry simulation creates a `TelemetryReading`, updates the
`Charger` status, records `TelemetryReceived`, optionally records
`ChargerStatusChanged`, and opens an `Incident` if the simulated status is
`faulted`.

## Operations and Security

The MVP includes:

- `/health` for liveness.
- `/ready` for database readiness.
- Flask request logging.
- Security headers, including CSP and `X-Content-Type-Options`.
- Dockerfile with container healthcheck.
- GitHub Actions CI for tests and Docker build.
- Power BI JSON endpoints for external BI reporting.

Production improvements would include managed database storage, authentication,
central monitoring, alerting, secret management and a full rollback strategy.
