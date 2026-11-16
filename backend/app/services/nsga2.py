"""Reproducible NSGA-II attraction-set alternatives for ADAPT-Trip."""

import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import ElementwiseProblem
from pymoo.operators.crossover.pntx import TwoPointCrossover
from pymoo.operators.mutation.bitflip import BitflipMutation
from pymoo.operators.sampling.rnd import BinaryRandomSampling
from pymoo.optimize import minimize

from app.schemas import AttractionInput, Preferences
from app.services.planner import calculate_attraction_risk, generate_greedy_itinerary
from app.services.routing import TravelMatrix


class AttractionSelectionProblem(ElementwiseProblem):
    """Selection model with cost, time, risk, and preference objectives."""

    def __init__(self, attractions, preferences, matrix, budget, minutes):
        super().__init__(n_var=len(attractions), n_obj=4, n_ieq_constr=2, xl=0, xu=1, vtype=bool)
        self.attractions = attractions
        self.preferences = preferences
        self.matrix = matrix
        self.budget = budget
        self.minutes = minutes

    def _evaluate(self, x, out, *args, **kwargs):
        chosen = [a for a, selected in zip(self.attractions, x) if selected]
        cost = sum(a.cost for a in chosen)
        visit_time = sum(a.visit_minutes for a in chosen)
        # A conservative, reproducible route-time proxy before decoding the route.
        travel = sum(
            (self.matrix[0][index + 1] if self.matrix[0][index + 1] is not None else self.minutes + 1)
            for index, selected in enumerate(x) if selected
        )
        survival = 1.0
        for attraction in chosen:
            survival *= 1.0 - calculate_attraction_risk(attraction)
        risk = 1.0 - survival
        utility = sum(a.preference_score * self.preferences.interests.get(a.category.lower(), 0.5) for a in chosen)
        out["F"] = [cost, travel + visit_time, risk, -utility]
        out["G"] = [cost - self.budget, travel + visit_time - self.minutes]


def generate_nsga2_alternatives(
    *, attractions: list[AttractionInput], preferences: Preferences,
    start_latitude: float, start_longitude: float, budget: float,
    available_minutes: int, travel_matrix: TravelMatrix, seed: int = 42,
    max_alternatives: int = 3,
) -> list[dict]:
    """Generate a small, deterministic Pareto set and decode it with greedy routing."""
    problem = AttractionSelectionProblem(attractions, preferences, travel_matrix, budget, available_minutes)
    result = minimize(
        problem,
        NSGA2(pop_size=48, sampling=BinaryRandomSampling(), crossover=TwoPointCrossover(), mutation=BitflipMutation()),
        termination=("n_gen", 60), seed=seed, verbose=False,
    )
    if result.X is None:
        return []
    solutions = np.atleast_2d(result.X)
    objectives = np.atleast_2d(result.F)
    ranked = sorted(zip(solutions, objectives), key=lambda item: (item[1][0], item[1][1], item[1][2]))
    alternatives = []
    seen: set[tuple[str, ...]] = set()
    for selected, objective in ranked:
        subset = [a for a, active in zip(attractions, selected) if active]
        signature = tuple(a.id for a in subset)
        if not subset or signature in seen:
            continue
        matrix_indices = [0, *[index + 1 for index, active in enumerate(selected) if active]]
        subset_matrix = [[travel_matrix[row][column] for column in matrix_indices] for row in matrix_indices]
        decoded = generate_greedy_itinerary(
            attractions=subset, preferences=preferences, start_latitude=start_latitude,
            start_longitude=start_longitude, budget=budget, available_minutes=available_minutes,
            travel_matrix=subset_matrix,
        )
        if decoded["feasible"]:
            alternatives.append({"itinerary": decoded, "objectives": {
                "cost": round(float(objective[0]), 2), "time_proxy_minutes": round(float(objective[1]), 2),
                "risk_proxy": round(float(objective[2]), 4), "utility": round(float(-objective[3]), 4),
            }})
            seen.add(signature)
        if len(alternatives) == max_alternatives:
            break
    return alternatives
