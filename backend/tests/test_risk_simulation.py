from app.services.risk import simulate_completion_probability


def test_seeded_risk_simulation_is_reproducible():
    first = simulate_completion_probability([0.2, 0.3], scenarios=500, seed=9)
    second = simulate_completion_probability([0.2, 0.3], scenarios=500, seed=9)
    assert first == second
    assert 0 <= first[0] <= 1
    assert first[1] >= 0
