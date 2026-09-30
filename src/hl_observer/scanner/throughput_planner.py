from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.scanner.scan_budget import estimate_warm_scan_rest_cost


RATE_LIMIT_BYPASS_REFUSED = "RATE_LIMIT_BYPASS_REFUSED"
AGGRESSIVE_SCRAPING_REFUSED = "AGGRESSIVE_SCRAPING_REFUSED"
NETWORK_READ_DISABLED = "NETWORK_READ_DISABLED"
RATE_LIMIT_GUARD = "RATE_LIMIT_GUARD"
SAFE_ROTATION_ACTIVE = "SAFE_ROTATION_ACTIVE"
NO_WALLETS_SELECTED = "NO_WALLETS_SELECTED"
PLAN_OK = "PLAN_OK"


@dataclass(slots=True)
class ThroughputRequest:
    """Requested scan size before safe capping.

    This object is intentionally explicit about unsafe intent. HyperSmart should
    maximize read-only coverage, but it must never bypass provider limits.
    """

    requested_wallets: int
    network_read_enabled: bool = False
    ws_enabled: bool = False
    bypass_requested: bool = False
    aggressive_scraping_requested: bool = False
    rest_weight_remaining: int = 1200
    max_leaders_per_run: int = 50
    fills_expected_per_wallet: int = 200
    ws_requested_unique_users: int = 10
    ws_max_unique_users: int = 10
    ws_requested_subscriptions: int = 1000
    ws_max_subscriptions: int = 1000
    max_public_trade_wallets: int = 10_000
    requested_public_trade_wallets: int = 10_000


@dataclass(slots=True)
class ThroughputPlan:
    status: str
    requested_wallets: int
    selected_wallets: int
    deferred_wallets: int
    estimated_rest_weight: int
    rest_weight_remaining: int
    rest_weight_remaining_after: int
    user_specific_ws_users: int
    public_trade_wallet_cap: int
    ws_subscriptions_cap: int
    cache_first: bool = True
    read_only: bool = True
    execution: str = "forbidden"
    refusal_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_action: str = ""

    @property
    def starts(self) -> bool:
        """True when the scanner can start in observation mode."""

        return self.selected_wallets > 0 and self.status in {PLAN_OK, SAFE_ROTATION_ACTIVE}


def plan_safe_high_throughput_scan(request: ThroughputRequest) -> ThroughputPlan:
    """Build the fastest safe read-only scan plan that respects limits.

    The planner deliberately converts oversize requests into rotation instead of
    refusing the whole run. Only unsafe bypass/aggressive scraping requests and
    disabled network reads are hard refusals.
    """

    requested_wallets = max(0, int(request.requested_wallets))
    rest_weight_remaining = max(0, int(request.rest_weight_remaining))
    max_leaders = max(0, int(request.max_leaders_per_run))
    base_cap = min(requested_wallets, max_leaders)
    refusal_reasons: list[str] = []
    warnings: list[str] = []

    if not request.network_read_enabled:
        return ThroughputPlan(
            status="REFUSED",
            requested_wallets=requested_wallets,
            selected_wallets=0,
            deferred_wallets=requested_wallets,
            estimated_rest_weight=0,
            rest_weight_remaining=rest_weight_remaining,
            rest_weight_remaining_after=rest_weight_remaining,
            user_specific_ws_users=0,
            public_trade_wallet_cap=0,
            ws_subscriptions_cap=0,
            refusal_reasons=[NETWORK_READ_DISABLED],
            next_action="Relancer avec --network-read pour autoriser les lectures.",
        )

    if request.bypass_requested or request.aggressive_scraping_requested:
        if request.bypass_requested:
            refusal_reasons.append(RATE_LIMIT_BYPASS_REFUSED)
        if request.aggressive_scraping_requested:
            refusal_reasons.append(AGGRESSIVE_SCRAPING_REFUSED)
        return ThroughputPlan(
            status="REFUSED",
            requested_wallets=requested_wallets,
            selected_wallets=0,
            deferred_wallets=requested_wallets,
            estimated_rest_weight=0,
            rest_weight_remaining=rest_weight_remaining,
            rest_weight_remaining_after=rest_weight_remaining,
            user_specific_ws_users=0,
            public_trade_wallet_cap=0,
            ws_subscriptions_cap=0,
            refusal_reasons=refusal_reasons,
            warnings=["USE_SAFE_ROTATION_AND_PUBLIC_STREAMS"],
            next_action=(
                "Utiliser la rotation read-only, le WebSocket public, le cache local et le sticky sharding sain; "
                "ne pas ignorer les budgets car cela degrade la fraicheur et le PnL simule."
            ),
        )

    if base_cap <= 0:
        return ThroughputPlan(
            status="REFUSED",
            requested_wallets=requested_wallets,
            selected_wallets=0,
            deferred_wallets=requested_wallets,
            estimated_rest_weight=0,
            rest_weight_remaining=rest_weight_remaining,
            rest_weight_remaining_after=rest_weight_remaining,
            user_specific_ws_users=0,
            public_trade_wallet_cap=0,
            ws_subscriptions_cap=0,
            refusal_reasons=[NO_WALLETS_SELECTED],
            next_action="Importer ou découvrir des adresses complètes avant la prochaine rotation.",
        )

    selected = _largest_wallet_count_that_fits(
        base_cap,
        rest_weight_remaining=rest_weight_remaining,
        fills_expected_per_wallet=request.fills_expected_per_wallet,
    )
    estimated = estimate_warm_scan_rest_cost(
        wallets=selected,
        fills_expected_per_wallet=request.fills_expected_per_wallet,
    )
    if selected <= 0:
        return ThroughputPlan(
            status="REFUSED",
            requested_wallets=requested_wallets,
            selected_wallets=0,
            deferred_wallets=requested_wallets,
            estimated_rest_weight=estimated,
            rest_weight_remaining=rest_weight_remaining,
            rest_weight_remaining_after=rest_weight_remaining,
            user_specific_ws_users=0,
            public_trade_wallet_cap=0,
            ws_subscriptions_cap=0,
            refusal_reasons=[RATE_LIMIT_GUARD],
            next_action="Attendre la fenêtre suivante ou réduire les pages/fills par wallet.",
        )

    if selected < requested_wallets:
        warnings.append(SAFE_ROTATION_ACTIVE)
    if selected < base_cap:
        warnings.append(RATE_LIMIT_GUARD)

    ws_users = min(
        max(0, int(request.ws_requested_unique_users if request.ws_enabled else 0)),
        max(0, int(request.ws_max_unique_users)),
        selected,
    )
    ws_subscriptions = min(
        max(0, int(request.ws_requested_subscriptions if request.ws_enabled else 0)),
        max(0, int(request.ws_max_subscriptions)),
    )
    public_trade_cap = min(
        max(0, int(request.requested_public_trade_wallets)),
        max(0, int(request.max_public_trade_wallets)),
    )
    return ThroughputPlan(
        status=SAFE_ROTATION_ACTIVE if selected < requested_wallets else PLAN_OK,
        requested_wallets=requested_wallets,
        selected_wallets=selected,
        deferred_wallets=max(0, requested_wallets - selected),
        estimated_rest_weight=estimated,
        rest_weight_remaining=rest_weight_remaining,
        rest_weight_remaining_after=max(0, rest_weight_remaining - estimated),
        user_specific_ws_users=ws_users,
        public_trade_wallet_cap=public_trade_cap,
        ws_subscriptions_cap=ws_subscriptions,
        warnings=warnings,
        next_action="Lancer la rotation suivante avec un offset; le logiciel reste en observation si aucun signal n'est acceptable.",
    )


def format_throughput_plan(plan: ThroughputPlan) -> str:
    lines = [
        "throughput_plan=read_only_safe",
        f"status={plan.status}",
        f"scanner_starts={'yes' if plan.starts else 'no'}",
        f"requested_wallets={plan.requested_wallets}",
        f"selected_wallets_now={plan.selected_wallets}",
        f"deferred_wallets_rotation={plan.deferred_wallets}",
        f"estimated_rest_weight={plan.estimated_rest_weight}",
        f"rest_weight_remaining_after={plan.rest_weight_remaining_after}",
        f"user_specific_ws_users={plan.user_specific_ws_users}",
        f"public_trade_wallet_cap={plan.public_trade_wallet_cap}",
        f"ws_subscriptions_cap={plan.ws_subscriptions_cap}",
        f"cache_first={str(plan.cache_first).lower()}",
        f"read_only={str(plan.read_only).lower()}",
        f"execution={plan.execution}",
    ]
    if plan.refusal_reasons:
        lines.append("refusal_reasons=" + ",".join(plan.refusal_reasons))
    if plan.warnings:
        lines.append("warnings=" + ",".join(plan.warnings))
    if plan.next_action:
        lines.append(f"next_action={plan.next_action}")
    return "\n".join(lines)


def _largest_wallet_count_that_fits(
    cap: int,
    *,
    rest_weight_remaining: int,
    fills_expected_per_wallet: int,
) -> int:
    for wallets in range(max(0, cap), 0, -1):
        estimated = estimate_warm_scan_rest_cost(
            wallets=wallets,
            fills_expected_per_wallet=fills_expected_per_wallet,
        )
        if estimated <= rest_weight_remaining:
            return wallets
    return 0
