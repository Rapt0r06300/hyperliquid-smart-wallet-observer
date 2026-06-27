from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, floor


REST_WEIGHT_LIMIT_PER_MINUTE = 1200
SAFE_REST_WEIGHT_TARGET_PER_MINUTE = 840
INFO_LIGHT_WEIGHT = 2
INFO_DEFAULT_WEIGHT = 20
INFO_TIME_RANGE_PAGE_LIMIT = 500
INFO_EXTRA_ITEM_BUCKET_SIZE = 20
EXPLORER_WEIGHT = 40

WS_MAX_CONNECTIONS = 10
WS_MAX_NEW_CONNECTIONS_PER_MINUTE = 30
WS_MAX_SUBSCRIPTIONS = 1000
WS_MAX_UNIQUE_USERS = 10
WS_MAX_MESSAGES_PER_MINUTE = 2000

NETWORK_READ_DISABLED = "NETWORK_READ_DISABLED"
RATE_LIMIT_BYPASS_REFUSED = "RATE_LIMIT_BYPASS_REFUSED"
AGGRESSIVE_SCRAPING_REFUSED = "AGGRESSIVE_SCRAPING_REFUSED"
RATE_LIMIT_GUARD = "RATE_LIMIT_GUARD"
WEBSOCKET_LIMIT_GUARD = "WEBSOCKET_LIMIT_GUARD"
PLAN_OK = "PLAN_OK"
PLAN_DEGRADED = "PLAN_DEGRADED"
PLAN_REFUSED = "REFUSED"


@dataclass(slots=True)
class ReadOnlyBudgetRequest:
    """One bounded Hyperliquid read-only collection cycle.

    The budgeter is intentionally conservative. It plans official public reads
    and refuses bypass/proxy/aggressive scraping requests. It does not execute,
    sign, route, or place orders.
    """

    network_read_enabled: bool = False
    all_mids_calls: int = 0
    light_info_calls: int = 0
    default_info_calls: int = 0
    explorer_calls: int = 0
    time_range_items_expected: int = 0
    ws_connections: int = 0
    ws_new_connections_per_minute: int = 0
    ws_subscriptions: int = 0
    ws_unique_users: int = 0
    ws_messages_per_minute: int = 0
    egress_count: int = 1
    target_utilization: float = 0.70
    bypass_requested: bool = False
    aggressive_scraping_requested: bool = False


@dataclass(slots=True)
class BudgetPlan:
    status: str
    estimated_rest_weight: int
    safe_rest_budget: int
    rest_weight_remaining_after: int
    ws_ok: bool
    read_only: bool = True
    execution: str = "forbidden"
    refusal_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommendation: str = ""

    @property
    def allowed(self) -> bool:
        return not self.refusal_reasons and self.status in {PLAN_OK, PLAN_DEGRADED}


def estimate_readonly_rest_weight(request: ReadOnlyBudgetRequest) -> int:
    """Estimate REST weight for one read-only cycle.

    Hyperliquid time-range responses are capped by page size. We keep the page
    cost pessimistic: each expected 20 returned items costs one default info
    unit, even when a future endpoint is cheaper in practice.
    """

    item_buckets = ceil(max(0, int(request.time_range_items_expected)) / INFO_EXTRA_ITEM_BUCKET_SIZE)
    return (
        max(0, int(request.all_mids_calls)) * INFO_LIGHT_WEIGHT
        + max(0, int(request.light_info_calls)) * INFO_LIGHT_WEIGHT
        + max(0, int(request.default_info_calls)) * INFO_DEFAULT_WEIGHT
        + max(0, int(request.explorer_calls)) * EXPLORER_WEIGHT
        + item_buckets * INFO_DEFAULT_WEIGHT
    )


def plan_readonly_collection_budget(request: ReadOnlyBudgetRequest) -> BudgetPlan:
    """Build the fastest safe public-data plan for one collection cycle."""

    refusal_reasons: list[str] = []
    warnings: list[str] = []
    effective_egress = max(1, int(request.egress_count))
    target_utilization = min(max(float(request.target_utilization), 0.10), 0.90)
    safe_budget = floor(REST_WEIGHT_LIMIT_PER_MINUTE * target_utilization * effective_egress)
    estimated = estimate_readonly_rest_weight(request)
    ws_ok = _ws_within_limits(request)

    if not request.network_read_enabled:
        refusal_reasons.append(NETWORK_READ_DISABLED)
    if request.bypass_requested:
        refusal_reasons.append(RATE_LIMIT_BYPASS_REFUSED)
    if request.aggressive_scraping_requested:
        refusal_reasons.append(AGGRESSIVE_SCRAPING_REFUSED)
    if estimated > safe_budget:
        refusal_reasons.append(RATE_LIMIT_GUARD)
    if not ws_ok:
        refusal_reasons.append(WEBSOCKET_LIMIT_GUARD)

    if estimated > SAFE_REST_WEIGHT_TARGET_PER_MINUTE * effective_egress:
        warnings.append("HIGH_REST_WEIGHT_PRESSURE")
    if request.time_range_items_expected > INFO_TIME_RANGE_PAGE_LIMIT:
        warnings.append("TIME_RANGE_PAGINATION_REQUIRED")
    if effective_egress > 1:
        warnings.append("MULTI_EGRESS_REQUIRES_STICKY_SAFE_SHARDING")

    if refusal_reasons:
        return BudgetPlan(
            status=PLAN_REFUSED,
            estimated_rest_weight=estimated,
            safe_rest_budget=safe_budget,
            rest_weight_remaining_after=max(0, safe_budget - estimated),
            ws_ok=ws_ok,
            refusal_reasons=refusal_reasons,
            warnings=warnings,
            recommendation=(
                "Reduire le batch, utiliser la rotation read-only, le cache local, "
                "les streams publics et attendre la fenetre suivante sans contourner les limites."
            ),
        )

    status = PLAN_DEGRADED if estimated >= floor(safe_budget * 0.80) or warnings else PLAN_OK
    return BudgetPlan(
        status=status,
        estimated_rest_weight=estimated,
        safe_rest_budget=safe_budget,
        rest_weight_remaining_after=max(0, safe_budget - estimated),
        ws_ok=ws_ok,
        warnings=warnings,
        recommendation=(
            "Budget accepte pour une collecte Hyperliquid read-only. "
            "Les donnees doivent rester evidence-only et toute action reste paper locale."
        ),
    )


def format_budget_plan(plan: BudgetPlan) -> str:
    lines = [
        "collection_budget=hyperliquid_read_only",
        f"status={plan.status}",
        f"allowed={str(plan.allowed).lower()}",
        f"estimated_rest_weight={plan.estimated_rest_weight}",
        f"safe_rest_budget={plan.safe_rest_budget}",
        f"rest_weight_remaining_after={plan.rest_weight_remaining_after}",
        f"ws_ok={str(plan.ws_ok).lower()}",
        f"read_only={str(plan.read_only).lower()}",
        f"execution={plan.execution}",
    ]
    if plan.refusal_reasons:
        lines.append("refusal_reasons=" + ",".join(plan.refusal_reasons))
    if plan.warnings:
        lines.append("warnings=" + ",".join(plan.warnings))
    if plan.recommendation:
        lines.append(f"recommendation={plan.recommendation}")
    return "\n".join(lines)


def _ws_within_limits(request: ReadOnlyBudgetRequest) -> bool:
    return (
        max(0, int(request.ws_connections)) <= WS_MAX_CONNECTIONS
        and max(0, int(request.ws_new_connections_per_minute)) <= WS_MAX_NEW_CONNECTIONS_PER_MINUTE
        and max(0, int(request.ws_subscriptions)) <= WS_MAX_SUBSCRIPTIONS
        and max(0, int(request.ws_unique_users)) <= WS_MAX_UNIQUE_USERS
        and max(0, int(request.ws_messages_per_minute)) <= WS_MAX_MESSAGES_PER_MINUTE
    )
