from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.auth import get_current_user, require_allowed_origin
from app.database import get_db
from app.models import AssistantTripProposal, Trip, User
from app.services.assistant import assistant_service
from app.schemas import MultiDayItineraryResponse, MultiDayOptimizeRequest, Preferences, TripPlanningOptions
from app.services.assistant.proposals import proposal_to_dict
from app.services.assistant.schemas import AssistantChatRequest, AssistantChatResponse, AssistantIntentOutput
from app.services.assistant.gemini_provider import (
    AssistantInvalidResponse,
    AssistantNotConfigured,
    AssistantRateLimited,
    AssistantTimedOut,
    AssistantUnavailable,
)


router = APIRouter(prefix="/api/v1/assistant", tags=["Assistant"])


@router.post(
    "/chat",
    response_model=AssistantChatResponse,
    dependencies=[Depends(require_allowed_origin)],
)
async def chat(
    payload: AssistantChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    trip = None
    if payload.trip_id is not None:
        trip = db.scalar(
            select(Trip).where(
                Trip.id == payload.trip_id,
                Trip.owner_user_id == user.id,
            )
        )
        if trip is None:
            raise HTTPException(status_code=404, detail="Trip not found.")
    if trip is not None and payload.request_id is not None:
        existing_proposal = db.scalar(
            select(AssistantTripProposal)
            .where(
                AssistantTripProposal.user_id == user.id,
                AssistantTripProposal.trip_id == trip.id,
                AssistantTripProposal.original_inputs["_assistant_request_id"].as_string()
                == str(payload.request_id),
            )
            .limit(1)
        )
        if existing_proposal is not None:
            return AssistantChatResponse(
                response="This request already created a proposal. I returned the existing proposal without creating another.",
                conversation_id=None,
                suggested_actions=[],
                proposal=proposal_to_dict(existing_proposal),
            )
    try:
        response, proposal = await assistant_service.process_assistant_message(
            db=db,
            user_id=user.id,
            message=payload.message,
            conversation_history=payload.conversation_history,
            trip=trip,
            request_id=str(payload.request_id) if payload.request_id is not None else None,
        )
    except AssistantNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The travel assistant is not configured. Set GEMINI_API_KEY on the backend.",
        ) from exc
    except AssistantRateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The travel assistant is temporarily rate limited. Please try again shortly.",
        ) from exc
    except AssistantTimedOut as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The travel assistant took too long to respond. Please try again.",
        ) from exc
    except (AssistantInvalidResponse, AssistantUnavailable) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The travel assistant is temporarily unavailable. Please try again.",
        ) from exc

    return AssistantChatResponse(response=response, conversation_id=None, suggested_actions=[], proposal=proposal)


def _owned_proposal(db: Session, proposal_id: str, user: User) -> tuple[AssistantTripProposal, Trip]:
    proposal = db.scalar(select(AssistantTripProposal).where(
        AssistantTripProposal.id == proposal_id,
        AssistantTripProposal.user_id == user.id,
    ))
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    trip = db.scalar(select(Trip).where(
        Trip.id == proposal.trip_id,
        Trip.owner_user_id == user.id,
    ))
    if trip is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    return proposal, trip


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@router.get("/proposals/{proposal_id}")
def get_assistant_proposal(
    proposal_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proposal, _trip = _owned_proposal(db, proposal_id, user)
    if proposal.status == "pending" and _aware(proposal.expires_at) <= datetime.now(timezone.utc):
        db.execute(update(AssistantTripProposal).where(
            AssistantTripProposal.id == proposal.id,
            AssistantTripProposal.user_id == user.id,
            AssistantTripProposal.status == "pending",
        ).values(status="expired"))
        db.commit()
        db.refresh(proposal)
    return proposal_to_dict(proposal)


@router.post("/proposals/{proposal_id}/accept", dependencies=[Depends(require_allowed_origin)])
def accept_assistant_proposal(
    proposal_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proposal, trip = _owned_proposal(db, proposal_id, user)
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"This proposal is {proposal.status} and cannot be applied.")
    if _aware(proposal.expires_at) <= datetime.now(timezone.utc):
        db.execute(update(AssistantTripProposal).where(
            AssistantTripProposal.id == proposal.id,
            AssistantTripProposal.user_id == user.id,
            AssistantTripProposal.status == "pending",
        ).values(status="expired"))
        db.commit()
        db.refresh(proposal)
        raise HTTPException(status_code=409, detail="This proposal has expired. Ask the assistant to create a new one.")
    if trip.itinerary_revision != proposal.base_revision:
        db.execute(update(AssistantTripProposal).where(
            AssistantTripProposal.id == proposal.id,
            AssistantTripProposal.user_id == user.id,
            AssistantTripProposal.status == "pending",
        ).values(status="stale"))
        db.commit()
        raise HTTPException(status_code=409, detail="The trip changed after this proposal was created. Ask the assistant for an updated proposal.")
    if not (proposal.validation or {}).get("valid"):
        raise HTTPException(status_code=422, detail="This proposal did not pass itinerary validation and cannot be applied.")

    try:
        proposed_inputs = proposal.proposed_inputs
        intent = AssistantIntentOutput.model_validate(proposal.requested_intent)
        expected_types = {
            "change_travel_pace": "travel_pace_change",
            "change_budget": "budget_change",
            "change_duration": "duration_change",
            "change_preferences": "preference_change",
            "change_attractions": "attraction_change",
        }
        expected_type = "combined_change" if intent.modifications else expected_types.get(intent.action)
        if expected_type != proposal.proposal_type:
            raise ValueError("Proposal action mismatch")
        budget = proposed_inputs["budget"]
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not 1 <= budget <= 5_000_000:
            raise ValueError("Invalid budget")
        preferences = Preferences.model_validate(proposed_inputs["preferences"]).model_dump(mode="json")
        if "planning_options" in proposed_inputs:
            planning_options = TripPlanningOptions.model_validate(
                proposed_inputs["planning_options"]
            ).model_dump(mode="json")
        else:
            # Older pending proposals predate staged planning options; preserve the
            # trip's existing stored value when one of those proposals is accepted.
            planning_options = deepcopy(trip.planning_options or {})
        planning_inputs = MultiDayOptimizeRequest.model_validate(proposed_inputs["planning_inputs"]).model_dump(mode="json")
        itinerary = MultiDayItineraryResponse.model_validate(proposal.proposed_itinerary).model_dump(mode="json")
        if itinerary.get("trip_id") != trip.id:
            raise ValueError("Trip mismatch")
        start_date = date.fromisoformat(proposed_inputs.get("start_date", trip.start_date.isoformat()))
        end_date = date.fromisoformat(proposed_inputs.get("end_date", trip.end_date.isoformat()))
        if start_date != trip.start_date or end_date < start_date or (end_date - start_date).days >= 60:
            raise ValueError("Invalid staged trip dates")
        duration_parameters = (
            next((item.parameters for item in intent.modifications if item.action == "change_duration"), None)
            if intent.modifications else intent.parameters if intent.action == "change_duration" else None
        )
        if duration_parameters is not None:
            current_days = (trip.end_date - trip.start_date).days + 1
            proposed_days = (end_date - start_date).days + 1
            requested_days = duration_parameters["duration_days"]
            if proposed_days != requested_days or requested_days == current_days:
                raise ValueError("Duration mismatch")
            direction = "extend" if requested_days > current_days else "shorten"
            if duration_parameters.get("direction") != direction:
                raise ValueError("Duration direction mismatch")
            days = itinerary.get("days", [])
            if len(days) != proposed_days:
                raise ValueError("Itinerary duration mismatch")
            for index, day in enumerate(days, start=1):
                if day.get("day_number") != index or day.get("date") != (start_date + timedelta(days=index - 1)).isoformat():
                    raise ValueError("Itinerary day dates are inconsistent")
            scheduled_ids = [
                str(stop.get("attraction_id"))
                for day in days for stop in day.get("stops", [])
            ]
            if len(scheduled_ids) != len(set(scheduled_ids)):
                raise ValueError("Duplicate scheduled activity")
        allowed_ids = {str(item["id"]) for item in planning_inputs["attractions"]}
        if any(
            str(stop.get("attraction_id")) not in allowed_ids
            for day in itinerary.get("days", [])
            for stop in day.get("stops", [])
        ):
            raise ValueError("Unknown itinerary attraction")
    except Exception as exc:
        raise HTTPException(status_code=422, detail="The proposal data failed validation and cannot be applied.") from exc

    completed = {str(value) for value in (trip.completed_attraction_ids or [])}
    before = {
        str(stop.get("attraction_id")): (day.get("day_number"), stop.get("arrival_minute"))
        for day in (trip.latest_itinerary or {}).get("days", [])
        for stop in day.get("stops", [])
    }
    after = {
        str(stop.get("attraction_id")): (day.get("day_number"), stop.get("arrival_minute"))
        for day in itinerary.get("days", [])
        for stop in day.get("stops", [])
    }
    if any(item not in before or after.get(item) != before[item] for item in completed):
        raise HTTPException(status_code=422, detail="The proposal does not preserve every completed activity on its original day and time.")

    now = datetime.now(timezone.utc)
    history = deepcopy(trip.itinerary_history or [])
    if trip.latest_itinerary is not None:
        history.append({
            "revision": trip.itinerary_revision,
            "saved_at": now.isoformat(),
            "itinerary": deepcopy(trip.latest_itinerary),
        })
    history = history[-20:]
    updated = db.execute(
        update(Trip)
        .where(
            Trip.id == trip.id,
            Trip.owner_user_id == user.id,
            Trip.itinerary_revision == proposal.base_revision,
        )
        .values(
            budget=budget,
            start_date=start_date,
            end_date=end_date,
            preferences=preferences,
            planning_options=planning_options,
            planning_inputs=planning_inputs,
            latest_itinerary=itinerary,
            itinerary_revision=proposal.base_revision + 1,
            itinerary_history=history,
            completed_attraction_ids=sorted(completed),
            pending_itinerary_revision=None,
            itinerary_stale=False,
            optimization_results={},
            updated_at=now,
        )
    )
    if updated.rowcount != 1:
        db.rollback()
        db.execute(update(AssistantTripProposal).where(
            AssistantTripProposal.id == proposal.id,
            AssistantTripProposal.user_id == user.id,
            AssistantTripProposal.status == "pending",
        ).values(status="stale"))
        db.commit()
        raise HTTPException(status_code=409, detail="The trip changed while accepting this proposal. Ask for an updated proposal.")

    accepted = db.execute(
        update(AssistantTripProposal)
        .where(
            AssistantTripProposal.id == proposal.id,
            AssistantTripProposal.user_id == user.id,
            AssistantTripProposal.status == "pending",
        )
        .values(status="accepted")
    )
    if accepted.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="This proposal has already been handled.")
    db.commit()
    db.refresh(trip)
    db.refresh(proposal)
    return {
        "proposal": proposal_to_dict(proposal),
        "trip": {
            "id": trip.id,
            "start_date": trip.start_date.isoformat(),
            "end_date": trip.end_date.isoformat(),
            "budget": trip.budget,
            "preferences": trip.preferences,
            "planning_inputs": trip.planning_inputs,
            "latest_itinerary": trip.latest_itinerary,
            "itinerary_revision": trip.itinerary_revision,
            "completed_attraction_ids": trip.completed_attraction_ids or [],
        },
    }


@router.post("/proposals/{proposal_id}/reject", dependencies=[Depends(require_allowed_origin)])
def reject_assistant_proposal(
    proposal_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proposal, _trip = _owned_proposal(db, proposal_id, user)
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"This proposal is {proposal.status} and cannot be rejected.")
    if _aware(proposal.expires_at) <= datetime.now(timezone.utc):
        db.execute(update(AssistantTripProposal).where(
            AssistantTripProposal.id == proposal.id,
            AssistantTripProposal.user_id == user.id,
            AssistantTripProposal.status == "pending",
        ).values(status="expired"))
        db.commit()
        raise HTTPException(status_code=409, detail="This proposal has expired.")
    changed = db.execute(
        update(AssistantTripProposal)
        .where(
            AssistantTripProposal.id == proposal.id,
            AssistantTripProposal.user_id == user.id,
            AssistantTripProposal.status == "pending",
        )
        .values(status="rejected")
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="This proposal has already been handled.")
    db.commit()
    db.refresh(proposal)
    return {"proposal": proposal_to_dict(proposal), "message": "No changes were made to your trip."}
