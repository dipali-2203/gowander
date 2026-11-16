"""Small, explicitly synthetic catalog for local MVP demonstrations."""

from app.schemas import AttractionInput


SYNTHETIC_CATALOG: dict[str, list[AttractionInput]] = {
    "jaipur": [
        AttractionInput(id="jaipur-amber", name="Amber Fort", category="history", latitude=26.9855, longitude=75.8513, cost=200, visit_minutes=150, preference_score=0.96, weather_risk=0.12, crowd_risk=0.36, availability_risk=0.03, opening_minute=480, closing_minute=1050),
        AttractionInput(id="jaipur-city-palace", name="City Palace", category="history", latitude=26.9258, longitude=75.8237, cost=300, visit_minutes=120, preference_score=0.88, weather_risk=0.05, crowd_risk=0.30, availability_risk=0.02, opening_minute=570, closing_minute=1050),
        AttractionInput(id="jaipur-jantar", name="Jantar Mantar", category="history", latitude=26.9248, longitude=75.8246, cost=200, visit_minutes=75, preference_score=0.82, weather_risk=0.08, crowd_risk=0.25, availability_risk=0.02, opening_minute=540, closing_minute=990),
        AttractionInput(id="jaipur-hawa-mahal", name="Hawa Mahal", category="history", latitude=26.9239, longitude=75.8267, cost=50, visit_minutes=60, preference_score=0.84, weather_risk=0.04, crowd_risk=0.42, availability_risk=0.02, opening_minute=540, closing_minute=990),
        AttractionInput(id="jaipur-jal-mahal", name="Jal Mahal viewpoint", category="sightseeing", latitude=26.9531, longitude=75.8469, cost=0, visit_minutes=45, preference_score=0.70, weather_risk=0.10, crowd_risk=0.22, availability_risk=0.01, opening_minute=480, closing_minute=1140),
        AttractionInput(id="jaipur-albert-hall", name="Albert Hall Museum", category="history", latitude=26.9117, longitude=75.8197, cost=40, visit_minutes=90, preference_score=0.78, weather_risk=0.03, crowd_risk=0.15, availability_risk=0.03, opening_minute=540, closing_minute=1020),
        AttractionInput(id="jaipur-food-walk", name="Old City food walk", category="food", latitude=26.9226, longitude=75.8231, cost=650, visit_minutes=120, preference_score=0.91, weather_risk=0.05, crowd_risk=0.34, availability_risk=0.04, opening_minute=720, closing_minute=1320),
    ]
    ,"udaipur": [
        AttractionInput(id="udaipur-city-palace", name="City Palace", category="history", latitude=24.5764, longitude=73.6835, cost=300, visit_minutes=150, preference_score=0.95, crowd_risk=0.32, opening_minute=540, closing_minute=1050),
        AttractionInput(id="udaipur-bagore", name="Bagore ki Haveli", category="history", latitude=24.5791, longitude=73.6806, cost=150, visit_minutes=100, preference_score=0.82, crowd_risk=0.20, opening_minute=570, closing_minute=1140),
        AttractionInput(id="udaipur-lake", name="Lake Pichola promenade", category="sightseeing", latitude=24.5737, longitude=73.6797, cost=0, visit_minutes=75, preference_score=0.87, weather_risk=0.12, opening_minute=480, closing_minute=1260),
        AttractionInput(id="udaipur-saheliyon", name="Saheliyon ki Bari", category="nature", latitude=24.6017, longitude=73.6957, cost=30, visit_minutes=60, preference_score=0.72, opening_minute=540, closing_minute=1080),
    ],
}

SYNTHETIC_START_LOCATIONS = {
    "jaipur": (26.9124, 75.7873),
    "udaipur": (24.5854, 73.7125),
}
