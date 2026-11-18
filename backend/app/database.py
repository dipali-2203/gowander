
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./trip_optimizer.db")

engine_options = {"connect_args": {"check_same_thread": False}}
if not DATABASE_URL.startswith("sqlite"):
    engine_options = {}

engine = create_engine(DATABASE_URL, **engine_options)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_sqlite_schema() -> None:
    """Apply additive MVP columns for existing local SQLite databases."""
    if not DATABASE_URL.startswith("sqlite"):
        if "trips" not in inspect(engine).get_table_names():
            return
        trip_columns = {column["name"] for column in inspect(engine).get_columns("trips")}
        additions = {
            "name": "VARCHAR(150) NOT NULL DEFAULT ''",
            "origin": "VARCHAR(100) NOT NULL DEFAULT ''",
            "planning_options": "JSON NOT NULL DEFAULT '{}'",
            "planning_inputs": "JSON",
            "optimization_results": "JSON NOT NULL DEFAULT '{}'",
            "updated_at": "TIMESTAMP WITH TIME ZONE",
            "itinerary_stale": "BOOLEAN NOT NULL DEFAULT FALSE",
            "itinerary_revision": "INTEGER NOT NULL DEFAULT 0",
            "itinerary_history": "JSON NOT NULL DEFAULT '[]'",
            "completed_attraction_ids": "JSON NOT NULL DEFAULT '[]'",
            "pending_itinerary_revision": "JSON",
        }
        with engine.begin() as connection:
            for name, definition in additions.items():
                if name not in trip_columns:
                    connection.execute(text(f"ALTER TABLE trips ADD COLUMN {name} {definition}"))
            connection.execute(text("UPDATE trips SET name = destination WHERE name = ''"))
            connection.execute(text("UPDATE trips SET updated_at = created_at WHERE updated_at IS NULL"))
        return
    inspector = inspect(engine)
    if "attractions" not in inspector.get_table_names():
        existing = set()
    else:
        existing = {column["name"] for column in inspector.get_columns("attractions")}
    additions = {"opening_minute": "INTEGER NOT NULL DEFAULT 540", "closing_minute": "INTEGER NOT NULL DEFAULT 1020", "data_source": "VARCHAR(30) NOT NULL DEFAULT 'user_supplied'", "fatigue_score": "FLOAT NOT NULL DEFAULT 0.5"}
    with engine.begin() as connection:
        if "attractions" in inspector.get_table_names():
            for name, definition in additions.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE attractions ADD COLUMN {name} {definition}"))
        if "trips" in inspector.get_table_names():
            trip_columns = {column["name"] for column in inspect(engine).get_columns("trips")}
            if "owner_user_id" not in trip_columns:
                connection.execute(text("ALTER TABLE trips ADD COLUMN owner_user_id INTEGER REFERENCES users(id)"))
                trip_columns.add("owner_user_id")
            trip_additions = {
                "name": "VARCHAR(150) NOT NULL DEFAULT ''",
                "origin": "VARCHAR(100) NOT NULL DEFAULT ''",
                "planning_options": "JSON NOT NULL DEFAULT '{}'",
                "planning_inputs": "JSON",
                "optimization_results": "JSON NOT NULL DEFAULT '{}'",
                "updated_at": "DATETIME",
                "itinerary_stale": "INTEGER NOT NULL DEFAULT 0",
                "itinerary_revision": "INTEGER NOT NULL DEFAULT 0",
                "itinerary_history": "JSON NOT NULL DEFAULT '[]'",
                "completed_attraction_ids": "JSON NOT NULL DEFAULT '[]'",
                "pending_itinerary_revision": "JSON",
            }
            for name, definition in trip_additions.items():
                if name not in trip_columns:
                    connection.execute(text(f"ALTER TABLE trips ADD COLUMN {name} {definition}"))
            connection.execute(text("UPDATE trips SET name = destination WHERE name = ''"))
            connection.execute(text("UPDATE trips SET updated_at = created_at WHERE updated_at IS NULL"))
        if "users" in inspector.get_table_names():
            user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
            if "google_subject" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN google_subject VARCHAR(255)"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_subject ON users (google_subject)"))


def migrate_auth_schema() -> None:
    """Add authentication columns to existing databases without replacing user data."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    dialect = engine.dialect.name
    with engine.begin() as connection:
        if "google_subject" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN google_subject VARCHAR(255)"))
            columns.add("google_subject")
        if "password_login_enabled" not in columns:
            default = "1" if dialect == "sqlite" else "TRUE"
            connection.execute(text(
                f"ALTER TABLE users ADD COLUMN password_login_enabled BOOLEAN NOT NULL DEFAULT {default}"
            ))
            # Before explicit linking existed, Google-created accounts had an
            # unusable random password hash. Preserve them as Google-only.
            connection.execute(text(
                "UPDATE users SET password_login_enabled = FALSE WHERE google_subject IS NOT NULL"
            ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_subject ON users (google_subject)"
        ))


def migrate_user_profile_schema() -> None:
    """Add profile and onboarding columns to existing user tables safely."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    sqlite = engine.dialect.name == "sqlite"
    bool_false = "0" if sqlite else "FALSE"
    bool_true = "1" if sqlite else "TRUE"
    with engine.begin() as connection:
        if "phone_number" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN phone_number VARCHAR(30)"))
        if "onboarding_completed" not in columns:
            # Existing users are treated as onboarded; new registrations set it false.
            connection.execute(text(
                f"ALTER TABLE users ADD COLUMN onboarding_completed BOOLEAN NOT NULL DEFAULT {bool_true}"
            ))
        if "onboarding_skipped" not in columns:
            connection.execute(text(
                f"ALTER TABLE users ADD COLUMN onboarding_skipped BOOLEAN NOT NULL DEFAULT {bool_false}"
            ))
        if "travel_preferences" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN travel_preferences JSON NOT NULL DEFAULT '{}'"))


def migrate_attraction_catalog_schema() -> None:
    """Add provider and verification metadata without rebuilding attraction rows."""
    inspector = inspect(engine)
    if "attractions" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("attractions")}
    datetime_type = "DATETIME" if engine.dialect.name == "sqlite" else "TIMESTAMP WITH TIME ZONE"
    additions = {
        "provider_name": "VARCHAR(40)",
        "source_dataset": "VARCHAR(160)",
        "external_provider_id": "VARCHAR(120)",
        "source_url": "VARCHAR(500)",
        "license_name": "VARCHAR(80)",
        "attribution": "VARCHAR(250)",
        "last_fetched_at": datetime_type,
        "last_verified_at": datetime_type,
        "data_freshness": "VARCHAR(20) NOT NULL DEFAULT 'unknown'",
        "verification_status": "VARCHAR(30) NOT NULL DEFAULT 'unverified'",
        # Existing numeric defaults cannot be distinguished from observations.
        # Keep the values intact and mark their provenance as unavailable.
        "weather_risk_known": "BOOLEAN NOT NULL DEFAULT FALSE",
        "crowd_risk_known": "BOOLEAN NOT NULL DEFAULT FALSE",
        "availability_risk_known": "BOOLEAN NOT NULL DEFAULT FALSE",
        "risk_metadata": "JSON NOT NULL DEFAULT '{}'",
        "data_confidence": "FLOAT",
        "raw_tags": "JSON NOT NULL DEFAULT '{}'",
        "opening_hours": "VARCHAR(500)",
        "entrance_fee": "FLOAT",
        "entrance_fee_currency": "VARCHAR(3)",
        "visit_duration_minutes": "INTEGER",
        "curated_opening_hours": "VARCHAR(500)",
        "curated_entrance_fee": "FLOAT",
        "curated_visit_duration_minutes": "INTEGER",
        "verification_notes": "VARCHAR(500)",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE attractions ADD COLUMN {name} {definition}"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_attractions_external_provider_id "
            "ON attractions (external_provider_id)"
        ))


def migrate_assistant_proposal_schema(bind=None) -> None:
    """Add missing assistant proposal columns without rebuilding proposal rows."""
    target = bind or engine
    if target.dialect.name != "sqlite":
        # The current legacy schema mismatch is specific to the local SQLite DB.
        return

    # Import here because models imports Base from this module.
    from app.models import AssistantTripProposal

    inspector = inspect(target)
    table_name = AssistantTripProposal.__tablename__
    if table_name not in inspector.get_table_names():
        return

    model_columns = {column.name for column in AssistantTripProposal.__table__.columns}
    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    missing_columns = model_columns - existing_columns
    if not missing_columns:
        return

    # Existing rows need a non-NULL JSON list. SQLite requires a constant default
    # when adding a NOT NULL column to a populated table.
    additions = {"changes": "JSON NOT NULL DEFAULT '[]'"}
    unhandled = missing_columns - additions.keys()
    if unhandled:
        raise RuntimeError(
            "Assistant proposal schema has unmapped model columns: "
            + ", ".join(sorted(unhandled))
        )

    with target.begin() as connection:
        # Re-check inside the migration transaction for safe repeated startup.
        columns = {column["name"] for column in inspect(connection).get_columns(table_name)}
        for name in sorted(missing_columns):
            if name not in columns:
                connection.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN {name} {additions[name]}"
                ))
