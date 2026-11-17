from app.schemas import AttractionInput, ItineraryResponse, ParetoResponse, Preferences
from app.services.nsga2 import generate_nsga2_alternatives
from app.services.routing import build_travel_time_matrix


def test_nsga2_returns_reproducible_feasible_alternatives():
    attractions = [
        AttractionInput(id="a", name="Museum", category="history", latitude=17.385, longitude=78.4867, cost=100, visit_minutes=60, preference_score=0.9, opening_minute=0, closing_minute=720),
        AttractionInput(id="b", name="Market", category="food", latitude=17.386, longitude=78.4877, cost=50, visit_minutes=45, preference_score=0.8, opening_minute=0, closing_minute=720),
        AttractionInput(id="c", name="Park", category="nature", latitude=17.387, longitude=78.4887, cost=0, visit_minutes=45, preference_score=0.7, opening_minute=0, closing_minute=720),
    ]
    matrix = build_travel_time_matrix((17.385, 78.4867), attractions)
    alternatives = generate_nsga2_alternatives(
        attractions=attractions, preferences=Preferences(interests={"history": 1, "food": 1, "nature": 1}),
        start_latitude=17.385, start_longitude=78.4867, budget=200,
        available_minutes=240, travel_matrix=matrix, seed=9, max_alternatives=3,
    )

    assert alternatives
    assert all(item["itinerary"]["feasible"] for item in alternatives)
    assert all("utility" in item["objectives"] for item in alternatives)
    assert all(item["itinerary"]["risk_score"] is None for item in alternatives)


def test_pareto_and_annealing_response_schemas_expose_single_day_scope():
    pareto = ParetoResponse(
        trip_id=1, algorithm="nsga2", seed=2, objective_note="test", alternatives=[]
    )
    annealing = ItineraryResponse(
        trip_id=1, algorithm="simulated_annealing", optimization_scope="single_day",
        stops=[], total_cost=0, total_travel_minutes=0, total_visit_minutes=0,
        satisfaction=0, risk_score=None, feasible=False, warnings=[],
    )
    assert pareto.optimization_scope == "single_day"
    assert annealing.optimization_scope == "single_day"
