"""Run a controlled Jaipur or Udaipur OSM catalog refresh.

Usage from the backend directory: python -m app.services.ingest_osm jaipur
"""
from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

load_dotenv()

from app.database import Base, SessionLocal, engine, migrate_attraction_catalog_schema
from app import models  # noqa: F401 - register models before create_all
from app.services.poi_catalog import DESTINATIONS, run_ingestion_job


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh GoWander OSM attraction data.")
    parser.add_argument("destination", choices=sorted(DESTINATIONS))
    args = parser.parse_args()
    Base.metadata.create_all(bind=engine)
    migrate_attraction_catalog_schema()
    with SessionLocal() as db:
        result = run_ingestion_job(db, args.destination)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
