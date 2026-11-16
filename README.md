# GoWander

GoWander is a research-oriented, risk-aware travel itinerary optimizer. The repository is organized as two independent applications:

- `frontend/` — React, TypeScript, Vite, TanStack Router, and Tailwind CSS.
- `backend/` — FastAPI, Pydantic, SQLAlchemy, and the optimization baseline.

## Install prerequisites

Install these once on Windows:

1. [Node.js LTS](https://nodejs.org/) (includes `npm`).
2. [Python 3.11 or newer](https://www.python.org/downloads/windows/). During setup, select **Add Python to PATH**.

After installation, open a new PowerShell window and confirm:

```powershell
node --version
npm --version
py --version
```

## Run locally

Backend:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --port 8000
```

Frontend, in a second PowerShell window:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open the frontend at `http://localhost:3000`. Keep the backend running on port `8000`.

## Current data boundaries

The bundled Jaipur attraction catalog is synthetic and every relevant response identifies its data source. Haversine routing is an estimate, while OSRM is optional and still not live traffic. Do not treat either as real-time travel information.
