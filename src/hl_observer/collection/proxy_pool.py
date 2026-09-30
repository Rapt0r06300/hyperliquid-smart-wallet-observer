from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256


PROXY_ACTIVE = "ACTIVE"
PROXY_COOLDOWN = "COOLDOWN"
PROXY_RETIRED = "RETIRED"
PROXY_BYPASS_REFUSED = "PROXY_BYPASS_REFUSED"
NO_HEALTHY_EGRESS = "NO_HEALTHY_EGRESS"


@dataclass(frozen=True, slots=True)
class ProxyEndpoint:
    """A configured read-only egress shard.

    The URL is optional and is never used here to perform requests. This module
    only plans safe sharding and health state; network clients decide separately
    how to execute official read-only calls.
    """

    endpoint_id: str
    label: str = "direct"
    url: str | None = None
    state: str = PROXY_ACTIVE
    rest_weight_limit_per_minute: int = 1200
    success_count: int = 0
    error_count: int = 0
    recent_429_count: int = 0
    recent_403_count: int = 0
    latency_ms: int | None = None

    @property
    def redacted_url(self) -> str | None:
        if not self.url:
            return None
        if "@" not in self.url:
            return self.url
        scheme, rest = self.url.split("://", 1) if "://" in self.url else ("", self.url)
        host = rest.split("@", 1)[1]
        return f"{scheme}://***:***@{host}" if scheme else f"***:***@{host}"

    @property
    def is_healthy(self) -> bool:
        return self.state == PROXY_ACTIVE and self.recent_429_count == 0 and self.recent_403_count == 0


@dataclass(frozen=True, slots=True)
class ShardAssignment:
    shard_key: str
    endpoint_id: str
    endpoint_label: str
    budget_per_minute: int


@dataclass(frozen=True, slots=True)
class ProxyPoolPlan:
    allowed: bool
    mode: str
    aggregate_rest_budget_per_minute: int
    assignments: tuple[ShardAssignment, ...] = ()
    refusal_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    read_only: bool = True
    execution: str = "forbidden"


def plan_sticky_proxy_shards(
    shard_keys: list[str] | tuple[str, ...],
    endpoints: list[ProxyEndpoint] | tuple[ProxyEndpoint, ...],
    *,
    bypass_requested: bool = False,
) -> ProxyPoolPlan:
    """Assign shards to healthy egress endpoints without overlap."""

    keys = tuple(dict.fromkeys(str(key).strip() for key in shard_keys if str(key).strip()))
    if bypass_requested:
        return ProxyPoolPlan(
            allowed=False,
            mode="REFUSED",
            aggregate_rest_budget_per_minute=0,
            refusal_reasons=(PROXY_BYPASS_REFUSED,),
            warnings=("USE_HEALTHY_STICKY_SHARDING_INSTEAD",),
        )
    usable = tuple(endpoint for endpoint in endpoints if endpoint.is_healthy)
    mode = "STICKY_BY_SHARD"
    if not usable:
        return ProxyPoolPlan(
            allowed=False,
            mode="REFUSED",
            aggregate_rest_budget_per_minute=0,
            refusal_reasons=(NO_HEALTHY_EGRESS,),
        )
    assignments = []
    for key in keys:
        endpoint = usable[_stable_index(key, len(usable))]
        assignments.append(
            ShardAssignment(
                shard_key=key,
                endpoint_id=endpoint.endpoint_id,
                endpoint_label=endpoint.label,
                budget_per_minute=max(0, int(endpoint.rest_weight_limit_per_minute)),
            )
        )
    base_warning = "DIRECT_ONLY" if all(endpoint.url is None for endpoint in usable) else "CONFIGURED_EGRESS_REDACTED"
    return ProxyPoolPlan(
        allowed=True,
        mode=mode,
        aggregate_rest_budget_per_minute=sum(max(0, int(item.rest_weight_limit_per_minute)) for item in usable),
        assignments=tuple(assignments),
        warnings=(base_warning,),
    )


def apply_proxy_health_event(endpoint: ProxyEndpoint, *, status_code: int | None = None, timeout: bool = False) -> ProxyEndpoint:
    """Return a new endpoint health state after one request observation."""

    if timeout:
        return _replace_endpoint(endpoint, state=PROXY_COOLDOWN, error_count=endpoint.error_count + 1)
    if status_code in {429, 403}:
        return _replace_endpoint(
            endpoint,
            state=PROXY_COOLDOWN,
            error_count=endpoint.error_count + 1,
            recent_429_count=endpoint.recent_429_count + (1 if status_code == 429 else 0),
            recent_403_count=endpoint.recent_403_count + (1 if status_code == 403 else 0),
        )
    if status_code is not None and 200 <= status_code < 300:
        return _replace_endpoint(
            endpoint,
            state=PROXY_ACTIVE,
            success_count=endpoint.success_count + 1,
            recent_429_count=0,
            recent_403_count=0,
        )
    if status_code is not None and status_code >= 500:
        return _replace_endpoint(endpoint, state=PROXY_COOLDOWN, error_count=endpoint.error_count + 1)
    return endpoint


def _stable_index(value: str, modulo: int) -> int:
    digest = sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % max(1, modulo)


def _replace_endpoint(endpoint: ProxyEndpoint, **changes) -> ProxyEndpoint:
    data = {
        "endpoint_id": endpoint.endpoint_id,
        "label": endpoint.label,
        "url": endpoint.url,
        "state": endpoint.state,
        "rest_weight_limit_per_minute": endpoint.rest_weight_limit_per_minute,
        "success_count": endpoint.success_count,
        "error_count": endpoint.error_count,
        "recent_429_count": endpoint.recent_429_count,
        "recent_403_count": endpoint.recent_403_count,
        "latency_ms": endpoint.latency_ms,
    }
    data.update(changes)
    return ProxyEndpoint(**data)
