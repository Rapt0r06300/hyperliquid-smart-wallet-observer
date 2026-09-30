from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.data_sources.acquisition_engine import (
    AcquisitionStatus,
    FetchBatch,
    FetchRequest,
    PersistentFetchQueue,
    RequestBudgetManager,
)


@dataclass(frozen=True, slots=True)
class FreshDataPlanRequest:
    network_read_enabled: bool = False
    active_coins: tuple[str, ...] = ("BTC", "ETH", "SOL", "HYPE")
    hot_wallets: tuple[str, ...] = ()
    requested_wallet_universe: int = 50_000
    rest_weight_remaining: int = 1200
    max_hot_wallets: int = 10
    max_items: int = 128
    now_ms: int = 0
    gap_recovery: bool = False
    stale_pressure: str = "LOW"


@dataclass(frozen=True, slots=True)
class FreshDataPlan:
    status: str
    network_read_enabled: bool
    requested_wallet_universe: int
    selected_requests: tuple[FetchRequest, ...]
    blocked_reasons: tuple[tuple[str, int], ...]
    pending_after_batch: int
    rest_weight_remaining_after: int
    public_streams: int
    hot_user_streams: int
    rest_gap_recovery_requests: int
    next_actions: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    read_only: bool = True
    execution: str = "forbidden"


def build_fresh_data_plan(request: FreshDataPlanRequest) -> FreshDataPlan:
    """Plan the next freshest read-only acquisition cycle.

    Public WebSocket streams are modeled as zero REST weight. User-specific
    streams stay capped to 10 users; REST reads are reserved for gap recovery.
    """

    queue = PersistentFetchQueue()
    now_ms = max(0, int(request.now_ms))
    active_coins = _clean_coins(request.active_coins)
    hot_wallets = _unique_wallets(request.hot_wallets)[: max(0, min(10, int(request.max_hot_wallets)))]
    warnings: list[str] = []
    next_actions: list[str] = []

    for coin in active_coins:
        queue.enqueue(
            FetchRequest(
                request_id=f"publicTrades:{coin}:{now_ms}",
                provider_name="OfficialWsProvider",
                endpoint="ws/publicTrades",
                request_type="publicTrades",
                coin=coin,
                weight=0,
                priority=100.0,
                network_required=True,
                created_at_ms=now_ms,
                ttl_ms=5_000,
                metadata={"read_only": True, "purpose": "discover fresh wallets"},
            )
        )

    queue.enqueue(
        FetchRequest(
            request_id=f"allMids:{now_ms}",
            provider_name="OfficialInfoProvider",
            endpoint="/info",
            request_type="allMids",
            weight=2,
            priority=98.0,
            network_required=True,
            created_at_ms=now_ms,
            ttl_ms=3_000,
            metadata={"read_only": True, "purpose": "current marks for paper PnL"},
        )
    )

    for index, wallet in enumerate(hot_wallets):
        priority = 95.0 - index * 0.01
        queue.enqueue(
            FetchRequest(
                request_id=f"userFillsWs:{wallet}:{now_ms}",
                provider_name="OfficialWsProvider",
                endpoint="ws/userFills",
                request_type="userFills",
                wallet_address=wallet,
                weight=0,
                priority=priority,
                network_required=True,
                created_at_ms=now_ms,
                ttl_ms=20_000,
                metadata={"read_only": True, "purpose": "fresh leader deltas"},
            )
        )
        if request.gap_recovery or request.stale_pressure in {"HIGH", "CRITICAL"}:
            queue.enqueue(
                FetchRequest(
                    request_id=f"clearinghouseState:{wallet}:{now_ms}",
                    provider_name="OfficialInfoProvider",
                    endpoint="/info",
                    request_type="clearinghouseState",
                    wallet_address=wallet,
                    weight=2,
                    priority=70.0 - index * 0.01,
                    network_required=True,
                    created_at_ms=now_ms,
                    ttl_ms=30_000,
                    metadata={"read_only": True, "purpose": "gap recovery snapshot"},
                )
            )
            queue.enqueue(
                FetchRequest(
                    request_id=f"openOrders:{wallet}:{now_ms}",
                    provider_name="OfficialInfoProvider",
                    endpoint="/info",
                    request_type="openOrders",
                    wallet_address=wallet,
                    weight=2,
                    priority=65.0 - index * 0.01,
                    network_required=True,
                    created_at_ms=now_ms,
                    ttl_ms=30_000,
                    metadata={"read_only": True, "purpose": "context only"},
                )
            )

    budget = RequestBudgetManager(
        network_read_enabled=request.network_read_enabled,
        rest_weight_remaining=max(0, int(request.rest_weight_remaining)),
    )
    batch = queue.due_batch(now_ms=now_ms, max_items=max(0, int(request.max_items)), budget=budget)
    blocked = _blocked_counts(batch)
    selected = batch.selected
    public_streams = sum(1 for item in selected if item.request_type == "publicTrades")
    hot_user_streams = sum(1 for item in selected if item.request_type == "userFills")
    rest_gap_recovery = sum(1 for item in selected if item.request_type in {"clearinghouseState", "openOrders"})
    if not request.network_read_enabled:
        next_actions.append("Relancer avec --network-read pour autoriser uniquement les lectures read-only.")
    if public_streams < len(active_coins):
        warnings.append("PUBLIC_STREAMS_NOT_FULLY_SELECTED")
    if not hot_wallets:
        next_actions.append("Laisser publicTrades/promotions alimenter la shortlist chaude avant userFills.")
    if request.stale_pressure in {"HIGH", "CRITICAL"}:
        next_actions.append("Maintenir publicTrades a chaque cycle et utiliser gap recovery REST borne sur les 10 leaders chauds.")
    if hot_user_streams >= 10:
        warnings.append("USER_SPECIFIC_WS_CAP_REACHED")
    status = "FRESH_DATA_READY" if selected and request.network_read_enabled else "FRESH_DATA_BLOCKED"
    if request.network_read_enabled and not selected:
        status = "FRESH_DATA_WAITING"
    return FreshDataPlan(
        status=status,
        network_read_enabled=request.network_read_enabled,
        requested_wallet_universe=max(0, int(request.requested_wallet_universe)),
        selected_requests=selected,
        blocked_reasons=blocked,
        pending_after_batch=batch.remaining_pending,
        rest_weight_remaining_after=budget.rest_weight_remaining,
        public_streams=public_streams,
        hot_user_streams=hot_user_streams,
        rest_gap_recovery_requests=rest_gap_recovery,
        next_actions=tuple(next_actions or ["Executer le batch selectionne puis reclasser la shortlist avec les evenements frais."]),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def format_fresh_data_plan(plan: FreshDataPlan) -> str:
    lines = [
        "fresh_data_plan=read_only_safe",
        f"status={plan.status}",
        f"network_read={'enabled' if plan.network_read_enabled else 'disabled'}",
        f"requested_wallet_universe={plan.requested_wallet_universe}",
        f"selected_requests={len(plan.selected_requests)}",
        f"public_streams={plan.public_streams}",
        f"hot_user_streams={plan.hot_user_streams}/10",
        f"rest_gap_recovery_requests={plan.rest_gap_recovery_requests}",
        f"pending_after_batch={plan.pending_after_batch}",
        f"rest_weight_remaining_after={plan.rest_weight_remaining_after}",
        f"read_only={str(plan.read_only).lower()}",
        f"execution={plan.execution}",
        "real_orders_created=0",
        "simulation_positions_are_virtual=true",
    ]
    if plan.blocked_reasons:
        lines.append("blocked_reasons=" + ",".join(f"{reason}:{count}" for reason, count in plan.blocked_reasons))
    if plan.warnings:
        lines.append("warnings=" + ",".join(plan.warnings))
    lines.append("selected:")
    if plan.selected_requests:
        for item in plan.selected_requests[:20]:
            wallet = item.wallet_address or "-"
            coin = item.coin or "-"
            lines.append(f"- {item.provider_name} {item.request_type} wallet={wallet} coin={coin} weight={item.weight} priority={item.priority:.2f}")
        if len(plan.selected_requests) > 20:
            lines.append(f"- ... {len(plan.selected_requests) - 20} more")
    else:
        lines.append("- none")
    lines.append("next_actions:")
    lines.extend(f"- {action}" for action in plan.next_actions)
    return "\n".join(lines)


def _blocked_counts(batch: FetchBatch) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for item in batch.blocked:
        if item.status != AcquisitionStatus.BLOCKED:
            continue
        counts[item.reason] = counts.get(item.reason, 0) + 1
    return tuple(sorted(counts.items()))


def _clean_coins(coins: tuple[str, ...]) -> tuple[str, ...]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for coin in coins:
        value = str(coin).strip().upper()
        if not value or value in seen or value.startswith(("@", "#")):
            continue
        seen.add(value)
        cleaned.append(value)
    return tuple(cleaned[:80])


def _unique_wallets(wallets: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for wallet in wallets:
        value = str(wallet).strip().lower()
        if value in seen or not value.startswith("0x") or len(value) != 42:
            continue
        seen.add(value)
        unique.append(value)
    return tuple(unique)
