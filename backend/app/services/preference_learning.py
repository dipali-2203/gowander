"""Transparent bounded updates for explicit traveler feedback."""

from app.schemas import PreferenceFeedbackEvent, Preferences


def apply_feedback(preferences: Preferences, events: list[PreferenceFeedbackEvent]) -> Preferences:
    interests = dict(preferences.interests)
    for event in events:
        category = event.category.strip().lower()
        current = interests.get(category, 0.5)
        rating_delta = ((event.rating - 3) / 2) * 0.1 if event.rating is not None else 0.0
        skip_delta = -0.12 if event.skipped else 0.0
        interests[category] = round(min(1.0, max(0.0, current + rating_delta + skip_delta)), 3)
    return preferences.model_copy(update={"interests": interests})
