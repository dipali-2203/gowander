# GoWander: Technical Documentation and Viva Preparation

> **Implementation-grounded review** · Repository inspected 20 November 2026. This describes code present in the workspace, not proposed features. Configurable values are defaults unless stated otherwise. No application source, configuration, environment file, or database was changed for this deliverable.

## How to use this document

“Implemented” means confirmed in the cited code path. “Approximation” means a heuristic is substituted for missing real-world information. “External” means a network provider can fail independently. “Not confirmed” means the inspected source does not establish the claim; do not present it as implemented. Paths are relative to repository root. Function names are the most stable code anchors.

## 1. System overview and architecture

### 1.1 Problem and objectives

GoWander helps a traveller turn a destination, dates, group size, budget, interests, pace, and constraints into a saved multi-day itinerary. It combines a locally persisted attraction catalog with heuristic scheduling and several alternative optimization methods. It estimates major trip-budget categories, visualizes attractions and lodging, assesses forecast-related itinerary concerns, and prepares user-approved revisions. Its AI assistant translates natural language into a constrained intent and delegates proposal generation to deterministic planner and validation services.

The engineering problem is constrained, preference-sensitive planning with incomplete data. The application therefore distinguishes unknown catalog/provider values from estimates, uses hard feasibility checks for core schedule limits, and labels travel and budget quantities as estimates where appropriate. It is not a booking platform, live fare aggregator, or safety-prediction service.

### 1.2 Major capabilities

| Capability | Main implementation | Actual behavior |
|---|---|---|
| Authentication and profiles | backend/app/api/auth.py, account APIs, frontend auth context | Password sessions, Google OAuth, account preferences, bookmarks and user-scoped trips. |
| Attraction catalog | backend/app/services/poi_catalog.py, backend/app/api/attractions.py | Database-backed attractions; OSM imports and a separately marked synthetic fallback may be available under configuration. |
| Itinerary planning | backend/app/api/trips.py, planner.py, multiday.py | Creates a trip, schedules multi-day activities and persists planning inputs and itinerary revisions. |
| Alternatives | nsga2.py, annealing.py | Generates single-day selection alternatives using separate search strategies. |
| Budget | budget.py, transportation_estimator.py | Seven-category complete-trip estimate plus legacy destination-only compatibility values. |
| Maps and lodging | Explore and Hotels route/components, Leaflet components | Uses coordinates returned by backend data; India overview map is a stylized destination map. |
| Weather replanning | weather.py, weather_risk.py, weather_replanning.py | Retrieves forecasts, assesses known exposure/conditions and presents a proposal for user decision. |
| AI assistant | assistant_service.py, gemini_provider.py, proposals.py | Extracts structured intent with Gemini and asks deterministic services to generate a pending proposal. |
| Sharing/export | shared-trip API and itinerary_pdf.py | Provides restricted shared itinerary views and PDF export. |

### 1.3 Architecture

~~~mermaid
flowchart LR
  U[Traveller] --> FE[React / TanStack Start frontend]
  FE -->|JSON and session cookie| API[FastAPI routers]
  API --> S[Domain services]
  S --> DB[(SQLAlchemy database)]
  S --> OSM[OSM catalog/import data]
  S -. optional .-> NOM[Nominatim geocoding]
  S -. optional .-> OSRM[OSRM routing]
  S --> WX[Open-Meteo forecast]
  S --> GM[Gemini structured intent]
  FE --> MAP[Leaflet and OSM tiles]
  FE --> CHART[Recharts]
~~~

The normal catalog lookup reads persisted records. It does not contact Overpass for every Explore or planner render. Map tile delivery is also a network dependency.

### 1.4 Frontend and backend

The frontend is React 19 with TypeScript, Vite, TanStack Start/Router file-based routes, Tailwind styling, and Radix-based UI wrappers. Routes are under frontend/src/routes/app; shared requests are in frontend/src/lib/api.ts; reusable travel components are under frontend/src/components/travel; Zustand state includes frontend/src/store/trip.ts. Recharts draws budget visualizations and Leaflet/react-leaflet draws geographic maps.

The backend is FastAPI, Pydantic, and SQLAlchemy. backend/app/main.py loads dotenv configuration, configures CORS and includes routers. Business rules primarily live in service modules, while route handlers perform HTTP orchestration, validation and access control.

### 1.5 Database and lifecycle

The configured SQLAlchemy URL defaults to a local SQLite file, sqlite:///./trip_optimizer.db. Base.metadata.create_all() creates missing tables. Centralized additive SQLite migrations inspect schema and add known missing columns for assistant proposals, auth/profile, attraction catalog and complete trip budget. No Alembic migration history was confirmed. The migration approach is additive; it does not intentionally drop/recreate application tables.

Important model groups in backend/app/models.py:

- User, AuthSession, password reset and OAuth-link challenge records.
- Trip: owner, origin/destination/dates/budget, preferences/options/planning inputs, optimization output, itinerary state, revision/completion and pending weather proposal data.
- Attraction, AttractionIngestionJob and Hotel.
- TripAccommodation, TripShare, DestinationBookmark and AssistantTripProposal.

Flexible JSON snapshots store preferences, planning inputs, optimization results and itinerary state. Relational foreign keys and ownership checks support relationships requiring enforcement.

### 1.6 Trip generation lifecycle

The frontend helper createAndOptimizeTrip in frontend/src/lib/api.ts, called from frontend/src/routes/app/planner.tsx, orchestrates several calls. The three optimization requests are alternatives, not a chain where one algorithm consumes the preceding algorithm's result.

~~~mermaid
sequenceDiagram
  actor User
  participant UI as Planner
  participant API as FastAPI
  participant Catalog
  participant DB as SQL database
  participant Opt as Optimization services
  User->>UI: Enter trip inputs
  UI->>API: Load attraction catalog and bookmarks
  API->>Catalog: Read destination records
  Catalog-->>UI: Candidates and provenance
  UI->>API: Preview transportation estimate
  UI->>API: Create trip
  API->>DB: Persist trip inputs
  UI->>API: Request multi-day optimization
  API->>Opt: Reserve fixed costs and plan days
  Opt-->>API: Itinerary and metrics
  API->>DB: Save plan and revision
  UI->>API: Request Pareto and annealing alternatives
  API->>Opt: Generate independent alternatives
  API-->>UI: Plan and alternatives
  UI-->>User: Display itinerary
~~~

The planner obtains catalog records and sends normalized attraction inputs to the optimizer. It does not depend on the LLM to contact an attraction provider.

### 1.7 Saved budget and weather-replanning data flows

estimate_saved_itinerary_budget in backend/app/services/budget.py rebuilds the current budget view from saved inputs and itinerary when applicable. It can calculate a presentation estimate in memory; this is not an expense ledger. Scheduled attractions are deduplicated, and daily fees derive from the same backend fee calculation.

~~~mermaid
sequenceDiagram
  actor User
  participant UI as Itinerary
  participant API as Trips API
  participant WX as Open-Meteo
  participant RP as Weather replanner
  participant DB as Database
  User->>UI: Check weather
  UI->>API: Request weather replanning
  API->>WX: Fetch relevant hourly forecast
  WX-->>API: Forecast values or unavailable fields
  API->>RP: Assess and build proposal
  RP-->>API: Advisory and original/proposed plan
  API->>DB: Persist pending proposal
  API-->>UI: Forecast and proposal
  User->>UI: Accept or reject
  UI->>API: Submit decision
  API->>DB: Revision-checked update or clear pending proposal
  API-->>UI: Current itinerary state
~~~

An assessment is not an automatic itinerary change. Acceptance/rejection is explicit and revision checked.

## 2. Data sources and processing

### 2.1 OpenStreetMap fundamentals

OpenStreetMap (OSM) is a collaboratively maintained geographic database. A **node** is a point with coordinates and tags. A **way** is an ordered sequence of node references representing a line or closed area. A **relation** is a collection of nodes, ways or relations with roles, useful for complex features.

OSM identity is element type plus numeric ID. GoWander IDs such as osm:node:123 or osm:way:456 preserve type; same numeric ID with a different type is a different object. Identity supports upsert and attribution but does not promise a feature will never be split, merged, deleted or retagged.

### 2.2 Attraction catalog pipeline

Relevant files: backend/app/data/catalog.py, backend/app/services/poi_catalog.py, backend/app/services/ingest_osm.py, backend/app/services/ingest_osm_pbf.py.

Configured destination boxes are Jaipur (approximately south 26.75, west 75.68, north 27.05, east 76.00) and Udaipur (24.45, 73.60, 24.72, 73.85). These rectangular filters are not official municipal boundaries.

normalize_category(tags) applies tag-priority rules for museum, worship/temple, park/garden/nature reserve, water/lake/viewpoint, cultural arts/cinema/gallery/artwork, historic/heritage, entertainment/zoo/theme park/aquarium, then other. Names prefer English-specific name tags where available. normalize_osm_element requires usable identity/name/coordinates/category, retains raw tags, source object URL, provider, OSM attribution and ODbL metadata. Missing entry fees, opening hours and visit duration remain unknown in source-specific fields.

The Overpass importer makes a bounded request for selected named tags and element centers/tags. Its endpoint is configurable with OSM_OVERPASS_URL; timeouts/retries are bounded. This is an administrative import path, not normal catalog retrieval.

The PBF importer reads a locally supplied Geofabrik extract with PyOsmium; it does not automatically download large files on startup. It processes named nodes and ways, applies city bounds and reuses common normalization/dedup/upsert logic. Closed way representative coordinates use a shoelace centroid; non-closed way coordinates use a vertex average. The current traversal does not establish comprehensive relation processing. OSM tags and licensing/source metadata are retained. Existing rows are upserted by provider identity rather than catalog reset.

~~~mermaid
flowchart LR
  PBF[Geofabrik regional PBF] --> READ[PyOsmium node and way reader]
  READ --> GEO[Bounds and representative coordinate]
  GEO --> TAG[Name and relevant tag filter]
  TAG --> NORM[Common category and row normalizer]
  NORM --> DEDUP[Duplicate resolution]
  DEDUP --> UPSERT[Provider identity upsert]
  UPSERT --> DB[(Attraction rows)]
  DB --> API[Database-backed catalog API]
  API --> PLAN[Optimizer input conversion]
  API --> EXPLORE[Explore cards and map]
~~~

A small SYNTHETIC_CATALOG exists separately in backend/app/data/catalog.py, controlled by environment/configuration. Do not confuse these fallback values with imported OSM. Catalog and planner deduplication do not delete source rows; planner candidate deduplication collapses likely duplicate representations within a planning request. OSM attribution and ODbL obligations apply when redistributing/rendering the data.

### 2.3 Other providers

| Provider | Data and usage | Caching/failure/limits |
|---|---|---|
| Nominatim | transportation_estimator.py geocodes place text to coordinates. | Configurable provider/base and user agent; in-process LRU up to 512, serial lock and at least one second between requests, ~5 sec timeout. Failures result in unavailable coordinates. |
| OSRM | routing.py can request road duration matrices; intercity estimator can request a road route. | Optional ROUTING_PROVIDER=osrm; public demo endpoint, bounded request size (matrix about 50 locations) and timeout. No production SLA or live traffic guarantee. |
| Open-Meteo | weather.py requests hourly precipitation probability/amount, temperature/apparent temperature, wind and weather code. | Asia/Kolkata, up to 16 days, batch up to 50 coordinates, ~30 minute in-process cache, bounded httpx timeouts. Missing values remain null. |
| Geofabrik | Regional OSM PBF download source used by offline importer. | Importer expects local file; source snapshot may age. ODbL attribution applies. |
| Gemini | Structured intent extraction for assistant, not itinerary generation by itself. | Configurable model/key; provider availability/latency/schema behavior are external. |
| Hotel records | ingest_osm_hotels.py accepts lodging records from PBF. | OSM tagged prices are not booking quotes, inventory, current availability or comprehensive hotel coverage. |

No live Google Places, train/bus/flight fare, or public-transit timetable provider was confirmed. Hotel ranking is an application recommendation score, not guest-star rating.

## 3. Optimization algorithms

### 3.1 Shared candidate model and feasibility

poi_catalog.to_optimizer_attraction maps catalog categories into planner categories, passes coordinates and source/known flags, and supplies schedule-compatible assumptions if duration/hours are missing. This lets the planner calculate but must not be confused with verified catalog values.

planner.generate_greedy_itinerary takes candidate attractions, start coordinate, travel matrix, time window, budget and preferences. It checks numeric validity, travel, waits, meal/rest breaks, visit duration, budget and closing time. Stop cap is at most five, with lower caps for slower pace. Confirmed activities are handled first by the multi-day service. Hard infeasibility rejects a candidate.

### 3.2 Greedy scoring

A greedy method repeatedly takes the locally best feasible choice. In planner.py, the score combines preference, interest fit, category diversity, priority, duration, known-risk/crowd-risk, cost and walking effort. A compact representation is:

$$
U_i=p_i(0.7+0.6f_i)\frac{1}{1+0.7c_i}(0.75+0.5q_i)
$$
$$
P_i=(1-r_t)r_i+(1-c_t)c_i^{risk}
+\frac{cost_i}{\max(B,1)}b_s+e_i(1-w_t)
$$
$$
S_i=\frac{U_i(1-P_i)}{\max(T_i,1)}+(q_i-0.5)0.01
$$

Here p is base preference score; f is weighted interest fit; c is count of already selected attractions in the category; q is priority; r is known risk proxy; r_t is risk tolerance; c_t crowd tolerance; c-risk is known crowd risk; B is remaining budget; b_s budget sensitivity; e effort; w_t walking tolerance; T required minutes. This is a compact expression of the code path, whose input clamping and helper details remain authoritative.

Candidates are deterministically tie-broken by stable ID. The planner prefers feasible candidates with wait ≤45 minutes; fallback candidates must be within 15 minutes of minimum wait. The algorithm does not guarantee a global optimum: an early local choice can block a better combination.

~~~text
selected = []
while under stop cap and candidates remain:
    evaluate each remaining candidate's travel, wait, visit, departure
    reject budget, daily-time or closing-time violations
    score feasible candidates
    choose best candidate with deterministic tie-break
    append schedule row and reduce remaining resources
~~~

With n candidates and k≤5 choice rounds, selection/scoring is approximately O(k n log n); matrix construction is O(n²) time and space. For fixed small k, matrix construction dominates. Extra selection state is O(n).

### 3.3 Multi-day greedy

multiday.generate_multiday_greedy handles days in sequence, preserves confirmed activities where possible, reports conflicts, allocates daily budgets and breaks, spreads flexible candidates over days, and removes selected IDs to avoid repeats. trips.py reserves fixed costs from attraction budget; it may re-run after local transport estimation using a more conservative reservation. This is a day-by-day heuristic, not global multi-day optimization.

### 3.4 NSGA-II

NSGA-II is an evolutionary multi-objective algorithm. GoWander uses pymoo for population operations and non-dominated survival; nsga2.py defines the binary problem and objective evaluation.

Each candidate chromosome is a binary vector of length n; 1 means select attraction i. Initial sampling is BinaryRandomSampling. Defaults in the inspected implementation are population 48, 60 generations, two-point crossover, bit-flip mutation, and seed 42.

AttractionSelectionProblem._evaluate minimizes four objectives:

$$
f_1(x)=\sum_i x_i cost_i
$$
$$
f_2(x)=\sum_{i:x_i=1}(visit_i+travel_{0i})
$$
$$
f_3(x)=RiskProxy(\{i:x_i=1\})
$$
$$
f_4(x)=-Utility(\{i:x_i=1\})
$$

The negative utility makes a maximization criterion usable in a minimization framework. Constraints are g1 = cost − budget ≤ 0 and g2 = time − availableMinutes ≤ 0. The time objective sums start-to-attraction matrix values; it does **not** compute travel between every consecutive selected attraction. It is a proxy, not tour length.

Solution a dominates b if a is no worse in all minimized objectives and strictly better in one. The Pareto front contains nondominated trade-offs. Pymoo supplies non-dominated sorting and crowding-distance survival; GoWander does not custom-implement these. Crowding distance favors points isolated in objective space, retaining front diversity. The project then decodes result.X/F, removes duplicate selected-ID signatures, sorts/selects a limited number of alternatives, and schedules each subset with the greedy decoder. Selection and visit order are separate.

Per individual, project evaluation is approximately O(n log n+nI) where I is active interests. With P=48 and G=60, nominal evaluations are about 2,880 plus initialization/library details. Standard non-dominated sorting is commonly O(MP²) per generation for M=4; exact runtime depends on pymoo version. Population storage is O(Pn), plus an O(n²) matrix.

### 3.5 Simulated annealing

annealing.generate_annealed_itinerary starts with all attractions selected, flips one random bit per neighbor, and computes a penalized utility. It uses a seeded random generator (default seed 42), 400 steps, and linear temperature:

$$
Score(x)=Utility(x)-\frac{\max(0,Cost(x)-B)}{\max(B,1)}
-\frac{\max(0,Duration(x)-T)}{\max(T,1)}
-(1-riskTolerance)\sum_{i:x_i=1}RiskProxy_i
$$

For score difference Δ = candidate − current, accept better/equal candidates; accept worse with probability exp(Δ/temperature). Temperature at step k is:

$$
T_k=\max(0.01,1-k/400).
$$

A worse move is more likely early when temperature is high and less likely later. The subset score penalizes overflow, then a greedy decoder enforces hard final schedule feasibility. The annealing objective does not fully model opening hours or route order, so subset score and decoded schedule can differ. Complexity is roughly O(400(n log n+nI)) plus decode; memory O(n) plus any O(n²) travel matrix.

### 3.6 Comparison

| Property | Multi-day greedy | NSGA-II | Simulated annealing |
|---|---|---|---|
| Search | Sequential local choice | Evolutionary population | Stochastic neighborhood |
| Output | Main saved day-wise plan | Nondominated single-day alternatives | Single-day subset alternative |
| Objective | Composite score under constraints | Cost, time proxy, risk, negative utility | Utility less overflow/risk penalties |
| Diversity | Category diminishing return | Pareto front and library crowding | Worse moves can escape local basin |
| Strength | Fast, understandable baseline | Explicit trade-offs | Explores nonlocal subsets |
| Limitation | No global guarantee | Travel objective is proxy | Subset objective differs from final decoder |
| Relationship | Primary multi-day plan | Independent API alternative | Independent API alternative |

The frontend invokes these as separate requests. Do not say NSGA-II or annealing refines the saved greedy plan unless a request explicitly passes that result.

## 4. Personalization

The planning Preferences schema has interest weights and numeric tolerances (risk, walking, crowd, budget sensitivity, pace) bounded to [0,1]. Account TravelPreferences separately stores readable onboarding choices such as interests/styles, budget, transport/accommodation, duration and pace. User profile preferences seed planner defaults; trip-specific planning inputs are persisted.

attraction_relevance.py maps interests to tags/categories: heritage/history, spiritual/worship, nature, adventure, photo, food, wellness, shopping, nightlife and others. This is deterministic rule matching, not ML. Interest fit is a weighted average:

$$
fit_i=\frac{\sum_j w_jm_{ij}}{\sum_jw_j}
$$

where w is selected interest weight and m is the code-defined match score. With no active weights, fit is neutral 0.5.

attraction_priority uses category bases and tag/verification cues, generic-name penalties and clipping to [0,1], with environment category overrides. It is not popularity, review rating or a trained model. frontend/src/lib/api.ts boostBookmarkedAttractions matches user bookmarks to candidate IDs and softly adjusts rank/priority; it does not require bookmarked places. Quote exact current numeric boost from that helper if challenged, since request paths have evolved.

preference_learning.apply_feedback uses small explicit changes: rating delta approximately ((rating−3)/2)×0.1, skipped −0.12, clamp [0,1], round to three decimals. This is rule-based adaptation, not model training.

Inputs are shared across methods, but usage differs: greedy has explicit crowd/walking/cost terms; NSGA-II and annealing use their own utility/risk formulas. Personalization is not mathematically identical across algorithms.

## 5. Routing and itinerary construction

### 5.1 Haversine and route estimates

routing.haversine_km and planner.distance_km use Earth radius R=6371 km:

$$
a=\sin^2(\Delta\phi/2)+\cos\phi_1\cos\phi_2\sin^2(\Delta\lambda/2),\quad
d=2R\arcsin(\sqrt a).
$$

Coordinates are converted to radians and a is clamped [0,1]. This is great-circle straight-line distance, not road distance.

routing.estimate_minutes defaults to a 1.35 distance detour multiplier, mode speed and fixed buffer:

| Mode | Assumed speed | Buffer |
|---|---:|---:|
| Walking | 3.8 + clamp(walking tolerance)×1.2 km/h | 3 min |
| Car | 22 km/h | 10 min |
| Taxi/auto/rental | 20 km/h | 10 min |
| Other/mixed | 16 km/h | 12 min |

Approximate formula: minutes = 60 × (1.35 × Haversine km) / speed + buffer. For 4 km straight-line by car: proxy distance 5.4 km, about 15 minutes moving plus 10 minutes buffer ≈25 minutes. These are assumptions. Optional OSRM can provide road-network driving durations but not live traffic guarantees or complete public transit.

### 5.2 Schedule construction

Origin/intercity coordinates and destination-local start coordinates are distinct. Configured destination centers can be start points. A travel matrix has N attractions plus start. Each day considers travel, opening wait, visit duration, meal/rest blocks and closing time. Unknown hours use an assumed window around 09:00–19:00 with known flag false; category duration defaults likewise remain assumptions.

The implementation is not a traveling-salesperson solver. Greedy chooses sequentially; NSGA-II uses a start-to-stop time proxy and then greedy ordering; annealing selects a subset and then greedy decodes. Local route estimates may omit return-to-hotel, transfers, waiting, parking, tolls and real traffic.

## 6. Complete-trip budget estimation

### 6.1 Categories, provenance and completeness

budget.py models seven categories: intercity outbound, intercity return, local transportation, accommodation, food, attraction fees and miscellaneous. Categories can be user-provided, source-backed/verified, estimated, partial or unavailable, with lower/representative/upper ranges where applicable.

Unknown is not zero. A fee is verified only when valid INR amount and pricing basis are available (per person or group). Missing required data keeps complete total incomplete rather than treating known subtotal as a complete trip. Feasibility for a complete estimate uses the conservative upper bound: high total ≤ user budget. The service may show partial/known subtotals; that is not actual spending. Legacy destination-only totals remain for compatibility and are not door-to-door totals if intercity legs are missing.

### 6.2 Intercity transportation

transportation_estimator.py geocodes origin/destination if necessary and gets straight-line air distance. With OSRM, road route distance may be queried; otherwise road proxy is air distance ×1.3. Current configured shapes include:

| Mode | Approximate formula | Basis |
|---|---|---|
| Train | Rail distance proxy air×1.2; ~₹0.8–₹2.5 passenger-km, minimum ~₹100/person | Per person, multiplied by travellers |
| Bus | Road proxy; ~₹1.2–₹2.2 passenger-km, minimum ~₹100 | Per person, multiplied by travellers |
| Flight | ~₹800–₹1,800 base plus ₹5–₹10 per air-km | Per person, multiplied by travellers |
| Private car | Road distance × ₹12–₹18/km plus toll allowance ₹0–₹800 | Per vehicle, not multiplied by travellers |

These are indicative configurable rates, not quotes. They do not include live schedules, inventory, dates/demand, booking class or complete fees. Outbound and return are separate categories. Without selected mode, the system should not invent a blended estimate; mode-specific provisional ranges can be exposed separately. User values are group totals and override calculated estimates; bounds and unusual/zero confirmation rules are schema/UI validated.

### 6.3 Local transport

local_transport_cost sums straight-line/proxy distances across scheduled stops, then applies mode rates. Illustrative defaults: public transport ₹18/km/person, auto ₹25/km/vehicle, private car ₹12/km/vehicle, rental ₹18/km/vehicle, mixed ₹18/km/vehicle, walking ₹0. Environment variables TRIP_LOCAL_FARE_INR_PER_KM_* override rates. Lower/high multipliers are about .75 and 1.35. Passenger modes multiply by group size; vehicles do not.

This is not a complete daily trip loop. Return-to-lodging legs, transfers, hotel transfers, parking and tolls may be omitted. Intercity category is separate, avoiding direct addition of the same intercity fare into local transport.

### 6.4 Accommodation and food

Accommodation uses a usable selected INR nightly price if present, otherwise tier defaults (budget ₹1,800, standard ₹3,800, premium ₹7,800, luxury ₹15,000 per room/night in inspected configuration). Rooms = ceil(travellers/2); nights = (end date − start date).days, thus six trip days means five nights. A luxury-level factor adjusts fallback, with approximate lower .75× and upper 1.4×. A tagged listing price is not a bookable quote.

Food default is TRIP_MEAL_ESTIMATE_INR_PER_PERSON_PER_DAY, ₹600. Representative = travellers × trip days × daily rate; lower .70× and upper 1.50×. This is an allowance, not menu data, and it is decoupled from accommodation tier.

### 6.5 Attraction fees

_fee_range_for_attraction applies verified valid INR fee first, specific estimate second, eligible category estimate third. Current budget_estimates.json allows positive category assumptions only for categories with defensible admission assumptions, such as historical/history/museum and entertainment. Values have lower/representative/upper per-person amounts. Explicit fee=no produces provenance-labeled estimated zero; ambiguous categories remain unavailable. Per-person prices multiply by travellers; group prices do not.

Identical scheduled OSM IDs are charged once. Daily values come from the same calculation. Optimizer numeric cost placeholders are not fee evidence. Dashboard reporting distinguishes original catalog fee absence, successfully estimated fees and unresolved fees.

### 6.6 Miscellaneous and total formula

Automatic miscellaneous contingency uses configured 5%, 10%, 15% rates against other categories, excluding itself to prevent circularity. Manual amount (including intentional zero) and disabled mode are separate. Incomplete base categories may make automatic contingency partial. It may overlap with separately entered incidentals, which should be disclosed.

For complete category ranges c:

$$
Total_{low}=\sum_c c_{low},\quad Total_{rep}=\sum_c c_{rep},\quad Total_{high}=\sum_c c_{high}.
$$

If any required category is unavailable, the service does not call known subtotal the complete total. When complete:

$$
WithinBudget=(Total_{high}\leq UserBudget).
$$

The result is a forecast estimate, not proof of spend.

## 7. Weather and dynamic replanning

weather.py fetches hourly Open-Meteo values. weather_risk.assess_weather_risk evaluates provider values against configurable thresholds: defaults include rain probability 60%, rain amount 2.5 mm, heat 38°C, cold 5°C, wind 50 km/h, thunder code ≥95. Exposure comes from attraction category/tags; indoor attractions receive reduced weather exposure (about ×0.35). forecast_at selects a nearby hour only within roughly 90 minutes. Partial fields remain unknown.

calculate_attraction_risk uses:

$$
R=1-(1-r_w)(1-r_c)(1-r_a).
$$

This independence-style formula is not calibrated probability of harm. optimizer_risk_proxy uses known dimensions for arithmetic and can neutralize unknown dimensions internally for compatibility; known flags/status remain partial/unavailable. Low risk is not a guarantee.

weather_replanning.build_weather_proposal considers scheduled future outdoor activities over WEATHER_REPLAN_RISK_THRESHOLD (default about .65), protects completed IDs and searches unplanned indoor alternatives with forecast, time, opening, travel and budget feasibility. It ranks alternatives by added travel/weather/preference. No match means no proposed replacement. Accept checks ownership and base revision, saves bounded history and applies changes. Reject clears pending proposal without changing the itinerary. Weather assessment can be persisted for future replanning but traveler-facing daily activity rows should remain focused on schedule/activity; forecast belongs in its panel.

Manual what-if disruptions in disruptions.py model explicit closure, traffic multiplier or risk adjustments. These are scenarios, not observations.

## 8. Risk and constraints

**Hard constraints:** numeric input validation; attraction budget; schedule duration and closing time; confirmed/completed activity preservation; trip ownership; proposal status and revision checks.

**Soft constraints:** interest fit, pace, category diversity, risk tolerance, crowd tolerance, walking effort, budget sensitivity. Their exact influence differs by algorithm.

Risk sources are distinct: forecast-derived weather, scenario-derived what-if values, verified observations only where explicit verified metadata exists, and unknown where there is no evidence. OSM imported numeric zeros with known=false are not verified zero risk. Crowd/availability observations are generally not live provider data.

risk.py includes seeded Monte Carlo simulation for fully known risk inputs, with scenario counts constrained to about 100–100,000. This simulates outcomes conditional on supplied probabilities; it is not an external predictive model. Incomplete dimensions prevent a confidently complete result.

## 9. AI assistant

gemini_provider.py uses google-genai async client and a configurable GEMINI_MODEL (default observed in source gemini-3.8-flash) with key from GEMINI_API_KEY. The key must never be logged. Requests use structured JSON output, bounded timeout/retry and sanitized diagnostics.

assistant_service.py builds bounded server-side context and validates model output with Pydantic. Allowed actions are constrained (pace, budget, duration, preferences, attractions and conversational clarification as implemented). The model parses intent; it does not directly execute SQL.

proposals.py copies planning inputs, applies validated changes and invokes deterministic planner/replanning logic. AssistantTripProposal persists original/proposed snapshots, changes, warnings, status, base revision and expiry. User explicitly accepts/rejects. Acceptance checks user ownership, status/expiry and trip revision. This treats LLM output as untrusted input. Structured output improves format, not factual correctness. Provider latency/model availability remain external. Frontend receives sanitized errors, not prompt/context/credentials.

## 10. Backend engineering and APIs

### 10.1 API families

backend/app/api/trips.py includes transportation estimate preview; trip list/create/read/update/delete; duplicate; sharing; PDF export; feedback; risk/conditions; single-day and multi-day optimize; regenerate; Pareto; annealing; scenario replan; completion state; weather replan/accept/reject; saved optimize and replan.

Other routers cover attractions/catalog/admin ingestion, auth/account/preferences/bookmarks, hotel recommendations/accommodation selection, assistant chat/proposal decisions and restricted shared itinerary views. Router prefixes are composed in main.py; check route decorators for exact paths during a live API demonstration.

Pydantic schemas validate request fields, ranges and enums. Access dependencies enforce owner/share access. SQLAlchemy sessions persist state; errors map to HTTP responses. Pending proposal acceptance uses state/revision checks to avoid stale writes.

### 10.2 Authentication, data integrity and export

Password hashing in auth.py uses scrypt (n=2^14, r=8, p=1, 64-byte derived key), random salt and constant-time comparison. Session token is opaque; server stores a digest and expiration, with HttpOnly cookie controls. Google OAuth validates state, nonce, PKCE and ID token. Reset tokens are hashed, expire and are one-use. Secure/SameSite cookie behavior depends on configuration/environment; do not infer production deployment hardening from local defaults.

User IDs scope trips and bookmarks. JSON itinerary snapshots aid flexibility but limit relational querying. Revision history is bounded. Shared serializers expose a restricted public view; share links are sensitive and revocable. itinerary_pdf.py renders a server PDF. Exports must retain estimate/incomplete labels.

## 11. Frontend and visualization

TanStack file routes cover dashboard, Explore, Planner, Itinerary, Saved Trips, Budget, Hotels, Profile/Settings, onboarding and assistant. frontend/src/lib/api.ts centralizes requests, session credentials and error parsing. Zustand holds cross-route trip state; persisted backend records remain source of truth.

Explore reads the DB catalog and renders cards/Leaflet markers with actual coordinates, selection sync, OSM attribution and source links. IndiaMap is a stylized SVG destination overview, not a POI map. Hotels map components use actual API hotel/itinerary coordinates where valid, distinct marker styles and selected-hotel state.

Budget uses Recharts and frontend/src/lib/budget-dashboard.mjs for category/daily aggregation grouped by trip. It shows estimates and missing-data status; it does not track spending. Itinerary displays schedule/completion/revision state and a separate weather panel. Hotels cards show recommendation rank/score, not a guest rating; distance is Haversine proximity unless routing is configured.

## 12. Formula and complexity reference

| Formula | Meaning and small example |
|---|---|
| Haversine: d=2R asin(sqrt(sin²(Δφ/2)+cosφ1 cosφ2 sin²(Δλ/2))), R=6371 km | Great-circle distance between two coordinates. |
| Local proxy: minutes≈60×(1.35d)/speed+buffer | At d=4 km, car proxy 5.4 km at 22 km/h +10 min ≈25 min. |
| Fit: Σ(wj mj)/Σwj; default .5 if no active interests | Weighted tag/category match. |
| Diversity: 1/(1+.7×categoryCount) | Repeat category utility declines. |
| Greedy utility: p(0.7+0.6fit)×diversity×(0.75+0.5priority) | Preference adjusted for fit, diversity and priority. |
| Annealing: accept worse with exp(Δ/T) | Δ=−.1,T=.5 gives ≈.819; T=.05 gives ≈.135. |
| Cooling: max(.01,1−step/400) | Linear cooling with floor. |
| Combined risk: 1−Π(1−rj) | .2 and .3 combine to .44 under independence assumption. |
| Food: people×days×daily rate | 2×6×₹600 = ₹7,200 representative. |
| Rooms: ceil(people/2) | Three travellers require two rooms under assumed occupancy. |
| Hotel: nightly×nights×rooms×factor | Six trip days = five nights. |
| Misc: percentage×other category base | 10% of ₹50,000 = ₹5,000; excludes itself. |
| Total: sum category range only when complete | Missing category keeps total incomplete. |
| Feasibility: upper estimate ≤ user budget | Conservative range check. |

Attraction scoring and NSGA objective equations are in §3. Transportation rates and bases are in §6. Complexity estimates:

| Component | Time | Space | Assumption |
|---|---:|---:|---|
| One Haversine pair | O(1) | O(1) | Constant arithmetic. |
| Pairwise matrix | O(n²) | O(n²) | Attractions plus start. |
| Greedy selection | O(k n log n), k≤5 | O(n) plus matrix | Matrix also O(n²). |
| Candidate dedupe | O(n²) | O(n) | Pairwise comparison. |
| NSGA-II | Evaluation plus typical O(MP²) sorting/generation | O(Pn)+matrix | M=4,P=48,G=60 defaults; library-specific. |
| Annealing | O(S(n log n+nI))+decode | O(n)+matrix | S=400 steps. |
| Budget aggregation | O(A+C) | O(A) | A unique scheduled attractions, C=7 categories. |

## 13. Limitations and future improvements

1. OSM coverage/freshness varies; city bounding boxes are rectangular, not official boundaries.
2. Current PBF traversal handles named nodes/ways; comprehensive relation support is not confirmed.
3. Fees, hours and durations are frequently missing; configured category estimates are not verified prices.
4. Synthetic fallback must remain clearly distinguished from imported OSM.
5. Haversine detour/speed estimates are not road routes; public OSRM demo has no production SLA and no comprehensive transit.
6. Intercity rates are illustrative; no live fare feed, date demand, operator, class or booking availability.
7. Local sum may omit return legs, lodging transfers, transfer waits, tolls and parking.
8. OSM hotel tags do not establish current booking availability or rates.
9. Weather has finite horizon, field gaps, model uncertainty and threshold/exposure assumptions.
10. Crowd/availability risks are generally unknown; numeric proxies may neutralize unknown internally but status must stay partial.
11. Greedy can miss global combinations; NSGA travel is a proxy; annealing score differs from decoder; alternatives are single-day.
12. Pairwise matrices use quadratic memory; larger datasets may need sparse/on-demand routing.
13. Gemini can fail, hallucinate intent or return invalid structure; validation reduces but cannot eliminate errors.
14. SQLite is suited to local/small deployments; concurrent production writes may call for managed SQL and migration tooling.
15. Seeds improve repeatability but dependency version, data and floating-point changes can alter outputs.
16. Share links and trip details are sensitive; data minimization and revocation matter.

Future work could include relation-aware geometry, migration history, production routing/fare providers, calibrated city price samples, confidence intervals, route-aware sequence optimization, provider observability and estimate-error evaluation.

## 14. Viva question bank

Answers are implementation-grounded; follow-up prompts are included to rehearse deeper discussion.

### General architecture

**1. What problem does GoWander solve?**  
It turns traveller and destination inputs into a feasible personalized saved itinerary and exposes budget/risk context. It is not a booking or live-price system.  
*Follow-up:* Main output? A persisted day-wise itinerary plus estimates and alternatives.

**2. Describe the architecture.**  
React/TanStack frontend calls FastAPI JSON routes; routers validate/authenticate and invoke services; SQLAlchemy persists users, trips, catalog, lodging and proposals; optional providers supply geocoding, routing, weather and LLM intent.  
*Follow-up:* Where do core business rules live? Primarily backend services.

**3. Why separate routes from services?**  
Routes own HTTP concerns; services hold reusable domain logic. The same deterministic planner can serve regular and assistant proposal paths.  
*Follow-up:* Is separation perfect? No; route handlers still orchestrate multiple services.

**4. Walk through trip creation.**  
Load catalog/bookmarks, preview transport, create trip, request multi-day greedy, then request Pareto and annealing alternatives.  
*Follow-up:* Are optimizers sequential? No, alternatives are independent calls.

**5. Why SQLite?**  
Low-friction local relational persistence via SQLAlchemy. It is not necessarily suitable for high concurrent production load.  
*Follow-up:* Scale path? Managed PostgreSQL, migration history and concurrency testing.

### OSM and data

**6. What does an OSM ID identify?**  
Element type plus numeric ID; node and way IDs are distinct identities.  
*Follow-up:* Permanent? No; upstream features can be edited/split/deleted.

**7. Node vs way?**  
Node is point; way is ordered node sequence representing line/area. GoWander derives representative way coordinates.  
*Follow-up:* Is centroid a visitor entrance? No.

**8. What is Geofabrik's role?**  
Distributes regional OSM extracts. A local PBF importer reads them; app startup does not fetch large files.  
*Follow-up:* License? ODbL attribution/share-alike obligations.

**9. How are attractions classified?**  
normalize_category applies rules over tags, then falls back to other. It is not ML.  
*Follow-up:* What if tags are ambiguous? A heuristic category or excluded/other record, depending on normalization.

**10. How are duplicates handled?**  
Provider identity supports upsert; same-name/nearby heuristics normalize duplicates; planner has separate request-level candidate dedupe.  
*Follow-up:* Does dedupe delete catalog records? No.

**11. What are OSM limitations?**  
Missing, stale or inconsistent tags; not an authoritative source for prices, hours or availability.  
*Follow-up:* Mitigation? Preserve nullable source fields, provenance, and estimate labels.

**12. Is synthetic catalog OSM?**  
No. catalog.py has a separate configuration-controlled fallback dataset.  
*Follow-up:* Why distinguish? Different provenance and confidence.

### Greedy algorithm

**13. Explain greedy.**  
Repeatedly select the best local feasible candidate. Fast and understandable but not globally optimal.  
*Follow-up:* Failure case? A locally good early stop blocks a better later combination.

**14. What affects its score?**  
Interest fit, preference, category diversity, priority, duration, known risk/crowd, cost and walking effort.  
*Follow-up:* Are all constraints penalties? No; budget/time/closing violations are hard rejection.

**15. How is feasibility checked?**  
Calculate travel, wait, visit and departure, then reject candidates outside budget/time/closing limits.  
*Follow-up:* Unknown fees? Keep knowledge flags; budget logic remains separate from optimizer placeholder.

**16. Does it guarantee optimality?**  
No; no exhaustive search or backtracking.  
*Follow-up:* Why use it? Fast baseline and scheduling decoder.

**17. Complexity?**  
Pairwise matrix O(n²); up to five greedy rounds about O(k n log n).  
*Follow-up:* Scale? Prune/cache and avoid dense matrices for large n.

### NSGA-II

**18. Why multiple objectives?**  
Cost, time, risk and utility conflict; Pareto alternatives expose trade-offs instead of hiding them in one weighted sum.  
*Follow-up:* Who selects? Traveller.

**19. Chromosome?**  
Binary vector, one bit per attraction.  
*Follow-up:* Does it encode order? No, only subset.

**20. Objectives?**  
Minimize cost, visit plus start-to-stop time proxy, risk, and negative utility; budget/time are constraints.  
*Follow-up:* Why negative utility? Framework minimizes objectives.

**21. Pareto dominance?**  
No worse in all objectives and strictly better in at least one.  
*Follow-up:* Is there one best? Not without preference among trade-offs.

**22. Pareto front?**  
Nondominated candidate set.  
*Follow-up:* Does GoWander show all? It selects/deduplicates a limited number.

**23. Crowding distance?**  
Diversity metric favoring isolated points; pymoo supplies it here.  
*Follow-up:* Custom implementation? Not confirmed; code uses library mechanism.

**24. Operators?**  
Binary random sampling, two-point crossover, bit-flip mutation, seeded pymoo run.  
*Follow-up:* Meaning? Generate, recombine, and mutate selected subsets.

**25. Stopping criteria?**  
Fixed 60 generations in inspected configuration.  
*Follow-up:* Does fixed stop prove convergence? No.

**26. Is its travel objective a tour?**  
No, it sums start-to-attraction entries; greedy decoder orders the chosen set.  
*Follow-up:* Consequence? Selection proxy can differ from actual sequence cost.

**27. Complexity?**  
Evaluation depends on n/interests; typical nondominated sorting O(MP²), M=4, P=48, G=60. Library version affects details.  
*Follow-up:* Approx evaluations? About 2,880 plus initialization details.

### Simulated annealing

**28. Why annealing?**  
Worse moves early can escape local basins.  
*Follow-up:* Global guarantee? No, finite heuristic search.

**29. Neighbor operation?**  
Flip one random selection bit.  
*Follow-up:* Is it a swap? Not as a single operation.

**30. Acceptance probability?**  
For Δ<0, exp(Δ/T); otherwise accept.  
*Follow-up:* Temperature effect? High T accepts worse moves more often.

**31. Cooling schedule?**  
max(.01, 1−step/400) across 400 steps.  
*Follow-up:* Why floor? Avoid zero temperature/division issues.

**32. How preserve feasibility?**  
Penalties guide subset search; final greedy decoder enforces schedule constraints.  
*Follow-up:* Same objective? Not fully; this is a limitation.

### Personalization

**33. Is recommendation ML?**  
No; source confirms deterministic rules/weighted heuristics, not a learned model.  
*Follow-up:* Why avoid “AI recommendations”? Accuracy.

**34. Interest fit?**  
Weighted average of code-defined attraction-interest matches; neutral .5 with no active weights.  
*Follow-up:* Missing tags? No fabricated match.

**35. Bookmark effect?**  
Soft boost to matching attraction IDs, not mandatory inclusion.  
*Follow-up:* User-specific? Yes.

**36. Are preferences identical across optimizers?**  
No; each objective uses some shared signals but not every term identically.  
*Follow-up:* Future improvement? Common objective definitions or explicit documented differences.

### Routing and geography

**37. Explain Haversine.**  
Great-circle distance from lat/lon using Earth radius 6371 km.  
*Follow-up:* Road distance? No.

**38. Always OSRM?**  
No, default Haversine; OSRM is optional and externally limited.  
*Follow-up:* Traffic? No live guarantee.

**39. Local travel estimate?**  
Distance proxy × detour factor, divided by assumed mode speed, plus buffer.  
*Follow-up:* Omissions? Traffic, transfers, parking, lodging legs.

**40. Is this TSP?**  
No. Greedy scheduling and subset alternatives do not solve full tour optimization.  
*Follow-up:* Improvement? Route-aware ordering after selection.

### Budget

**41. Seven categories?**  
Outbound, return, local, accommodation, food, attraction fees, miscellaneous.  
*Follow-up:* Why split legs? They can have different status/input.

**42. Meaning of partial?**  
Some amount exists but a required portion remains unknown; not zero and not complete.  
*Follow-up:* Can estimates fill gaps? Yes, only where rules are defensible.

**43. Fee precedence?**  
Verified valid INR, attraction-specific estimate, category estimate; otherwise unavailable. Deduplicate OSM IDs.  
*Follow-up:* Is optimizer zero a free ticket? No.

**44. Why upper-range feasibility?**  
If upper bound fits, it is a conservative estimate check.  
*Follow-up:* Guarantee actual spend? No.

**45. Food formula?**  
₹600/person/day default × travellers × days, range .70–1.50×.  
*Follow-up:* Live data? No.

**46. Accommodation formula?**  
Selected usable nightly price or tier fallback × nights × ceil(travellers/2); six days means five nights.  
*Follow-up:* Booking quote? No.

**47. Misc formula?**  
Configured contingency on other categories, excluding itself; manual and disabled modes remain distinct.  
*Follow-up:* Circularity? Exclusion prevents it.

**48. Budget vs spending?**  
Planning estimate, not transaction tracking.  
*Follow-up:* Why ranges? Communicate uncertainty.

### Weather and risk

**49. How is weather used?**  
Open-Meteo hourly fields matched near activity time, threshold/exposure rules create assessments.  
*Follow-up:* Auto-change itinerary? No, proposal only.

**50. Missing forecast?**  
Unknown/partial, never substituted with zero or suitability.  
*Follow-up:* Can known days still display? Yes, with partial coverage label.

**51. Risk formula?**  
1−product(1−dimension risk), an independence assumption, not calibrated harm probability.  
*Follow-up:* Unknown dimension? Overall verified status withheld.

**52. Completed activity protection?**  
IDs are protected and proposal acceptance checks base revision.  
*Follow-up:* Stale proposal? Revision mismatch blocks apply.

**53. What-if scenario meaning?**  
Explicit scenario transformation in disruptions.py; not live observation.  
*Follow-up:* Is the full Demo Scenario Mode present? Its proposed service/datasets were not confirmed in inspected source; do not claim it.

### AI assistant

**54. What does Gemini do?**  
Extracts structured intent; backend validates and plans.  
*Follow-up:* Direct database access? No.

**55. Why validate LLM output?**  
Schema and allowlist constrain malformed or unsupported actions; business rules remain deterministic.  
*Follow-up:* Structured output guarantees truth? No.

**56. How are changes applied?**  
Persisted pending proposal, explicit accept/reject, ownership/status/expiry/revision checks.  
*Follow-up:* Provider failure? Sanitized error and bounded retry behavior.

### Database and engineering

**57. Why store snapshots?**  
Support durable saved itinerary, revision history, completion state, share and export.  
*Follow-up:* JSON tradeoff? Flexible but harder to query/validate relationally.

**58. Schema migrations?**  
create_all plus centralized additive SQLite migration functions.  
*Follow-up:* Alembic? Not confirmed.

**59. How isolate users?**  
Authenticated user IDs scope records; dependencies check ownership or authorized sharing.  
*Follow-up:* Key tests? Cross-user reads/writes and share serializer allowlist.

**60. Main limitations?**  
Missing catalog data, approximate routes/fares, no live lodging inventory, unknown crowd/availability and external provider outages.  
*Follow-up:* Most impactful? Route/budget uncertainty is highly visible.

### Challenging questions

**61. Why three optimizers?**  
They demonstrate fast baseline, Pareto trade-offs and stochastic subset exploration; this is not proof all are needed in production.  
*Follow-up:* Primary result? Multi-day greedy.

**62. Why not set missing risk to zero?**  
Zero means measured/known absence; missing means no evidence. Compatibility proxies may neutralize unknown internally, but status stays incomplete.  
*Follow-up:* Is internal neutralization present? Yes in some optimizer proxy paths.

**63. Does forecast mean safe?**  
No; forecast thresholds and exposure assumptions are decision support only.  
*Follow-up:* Safeguard? Disclose coverage and require user acceptance.

**64. Why Pareto instead of weighted sum?**  
It exposes nondominated tradeoffs without choosing one fixed weight set, but costs more and needs a user choice.  
*Follow-up:* Is current time objective exact? No, it is a start-to-stop proxy.

**65. How validate budget realism?**  
Compare estimates to dated local quotes/receipts and measure error; current configurable rates are not live prices.  
*Follow-up:* What metrics? Absolute/percentage error by mode, party size and tier.

**66. What if providers fail?**  
Bounded failure handling returns unavailable or uses configured approximation; public endpoints have no guaranteed SLA.  
*Follow-up:* Are fallbacks always safe? Only if clearly labeled.

**67. Impossible LLM change?**  
Pydantic and deterministic planner validation reject or warn; user sees proposal rather than auto-apply.  
*Follow-up:* Is LLM trusted? No.

**68. How prove reproducibility?**  
Fix inputs, data/config versions and seed, compare normalized results; dependency/platform changes can still affect output.  
*Follow-up:* Is seed alone enough? No.

**69. Technical contribution?**  
Integration of constrained planning, provenance-aware data/budget, alternative search methods and revision-controlled replanning—not a new optimization theorem.  
*Follow-up:* Novelty? System integration and user-facing uncertainty handling.

**70. What improve first?**  
Validate route/fare assumptions and regional data, then improve route-aware optimization and quantify estimation errors.  
*Follow-up:* Why not more AI? Better data and feasibility improve trust more directly.

## 15. Presentation-ready explanations

### 15.1 Two-minute technical overview

“GoWander is a full-stack trip-planning application. A traveller enters destination, dates, group size, budget and preferences in a React interface. The frontend calls a FastAPI backend, which loads normalized attractions from SQLAlchemy storage and creates a multi-day itinerary with a greedy scheduler. It checks time windows, opening-hour assumptions, travel and budget allocation while ranking by interests, priority and diversity. The app also offers independent NSGA-II and simulated-annealing alternatives so travellers can compare trade-offs.

“The system combines OSM attractions and lodging with optional geocoding/routing, Open-Meteo forecasts and Gemini structured intent extraction. It separates source data from assumptions: unknown fees and risk are not verified zero. A seven-category budget estimator exposes ranges and completeness. Weather and AI changes are proposals requiring explicit acceptance, and revisions are checked against saved state. It is not a booking platform; many route and price values remain estimates rather than live quotes.”

### 15.2 Five-minute optimization explanation

“The planner converts catalog rows into optimizer inputs, preserving source and known flags. Missing schedule values can receive explicit assumptions so a schedule is possible without pretending source data is complete. A travel matrix uses Haversine plus mode speed/buffer defaults unless optional OSRM is configured.

“The primary multi-day schedule uses greedy construction. On each day it first protects confirmed activities, then evaluates feasible remaining attractions. It calculates travel, wait, visit and departure, rejecting candidates outside budget, time or closing constraints. Its score combines preference and interest fit, category diversity, priority, duration, cost, effort and known risk. It is explainable and quick, but local choice means no global optimality guarantee.

“NSGA-II encodes a subset as a binary chromosome. It minimizes cost, visit-plus-start-to-stop time proxy, risk and negative utility, with budget/time constraints. Pymoo handles evolutionary mechanics, nondominated sorting and diversity; GoWander defines objectives and decoding. Pareto solutions expose trade-offs. Its travel objective is not a tour length: it sums start-to-attraction entries and uses greedy scheduling afterward.

“Annealing explores subsets by flipping one bit. It scores utility with budget/time-overflow and risk penalties and can accept worse moves with exp(Δ/T). Temperature decreases linearly for 400 steps. The final set is greedily scheduled with hard checks. It can explore different combinations, though its selection score and final decoder are not identical.

“These are separate alternatives: multi-day greedy is the primary saved plan, while NSGA-II and annealing provide single-day alternatives. All depend on imperfect coordinates, durations, fees and risk data, so outputs need uncertainty labels.”

### 15.3 Five-minute data-pipeline explanation

“Attraction data enters through administrative Overpass or controlled local PBF ingestion. A Geofabrik PBF is read by PyOsmium. The importer processes relevant named nodes and ways, applies Jaipur/Udaipur bounds, derives representative coordinates, and passes tags into shared normalization. Normalization creates type-plus-ID identities, chooses names, classifies tags, retains source links/raw tags and ODbL attribution, and leaves missing fee/hours unknown.

“Rows are upserted by provider identity; the database is not reset. Normal frontend catalog requests read stored rows rather than Overpass. A small synthetic fallback exists separately and must not be called OSM.

“The planner adapts catalog records into optimizer fields. It maps categories and may supply schedule assumptions where numeric inputs are required, while knowledge flags preserve uncertainty. Legacy numeric cost placeholders are not admission evidence.

“Other data is isolated: Nominatim can geocode place names with caching/rate spacing; OSRM is optional for road matrices; Open-Meteo supplies hourly forecast values; Gemini extracts assistant intent. A geocode is not a route, a forecast is not an observation, and a tagged hotel price is not a booking quote. Provenance and explicit unknowns are central to making these mixed sources safe to consume.”

### 15.4 Five-minute personalization explanation

“Personalization starts with onboarding and trip preferences: interests, pace, risk/walking/crowd tolerances, budget sensitivity and travel preferences. Account preferences seed planner defaults, while trip inputs are saved per trip.

“Attraction relevance is rule-based. Heritage maps to historic tags, nature to parks/lakes, spiritual to worship sites, and so forth. Interest fit is a weighted average. With no active preferences, it uses neutral fit rather than inventing interests. Category priority uses hand-coded values and tag adjustments; it is not popularity or a learned model.

“The greedy score combines fit, diminishing return for repeated categories, priority and penalties. Pace affects schedule capacity; bookmarks add a soft preference to matching IDs without forcing selection. Feedback changes preference weights using small explicit deltas; this is not model training.

“Algorithms share some inputs but not every term: greedy has explicit crowd/walking/cost components, while NSGA-II and annealing define their own utility/risk objectives. Thus personalization is shared-input but algorithm-specific. The resulting itinerary still respects hard feasibility.”

### 15.5 Five-minute budget explanation

“The seven categories are intercity outbound, intercity return, local transport, accommodation, food, admission fees and miscellaneous. Each amount has status and possibly low/representative/high range. Verified fee requires valid currency and pricing basis. Otherwise specific then eligible category estimates may apply; unresolved data remains unavailable.

“Duplicate attraction IDs are charged once. Explicit free status can be zero with provenance; public viewpoints are not automatically charged. Per-person admission multiplies by party size; group price does not. Daily chart uses the same backend fee calculation.

“Transport rates are configurable assumptions. Passenger train/bus/flight rates multiply by travellers; a car is per vehicle. No mode selected means no invented blended fare. Local travel uses route-distance proxy and may omit transfers/return. Accommodation uses room occupancy and nights; six days is five nights. Food is per-person daily rate times days and party. Miscellaneous applies a percentage to other categories without applying to itself.

“If a required category is incomplete, the complete total and within-budget status remain incomplete. When complete, the high estimate is compared with budget. These are planning estimates, not actual spending or live quotes.”

### 15.6 Five-minute dynamic-replanning explanation

“A weather check retrieves hourly Open-Meteo fields and matches a timestamp near the scheduled activity. Threshold rules evaluate rain, heat, cold, wind and thunder. Category/tag exposure determines indoor/outdoor assumptions; indoor sites receive a reduced weather score. Missing fields remain unknown, and coverage gaps are disclosed.

“The replanner looks for future outdoor activities crossing a configured threshold and searches for unplanned indoor alternatives that fit forecast, time, opening, travel and budget conditions. Completed activities are protected. It stores an original/proposed comparison but does not apply it automatically.

“Accept verifies owner and base revision, preserves history and updates itinerary; reject clears proposal without changing the schedule. A stale proposal cannot overwrite a newer revision. The result is decision support, not a weather guarantee or safety prediction.”

### 15.7 Why three algorithms?

“Greedy supplies a fast feasible baseline, NSGA-II exposes multi-objective trade-offs, and simulated annealing explores subsets with occasional worse moves. They are complementary independent alternatives, not a chain.”

### 15.8 Main technical contribution

“The contribution is a coherent application integrating provenance-aware attraction data, constrained multi-day scheduling, preference-sensitive ranking, alternative optimization outputs, range-based budgeting and revision-controlled weather/AI proposals. The algorithms are established methods; the engineering contribution is their integration, data contracts and uncertainty handling.”

## Study first for the final review

1. Greedy scoring and hard feasibility checks; be explicit that it is not globally optimal.
2. NSGA-II binary encoding, objectives, Pareto dominance, and which mechanics are provided by pymoo.
3. Limitation that the NSGA-II travel objective is start-to-stop proxy and alternatives are single-day.
4. Haversine derivation and distinction among straight-line distance, OSRM road routing and route optimization.
5. Seven budget categories, status/provenance, person versus vehicle multiplication, and conservative upper-bound check.
6. OSM node/way identities, PBF ingestion, bounds, normalization and ODbL attribution.
7. Weather thresholds as forecast assumptions; pending proposal acceptance and revision checks.
8. Gemini boundary: structured intent extraction followed by deterministic validation and proposal creation.
9. Be ready to name missing data, approximations and external dependencies without overclaiming.

