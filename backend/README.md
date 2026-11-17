# ADAPT-Trip backend

FastAPI service for the ADAPT-Trip Phase 1 baseline. It provides trip creation, a deterministic greedy itinerary generator, hard-constraint validation, routing-matrix abstraction, and basic replanning.

## Local setup

Create a Python environment, install `requirements.txt`, then run:

```powershell
uvicorn app.main:app --reload --port 8000
```

Set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL when moving beyond local development. SQLite remains the default for the MVP.

Authentication supports email/password, Google OpenID Connect, and SMTP-delivered password reset links. Password reset tokens expire after 30 minutes, are stored hashed, and are single-use; changing a password revokes active sessions. Google sign-in creates a separate Google account and does not automatically link an existing email/password account. Copy `.env.example` to `.env` for local development. Configure SMTP and Google OAuth values there, register `GOOGLE_REDIRECT_URI` exactly in Google Cloud Console, set `FRONTEND_BASE_URL`, and set `FRONTEND_ORIGINS` to the exact frontend origin. Set `VITE_GOOGLE_SIGN_IN_ENABLED=true` in the frontend environment after backend OAuth credentials are configured. For production, use HTTPS and set `AUTH_COOKIE_SECURE=true`. If the frontend and API are on different sites, set `AUTH_COOKIE_SAMESITE=none` (HTTPS is required); keep `FRONTEND_ORIGINS` exact.

## Data provenance

`GET /api/v1/attractions/catalog/{destination}` reads the database-backed attraction catalog. If a destination has not been ingested, it returns a clearly marked synthetic development fallback unless `APP_ENV=production` or `POI_ALLOW_SYNTHETIC_FALLBACK=false`. Synthetic entries are not live attraction, weather, crowd, or routing data. When `ROUTING_PROVIDER` is `haversine` (the default), travel minutes use straight-line distance at a fixed assumed speed, not road routing.

## Current scope

The greedy algorithm is the reproducible baseline. `POST /api/v1/trips/{trip_id}/optimize-multiday` allocates attractions across trip days, returns configured meal-break windows, and preserves confirmed activities at their fixed start time. It marks incomplete schedules and constraint conflicts rather than treating them as successful plans. Schedule times and `available_minutes_per_day` are minutes from midnight; the frontend baseline uses a 20:00 cutoff. Accommodation, transport costs, and meal costs are outside the attraction-fee budget.

`POST /api/v1/trips/{trip_id}/pareto` uses NSGA-II to return alternative attraction selections. Its objective values are proxies and its decoded itineraries are checked by the greedy feasibility baseline. Run `python -m experiments.run --output reports/baseline_comparison.json` to generate a seed-controlled synthetic comparison report.

`POST /api/v1/trips/{trip_id}/anneal` runs a seeded simulated-annealing attraction-set baseline and returns a decoded feasible itinerary.

`POST /api/v1/trips/{trip_id}/replan-scenario` accepts completed activities plus rainfall, traffic, crowding, and closure disruptions. It recalculates only eligible remaining stops, carries the completed IDs forward, and labels the applied scenario assumptions in its response.

## Trip records and budget estimates

Trip detail, update, duplicate, delete, and regeneration APIs are authenticated and owner-scoped. Multi-day optimization stores its attraction inputs so saved trips can be reopened and regenerated. Editing itinerary constraints marks the previous schedule stale but leaves it intact until regeneration succeeds.

Budget estimates reserve accommodation, meals, and user-entered miscellaneous expenses before attraction selection. Local transport uses the selected mode and estimated straight-line route distance. These are fallback estimates, not verified prices. There is no configured hotel inventory, restaurant/menu data, intercity fare provider, or live availability source. Defaults can be overridden with `TRIP_HOTEL_ESTIMATE_INR_PER_NIGHT_BUDGET`, `_STANDARD`, `_PREMIUM`, `_LUXURY`, `TRIP_MEAL_ESTIMATE_INR_PER_PERSON_PER_DAY`, and `TRIP_LOCAL_FARE_INR_PER_KM_<MODE>` (for example `_PUBLIC_TRANSPORT`, `_TAXI`, or `_CAR`). The default hotel allowance is ₹1,800/₹3,800/₹7,800/₹15,000 per room per night by category; the meal allowance is ₹600 per person/day before its category multiplier. No property or restaurant name is invented.

Render the measured comparison as Markdown with `python -m experiments.report reports/baseline_comparison.json --output reports/baseline_comparison.md`.

Run fixed disruption robustness cases with `python -m experiments.disruptions --output reports/disruption_robustness.json`.
# OpenStreetMap attraction catalog

Attraction catalog reads use the local database and never call Overpass. To refresh one supported city, run from `backend`:

```powershell
.venv\Scripts\python.exe -m app.services.ingest_osm jaipur
.venv\Scripts\python.exe -m app.services.ingest_osm udaipur
```

Each command performs one bounded city query with a 25-second timeout and at most three attempts, then inserts newly discovered OSM elements or refreshes provider-owned fields. Manual curation is preserved. Recent outcomes are recorded in `attraction_ingestion_jobs`; failed jobs keep an error summary. The admin endpoint is available only when `POI_INGESTION_ENABLED=true` and the caller has the `admin` role: `POST /api/v1/attractions/admin/ingest/{jaipur|udaipur}`. `GET /api/v1/attractions/admin/ingestion-jobs` lists outcomes. Configure `OSM_USER_AGENT` with a project contact before production use.

Imported records use stable IDs such as `osm:node:123`, retain raw OSM tags, source links, ODbL license and attribution, fetch/verification metadata, and nullable fee, hours, and duration fields. Unknown planning values stay nullable in the catalog; the legacy optimizer still requires numbers, so its adapter uses neutral internal projections (zero fee, 60-minute visit, and an all-day window) and returns `cost_known`, `visit_duration_known`, and `opening_window_known` flags. These projections must not be presented as facts. Simple OSM opening-hour ranges are translated to the legacy planner window; complex schedules are displayed as source text but not enforced as schedule constraints.

Use `PATCH /api/v1/attractions/admin/{attraction_id}/verify` to record curated fee, opening hours, visit duration, confidence, and verification notes. Curated values are stored separately and survive refreshes. `POI_ALLOW_SYNTHETIC_FALLBACK` controls the clearly labeled development fallback. In production, set `APP_ENV=production` or disable that flag so an un-ingested destination returns an explicit empty state. Publicly displayed OSM-derived data must retain `© OpenStreetMap contributors` attribution and comply with ODbL.
# Offline OSM attraction import

Live Overpass ingestion remains available through `python -m app.services.ingest_osm`.
For a local bulk import, install the optional Pyosmium dependency and download a
Geofabrik extract separately. Jaipur and Udaipur are covered by Geofabrik's
Northern Zone extract; the current PBF is about 214 MB, compared with about
1.6 GB for all India. The importer filters the extract to the existing Jaipur
or Udaipur destination bounds and does not download data during application startup.

Install the PBF dependency from the backend directory:

```powershell
python -m pip install -r requirements-pbf.txt
```

Download the current Northern Zone extract in PowerShell:

```powershell
New-Item -ItemType Directory -Force data | Out-Null
Invoke-WebRequest `
  -Uri https://download.geofabrik.de/asia/india/northern-zone-latest.osm.pbf `
  -OutFile data/northern-zone-latest.osm.pbf
```

First preview the bounded changes, then run each city separately:

```powershell
python -m app.services.ingest_osm_pbf jaipur data/northern-zone-latest.osm.pbf --dry-run
python -m app.services.ingest_osm_pbf jaipur data/northern-zone-latest.osm.pbf
python -m app.services.ingest_osm_pbf udaipur data/northern-zone-latest.osm.pbf --dry-run
python -m app.services.ingest_osm_pbf udaipur data/northern-zone-latest.osm.pbf
```

Dry-run performs the PBF scans and checks existing database identities but does
not write attraction rows or ingestion jobs. Real runs are recorded as
`geofabrik-pbf` ingestion jobs. Repeated imports update matching `node/<id>` or
`way/<id>` rows and preserve manually curated planning values. The output reports
new and updated records, within-file duplicates, invalid/missing-geometry records,
the extract filename, attribution, and ODbL license. Node and way records retain
their OpenStreetMap object URLs; `source_dataset` records the Geofabrik extract.

Unknown fees, opening hours, and visit durations remain null. The optimizer's
legacy numeric projections remain unchanged for compatibility and should not be
interpreted as verified source data.

Geofabrik's PBF excludes contributor usernames, user IDs, and changeset IDs.
Give visible attribution to OpenStreetMap contributors and comply with ODbL 1.0
when redistributing or producing a database derived from OSM data.
