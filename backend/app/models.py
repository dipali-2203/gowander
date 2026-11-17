
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True
    )
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(150), default="", nullable=False)
    origin: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    destination: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    budget: Mapped[float] = mapped_column(Float)
    available_minutes_per_day: Mapped[int] = mapped_column(Integer)
    start_latitude: Mapped[float] = mapped_column(Float)
    start_longitude: Mapped[float] = mapped_column(Float)
    preferences: Mapped[dict] = mapped_column(JSON)
    planning_options: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    planning_inputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    optimization_results: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    itinerary_stale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    latest_itinerary: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    password_login_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    google_subject: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    onboarding_skipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    travel_preferences: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class OAuthLinkChallenge(Base):
    __tablename__ = "oauth_link_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    auth_session_id: Mapped[int] = mapped_column(ForeignKey("auth_sessions.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DestinationBookmark(Base):
    __tablename__ = "destination_bookmarks"
    __table_args__ = (UniqueConstraint("user_id", "destination_id", name="uq_bookmark_user_destination"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    destination_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Attraction(Base):
    __tablename__ = "attractions"

    id: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )
    destination: Mapped[str] = mapped_column(
        String(100), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(50))

    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)

    # Legacy optimizer projections. Provider imports keep unknown values here as
    # neutral planning defaults while the nullable source/curated fields below
    # remain authoritative for display and provenance.
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    visit_minutes: Mapped[int] = mapped_column(Integer, default=60)

    preference_score: Mapped[float] = mapped_column(Float, default=0.5)
    weather_risk: Mapped[float] = mapped_column(Float, default=0.0)
    crowd_risk: Mapped[float] = mapped_column(Float, default=0.0)
    availability_risk: Mapped[float] = mapped_column(Float, default=0.0)
    weather_risk_known: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    crowd_risk_known: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    availability_risk_known: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    opening_minute: Mapped[int] = mapped_column(Integer, default=540)
    closing_minute: Mapped[int] = mapped_column(Integer, default=1020)
    data_source: Mapped[str] = mapped_column(String(30), default="user_supplied")
    fatigue_score: Mapped[float] = mapped_column(Float, default=0.5)
    provider_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_dataset: Mapped[str | None] = mapped_column(String(160), nullable=True)
    external_provider_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    license_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attribution: Mapped[str | None] = mapped_column(String(250), nullable=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_freshness: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified", nullable=False)
    data_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_tags: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    opening_hours: Mapped[str | None] = mapped_column(String(500), nullable=True)
    entrance_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    entrance_fee_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    visit_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    curated_opening_hours: Mapped[str | None] = mapped_column(String(500), nullable=True)
    curated_entrance_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    curated_visit_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verification_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)


class AttractionIngestionJob(Base):
    __tablename__ = "attraction_ingestion_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    destination: Mapped[str] = mapped_column(String(100), index=True)
    provider_name: Mapped[str] = mapped_column(String(40), default="openstreetmap")
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
