from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.scanner.throughput_planner import ThroughputPlan, ThroughputRequest, plan_safe_high_throughput_scan


@dataclass(frozen=True, slots=True)
class FreshScanStrategyRequest:
    requested_wallet_universe: int = 50_000
    network_read_enabled: bool = False
    cycle_seconds: int = 15
    rest_weight_remaining: int = 1200
    leaders_per_user_stream: int = 10
    public_trade_wallet_cap_requested: int = 10_000
    candidate_refresh_every_polls: int = 1
    gap_recovery_every_polls: int = 8
    stale_signal_count: int = 0
    fresh_leader_count: int = 0
    fresh_delta_count: int = 0
    fresh_opportunity_groups: int = 0
    bypass_requested: bool = False
    aggressive_scraping_requested: bool = False


@dataclass(frozen=True, slots=True)
class FreshScanStrategyPlan:
    status: str
    scanner_starts: bool
    public_trade_scan_every_polls: int
    public_trade_duration_seconds: int
    public_trade_wallet_cap: int
    user_fills_ws_users: int
    user_fills_duration_seconds: int
    gap_recovery_every_polls: int
    rest_wallets_per_gap_recovery: int
    open_orders_scope: str
    all_mids_scope: str
    stale_pressure: str
    next_actions: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    refusal_reasons: tuple[str, ...] = field(default_factory=tuple)
    read_only: bool = True
    execution: str = "forbidden"
    throughput_plan: ThroughputPlan | None = None


def plan_fresh_scan_strategy(request: FreshScanStrategyRequest) -> FreshScanStrategyPlan:
    """Plan maximum fresh coverage without bypassing provider limits.

    The strategy is built around Hyperliquid's constraints: broad public streams
    discover wallets cheaply, while user-specific streams and /info are reserved
    for the hottest shortlist. It never suggests spam, bypass, or execution.
    """

    cycle_seconds = max(5, int(request.cycle_seconds))
    public_scan_every = max(1, int(request.candidate_refresh_every_polls))
    gap_recovery_every = max(1, int(request.gap_recovery_every_polls))
    stale_pressure = _stale_pressure(request)
    warnings: list[str] = []
    next_actions: list[str] = []

    if stale_pressure in {"HIGH", "CRITICAL"} or request.fresh_leader_count <= 0:
        public_scan_every = 1
        gap_recovery_every = min(gap_recovery_every, 8)
        next_actions.append("Scanner les trades publics a chaque cycle pour reconstruire une shortlist chaude.")
    if request.fresh_delta_count <= 0:
        next_actions.append("Faire tourner userFills WebSocket sur 10 leaders chauds; attendre des fills frais avant toute position virtuelle.")
    if request.fresh_opportunity_groups <= 0:
        next_actions.append("Chercher des clusters meme coin + meme sens dans une fenetre 4s; ne pas simuler de position sans cluster/edge.")

    throughput = plan_safe_high_throughput_scan(
        ThroughputRequest(
            requested_wallets=max(0, int(request.requested_wallet_universe)),
            network_read_enabled=request.network_read_enabled,
            ws_enabled=True,
            bypass_requested=request.bypass_requested,
            aggressive_scraping_requested=request.aggressive_scraping_requested,
            rest_weight_remaining=max(0, int(request.rest_weight_remaining)),
            max_leaders_per_run=max(1, min(10, int(request.leaders_per_user_stream))),
            fills_expected_per_wallet=200,
            ws_requested_unique_users=max(1, min(10, int(request.leaders_per_user_stream))),
            requested_public_trade_wallets=max(0, int(request.public_trade_wallet_cap_requested)),
            max_public_trade_wallets=10_000,
        )
    )
    if throughput.refusal_reasons:
        return FreshScanStrategyPlan(
            status="REFUSED",
            scanner_starts=False,
            public_trade_scan_every_polls=0,
            public_trade_duration_seconds=0,
            public_trade_wallet_cap=0,
            user_fills_ws_users=0,
            user_fills_duration_seconds=0,
            gap_recovery_every_polls=0,
            rest_wallets_per_gap_recovery=0,
            open_orders_scope="disabled",
            all_mids_scope="disabled",
            stale_pressure=stale_pressure,
            next_actions=tuple(next_actions or [throughput.next_action]),
            refusal_reasons=tuple(throughput.refusal_reasons),
            warnings=tuple(throughput.warnings),
            throughput_plan=throughput,
        )

    public_duration = max(5, min(cycle_seconds - 3, 12))
    user_fills_duration = max(5, min(cycle_seconds - 3, 12))
    rest_wallets = max(0, min(throughput.selected_wallets, throughput.user_specific_ws_users or 10))
    if throughput.deferred_wallets > 0:
        warnings.append("SAFE_ROTATION_ACTIVE")
        next_actions.append("Utiliser leader-offset a chaque cycle pour couvrir le pool sans depasser 10 users WS.")
    if throughput.public_trade_wallet_cap >= 10_000:
        warnings.append("PUBLIC_TRADE_LOCAL_CAP_HIGH_MEMORY_ONLY")

    return FreshScanStrategyPlan(
        status="FRESH_SCAN_ACTIVE" if throughput.starts else "OBSERVE_ONLY",
        scanner_starts=throughput.starts,
        public_trade_scan_every_polls=public_scan_every,
        public_trade_duration_seconds=public_duration,
        public_trade_wallet_cap=throughput.public_trade_wallet_cap,
        user_fills_ws_users=throughput.user_specific_ws_users,
        user_fills_duration_seconds=user_fills_duration,
        gap_recovery_every_polls=gap_recovery_every,
        rest_wallets_per_gap_recovery=rest_wallets,
        open_orders_scope="hot_shortlist_only_gap_recovery",
        all_mids_scope="once_per_cycle_or_public_trade_price_fallback",
        stale_pressure=stale_pressure,
        next_actions=tuple(next_actions or ["Continuer la rotation; accepter seulement les signaux frais avec edge net positif."]),
        warnings=tuple(dict.fromkeys([*warnings, *throughput.warnings])),
        throughput_plan=throughput,
    )


def format_fresh_scan_strategy(plan: FreshScanStrategyPlan) -> str:
    lines = [
        "fresh_scan_plan=read_only_safe",
        f"status={plan.status}",
        f"scanner_starts={'yes' if plan.scanner_starts else 'no'}",
        f"public_trade_scan_every_polls={plan.public_trade_scan_every_polls}",
        f"public_trade_duration_seconds={plan.public_trade_duration_seconds}",
        f"public_trade_wallet_cap={plan.public_trade_wallet_cap}",
        f"user_fills_ws_users={plan.user_fills_ws_users}/10",
        f"user_fills_duration_seconds={plan.user_fills_duration_seconds}",
        f"gap_recovery_every_polls={plan.gap_recovery_every_polls}",
        f"rest_wallets_per_gap_recovery={plan.rest_wallets_per_gap_recovery}",
        f"open_orders_scope={plan.open_orders_scope}",
        f"all_mids_scope={plan.all_mids_scope}",
        f"stale_pressure={plan.stale_pressure}",
        f"read_only={str(plan.read_only).lower()}",
        f"execution={plan.execution}",
        "real_orders_created=0",
        "simulation_positions_are_virtual=true",
    ]
    if plan.refusal_reasons:
        lines.append("refusal_reasons=" + ",".join(plan.refusal_reasons))
    if plan.warnings:
        lines.append("warnings=" + ",".join(plan.warnings))
    if plan.next_actions:
        lines.append("next_actions:")
        lines.extend(f"- {action}" for action in plan.next_actions)
    return "\n".join(lines)


def _stale_pressure(request: FreshScanStrategyRequest) -> str:
    stale = max(0, int(request.stale_signal_count))
    fresh_leaders = max(0, int(request.fresh_leader_count))
    fresh_deltas = max(0, int(request.fresh_delta_count))
    if fresh_leaders <= 0 and stale > 0:
        return "CRITICAL"
    if stale >= 1000 and fresh_deltas <= 0:
        return "CRITICAL"
    if stale >= 100 or fresh_deltas <= 0:
        return "HIGH"
    if stale > 0:
        return "MEDIUM"
    return "LOW"

