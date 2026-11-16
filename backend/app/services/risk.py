
def calculate_attraction_risk(
    weather: float,
    crowd: float,
    availability: float,
) -> float:
    """Combine independent disruption probabilities."""
    return 1 - (
        (1 - weather)
        * (1 - crowd)
        * (1 - availability)
    )


def calculate_trip_risk(stop_risks: list[float]) -> float:
    """Approximate probability of at least one disruption."""
    survival_probability = 1.0

    for risk in stop_risks:
        survival_probability *= 1 - risk

    return 1 - survival_probability


def simulate_completion_probability(stop_risks: list[float], scenarios: int, seed: int) -> tuple[float, float]:
    """Seeded Bernoulli scenarios under the documented independence assumption."""
    from random import Random

    random = Random(seed)
    completed = 0
    disruption_count = 0
    for _ in range(scenarios):
        disruptions = sum(random.random() < risk for risk in stop_risks)
        disruption_count += disruptions
        if disruptions == 0:
            completed += 1
    return completed / scenarios, disruption_count / scenarios
