from sqlalchemy import create_engine, inspect, text

from app.database import migrate_complete_trip_budget_schema


def test_origin_location_migration_is_additive_idempotent_and_preserves_trip_rows():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE trips (id INTEGER PRIMARY KEY, origin VARCHAR(100))"))
        connection.execute(text("INSERT INTO trips (id, origin) VALUES (1, 'Delhi')"))

    migrate_complete_trip_budget_schema(engine)
    migrate_complete_trip_budget_schema(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("trips")}
    assert {"origin_latitude", "origin_longitude", "origin_place_id"} <= columns
    with engine.connect() as connection:
        row = connection.execute(text("SELECT id, origin, origin_latitude, origin_longitude, origin_place_id FROM trips")).one()
    assert row == (1, "Delhi", None, None, None)
    engine.dispose()
