from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import os
from datetime import datetime, timezone

from app.database import get_db
from app.models import Trip, Attraction, User
from app.api.auth import get_current_user, require_trip_access
from app.schemas import (
    AttractionInput,
    ItineraryResponse,
    MultiDayItineraryResponse,
    MultiDayOptimizeRequest,
    ParetoRequest,
    ParetoResponse,
    PreferenceFeedbackRequest,
    RiskSimulationRequest,
    RiskSimulationResponse,
    ConditionsRequest,
    ConditionsResponse,
    AnnealingRequest,
    OptimizeRequest,
    Preferences,
    TripCreate,
    TripUpdate,
    ReplanRequest,
    ReplanResponse,
    ScenarioReplanRequest,
    ScenarioReplanResponse,
)
from app.services.planner import generate_greedy_itinerary
from app.services.routing import build_travel_time_matrix
from app.services.multiday import generate_multiday_greedy
from app.services.nsga2 import generate_nsga2_alternatives
from app.services.disruptions import apply_disruptions
from app.services.preference_learning import apply_feedback
from app.services.risk import calculate_attraction_risk, simulate_completion_probability
from app.services.conditions import estimated_conditions
from app.services.annealing import generate_annealed_itinerary
from app.services.budget import attraction_budget_after_fixed_costs, estimate_trip_budget

router = APIRouter(prefix="/api/v1/trips", tags=["Trips"], dependencies=[Depends(require_trip_access)])


def _build_saved_multiday_plan(trip: Trip, request: MultiDayOptimizeRequest):
    def generate(attraction_budget: float):
        return generate_multiday_greedy(
            attractions=request.attractions,
            preferences=Preferences.model_validate(trip.preferences),
            start_date=trip.start_date,
            end_date=trip.end_date,
            start_latitude=trip.start_latitude,
            start_longitude=trip.start_longitude,
            budget=attraction_budget,
            available_minutes_per_day=trip.available_minutes_per_day,
            meal_breaks=request.meal_breaks,
            confirmed_activities=request.confirmed_activities,
            routing_provider=os.getenv("ROUTING_PROVIDER", "haversine"),
        )

    allocation = attraction_budget_after_fixed_costs(trip)
    result = generate(allocation)
    estimate = estimate_trip_budget(
        trip=trip, days=result["days"], attractions=request.attractions, data_source=request.data_source,
    )
    transport_amount = next(
        (item["amount"] for item in estimate["categories"] if item["key"] == "transportation"), 0.0,
    )
    adjusted_allocation = max(0.0, allocation - transport_amount)
    if adjusted_allocation < allocation and result["total_cost"] > adjusted_allocation:
        result = generate(adjusted_allocation)
        estimate = estimate_trip_budget(
            trip=trip, days=result["days"], attractions=request.attractions, data_source=request.data_source,
        )
    result["budget_estimate"] = estimate
    if not estimate["within_budget"]:
        result["feasible"] = False
        result["warnings"].append(
            f"Estimated full-trip costs exceed the budget by ₹{abs(estimate['remaining_budget']):,.0f}; review the fallback assumptions or adjust trip inputs."
        )
    if allocation <= 0:
        result["warnings"].append(
            "Estimated accommodation, meals, and miscellaneous costs use the full trip budget, leaving no attraction budget."
        )
        result["feasible"] = False
    scheduled_ids = {stop.attraction_id for day in result["days"] for stop in day["stops"]}
    unknown_fees = [item.name for item in request.attractions if item.id in scheduled_ids and item.cost_known is False]
    unknown_hours = [item.name for item in request.attractions if item.id in scheduled_ids and item.opening_window_known is False]
    unknown_durations = [item.name for item in request.attractions if item.id in scheduled_ids and item.visit_duration_known is False]
    if unknown_fees:
        result["warnings"].append(
            f"Entrance fees are unknown for {len(unknown_fees)} scheduled attraction(s); the numeric optimizer used a zero-cost placeholder. Verify fees before relying on the budget fit."
        )
    if unknown_hours:
        result["warnings"].append(
            f"Opening hours are not usable as schedule constraints for {len(unknown_hours)} scheduled attraction(s); the optimizer used an all-day window."
        )
    if unknown_durations:
        result["warnings"].append(
            f"Visit duration is unverified for {len(unknown_durations)} scheduled attraction(s); the optimizer used a 60-minute planning placeholder."
        )
    return result


@router.get("")
def list_trips(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trips = (
        db.query(Trip)
        .filter(Trip.owner_user_id == user.id)
        .order_by(Trip.updated_at.desc(), Trip.created_at.desc(), Trip.id.desc())
        .all()
    )
    return [
        {
            "id": trip.id,
            "name": trip.name or trip.destination,
            "origin": trip.origin,
            "destination": trip.destination,
            "start_date": str(trip.start_date),
            "end_date": str(trip.end_date),
            "budget": trip.budget,
            "preferences": trip.preferences,
            "planning_options": trip.planning_options,
            "optimization_results": trip.optimization_results,
            "latest_itinerary": trip.latest_itinerary,
            "created_at": trip.created_at.isoformat() if trip.created_at else None,
            "updated_at": trip.updated_at.isoformat() if trip.updated_at else None,
            "itinerary_stale": trip.itinerary_stale,
        }
        for trip in trips
    ]


@router.post("", status_code=201)
def create_trip(
    request: TripCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    trip = Trip(
        owner_user_id=user.id,
        name=(request.name or request.destination).strip(),
        origin=request.origin.strip(),
        destination=request.destination,
        start_date=request.start_date,
        end_date=request.end_date,
        budget=request.budget,
        available_minutes_per_day=request.available_minutes_per_day,
        start_latitude=request.start_latitude,
        start_longitude=request.start_longitude,
        preferences=request.preferences.model_dump(),
        planning_options=request.planning_options.model_dump(),
    )

    db.add(trip)
    db.commit()
    db.refresh(trip)

    return {
        "id": trip.id,
        "name": trip.name,
        "origin": trip.origin,
        "destination": trip.destination,
        "start_date": str(trip.start_date),
        "end_date": str(trip.end_date),
        "budget": trip.budget,
        "planning_options": trip.planning_options,
    }


@router.get("/{trip_id}")
def get_trip(
    trip_id: int,
    db: Session = Depends(get_db),
):
    trip = db.get(Trip, trip_id)

    if trip is None:
        raise HTTPException(
            status_code=404,
            detail="Trip not found",
        )

    return {
        "id": trip.id,
        "name": trip.name or trip.destination,
        "origin": trip.origin,
        "destination": trip.destination,
        "start_date": str(trip.start_date),
        "end_date": str(trip.end_date),
        "budget": trip.budget,
        "preferences": trip.preferences,
        "planning_options": trip.planning_options,
        "planning_inputs": trip.planning_inputs,
        "optimization_results": trip.optimization_results,
        "latest_itinerary": trip.latest_itinerary,
        "created_at": trip.created_at.isoformat() if trip.created_at else None,
        "updated_at": trip.updated_at.isoformat() if trip.updated_at else None,
        "itinerary_stale": trip.itinerary_stale,
    }


@router.put("/{trip_id}")
def update_trip(trip_id: int, request: TripUpdate, db: Session = Depends(get_db)):
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    changes = request.model_dump(exclude_unset=True)
    itinerary_inputs = {
        "origin", "destination", "start_date", "end_date", "budget",
        "available_minutes_per_day", "start_latitude", "start_longitude",
        "preferences", "planning_options",
    }
    if "preferences" in changes and changes["preferences"] is not None:
        changes["preferences"] = request.preferences.model_dump()
    if "planning_options" in changes and changes["planning_options"] is not None:
        changes["planning_options"] = request.planning_options.model_dump()
    start_date = changes.get("start_date", trip.start_date)
    end_date = changes.get("end_date", trip.end_date)
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date must not precede start_date")
    for key, value in changes.items():
        if value is not None:
            setattr(trip, key, value)
    if itinerary_inputs.intersection(changes):
        trip.itinerary_stale = True
    trip.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(trip)
    return {"trip": {"id": trip.id, "name": trip.name, "destination": trip.destination,
                     "start_date": str(trip.start_date), "end_date": str(trip.end_date),
                     "budget": trip.budget, "latest_itinerary": trip.latest_itinerary}}


@router.post("/{trip_id}/duplicate", status_code=201)
def duplicate_trip(trip_id: int, db: Session = Depends(get_db)):
    source = db.get(Trip, trip_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    duplicate = Trip(
        owner_user_id=source.owner_user_id,
        name=f"{source.name or source.destination} (copy)"[:150],
        origin=source.origin,
        destination=source.destination,
        start_date=source.start_date,
        end_date=source.end_date,
        budget=source.budget,
        available_minutes_per_day=source.available_minutes_per_day,
        start_latitude=source.start_latitude,
        start_longitude=source.start_longitude,
        preferences=source.preferences,
        planning_options=source.planning_options,
        planning_inputs=source.planning_inputs,
        optimization_results=source.optimization_results,
        latest_itinerary=source.latest_itinerary,
        itinerary_stale=source.itinerary_stale,
    )
    db.add(duplicate)
    db.commit()
    db.refresh(duplicate)
    return {"id": duplicate.id, "name": duplicate.name}


@router.delete("/{trip_id}")
def delete_trip(trip_id: int, db: Session = Depends(get_db)):
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    db.delete(trip)
    db.commit()
    return {"ok": True}


@router.post("/{trip_id}/preference-feedback")
def record_preference_feedback(trip_id: int, request: PreferenceFeedbackRequest, db: Session = Depends(get_db)):
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    updated = apply_feedback(Preferences.model_validate(trip.preferences), request.events)
    trip.preferences = updated.model_dump()
    db.commit()
    return {"trip_id": trip.id, "preferences": updated}


@router.post("/{trip_id}/risk-simulation", response_model=RiskSimulationResponse)
def simulate_trip_risk(trip_id: int, request: RiskSimulationRequest, db: Session = Depends(get_db)):
    if db.get(Trip, trip_id) is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    completion, expected = simulate_completion_probability(
        [
            calculate_attraction_risk(
                item.weather_risk,
                item.crowd_risk,
                item.availability_risk,
            )
            for item in request.attractions
        ],
        request.scenarios,
        request.seed,
    )
    return RiskSimulationResponse(
        trip_id=trip_id, scenarios=request.scenarios, seed=request.seed,
        completion_probability=round(completion, 4), expected_disruptions=round(expected, 4),
        assumption="Independent Bernoulli disruptions from supplied weather, crowd, and availability risk estimates.",
    )


@router.post("/{trip_id}/conditions", response_model=ConditionsResponse)
def get_trip_conditions(trip_id: int, request: ConditionsRequest, db: Session = Depends(get_db)):
    if db.get(Trip, trip_id) is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    return estimated_conditions(request.attractions)


@router.post(
    "/{trip_id}/optimize",
    response_model=ItineraryResponse,
)
def optimize_trip(
    trip_id: int,
    request: OptimizeRequest,
    db: Session = Depends(get_db),
):
    trip = db.get(Trip, trip_id)

    if trip is None:
        raise HTTPException(
            status_code=404,
            detail="Trip not found",
        )

    preferences = Preferences.model_validate(trip.preferences)

    # Select the routing provider from the environment.
    provider = os.getenv("ROUTING_PROVIDER", "haversine")

    # Build the travel-time matrix before running the planner.
    try:
        travel_matrix = build_travel_time_matrix(
            start=(
                trip.start_latitude,
                trip.start_longitude,
            ),
            attractions=request.attractions,
            provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not retrieve travel-time data.",
        ) from exc

    # Generate the itinerary using the matrix.
    try:
        result = generate_greedy_itinerary(
            attractions=request.attractions,
            preferences=preferences,
            start_latitude=trip.start_latitude,
            start_longitude=trip.start_longitude,
            budget=attraction_budget_after_fixed_costs(trip),
            available_minutes=trip.available_minutes_per_day,
            travel_matrix=travel_matrix,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    response = ItineraryResponse(
        trip_id=trip.id,
        algorithm="greedy",
        data_source="user_supplied",
        **result,
    )

    trip.latest_itinerary = response.model_dump(mode="json")
    trip.itinerary_stale = False
    trip.optimization_results = {}
    db.commit()

    return response


@router.post("/{trip_id}/optimize-multiday", response_model=MultiDayItineraryResponse)
def optimize_multiday_trip(
    trip_id: int,
    request: MultiDayOptimizeRequest,
    db: Session = Depends(get_db),
):
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    try:
        result = _build_saved_multiday_plan(trip, request)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = MultiDayItineraryResponse(
        trip_id=trip.id, algorithm="greedy_multiday", data_source=request.data_source, **result
    )
    trip.latest_itinerary = response.model_dump(mode="json")
    trip.planning_inputs = request.model_dump(mode="json")
    trip.itinerary_stale = False
    trip.optimization_results = {}
    db.commit()
    return response


@router.post("/{trip_id}/regenerate", response_model=MultiDayItineraryResponse)
def regenerate_saved_trip(trip_id: int, db: Session = Depends(get_db)):
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    if not trip.planning_inputs:
        raise HTTPException(
            status_code=409,
            detail="This trip does not have saved attraction inputs. Generate a new itinerary from the planner first.",
        )
    try:
        request = MultiDayOptimizeRequest.model_validate(trip.planning_inputs)
        result = _build_saved_multiday_plan(trip, request)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not result["feasible"]:
        reasons = " ".join(result["warnings"])
        raise HTTPException(
            status_code=422,
            detail=f"The updated constraints do not produce a feasible replacement itinerary. {reasons}".strip(),
        )
    response = MultiDayItineraryResponse(
        trip_id=trip.id,
        algorithm="greedy_multiday",
        data_source=request.data_source,
        **result,
    )
    # Replace the saved plan only after a complete replacement has been built.
    trip.latest_itinerary = response.model_dump(mode="json")
    trip.updated_at = datetime.now(timezone.utc)
    trip.itinerary_stale = False
    trip.optimization_results = {}
    db.commit()
    return response


@router.post("/{trip_id}/pareto", response_model=ParetoResponse)
def generate_pareto_alternatives(trip_id: int, request: ParetoRequest, db: Session = Depends(get_db)):
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    try:
        matrix = build_travel_time_matrix(
            start=(trip.start_latitude, trip.start_longitude), attractions=request.attractions,
            provider=os.getenv("ROUTING_PROVIDER", "haversine"),
        )
        alternatives = generate_nsga2_alternatives(
            attractions=request.attractions, preferences=Preferences.model_validate(trip.preferences),
            start_latitude=trip.start_latitude, start_longitude=trip.start_longitude,
            budget=attraction_budget_after_fixed_costs(trip), available_minutes=trip.available_minutes_per_day,
            travel_matrix=matrix, seed=request.seed, max_alternatives=request.max_alternatives,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = ParetoResponse(
        trip_id=trip.id, algorithm="nsga2", seed=request.seed,
        objective_note="Cost, travel-time, and risk values are planning proxies; decoded stops are validated by the greedy feasibility baseline.",
        alternatives=[{"itinerary": {"trip_id": trip.id, "algorithm": "nsga2", **item["itinerary"]}, "objectives": item["objectives"]} for item in alternatives],
    )
    trip.optimization_results = {
        **(trip.optimization_results or {}),
        "pareto": [item.model_dump(mode="json") for item in response.alternatives],
    }
    db.commit()
    return response


@router.post("/{trip_id}/anneal", response_model=ItineraryResponse)
def optimize_with_annealing(trip_id: int, request: AnnealingRequest, db: Session = Depends(get_db)):
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    result = generate_annealed_itinerary(
        request.attractions, Preferences.model_validate(trip.preferences), trip.start_latitude,
        trip.start_longitude, attraction_budget_after_fixed_costs(trip), trip.available_minutes_per_day, request.seed,
    )
    response = ItineraryResponse(trip_id=trip.id, algorithm="simulated_annealing", **result)
    trip.optimization_results = {
        **(trip.optimization_results or {}),
        "simulated_annealing": {
            "total_cost": result["total_cost"],
            "total_travel_minutes": result["total_travel_minutes"],
            "satisfaction": result["satisfaction"],
            "risk_score": result["risk_score"],
            "feasible": result["feasible"],
        },
    }
    db.commit()
    return response


@router.post("/{trip_id}/replan-scenario", response_model=ScenarioReplanResponse)
def replan_scenario(trip_id: int, request: ScenarioReplanRequest, db: Session = Depends(get_db)):
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    remaining = [item for item in request.attractions if item.id not in request.completed_attraction_ids]
    matrix = build_travel_time_matrix(
        start=(request.current_latitude, request.current_longitude), attractions=remaining,
        provider=os.getenv("ROUTING_PROVIDER", "haversine"),
    )
    adjusted, adjusted_matrix, closed, applied = apply_disruptions(remaining, request.disruptions, matrix)
    eligible = [item for item in adjusted if item.id not in closed and item.id not in request.closed_attraction_ids]
    if not eligible:
        result = {"stops": [], "total_cost": 0.0, "total_travel_minutes": 0, "total_visit_minutes": 0,
                  "satisfaction": 0.0, "risk_score": 0.0, "feasible": False,
                  "warnings": ["No eligible attractions remain after disruptions."]}
    else:
        eligible_ids = {item.id for item in eligible}
        indices = [0, *[index + 1 for index, item in enumerate(adjusted) if item.id in eligible_ids]]
        submatrix = [[adjusted_matrix[i][j] for j in indices] for i in indices]
        result = generate_greedy_itinerary(
            attractions=eligible, preferences=Preferences.model_validate(trip.preferences),
            start_latitude=request.current_latitude, start_longitude=request.current_longitude,
            budget=request.remaining_budget, available_minutes=request.remaining_minutes, travel_matrix=submatrix,
            priority_attraction_ids=set(request.previous_planned_attraction_ids),
        )
    selected_ids = {stop.attraction_id for stop in result["stops"]}
    previous_ids = set(request.previous_planned_attraction_ids)
    retained_ids = sorted(selected_ids & previous_ids)
    return ScenarioReplanResponse(
        trip_id=trip.id, algorithm="scenario_replan", data_source=request.data_source,
        completed_attraction_ids=sorted(request.completed_attraction_ids),
        excluded_closed_attraction_ids=sorted(set(request.closed_attraction_ids) | closed),
        disruptions_applied=applied, retained_planned_attraction_ids=retained_ids,
        change_count=len(selected_ids.symmetric_difference(previous_ids)), **result,
    )

from sqlalchemy import func

@router.post(
    "/{trip_id}/optimize-saved",
    response_model=ItineraryResponse,
)
def optimize_saved_trip(
    trip_id: int,
    db: Session = Depends(get_db),
):
    trip = db.get(Trip, trip_id)

    if trip is None:
        raise HTTPException(
            status_code=404,
            detail="Trip not found",
        )

    saved_attractions = (
        db.query(Attraction)
        .filter(
            func.lower(Attraction.destination)
            == trip.destination.strip().lower()
        )
        .order_by(Attraction.id)
        .all()
    )

    if not saved_attractions:
        raise HTTPException(
            status_code=404,
            detail="No saved attractions found for this destination.",
        )

    # Convert database records into the planner's input schema.
    attractions = [
        AttractionInput(
            id=a.id,
            name=a.name,
            category=a.category,
            latitude=a.latitude,
            longitude=a.longitude,
            cost=a.cost,
            visit_minutes=a.visit_minutes,
            preference_score=a.preference_score,
            weather_risk=a.weather_risk,
            crowd_risk=a.crowd_risk,
            availability_risk=a.availability_risk,
            fatigue_score=a.fatigue_score,
            opening_minute=a.opening_minute,
            closing_minute=a.closing_minute,
        )
        for a in saved_attractions
    ]

    preferences = Preferences.model_validate(trip.preferences)

    provider = os.getenv("ROUTING_PROVIDER", "haversine")

    try:
        travel_matrix = build_travel_time_matrix(
            start=(trip.start_latitude, trip.start_longitude),
            attractions=attractions,
            provider=provider,
        )

        result = generate_greedy_itinerary(
            attractions=attractions,
            preferences=preferences,
            start_latitude=trip.start_latitude,
            start_longitude=trip.start_longitude,
            budget=attraction_budget_after_fixed_costs(trip),
            available_minutes=trip.available_minutes_per_day,
            travel_matrix=travel_matrix,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not retrieve travel-time data.",
        ) from exc

    response = ItineraryResponse(
        trip_id=trip.id,
        algorithm="greedy",
        data_source="synthetic",
        **result,
    )

    trip.latest_itinerary = response.model_dump(mode="json")
    trip.itinerary_stale = False
    db.commit()

    return response

@router.post(
    "/{trip_id}/replan",
    response_model=ReplanResponse,
)
def replan_trip(
    trip_id: int,
    request: ReplanRequest,
    db: Session = Depends(get_db),
):
    # 1. Find the trip.
    trip = db.get(Trip, trip_id)

    if trip is None:
        raise HTTPException(
            status_code=404,
            detail="Trip not found",
        )

    # 2. Load attractions saved for this destination.
    saved_attractions = (
        db.query(Attraction)
        .filter(
            func.lower(Attraction.destination)
            == trip.destination.strip().lower()
        )
        .order_by(Attraction.id)
        .all()
    )

    if not saved_attractions:
        raise HTTPException(
            status_code=404,
            detail="No saved attractions found for this destination.",
        )

    # 3. Exclude attractions already visited or now closed.
    completed_ids = set(request.completed_attraction_ids)
    closed_ids = set(request.closed_attraction_ids)

    known_ids = {a.id for a in saved_attractions}

    excluded_closed_ids = sorted(closed_ids & known_ids)

    remaining_attractions = [
        AttractionInput(
            id=a.id,
            name=a.name,
            category=a.category,
            latitude=a.latitude,
            longitude=a.longitude,
            cost=a.cost,
            visit_minutes=a.visit_minutes,
            preference_score=a.preference_score,
            weather_risk=a.weather_risk,
            crowd_risk=a.crowd_risk,
            availability_risk=a.availability_risk,
            fatigue_score=a.fatigue_score,
            opening_minute=a.opening_minute,
            closing_minute=a.closing_minute,
        )
        for a in saved_attractions
        if a.id not in completed_ids
        and a.id not in closed_ids
    ]

    # 4. If no eligible attractions remain, return an empty plan.
    if not remaining_attractions:
        result = {
            "stops": [],
            "total_cost": 0.0,
            "total_travel_minutes": 0,
            "total_visit_minutes": 0,
            "satisfaction": 0.0,
            "risk_score": 0.0,
            "feasible": False,
            "warnings": [
                "No eligible attractions remain after excluding completed and closed attractions."
            ],
        }
    else:
        # 5. Load the travel preferences and routing provider.
        preferences = Preferences.model_validate(
            trip.preferences
        )
        provider = os.getenv(
            "ROUTING_PROVIDER",
            "haversine",
        )

        # 6. Calculate routes from the traveler's current location.
        try:
            travel_matrix = build_travel_time_matrix(
                start=(
                    request.current_latitude,
                    request.current_longitude,
                ),
                attractions=remaining_attractions,
                provider=provider,
            )

            # 7. Generate a new plan using remaining resources.
            result = generate_greedy_itinerary(
                attractions=remaining_attractions,
                preferences=preferences,
                start_latitude=request.current_latitude,
                start_longitude=request.current_longitude,
                budget=request.remaining_budget,
                available_minutes=request.remaining_minutes,
                travel_matrix=travel_matrix,
            )

        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=502,
                detail="Could not retrieve travel-time data.",
            ) from exc

    # 8. Return the new plan and record which stops were completed
    #    or excluded because they were closed.
    response = ReplanResponse(
        trip_id=trip.id,
        algorithm="greedy_replan",
        completed_attraction_ids=sorted(completed_ids),
        excluded_closed_attraction_ids=excluded_closed_ids,
        **result,
    )

    trip.latest_itinerary = response.model_dump(mode="json")
    trip.itinerary_stale = False
    db.commit()

    return response
