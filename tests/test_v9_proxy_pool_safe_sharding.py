from hl_observer.collection.proxy_pool import (
    NO_HEALTHY_EGRESS,
    PROXY_COOLDOWN,
    PROXY_ACTIVE,
    PROXY_BYPASS_REFUSED,
    ProxyEndpoint,
    apply_proxy_health_event,
    plan_sticky_proxy_shards,
)


def test_proxy_pool_bypass_intent_is_refused_without_disabling_safe_sharding():
    plan = plan_sticky_proxy_shards(
        ["BTC", "ETH"],
        [ProxyEndpoint(endpoint_id="direct-1")],
        bypass_requested=True,
    )

    assert plan.allowed is False
    assert plan.mode == "REFUSED"
    assert PROXY_BYPASS_REFUSED in plan.refusal_reasons
    assert "USE_HEALTHY_STICKY_SHARDING_INSTEAD" in plan.warnings
    assert plan.execution == "forbidden"


def test_proxy_pool_sticky_sharding_is_deterministic_and_non_overlapping():
    endpoints = [
        ProxyEndpoint(endpoint_id="egress-a", label="a"),
        ProxyEndpoint(endpoint_id="egress-b", label="b"),
    ]
    first = plan_sticky_proxy_shards(["BTC", "ETH", "HYPE", "BTC"], endpoints)
    second = plan_sticky_proxy_shards(["BTC", "ETH", "HYPE"], endpoints)

    assert first.allowed is True
    assert [item.shard_key for item in first.assignments] == ["BTC", "ETH", "HYPE"]
    assert first.assignments == second.assignments
    assert first.aggregate_rest_budget_per_minute == 2400


def test_proxy_pool_health_event_429_moves_endpoint_to_cooldown():
    endpoint = ProxyEndpoint(endpoint_id="egress-a", state=PROXY_ACTIVE)

    updated = apply_proxy_health_event(endpoint, status_code=429)

    assert updated.state == PROXY_COOLDOWN
    assert updated.recent_429_count == 1
    assert updated.error_count == 1


def test_proxy_pool_health_recovery_after_success():
    endpoint = ProxyEndpoint(endpoint_id="egress-a", state=PROXY_COOLDOWN, recent_429_count=1, error_count=1)

    updated = apply_proxy_health_event(endpoint, status_code=200)

    assert updated.state == PROXY_ACTIVE
    assert updated.recent_429_count == 0
    assert updated.success_count == 1


def test_proxy_pool_refuses_when_no_healthy_egress_exists():
    plan = plan_sticky_proxy_shards(
        ["BTC"],
        [ProxyEndpoint(endpoint_id="egress-a", state=PROXY_COOLDOWN)],
    )

    assert plan.allowed is False
    assert NO_HEALTHY_EGRESS in plan.refusal_reasons


def test_proxy_pool_redacts_credentials():
    endpoint = ProxyEndpoint(
        endpoint_id="egress-a",
        url="https://user:password@example.invalid:8080",
    )

    assert endpoint.redacted_url == "https://***:***@example.invalid:8080"
    assert "password" not in endpoint.redacted_url
