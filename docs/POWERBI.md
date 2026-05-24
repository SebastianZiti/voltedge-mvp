# Power BI Integration

## Integration Direction

Power BI consumes data from the VoltEdge app through HTTP API endpoints. The app
remains the operational system of record, while Power BI is the independent
analytics and visualization solution.

```text
Flask MVP + SQLite
        |
        | JSON endpoints
        v
Power BI Web connector
        |
        v
Power BI report/dashboard
```

Power BI does not read `voltedge.db` directly. The Flask app is the API layer in
front of the database.

```text
Power BI Desktop
  -> GET /api/powerbi/report-data
  -> Flask route in app.py
  -> services.build_powerbi_report_rows()
  -> database.query_all()
  -> voltedge.db
```

The MVP does not embed Power BI inside the web app. The Power BI report is a
separate BI artifact.

## Data Sources

Use these endpoints in Power BI Desktop:

```text
GET /api/powerbi/report-data
GET /api/powerbi/summary
```

`/api/powerbi/report-data` returns a normalized operational dataset with rows for
chargers, telemetry, sessions, incidents and domain events.

`/api/powerbi/summary` returns dashboard-level KPIs as JSON, such as total
energy, peak load, incident count, uptime and next-hour forecast.

## Data Contract

`/api/powerbi/report-data` has this shared schema:

| Field | Meaning |
| --- | --- |
| `dataset` | Source dataset type: charger, telemetry, session, incident or domain_event. |
| `record_id` | Source record ID. |
| `charger_id` | Charger ID or event entity ID. |
| `location` | Charger location when available. |
| `status` | Charger/session/event/incident status. |
| `metric` | Describes how `value` should be interpreted. |
| `value` | Numeric value. |
| `timestamp` | Event, telemetry, heartbeat or session timestamp. |
| `description` | Human-readable context. |

Important metric values:

- `max_power_kw`
- `power_kw`
- `energy_kwh`
- `incident`
- `event`

## Local Test Without Deployment

1. Start the Flask app:

```powershell
python app.py
```

2. Open the JSON endpoints:

```text
http://127.0.0.1:5001/api/powerbi/report-data
http://127.0.0.1:5001/api/powerbi/summary
```

3. In Power BI Desktop:

- Choose `Get Data`.
- Choose `Web`.
- Enter `http://127.0.0.1:5001/api/powerbi/report-data`.
- Transform the JSON list into a table if Power BI does not do it automatically.
- Build visuals using `dataset`, `metric`, `charger_id`, `value` and `timestamp`.

This proves that Power BI Desktop can consume the app's operational data through
the app's API layer.

## Refresh Behavior

In Power BI Desktop, refresh is manual:

```text
App writes new data -> Power BI Desktop Refresh -> visuals update
```

Power BI Service scheduled refresh requires that the API endpoint is reachable
from Power BI Service, either through an online deployment or a gateway.

## Suggested Dashboard Visuals

- Total energy by charger: filter `dataset = session`, `metric = energy_kwh`.
- Current/peak load by charger: filter `dataset = telemetry`, `metric = power_kw`.
- Charger status distribution: filter `dataset = charger`.
- Incidents count: filter `dataset = incident`, `metric = incident`.
- Domain events timeline: filter `dataset = domain_event`.
- Forecast KPI: use `/api/powerbi/summary`.

## Exam Explanation

This integration satisfies the BI requirement because Power BI is independent of
the Flask app and consumes the app's exposed operational data through HTTP
endpoints. The database stays behind the application boundary instead of being
opened directly to reporting tools.
