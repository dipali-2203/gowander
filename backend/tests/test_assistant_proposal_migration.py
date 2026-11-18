from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database import migrate_assistant_proposal_schema
from app.models import AssistantTripProposal


def _create_legacy_database(engine):
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE assistant_trip_proposals (
                id VARCHAR(36) PRIMARY KEY,
                user_id INTEGER NOT NULL,
                trip_id INTEGER NOT NULL,
                proposal_type VARCHAR(40) NOT NULL,
                status VARCHAR(20) NOT NULL,
                created_at DATETIME NOT NULL,
                expires_at DATETIME NOT NULL,
                base_revision INTEGER NOT NULL,
                requested_intent JSON NOT NULL,
                original_inputs JSON NOT NULL,
                proposed_inputs JSON NOT NULL,
                original_itinerary JSON NOT NULL,
                proposed_itinerary JSON NOT NULL,
                budget_comparison JSON NOT NULL,
                validation JSON NOT NULL,
                warnings JSON NOT NULL,
                summary VARCHAR(500) NOT NULL
            )
        """))
        connection.execute(text("""
            INSERT INTO assistant_trip_proposals (
                id, user_id, trip_id, proposal_type, status, created_at, expires_at,
                base_revision, requested_intent, original_inputs, proposed_inputs,
                original_itinerary, proposed_itinerary, budget_comparison, validation,
                warnings, summary
            ) VALUES (
                'existing-proposal', 4, 9, 'budget_change', 'pending', '2026-11-18T00:00:00',
                '2026-11-25T00:00:00', 3, '{}', '{}', '{}', '{}', '{}', '{}', '{}', '[]',
                'Existing proposal'
            )
        """))
        connection.execute(text("CREATE TABLE unrelated_table (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO unrelated_table (id, value) VALUES (1, 'keep-me')"))


def test_assistant_proposal_migration_is_additive_idempotent_and_preserves_records():
    engine = create_engine("sqlite://")
    try:
        _create_legacy_database(engine)
        before_columns = {column["name"] for column in inspect(engine).get_columns("assistant_trip_proposals")}
        assert "changes" not in before_columns
        assert before_columns == {column.name for column in AssistantTripProposal.__table__.columns} - {"changes"}
        before_tables = set(inspect(engine).get_table_names())

        migrate_assistant_proposal_schema(engine)
        migrate_assistant_proposal_schema(engine)

        after_columns = {column["name"] for column in inspect(engine).get_columns("assistant_trip_proposals")}
        assert after_columns == {column.name for column in AssistantTripProposal.__table__.columns}
        changes_column = next(
            column for column in inspect(engine).get_columns("assistant_trip_proposals")
            if column["name"] == "changes"
        )
        assert changes_column["type"].__class__.__name__ == "JSON"
        assert changes_column["nullable"] is False
        assert changes_column["default"] == "'[]'"

        with engine.connect() as connection:
            legacy = connection.execute(text(
                "SELECT id, status, summary, changes FROM assistant_trip_proposals WHERE id='existing-proposal'"
            )).one()
            unrelated = connection.execute(text("SELECT id, value FROM unrelated_table")).one()
        assert tuple(legacy) == ("existing-proposal", "pending", "Existing proposal", "[]")
        assert tuple(unrelated) == (1, "keep-me")
        assert set(inspect(engine).get_table_names()) == before_tables
    finally:
        engine.dispose()


def test_proposal_orm_insert_succeeds_after_legacy_schema_migration():
    engine = create_engine("sqlite://")
    try:
        _create_legacy_database(engine)
        migrate_assistant_proposal_schema(engine)
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            proposal = AssistantTripProposal(
                id="new-proposal",
                user_id=4,
                trip_id=9,
                proposal_type="travel_pace_change",
                status="pending",
                created_at=now,
                expires_at=now + timedelta(days=7),
                base_revision=4,
                requested_intent={"intent": "modify_trip"},
                original_inputs={},
                proposed_inputs={},
                original_itinerary={},
                proposed_itinerary={},
                budget_comparison={},
                validation={"valid": True},
                warnings=[],
                summary="A new proposal",
            )
            session.add(proposal)
            session.commit()
            session.refresh(proposal)
            assert proposal.changes == []
            assert proposal.id == "new-proposal"
    finally:
        engine.dispose()
