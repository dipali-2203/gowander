from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import _public_user, get_current_user, require_allowed_origin
from app.database import get_db
from app.models import DestinationBookmark, User
from app.schemas import ProfileUpdate, TravelPreferences

router = APIRouter(prefix="/api/v1/account", tags=["Account"])


def _profile(user: User) -> dict[str, object]:
    name_parts = user.name.split(maxsplit=1)
    return {
        **_public_user(user),
        "first_name": name_parts[0] if name_parts else "",
        "last_name": name_parts[1] if len(name_parts) > 1 else "",
    }


@router.get("/profile")
def get_profile(user: User = Depends(get_current_user)):
    return {"profile": _profile(user)}


@router.patch("/profile", dependencies=[Depends(require_allowed_origin)])
def update_profile(
    payload: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.name = f"{payload.first_name.strip()} {payload.last_name.strip()}".strip()
    user.phone_number = payload.phone_number
    db.commit()
    db.refresh(user)
    return {"profile": _profile(user)}


@router.get("/preferences")
def get_preferences(user: User = Depends(get_current_user)):
    preferences = TravelPreferences.model_validate(user.travel_preferences or {})
    return {
        "preferences": preferences.model_dump(),
        "onboarding_completed": user.onboarding_completed,
        "onboarding_skipped": user.onboarding_skipped,
    }


@router.put("/preferences", dependencies=[Depends(require_allowed_origin)])
def update_preferences(
    payload: TravelPreferences,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.travel_preferences = payload.model_dump()
    user.onboarding_completed = True
    user.onboarding_skipped = False
    db.commit()
    return {"preferences": payload.model_dump(), "onboarding_completed": True}


@router.post("/onboarding/complete", dependencies=[Depends(require_allowed_origin)])
def complete_onboarding(
    payload: TravelPreferences,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.travel_preferences = payload.model_dump()
    user.onboarding_completed = True
    user.onboarding_skipped = False
    db.commit()
    return {"ok": True, "onboarding_completed": True, "user": _public_user(user)}


@router.post("/onboarding/skip", dependencies=[Depends(require_allowed_origin)])
def skip_onboarding(
    payload: TravelPreferences | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload is not None:
        user.travel_preferences = payload.model_dump()
    user.onboarding_completed = False
    user.onboarding_skipped = True
    db.commit()
    return {"ok": True, "onboarding_completed": False, "onboarding_skipped": True}


@router.get("/bookmarks")
def list_bookmarks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(DestinationBookmark)
        .where(DestinationBookmark.user_id == user.id)
        .order_by(DestinationBookmark.created_at, DestinationBookmark.id)
    ).all()
    return {"items": [{"destination_id": row.destination_id} for row in rows]}


@router.post("/bookmarks/{destination_id}", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_allowed_origin)])
def add_bookmark(
    destination_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized = destination_id.strip().lower()
    if not normalized or len(normalized) > 100:
        raise HTTPException(status_code=422, detail="Invalid destination identifier.")
    existing = db.scalar(select(DestinationBookmark.id).where(
        DestinationBookmark.user_id == user.id,
        DestinationBookmark.destination_id == normalized,
    ))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Destination is already bookmarked.")
    db.add(DestinationBookmark(user_id=user.id, destination_id=normalized))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Destination is already bookmarked.")
    return {"destination_id": normalized}


@router.delete("/bookmarks/{destination_id}", dependencies=[Depends(require_allowed_origin)])
def remove_bookmark(
    destination_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized = destination_id.strip().lower()
    removed = db.execute(delete(DestinationBookmark).where(
        DestinationBookmark.user_id == user.id,
        DestinationBookmark.destination_id == normalized,
    ))
    if removed.rowcount == 0:
        raise HTTPException(status_code=404, detail="Bookmark not found.")
    db.commit()
    return {"ok": True}
