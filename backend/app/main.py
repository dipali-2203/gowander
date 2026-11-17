
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.api.trips import router
from app.api.attractions import router as attractions_router
from app.api.auth import router as auth_router
from app.api.account import router as account_router
from app.api.shared_trips import router as shared_trips_router
from app.database import Base, engine, migrate_attraction_catalog_schema, migrate_auth_schema, migrate_sqlite_schema, migrate_user_profile_schema
from app import models  # Register SQLAlchemy models

Base.metadata.create_all(bind=engine)
migrate_sqlite_schema()
migrate_auth_schema()
migrate_user_profile_schema()
migrate_attraction_catalog_schema()

app = FastAPI(
    title="Personalized Risk-Aware Trip Optimization API",
    version="0.1.0",
    description=(
        "Backend for personalized itinerary generation, "
        "risk evaluation, and dynamic replanning."
    ),
)

# Development configuration. Restrict origins in deployment.
allowed_origins = [origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(attractions_router)
app.include_router(auth_router)
app.include_router(account_router)
app.include_router(shared_trips_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
