# Mundtligt forsvar — VoltEdge MVP

Cheat sheet til mundtlig eksamen. Læs igennem 2-3 gange.
Hvert afsnit kan stå alene — du behøver ikke huske detaljerne, kun det centrale ord-for-ord.

## 🟢 Status

| Område | Status |
|---|---|
| DDD-mapping (entities, value objects, domain events, domain services) | ✅ Implementeret + dokumenteret i `ARCHITECTURE.md` |
| Machine Learning som domain service (`forecast_load_next_hour`) | ✅ sklearn LinearRegression med R²-score |
| Deskriptive + diagnostiske + predictive analyser | ✅ `calculate_kpis`, `diagnose_incidents_by_charger`, `forecast_load_next_hour` |
| Tests | ✅ 33/33 grønne |
| Sikkerhedshærdning | ✅ USER i Docker, /ready info-leak, SECRET_KEY hard-fail (m. loophole-fix), seed-demo gate |
| CI/CD | ✅ Samlet i `cicd.yml`, CD via `needs: ci`, pip-audit indbygget |
| Docker image i registry | ✅ `ghcr.io/sebastianziti/voltedge-mvp:latest` + SHA-tags |
| Rollback-strategi | ✅ Via uforanderlige SHA-tags, dokumenteret i `README.md` |
| Public GitHub repo | ✅ https://github.com/SebastianZiti/voltedge-mvp |
| Video demo | ⏳ Laver du selv |

**Hvis censor spørger "har I deployet?"** → svar: *"Ja, hver godkendt commit på main bygger og publicerer automatisk et Docker-image til GitHub Container Registry via vores CI/CD-pipeline."*

---

## 1) "Forklar Domain Driven Design i jeres MVP"

> Vores MVP er bygget op om et enkelt **bounded context**: *Charging Operations Intelligence*.
> Det er den del af VoltEdges forretning der handler om at vide hvad ladestanderne laver lige nu —
> hvilke der er ledige, hvilke der lader, hvor meget energi der bruges, og hvad der er gået galt.
>
> Inde i det bounded context har vi 4 **entities** (Charger, ChargingSession, TelemetryReading,
> Incident) og 4 **value objects** (PowerKw, EnergyKwh, MoneyDkk, LoadForecast). Entities har
> identitet — fx har en Charger et ID som "CH-001" og lever over tid. Value objects beskriver
> bare en værdi og kan ikke ændres efter de er oprettet.
>
> Hver gang noget vigtigt sker — fx en session starter, eller en charger melder fejl —
> publicerer vi et **domain event** og gemmer det i tabellen `domain_events`. Det giver os et
> sporbarheds-log over alt der er sket.

**Hvis censor spørger:** "Hvor i koden ser jeg det?"

| DDD-begreb | Fil | Linje |
|------------|-----|-------|
| Bounded context | `docs/ARCHITECTURE.md` | toppen |
| Entities | `domain.py` | `Charger`, `ChargingSession`, `TelemetryReading`, `Incident` |
| Value objects | `domain.py` | `PowerKw`, `EnergyKwh`, `MoneyDkk`, `LoadForecast` |
| Domain events | `domain.py` | `DomainEvent` + tabellen `domain_events` i `database.py` |
| Domain service | `services.py` | `forecast_load_next_hour()` |

---

## 2) "Forklar jeres Machine Learning-løsning"

> Vores **load forecasting domain service** bruger Python-biblioteket **scikit-learn** og en
> **lineær regression** til at forudsige hvor meget strøm der vil blive trukket i den næste time.
>
> Træningsdata kommer fra `telemetry`-tabellen — vi tager alle målinger hvor charger-statussen
> var "occupied" (altså en igangværende lade-session). For hver måling laver vi 2 features:
>
> 1. **`time_index`** — hvor langt henne i tidsserien er denne måling (0, 1, 2, ...). Det fanger
>    den **overordnede trend** — er belastningen stigende over tid?
> 2. **`hour_of_day`** — på hvilket tidspunkt af døgnet (0-23) blev målingen taget. Det fanger
>    **døgnmønstret** — folk lader mest om morgenen og aftenen.
>
> Target-variablen er `power_kw` — selve belastningen. Vi træner modellen med `model.fit(X, y)`,
> hvor X er vores 2 features og y er power_kw. Bagefter beder vi modellen om at forudsige
> belastningen for "næste time" med `model.predict(...)`.
>
> Vi måler modellens kvalitet med **R²-score** — et tal mellem 0 og 1. Hvis R² er tæt på 1
> forklarer modellen næsten al variationen i træningsdataene; hvis det er 0 er den ikke bedre
> end at gætte gennemsnittet. Den værdi vises live på `/analytics`-siden.
>
> Hvis der er **færre end 5 målinger** falder vi tilbage til en simpel baseline (gennemsnittet
> ganget med 1.08 vækstfaktor). Det er en bevidst "cold-start"-strategi — det giver ingen mening
> at træne en model med 2 datapunkter.

**Hvis censor spørger:** "Hvorfor lineær regression og ikke noget mere avanceret?"

> *Fordi vi er Økonomi+IT, ikke data science-studerende, og vores krav er at vi kan forklare
> hver linje. Lineær regression er den simpleste ML-model der findes — den tegner en ret linje
> gennem datapunkterne. Mere avancerede modeller (random forest, neural networks) ville være
> sværere at forsvare og krævet meget mere data. Den valgte model er let at forklare for
> business-stakeholders, hvilket matcher VoltEdges behov for transparens.*

**Konkrete kode-linjer at pege på** (`services.py`):
```python
from sklearn.linear_model import LinearRegression
import numpy as np

X = np.array(feats, dtype=float)     # features: [[time_index, hour], ...]
y = np.array(targets, dtype=float)   # target: power_kw
model = LinearRegression().fit(X, y) # her trænes modellen
prediction = float(model.predict(...)[0])  # her forudsiger vi
r2 = float(model.score(X, y))        # kvalitets-score
```

---

## 3) "Forklar CQRS-mønstret hos jer"

> CQRS står for **Command Query Responsibility Segregation**. Princippet er at funktioner der
> **læser** data, ikke samtidig må **ændre** data — og omvendt.
>
> I vores første version skrev `forecast_next_hour` et `LoadForecastCalculated`-event til
> databasen hver gang funktionen blev kaldt. Men funktionen blev kaldt fra GET-endpoints (fx
> når man åbnede dashboardet). Det betyder at et **dashboard-load** ændrede data — det er forkert
> ift. både REST-principper og CQRS.
>
> Vi splittede funktionen i to:
>
> - **`forecast_load_next_hour()`** — ren læseoperation. Den henter telemetri, kører ML-modellen,
>   returnerer et `LoadForecast`-objekt. Ingen skrivning til database.
> - **`publish_forecast_next_hour()`** — den eksplicitte skriveoperation. Den kalder først
>   læseoperationen for at få værdien, og skriver derefter et `LoadForecastCalculated`-event.
>
> I API'et er det eksponeret som:
> - `GET /api/analytics/forecast` — læse-versionen (idempotent — kan kaldes 1000 gange uden
>   bivirkninger)
> - `POST /api/analytics/forecast/publish` — skrive-versionen (bevidst handling)

**Hvis censor spørger:** "Hvorfor er det vigtigt?"

> *Hvis enhver GET-request skriver til databasen, så fylder vi events-tabellen op med "støj"
> hver gang nogen åbner dashboardet. Det gør det umuligt at bruge events til reelle
> forretningsindsigter, og det skalerer dårligt. CQRS gør koden forudsigelig — du ved hvilke
> funktioner der har bivirkninger.*

---

## 4) "Forklar jeres aggregat-konsistens"

> Når en bruger starter en charging session, sker der **3 ting i databasen** der hører sammen:
>
> 1. Charger-statussen ændres fra `available` til `occupied`
> 2. En ny række indsættes i `sessions`-tabellen med status `active`
> 3. Et `SessionStarted`-domain-event gemmes i `domain_events`
>
> Hvis programmet **crasher** mellem fx step 1 og step 2, ville charger stå som "occupied"
> uden at der er en tilhørende session. Det er en ulovlig forretningstilstand — så har vi en
> "ghost charger" der ikke kan udlejes igen.
>
> Vi løste det med en **transaktion**: enten gennemføres alle 3 trin sammen, eller også
> rulles alle ændringer tilbage. Det er implementeret som en `transaction()`-context-manager
> i `database.py` — den bruger Pythons `with`-syntax.
>
> Vi tilføjede også et **atomic claim**-mønster: i stedet for først at læse og så skrive
> (hvor en anden bruger kunne sneake ind imellem), gør vi det i én SQL-sætning:
> `UPDATE chargers SET status='occupied' WHERE id=? AND status='available'`. Hvis nogen anden
> nåede at tage chargeren først, opdaterer SQL'en 0 rækker, og vi melder fejl tilbage.

**Hvis censor spørger:** "Hvad er ACID?"

> *Det er en garanti databaser giver: Atomicitet (alt-eller-intet), Consistency (ingen
> ulovlige tilstande), Isolation (samtidige requests forstyrrer ikke hinanden), og Durability
> (det der er gemt, er gemt). Vi bruger Atomicitet via vores transaktion og Isolation via
> `BEGIN IMMEDIATE`.*

**Hvis censor spørger:** "Hvad er TOCTOU?"

> *Time-of-check vs Time-of-use. Hvis du først tjekker om en charger er ledig, og DEREFTER
> beslutter dig for at booke den, kan en anden bruger have booket den i mellemtiden. Vi
> løste det med atomic claim — vi tjekker OG booker i én operation.*

---

## 5) "Forklar value objects vs entities"

> En **entity** har en identitet der varer over tid. En `Charger` har ID'et "CH-001" og lever
> i hele systemets levetid — selv hvis dens status ændres er det stadig "samme" charger.
>
> Et **value object** har INGEN identitet — det er bare en værdi. To `PowerKw(22.0)` er den
> *samme* ting. Value objects er **immutable** (kan ikke ændres efter de er oprettet).
> Vi har lavet vores `LoadForecast` som `frozen=True` så Python tvinger den til at være
> immutable — du får en `FrozenInstanceError` hvis du prøver at ændre den.
>
> Eksempler fra koden:
>
> - `Charger` (entity) — har ID, status ændres over tid
> - `PowerKw(22.0)` (value object) — bare et tal med betydning, kan ikke ændres
> - `EnergyKwh(10.5)` (value object) — kan ikke være negativ (validerings-regel i `__post_init__`)
> - `LoadForecast(...)` (value object, frozen) — resultat af en ML-prediction

---

## 6) "Hvad er en domain service?"

> En **domain service** er forretningslogik der ikke naturligt hører til en bestemt entity.
> Vores `forecast_load_next_hour()` er et godt eksempel — den læser data fra MANGE
> telemetri-aflæsninger på tværs af alle chargers, og leverer en forecast. Den hører ikke
> til en specifik `Charger` eller `ChargingSession` — den hører til selve domænet.
>
> Det er forskelligt fra en **application service** (som koordinerer use cases, fx
> `start_session()`) og en **infrastructure service** (som taler med eksterne systemer).

---

## 7) "Forklar jeres BI-arkitektur"

> Power BI læser **ikke** direkte fra vores SQLite-database. I stedet eksponerer vi et
> JSON-endpoint (`GET /api/powerbi/report-data`) som Power BI henter via en Web Connector.
>
> Det er et **bevidst arkitekturvalg** for at:
>
> 1. **Beskytte databasen** — Power BI har ikke brug for SQL-adgang
> 2. **Skabe et stabilt data-kontrakt** — JSON-skemaet kan vi versionere uafhængigt af DB-tabeller
> 3. **Demonstrere kontekstadskillelse** — det operationelle system og BI-systemet er to
>    forskellige bounded contexts. API'et fungerer som **anti-corruption layer**.
>
> Vi har strukturer JSON'en som en flad union: hver række har et `dataset`-felt
> (charger/telemetry/session/incident/domain_event), et `metric`-felt der fortæller hvad `value`
> betyder, og et `timestamp`. Power BI kan filtrere på `dataset` og `metric` for at lave
> forskellige visualiseringer.

---

## 8) "Hvad har I gjort for sikkerhed?"

> Vi tog fire **sikkerheds-quick-wins** efter en gennemgang af koden:
>
> 1. **Container kører ikke som root** (`Dockerfile`). Vi opretter en bruger `appuser` og
>    skifter til den med `USER appuser`. Hvis nogen bryder ind i appen, har de kun denne
>    brugers rettigheder inde i containeren — ikke root. Det kaldes *"defense in depth"*.
>
> 2. **`/ready` lækker ikke fejldetaljer** (`app.py`, ready-endpoint). Tidligere returnerede
>    den `str(error)` direkte til klienten, hvilket kunne afsløre filstier eller
>    DB-detaljer (information disclosure). Nu logger vi fuld stack internt, men sender
>    kun `{"status": "not_ready"}` til klienten.
>
> 3. **`SECRET_KEY` hard-fail** (`app.py`, `create_app`). Flask bruger `SECRET_KEY` til at
>    signere sessions og cookies. Hvis nogen glemte at sætte en rigtig nøgle og vi kørte
>    i production med default-værdien, kunne angribere forfalske sessions. Derfor:
>    hvis `SERVICE_ENV != "development"` og `SECRET_KEY` mangler eller er default →
>    `RuntimeError` ved opstart. Appen nægter at starte.
>
> 4. **`/sessions/seed-demo` blokeret i production** (`app.py`, begge seed-demo-routes).
>    Det endpoint opretter test-data direkte i databasen. Hvis nogen ved en fejl
>    klikkede den i production, ville rigtige data blive forurenet. Vi returnerer 404
>    hvis `SERVICE_ENV == "production"`.

**Hvis censor spørger:** "Hvorfor lige disse 4?"

> *Det er klassiske OWASP-mønstre: privilege escalation (root i container), information
> disclosure (fejlbeskeder), broken authentication (svag SECRET_KEY), og insecure
> defaults (demo-endpoint åbent i prod). De er billige at fixe og giver stor effekt.*

**Hvis censor spørger:** "Hvorfor ikke også [authentication / rate limiting / HSTS]?"

> *Det er på vores liste men ligger udenfor MVP-scope. For en kritisk infrastruktur som
> ladestandere (NIS2-omfattet) ville vi som næste skridt tilføje rigtig authentication
> på POST-endpoints og rate limiting.*

**Tests:** vi har 6 sikkerhedstests i `tests/test_app.py` (`test_ready_does_not_leak_error_details`,
`SecretKeyHardeningTests` x3, `SeedDemoGateTests` x2).

---

## 9) "Hvordan opdager I sårbarheder i jeres afhængigheder?"

> Vi har tilføjet **`pip-audit`** som et step i vores CI-pipeline
> (`.github/workflows/cicd.yml` — `ci`-jobbet). Hver gang nogen pusher kode, slår GitHub alle vores
> Python-afhængigheder op i en offentlig database over kendte sårbarheder (PyPI Advisory
> DB / CVE-lister). Hvis der findes en sårbarhed, **fejler bygget** — så vi opdager det
> *før* koden går i production.
>
> Da vi indførte det, fandt pip-audit straks en sårbarhed i Flask 3.0.3 (CVE-2026-27205).
> Vi opdaterede til Flask 3.1.3 hvor fejlen er rettet, og auditen er nu grøn.

**Hvis censor spørger:** "Hvad er forskellen på pip-audit og fx Snyk eller Dependabot?"

> *Princippet er det samme — alle scanner deps mod en CVE-database. `pip-audit` er
> open source og kører lokalt/i CI. Dependabot kører som GitHub-service og laver
> automatiske PR'er med opdateringer. Vi valgte pip-audit fordi det er enkelt at
> integrere i CI med én linje, og vi kan forklare præcis hvad det gør.*

**Konkret kode at pege på** (`.github/workflows/cicd.yml`, `ci`-jobbet):
```yaml
- name: Audit dependencies for known vulnerabilities
  run: |
    pip install pip-audit
    pip-audit -r requirements.txt
```

---

## 10) "Hvad ændrede I i ARCHITECTURE.md?"

> Vi rettede tre konkrete ting så dokumentet matcher koden:
>
> 1. **`DomainEvent` blev fjernet fra Entities-listen.** Et domain event er ikke en
>    entity — det er et **faktum der er sket** (fx "session startede kl. 13:42"). Det
>    har ingen identitet over tid. Det er allerede korrekt beskrevet i sin egen
>    *Domain Events*-sektion. At have det begge steder var en fejl.
>
> 2. **`LoadForecast` blev tilføjet til Value Objects.** Den er deklareret med
>    `frozen=True` i `domain.py`, hvilket gør den **immutable** — du kan ikke ændre
>    resultatet af en forecast efter det er produceret. Det er en klassisk
>    value-object-egenskab.
>
> 3. **Domain Service-sektionen blev opdateret** til at beskrive
>    `forecast_load_next_hour` (vores rigtige scikit-learn-baserede service) i
>    stedet for kun den simple baseline `forecast_next_hour`. Baseline-funktionen
>    er nu beskrevet som "cold-start fallback" — det er hvad den faktisk gør.
>
> Derudover tilføjede vi to diagrammer som eksamen kræver:
>
> - **ER-diagram** der viser de 5 tabeller (chargers, telemetry, sessions, incidents,
>   domain_events) og deres relationer. Chargers er root-entiteten med 1:N forhold
>   til de tre operationelle tabeller. Domain_events er bevidst **decoupled** — den
>   bruger en løs `entity_id`-streng i stedet for foreign keys, så *enhver* domain
>   object kan publicere et event uden at låse skemaet.
>
> - **Bounded context-kort** der viser vores ene context (*Charging Operations
>   Intelligence*) sammen med de fire omkringliggende contexts (OCPP Adapters,
>   Billing, Partner Onboarding/Roaming, Power BI). Vi viser relationerne med
>   DDD-notation: U (upstream/supplier), D (downstream/consumer), og **ACL**
>   (anti-corruption layer) for Power BI-integrationen.

**Hvis censor spørger:** "Hvad er forskellen på en entity og et domain event?"

> *En entity har identitet og lever over tid — en `Charger` med ID "CH-001" er
> "samme" charger uanset hvor mange gange dens status ændres. Et domain event er
> derimod et **øjebliksbillede af noget der skete**: `SessionStarted` på et
> bestemt tidspunkt. Det ændrer sig ikke. Du publicerer det én gang og det er
> uforanderligt bagefter.*

**Hvis censor spørger:** "Hvad er et anti-corruption layer?"

> *Når to bounded contexts taler sammen, vil de gerne udvikle sig uafhængigt af
> hinanden. Et ACL er et "oversættelses-lag" mellem dem — det betyder at hvis vi
> ændrer vores interne database-skema, så går Power BI ikke i stykker, fordi Power
> BI læser fra vores JSON-API i stedet for direkte fra databasen. Vi kan ændre
> formen på data internt så længe JSON-API'et forbliver det samme.*

---

## 11) "Forklar jeres miljø-opdeling (dev/test/prod)"

> Vi styrer miljøet via miljøvariablen `SERVICE_ENV`, som kan være `development`,
> `test` eller `production`. Det er ikke bare et label — værdien styrer **konkret
> adfærd** i appen:
>
> | `SERVICE_ENV` | `SECRET_KEY` påkrævet? | `/sessions/seed-demo` |
> |---|---|---|
> | `development` | Nej — default-værdi tilladt | Tilladt |
> | `test` | Ja — appen nægter at starte uden | Tilladt |
> | `production` | Ja — appen nægter at starte uden | Blokeret (404) |
>
> Pointen er at de samme regler vi tester i CI (`test`) også gælder i `production` —
> så hvis vi har glemt at sætte `SECRET_KEY`, falder testen, ikke produktionen.

**Hvis censor spørger:** "Hvor i koden bestemmes det her?"

> *I `app.py` i `create_app`-funktionen. Vi læser `SERVICE_ENV` med
> `os.getenv("SERVICE_ENV", "development")`. Hvis det ikke er `development`,
> tjekker vi at `SECRET_KEY` er sat til noget andet end default-værdien — ellers
> `raise RuntimeError`. Og i begge seed-demo-routes returnerer vi 404 hvis
> `SERVICE_ENV == "production"`. Det er beskrevet i README under "Miljøer".*

**Hvis censor spørger:** "Hvorfor ikke bare bruge feature-flags i en database?"

> *For en MVP er det overkill. Miljøvariabler er den simpleste mekanisme der
> findes — de er en del af container-konfigurationen, ændres uden kode-deploy,
> og er let at forsvare. Et feature-flag-system kunne vi tilføje senere hvis vi
> får brug for at slå features til/fra uden at genstarte appen.*

---

## 12) "Forklar jeres rollback-strategi"

> Hver gang CD bygger et nyt Docker-image, publiceres det med **to tags**:
> `:latest` og `:<commit-sha>`. SHA-taggen er **uforanderlig** — det betyder at
> alle tidligere versioner stadig ligger i GitHub Container Registry.
>
> Hvis et nyt deploy viser sig at være fejlbehæftet, ruller vi tilbage ved at
> deploye den **forrige** SHA-tag i stedet for `:latest`. Det er beskrevet i
> README under "Rollback-strategi".
>
> For at gøre rollbacken **permanent** anbefaler vi `git revert` af den dårlige
> commit — så CD automatisk bygger en ny `:latest` med den gamle adfærd, og
> git-historikken eksplicit viser hvad der skete og hvorfor.
>
> **Databasen er bevidst uafhængig af container-versionen.** SQLite-filen ligger
> på værten/volume, så rollback af koden påvirker ikke data. Ved skema-ændringer
> i fremtidige versioner skal migrationer designes så de er bagudkompatible (nye
> kolonner skal være nullable eller have default), så en ældre container stadig
> kan læse tabellen efter rollback.

**Hvis censor spørger:** "Hvor lang tid tager rollback?"

> *Et minut eller to — det er kun `docker pull` af den gamle SHA-tag plus
> genstart af containeren. Det er hele pointen med immutable image-tags: ingen
> kompilering, ingen DB-migration, ingen pakke-install — bare kør en kendt god
> version igen.*

**Hvis censor spørger:** "Hvad hvis I har lavet en database-skema-ændring?"

> *Det er den sværeste case. Reglen er at skema-ændringer skal være
> **bagudkompatible**: tilføj nye kolonner som nullable eller med default,
> aldrig fjern kolonner i samme deploy som koden ændres. Hvis vi har brug for
> at fjerne en kolonne, gør vi det i to deploys: først ny kode der ikke
> bruger kolonnen, så et senere deploy der fjerner den. På den måde kan vi
> altid rulle tilbage uden at miste data.*

---

## 13) "Forklar deskriptive vs diagnostiske vs predictive analyser"

> Eksamen kræver alle tre lag — vi har dem som tre **separate domain services**
> i `services.py`:
>
> | Lag | Spørgsmål | Vores funktion |
> |---|---|---|
> | **Deskriptive** | *Hvad skete der?* | `calculate_kpis()` |
> | **Diagnostiske** | *Hvorfor skete det?* | `diagnose_incidents_by_charger()` |
> | **Predictive** | *Hvad vil ske?* | `forecast_load_next_hour()` |
>
> Alle tre vises på `/analytics`-siden, og diagnostik har sit eget API-endpoint
> `GET /api/analytics/diagnostics`.

**Forklar diagnostik i detaljer:**

> *Den deskriptive KPI siger fx "vi har 7 incidents totalt". Det fortæller os
> at noget er galt, men ikke **hvor**. Den diagnostiske funktion bryder
> incidents ned per charger — fx "CH-002 har 5, CH-003 har 2, de andre 0".
> Nu ved vi præcis hvor problemet er. Det er forskellen på at "se symptomer"
> og at "finde årsagen".*

**Hvis censor spørger:** "Hvordan ser SQL'en ud?"

> *Vi bruger en `LEFT JOIN` mellem `chargers` og `incidents` med en
> `GROUP BY chargers.id`. LEFT JOIN er vigtigt — det sikrer at chargers
> **uden** incidents stadig kommer med i resultatet (med count = 0). Hvis vi
> brugte en almindelig JOIN, ville sunde chargers helt forsvinde fra
> rapporten, og det ville være misvisende.*

**Hvis censor spørger:** "Er Power BI ikke nok til diagnostik?"

> *Power BI **kan** lave drill-down, men det kræver at man manuelt opsætter
> filtre og visualiseringer i BI-værktøjet. Ved at have det som en domain
> service i koden, har vi en **officiel** diagnostisk udregning der altid
> giver samme svar, kan testes, og kan tilgås via API af andre systemer
> (alarming, dashboards, månedsrapporter osv.).*

**Konkret kode at pege på** (`services.py` `diagnose_incidents_by_charger`):
```sql
SELECT c.id AS charger_id, c.location, c.status,
       COUNT(i.id) AS incident_count,
       MAX(i.created_at) AS last_incident_at,
       (SELECT description FROM incidents
        WHERE charger_id = c.id
        ORDER BY created_at DESC LIMIT 1) AS last_description
FROM chargers c
LEFT JOIN incidents i ON i.charger_id = c.id
GROUP BY c.id
ORDER BY incident_count DESC, c.id ASC
```

**Tests:** 2 nye tests i `test_services.py`
(`test_diagnose_incidents_returns_all_chargers_with_zero_when_no_incidents`,
`test_diagnose_incidents_attributes_counts_to_correct_charger`).

---

## 8. Idempotent `seed_demo_sessions` (duplikat-fix)

**Hvad var problemet?**
Knappen "Generate demo sessions" indsatte 9 nye rækker i `sessions`-tabellen
hver gang den blev trykket — selvom dataene var identiske. Det skete fordi:

1. `seed_demo_sessions` lavede `INSERT` uden at tjekke om en matchende session
   fandtes i forvejen.
2. `base_time = datetime.now().replace(minute=0, second=0, microsecond=0)`
   runder tiden til hele timer. To klik inden for samme time gav derfor
   **præcis samme `start_time`** for hver demo-charger → duplikater med
   forskellig `id` men ellers identisk indhold.

**Hvorfor er det vigtigt?**
Det er en klassisk **idempotency-mangel** — en operation skal kunne køres flere
gange uden at ændre resultatet ud over første kald. I DDD-termer mangler
`Session`-aggregatet en invariant: *"der må ikke findes to identiske demo-sessions
for samme charger på samme starttidspunkt"*.

**Hvordan løste vi det?**
I `services.py:seed_demo_sessions` tjekker vi nu før hver `INSERT`:

```python
existing = database.query_one(
    "SELECT id FROM sessions WHERE charger_id = ? AND contract_id = ? AND start_time = ?",
    (charger_id, DEMO_CONTRACT_ID, start_time.isoformat(timespec="seconds")),
    db_path=db_path,
)
if existing is not None:
    continue
```

Hvis en demo-session med samme (charger, kontrakt, start_time) findes →
spring INSERT over.

**Bevis:** Ny test `test_seed_demo_sessions_is_idempotent` i `test_services.py`
kalder `seed_demo_sessions` to gange og asserter at andet kald returnerer
`[]` (intet nyoprettet) og at databasen stadig kun har 9 sessions.

**Hvis censor spørger "kunne I ikke have brugt en UNIQUE constraint i databasen?"**
> *"Jo, det ville være den mest robuste løsning på lang sigt — en UNIQUE
> (charger_id, contract_id, start_time) i SQL ville håndhæve invariantet
> uafhængigt af kode-stien. Vi valgte application-side-checken her for at
> holde fix-omfanget minimalt og fordi vi ikke har et migrations-system
> opsat. Næste skridt ville være at lægge constraint'et i `database.py`'s
> schema-init."*

---

## 9. Samlet CI/CD-pipeline (`cicd.yml`)

**Hvad var problemet?**
Vi havde to separate workflows: `ci.yml` (test + audit + build) og `CD.yml`
(publish til GHCR). De kørte **uafhængigt** — CD blev udløst af push til main
uden at vente på CI. I praksis kunne et brudt build derfor blive publiceret
til container registry, hvis CI tilfældigvis fejlede samtidigt.

**Hvordan løste vi det?**
Filerne er samlet i én `.github/workflows/cicd.yml` med to jobs:

```yaml
jobs:
  ci:
    # test + pip-audit + docker build
  cd:
    needs: ci                    # <- CD kører kun hvis CI er grøn
    if: github.event_name == 'workflow_dispatch'
        || (github.event_name == 'push' && github.ref == 'refs/heads/main')
    # publish container til ghcr.io
```

**Hvad er det vigtigste at forstå?**
- `needs: ci` skaber en **hård afhængighed**: CD-jobbet starter slet ikke
  hvis ci-jobbet fejler. Det er vores **kvalitetsgate**.
- `if:`-betingelsen sikrer at CD kun kører på main eller manuel trigger
  (`workflow_dispatch`). PRs og feature-branches kører kun CI — ikke CD.
- CI-jobbet indeholder **ingen** publish-steps. CD-jobbet indeholder
  **ingen** test-steps. Adskillelsen er ren.

**Hvorfor er det bedre end to separate filer?**
1. **Synlighed:** Hele pipeline kan ses i ét billede på GitHub Actions.
2. **Garanti for rækkefølge:** `needs:` gør det umuligt at deploye uden
   først at have testet på samme commit.
3. **Mindre duplikation:** Vi har én `permissions:`-blok og én `on:`-trigger
   i stedet for to.

**Hvis censor spørger "hvad er forskellen på CI og CD?"**
> *"CI (Continuous Integration) er **kvalitetsporten** — den kører på alle
> commits og verificerer at koden bygger, består tests og ikke har kendte
> sårbarheder. CD (Continuous Delivery/Deployment) er **leveringen** — den
> tager et grønt build og udgiver det som et Docker-image i registry, klar
> til at blive deployet. Hos os: CI altid, CD kun på main, og CD kræver
> grøn CI via `needs:`."*

---

## 10. `.env.example` — dokumentation af miljøvariabler

**Hvad var problemet?**
Vores app læser konfiguration fra miljøvariabler (`SECRET_KEY`, `SERVICE_ENV`,
`DB_PATH`, `LOG_LEVEL`, `FLASK_DEBUG`), men der var **intet sted dokumenteret**
hvilke variabler der findes, eller hvad de skal indeholde. En ny udvikler
eller censor måtte grep'e i koden for at finde dem.

**Hvad er forskellen på `.env` og `.env.example`?**

| Fil | Indhold | Commits til Git? |
|---|---|---|
| `.env.example` | **Placeholder-værdier** (`SECRET_KEY=`, `SERVICE_ENV=development`) | **Ja** — skal kunne læses af alle |
| `.env` | **Rigtige værdier** (fx en produktion-`SECRET_KEY`) | **Nej** — gitignored |

Hvorfor er det vigtigt at adskille dem? **Fordi vores repo er public**.
Hvis vi committed en fil med rigtige hemmeligheder, ville alle der ser
GitHub kunne signere falske sessions, læse vores DB osv.

**Hvad er valgt i denne MVP?**
- `.env.example` ligger i `voltedge_mvp/.env.example` med safe defaults.
- `.env` er tilføjet til `.gitignore`.
- `docker-compose.yml` har **stadig** dev-defaults inline (admin/admin,
  default `SECRET_KEY`), så `docker compose up` virker direkte efter klon —
  ingen `.env` påkrævet for at komme i gang.
- `.env.example` er primært relevant ved deploy **udenfor** Compose,
  fx `docker run --env-file .env -e SERVICE_ENV=production ...`.

**Hvis censor spørger "hvorfor har I ikke flyttet hemmeligheder ud af compose?"**
> *"Det er en bevidst afgrænsning. Vi er et **development-MVP** der skal
> kunne klones og køres med ét `docker compose up`-kald. Hvis vi krævede
> `.env` for at starte, ville censor og medstuderende ramme en
> konfigurationsfejl før de overhovedet så koden køre. Vores app-kode
> har dog en `SECRET_KEY`-hard-fail som forhindrer at default-værdien
> kan bruges i `SERVICE_ENV=production` — så den **rigtige** beskyttelse
> ligger i app'en, ikke i compose-filen. `.env.example` dokumenterer
> hvad man skal sætte når man flytter ud af dev."*

**Hvis censor spørger "hvad er forskellen på `.env` og `.env.example`?"**
> *".env.example er en **template med placeholder-værdier** som er sikker
> at committe — den fortæller hvilke variabler der findes. `.env` er den
> **rigtige fil** med faktiske værdier, og den er gitignored så
> hemmeligheder ikke ender i et public repo. Workflowet er typisk:
> `cp .env.example .env` og udfyld."*

---

## 11. SECRET_KEY hard-fail — loophole-fix

**Hvad var problemet?**
Vi havde to placeholder-strenge der ikke matchede hinanden:

- `app.py:13`: `DEFAULT_DEV_SECRET_KEY = "dev-only-change-me"`
- `docker-compose.yml:11`: `SECRET_KEY: local-compose-change-before-production`

Den oprindelige hard-fail-check var:

```python
if not secret_key or secret_key == DEFAULT_DEV_SECRET_KEY:
    raise RuntimeError(...)
```

Den fangede *app-default'en* men IKKE *compose-default'en*. Resultat:
hvis nogen blot ændrede `SERVICE_ENV` til `production` i compose uden
også at overskrive `SECRET_KEY`, ville appen **starte** med en offentligt
kendt placeholder — fordi compose-strengen er forskellig fra app-konstanten.
Det er en klassisk "to defaults, kun én tjekkes"-fejl.

**Hvordan løste vi det?**
Vi indførte en frozen set af **alle** placeholder-strenge der findes i
repoet, og tjekker mod hele sættet:

```python
KNOWN_PLACEHOLDER_SECRET_KEYS = frozenset({
    DEFAULT_DEV_SECRET_KEY,
    "local-compose-change-before-production",
})

if not secret_key or secret_key in KNOWN_PLACEHOLDER_SECRET_KEYS:
    raise RuntimeError(...)
```

**Bevis:** Ny test `test_production_with_compose_placeholder_secret_key_raises`
i `test_app.py` sender præcis compose-strengen ind med `SERVICE_ENV=production`
og asserter `RuntimeError`. Den ville være failet før fixet.

**Hvis censor spørger "kunne I ikke bare have tjekket på et mønster (fx 'change' eller 'dev' i navnet)?"**
> *"Jo, det ville være mere robust mod fremtidige placeholder-strenge. Men
> det åbner også for falske positiver — en rigtig hemmelig nøgle kunne
> tilfældigvis indeholde 'dev' eller 'change'. Vi valgte den eksplicitte
> liste fordi den er **defensiv i kendte tilfælde** uden at gætte. Næste
> skridt ville være at lægge **alle** placeholder-strenge i én konstant
> der både importeres af tests og dokumenteres i `.env.example` — så der
> kun er ét sted at vedligeholde dem."*

**Hvis censor spørger "hvorfor er der overhovedet placeholder-strenge?"**
> *"Fordi vi vil have at `git clone && docker compose up` virker uden
> ekstra opsætning i development. Hvis vi havde tom `SECRET_KEY` i compose,
> ville Flask bruge en tilfældig session-nøgle, men det er sværere at
> forklare og test. Placeholder-strengen er en bevidst valgt 'her er
> jeg, og jeg er ikke en rigtig nøgle' — kombineret med hard-fail udenfor
> dev-miljøet."*

---

## Hvis du går i stå

Hvis du bliver spurgt om noget du ikke kan svare på, så sig hellere:

> *"Den specifikke detalje kan jeg ikke svare på i hovedet — men princippet bag er [X]. I
> rapporten/koden har vi løst det ved [Y]."*

Det er **meget bedre end at gætte**. Censor ved godt at I bruger AI til at generere koden,
og vil teste om I forstår *principperne* og *valgene* — ikke om I har lært syntaks udenad.
