"""Seeded simulated-annealing attraction-set baseline."""

from math import exp
from random import Random

from app.schemas import AttractionInput, Preferences
from app.services.planner import calculate_attraction_risk, generate_greedy_itinerary


def generate_annealed_itinerary(attractions: list[AttractionInput], preferences: Preferences, start_latitude: float, start_longitude: float, budget: float, available_minutes: int, seed: int = 42) -> dict:
    random = Random(seed)
    current = [True] * len(attractions)

    def score(selection):
        chosen = [item for item, active in zip(attractions, selection) if active]
        utility = sum(item.preference_score * preferences.interests.get(item.category.lower(), 0.5) for item in chosen)
        cost = sum(item.cost for item in chosen)
        duration = sum(item.visit_minutes for item in chosen)
        risk = sum(calculate_attraction_risk(item) for item in chosen)
        return utility - max(0, cost - budget) / max(budget, 1) - max(0, duration - available_minutes) / max(available_minutes, 1) - risk * (1 - preferences.risk_tolerance)

    current_score = score(current)
    best = current[:]
    best_score = current_score
    for step in range(400):
        candidate = current[:]
        index = random.randrange(len(candidate))
        candidate[index] = not candidate[index]
        candidate_score = score(candidate)
        temperature = max(0.01, 1 - step / 400)
        if candidate_score > current_score or random.random() < exp((candidate_score - current_score) / temperature):
            current, current_score = candidate, candidate_score
        if current_score > best_score:
            best, best_score = current[:], current_score
    selected = [item for item, active in zip(attractions, best) if active]
    return generate_greedy_itinerary(selected, preferences, start_latitude, start_longitude, budget, available_minutes)
