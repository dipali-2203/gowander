
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
