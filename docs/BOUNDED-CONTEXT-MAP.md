# Bounded Context Map — skabelon

> **Hvad denne fil er:** En tekstuel beskrivelse af hvad din Bounded Context
> Map skal indeholde. Brug den som "grundrids" når du tegner i draw.io,
> PowerPoint, Lucidchart eller hånden. Mermaid-blokken nederst kan også
> renderes direkte hvis du bruger en editor der understøtter det
> (GitHub, VS Code med Mermaid-extension, Obsidian).

---

## Formål

Bounded Context Map'et viser **din MVP placeret i det bredere VoltEdge-landskab**.
Den svarer på: "Hvilke andre systemer/contexts taler din løsning med, og hvilken
retning går data?"

---

## Elementer der skal være med

### Centrum (din MVP)
- **Charging Operations Intelligence** — din bounded context
  - Tegnes som et stort rektangel i midten
  - Skriv "MVP" eller "vores context" i hjørnet så det er tydeligt

### Upstream (sender data IND til din context)
- **OCPP Adapters** (charger-hardware)
  - Sender telemetri ind via simulate_telemetry
  - Markér med pilen pegende ind mod MVP'en
  - Skriv "U" (upstream supplier) ved siden af pilen

- **elprisenligenu.dk** (eksternt el-pris-API)
  - Leverer aktuelle danske spot-priser per time, regionsopdelt (DK1/DK2)
  - Hentes via HTTP GET af `price_service.py`
  - Skriv "U" + nævn at vi har fallback hvis API'et er nede
  - Markér gerne med en anden farve (lyseblå) — det er et eksternt offentligt API, ikke en intern VoltEdge-service

### Downstream (modtager data FRA din context)
- **Billing & Settlement**
  - Modtager session-data til afregning
  - Udenfor MVP-scope, men relevant senere
  - Pil peger fra MVP til Billing
  - Skriv "D" (downstream consumer)

- **Partner Onboarding & Roaming**
  - Modtager session-data til roaming-afregning
  - Også udenfor MVP-scope
  - Pil peger fra MVP til Partner
  - Skriv "D"

- **Power BI Desktop**
  - Henter rapporterings-data via /api/powerbi/*
  - Markér forbindelsen tydeligt — den ER implementeret
  - Pil peger fra MVP til Power BI
  - Skriv "D" (downstream konsument)

---

## Anbefalede farver

| Element | Forslag til farve | Begrundelse |
|---|---|---|
| Din MVP (centrum) | Grøn eller blå (kraftig) | Det er hovedfokus |
| Out-of-scope contexts (Billing, Partner) | Grå eller blegere | Viser at de er udenfor scope |
| Implementerede integrationer (OCPP, Power BI) | Solid farve | Disse er reelt i koden |

---

## Pile / relationer

Brug DDD-notation:
- **U** = Upstream (supplier — leverer data)
- **D** = Downstream (consumer — modtager data)

Pilen tegnes i data-flow retningen. Hvis OCPP sender telemetri til MVP, så peger pilen
fra OCPP til MVP, og OCPP markeres "U" (er upstream), MVP er "D".

---

## Mermaid-version (kan renderes direkte)

```mermaid
graph TB
    OCPP["OCPP Adapters<br/>(charger hardware)<br/>simuleret i MVP"]
    ELPRIS["elprisenligenu.dk<br/>(eksternt el-pris-API)<br/>DK1 / DK2 spot-priser"]

    MVP["CHARGING OPERATIONS INTELLIGENCE<br/>━━━━━━━━━━━━━━━━━━<br/>vores bounded context<br/>(MVP'en)<br/><br/>- chargers, telemetry, sessions<br/>- incidents, domain events<br/>- KPI'er + forecast<br/>- realtidspris fra price_service"]

    BILL["Billing & Settlement<br/>(udenfor MVP-scope)"]
    PART["Partner Onboarding<br/>& Roaming<br/>(udenfor MVP-scope)"]
    PBI["Power BI Desktop<br/>(eksternt rapport-værktøj)"]

    OCPP -->|U: sender telemetri| MVP
    ELPRIS -->|U: spot-pris pr. time<br/>fallback 3.25 hvis nede| MVP
    MVP -->|D: leverer session-data| BILL
    MVP -->|D: leverer partner-data| PART
    MVP -->|D: leverer rapport-data<br/>via /api/powerbi/*| PBI

    style MVP fill:#13795b,color:#fff,stroke:#0a4d3a,stroke-width:3px
    style OCPP fill:#fff7e0,stroke:#b8860b
    style ELPRIS fill:#e1f3ff,stroke:#245f93
    style BILL fill:#eee,color:#666,stroke:#999,stroke-dasharray:5
    style PART fill:#eee,color:#666,stroke:#999,stroke-dasharray:5
    style PBI fill:#e1effb,stroke:#245f93
```

---

## ASCII-version (hvis du tegner i hånden)

```
   ┌──────────────────────┐         ┌──────────────────────┐
   │   OCPP Adapters      │         │  elprisenligenu.dk   │
   │ (charger hardware)   │         │   (el-pris-API)      │
   └──────────┬───────────┘         └──────────┬───────────┘
              │                                │
              │ U: telemetri                   │ U: spot-pris
              v                                v
   ┌─────────────────────────────────────────────────────────┐
   │                                                         │
   │   CHARGING OPERATIONS INTELLIGENCE                      │
   │   ───────────────────────────────────                   │
   │   vores bounded context (MVP)                           │
   │                                                         │
   │   • chargers, telemetry, sessions                       │
   │   • incidents, domain events                            │
   │   • KPI'er + forecast (ML)                              │
   │   • realtids el-pris (via price_service)                │
   │                                                         │
   └──────┬─────────────────┬─────────────────┬──────────────┘
          │                 │                 │
          │ D               │ D               │ D
          │ session-data    │ partner-data    │ rapport-data
          v                 v                 v
   ┌────────────┐    ┌──────────────┐   ┌──────────────┐
   │  Billing & │    │   Partner    │   │   Power BI   │
   │ Settlement │    │  Onboarding  │   │   Desktop    │
   │ (out of    │    │  & Roaming   │   │  (ekstern    │
   │  scope)    │    │ (out of      │   │   klient)    │
   │            │    │   scope)     │   │              │
   └────────────┘    └──────────────┘   └──────────────┘
```

---

## Når du tegner det selv — tjekliste

- [ ] Din MVP står i midten og er tydeligt markeret som hovedfokus
- [ ] OCPP er øverst eller venstre (kommer "ind" til dig)
- [ ] Billing, Partner og Power BI er nedenunder eller højre
- [ ] Pile har retning (ikke bare linjer)
- [ ] Hver pil har en label med "U" eller "D"
- [ ] Out-of-scope contexts er visuelt tonet ned (fx grå)
- [ ] Power BI er fremhævet som **implementeret** (ikke out-of-scope)
- [ ] Diagrammet har en titel: "Bounded Context Map — VoltEdge MVP"

---

## Hvad censor kan spørge

> *"Hvorfor er Billing udenfor jeres scope?"*
>
> Fordi MVP'en fokuserer på det operationelle (drift, telemetri, sessions, analytics).
> Billing kræver kontraktlogik og afregningsmodeller der hører til et helt andet
> bounded context — at blande dem ville bryde DDD-princippet om separation of concerns.

> *"Hvordan taler I med Power BI?"*
>
> Via /api/powerbi/* JSON-endpoints. Power BI Desktop henter data via Web-connector
> og refresh'er manuelt. Vores interne database-skema er skjult bag JSON-formatet.

> *"Hvorfor er elprisenligenu.dk en upstream-context?"*
>
> Fordi de leverer data ind til vores context — de aktuelle danske spot-priser per
> time, regionsopdelt på DK1 (vest) og DK2 (øst). Vi har ingen kontrol over deres
> API, men vi har bygget en fallback i `price_service.py` så MVP'en stadig virker
> hvis API'et er nede. Vi ganger spot-prisen med 1.25 for at inkludere 25% moms,
> så tallet matcher hvad en EV-ejer faktisk betaler.
