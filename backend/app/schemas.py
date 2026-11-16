
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class Preferences(BaseModel):
    interests: dict[str, float] = Field(
        default_factory=lambda: {"history": 0.8, "food": 0.7}
    )
    risk_tolerance: float = Field(default=0.3, ge=0, le=1)
    walking_tolerance: float = Field(default=0.5, ge=0, le=1)
    crowd_tolerance: float = Field(default=0.5, ge=0, le=1)
    budget_sensitivity: float = Field(default=0.5, ge=0, le=1)
    travel_pace: float = Field(default=0.5, ge=0, le=1)
    preferred_transport: str = Field(default="mixed", max_length=30)


PreferenceChoice = Annotated[str, Field(min_length=1, max_length=80)]


class TravelPreferences(BaseModel):
    interests: list[PreferenceChoice] = Field(default_factory=list, max_length=12)
    styles: list[PreferenceChoice] = Field(default_factory=list, max_length=8)
    budget_preference: Literal["budget", "moderate", "premium", "luxury", "flexible"] | None = None
    daily_budget_inr: int | None = Field(default=None, ge=0, le=5_000_000)
    transportation: str | None = Field(default=None, max_length=40)
    accommodation: str | None = Field(default=None, max_length=40)
    preferred_trip_duration_days: int | None = Field(default=None, ge=1, le=60)
    travel_pace: Literal["relaxed", "balanced", "fast"] | None = None

    @model_validator(mode="after")
    def normalize_selections(self):
        self.interests = list(dict.fromkeys(item.strip() for item in self.interests if item.strip()))
        self.styles = list(dict.fromkeys(item.strip() for item in self.styles if item.strip()))
        return self


class ProfileUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(default="", max_length=60)
    phone_number: str | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def validate_profile(self):
        self.first_name = self.first_name.strip()
        self.last_name = self.last_name.strip()
        if not self.first_name:
            raise ValueError("First name is required.")
        if len(f"{self.first_name} {self.last_name}".strip()) > 100:
            raise ValueError("The full name must be 100 characters or fewer.")
        if self.phone_number is not None:
            self.phone_number = self.phone_number.strip() or None
        return self


class TripPlanningOptions(BaseModel):
    model_config = {"extra": "forbid"}

    traveler_count: int = Field(default=1, ge=1, le=30)
    transportation_mode: str = Field(default="mixed", min_length=1, max_length=40)
    accommodation_category: Literal["budget", "standard", "premium", "luxury"] = "standard"
    meal_preferences: list[str] = Field(default_factory=list, max_length=12)
    miscellaneous_budget: float = Field(default=0, ge=0, le=5_000_000)


class TripCreate(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    origin: str = Field(default="", max_length=100)
    destination: str = Field(min_length=2, max_length=100)
    start_date: date
    end_date: date
    budget: float = Field(gt=0)
    available_minutes_per_day: int = Field(default=1200, gt=0)
    start_latitude: float = Field(ge=-90, le=90)
    start_longitude: float = Field(ge=-180, le=180)
    preferences: Preferences = Field(default_factory=Preferences)
    planning_options: TripPlanningOptions = Field(default_factory=TripPlanningOptions)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class TripUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, min_length=1, max_length=150)
    origin: str | None = Field(default=None, max_length=100)
    destination: str | None = Field(default=None, min_length=2, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    budget: float | None = Field(default=None, gt=0)
    available_minutes_per_day: int | None = Field(default=None, gt=0)
    start_latitude: float | None = Field(default=None, ge=-90, le=90)
    start_longitude: float | None = Field(default=None, ge=-180, le=180)
    preferences: Preferences | None = None
    planning_options: TripPlanningOptions | None = None


class PreferenceFeedbackEvent(BaseModel):
    category: str = Field(min_length=1, max_length=50)
    rating: float | None = Field(default=None, ge=1, le=5)
    skipped: bool = False


class PreferenceFeedbackRequest(BaseModel):
    events: list[PreferenceFeedbackEvent] = Field(min_length=1, max_length=100)


class AttractionInput(BaseModel):
    id: str
    name: str
    category: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    cost: float = Field(default=0, ge=0)
    visit_minutes: int = Field(gt=0)
    preference_score: float = Field(ge=0, le=1)
    weather_risk: float = Field(default=0.0, ge=0, le=1)
    crowd_risk: float = Field(default=0.0, ge=0, le=1)
    availability_risk: float = Field(default=0.0, ge=0, le=1)
    fatigue_score: float = Field(default=0.5, ge=0, le=1)
    opening_minute: int = Field(default=540, ge=0, le=1439)
    closing_minute: int = Field(default=1020, ge=1, le=1440)

    @model_validator(mode="after")
    def validate_opening_window(self):
        if self.closing_minute <= self.opening_minute:
            raise ValueError("closing_minute must be after opening_minute")
        return self


class OptimizeRequest(BaseModel):
    attractions: list[AttractionInput] = Field(min_length=1)
    algorithm: Literal["greedy", "nsga2"] = "greedy"


class ParetoRequest(OptimizeRequest):
    algorithm: Literal["nsga2"] = "nsga2"
    seed: int = Field(default=42, ge=0)
    max_alternatives: int = Field(default=3, ge=1, le=10)


class AnnealingRequest(OptimizeRequest):
    algorithm: Literal["simulated_annealing"] = "simulated_annealing"
    seed: int = Field(default=42, ge=0)


class RiskSimulationRequest(BaseModel):
    attractions: list[AttractionInput] = Field(min_length=1)
    scenarios: int = Field(default=1_000, ge=100, le=100_000)
    seed: int = Field(default=42, ge=0)


class MealBreak(BaseModel):
    """A daily non-activity block; its duration is reserved by the baseline."""
    start_minute: int = Field(ge=0, le=1439)
    duration_minutes: int = Field(gt=0, le=240)


class ConfirmedActivity(BaseModel):
    attraction_id: str
    day_number: int = Field(gt=0)
    start_minute: int = Field(ge=0, le=1439)


class MultiDayOptimizeRequest(OptimizeRequest):
    meal_breaks: list[MealBreak] = Field(default_factory=list)
    confirmed_activities: list[ConfirmedActivity] = Field(default_factory=list)
    data_source: Literal["synthetic", "user_supplied"] = "user_supplied"

class ReplanRequest(BaseModel):
    current_latitude: float = Field(ge=-90, le=90)
    current_longitude: float = Field(ge=-180, le=180)

    remaining_budget: float = Field(ge=0)
    remaining_minutes: int = Field(ge=0)

    completed_attraction_ids: list[str] = Field(
        default_factory=list
    )


class Disruption(BaseModel):
    kind: Literal["rainfall", "traffic", "crowding", "closure"]
    severity: float = Field(default=0.5, ge=0, le=1)
    affected_attraction_ids: list[str] = Field(default_factory=list)


class ScenarioReplanRequest(ReplanRequest):
    attractions: list[AttractionInput] = Field(min_length=1)
    disruptions: list[Disruption] = Field(default_factory=list)
    data_source: Literal["synthetic", "user_supplied"] = "user_supplied"
    previous_planned_attraction_ids: list[str] = Field(default_factory=list)
    closed_attraction_ids: list[str] = Field(
        default_factory=list
    )

class ItineraryStop(BaseModel):
    attraction_id: str
    name: str
    arrival_minute: int
    departure_minute: int
    travel_minutes_before: int
    cost: float
    preference_score: float
    risk_score: float
    wait_minutes: int = 0


class ItineraryResponse(BaseModel):
    trip_id: int
    algorithm: str
    stops: list[ItineraryStop]
    total_cost: float
    total_travel_minutes: int
    total_visit_minutes: int
    satisfaction: float
    risk_score: float
    feasible: bool
    warnings: list[str]
    data_source: Literal["synthetic", "user_supplied"] = "user_supplied"


class ReplanResponse(ItineraryResponse):
    completed_attraction_ids: list[str] = Field(
        default_factory=list
    )
    excluded_closed_attraction_ids: list[str] = Field(
        default_factory=list
    )


class ScenarioReplanResponse(ReplanResponse):
    disruptions_applied: list[str]
    retained_planned_attraction_ids: list[str]
    change_count: int


class ItineraryDay(BaseModel):
    day_number: int
    date: date
    stops: list[ItineraryStop]
    total_cost: float
    total_travel_minutes: int
    total_visit_minutes: int
    reserved_break_minutes: int
    meal_breaks: list[MealBreak] = Field(default_factory=list)
    feasible: bool
    warnings: list[str]


class MultiDayItineraryResponse(BaseModel):
    trip_id: int
    algorithm: str
    days: list[ItineraryDay]
    total_cost: float
    total_travel_minutes: int
    total_visit_minutes: int
    satisfaction: float
    risk_score: float
    feasible: bool
    warnings: list[str]
    data_source: Literal["synthetic", "user_supplied"]
    budget_estimate: dict | None = None


class ParetoAlternative(BaseModel):
    itinerary: ItineraryResponse
    objectives: dict[str, float]


class ParetoResponse(BaseModel):
    trip_id: int
    algorithm: Literal["nsga2"]
    seed: int
    objective_note: str
    alternatives: list[ParetoAlternative]


class RiskSimulationResponse(BaseModel):
    trip_id: int
    scenarios: int
    seed: int
    completion_probability: float
    expected_disruptions: float
    assumption: str


class ConditionsRequest(BaseModel):
    attractions: list[AttractionInput] = Field(min_length=1)


class AttractionCondition(BaseModel):
    attraction_id: str
    weather_risk: float
    crowd_risk: float
    availability_risk: float


class ConditionsResponse(BaseModel):
    source: Literal["estimated", "live"]
    observed_at: datetime
    conditions: list[AttractionCondition]
