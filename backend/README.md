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

`GET /api/v1/attractions/catalog/jaipur` returns a small bundled catalog for demonstrations. Its response is marked `data_source: "synthetic"`; it is not live attraction, weather, crowd, or routing data. The frontend baseline workflow consumes this catalog and labels its result accordingly.

## Current scope

The greedy algorithm is the reproducible baseline. `POST /api/v1/trips/{trip_id}/optimize-multiday` allocates attractions across trip days, reserves configured meal-break time, and preserves confirmed activities at their fixed start time. Scenario-based risk evaluation remains a later roadmap phase.

`POST /api/v1/trips/{trip_id}/pareto` uses NSGA-II to return alternative attraction selections. Its objective values are proxies and its decoded itineraries are checked by the greedy feasibility baseline. Run `python -m experiments.run --output reports/baseline_comparison.json` to generate a seed-controlled synthetic comparison report.

`POST /api/v1/trips/{trip_id}/anneal` runs a seeded simulated-annealing attraction-set baseline and returns a decoded feasible itinerary.

`POST /api/v1/trips/{trip_id}/replan-scenario` accepts completed activities plus rainfall, traffic, crowding, and closure disruptions. It recalculates only eligible remaining stops, carries the completed IDs forward, and labels the applied scenario assumptions in its response.

Render the measured comparison as Markdown with `python -m experiments.report reports/baseline_comparison.json --output reports/baseline_comparison.md`.

Run fixed disruption robustness cases with `python -m experiments.disruptions --output reports/disruption_robustness.json`.
