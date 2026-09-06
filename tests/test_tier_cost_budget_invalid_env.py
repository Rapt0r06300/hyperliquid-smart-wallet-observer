from hl_observer.edge.tier_cost_budget import S_MIN_ENV, tier_of


def test_tier_of_falls_back_to_default_when_threshold_env_is_invalid() -> None:
    assert tier_of(90.0, {S_MIN_ENV: "not-a-number"}) == "S"
