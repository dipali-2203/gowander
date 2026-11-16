from app.schemas import PreferenceFeedbackEvent, Preferences
from app.services.preference_learning import apply_feedback


def test_feedback_increases_liked_category_and_decreases_skipped_category():
    updated = apply_feedback(
        Preferences(interests={"history": 0.5, "food": 0.5}),
        [PreferenceFeedbackEvent(category="history", rating=5), PreferenceFeedbackEvent(category="food", skipped=True)],
    )
    assert updated.interests["history"] == 0.6
    assert updated.interests["food"] == 0.38
