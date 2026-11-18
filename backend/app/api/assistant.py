from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user, require_allowed_origin
from app.database import get_db
from app.models import Trip, User
from app.services.assistant import assistant_service
from app.services.assistant.schemas import AssistantChatRequest, AssistantChatResponse
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
    trip_context = None
    if payload.trip_id is not None:
        trip = db.scalar(
            select(Trip).where(
                Trip.id == payload.trip_id,
                Trip.owner_user_id == user.id,
            )
        )
        if trip is None:
            raise HTTPException(status_code=404, detail="Trip not found.")
        trip_context = assistant_service.build_trip_context(trip)

    try:
        response = await assistant_service.ask_assistant(
            message=payload.message,
            conversation_history=payload.conversation_history,
            trip_context=trip_context,
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

    return AssistantChatResponse(response=response, conversation_id=None, suggested_actions=[])
