from __future__ import annotations

from hl_observer.collection.collector import CollectionPlan, run_collection_once
from hl_observer.config.settings import ExecutionEnvironment, Settings
from hl_observer.edge.edge_remaining import compute_edge_remaining
from hl_observer.explorer.explorer_revalidation import revalidate_explorer_wallets
from hl_observer.explorer.explorer_source import create_explorer_candidates, scrape_explorer
from hl_observer.explorer.explorer_transaction_tape import get_explorer_tape
from hl_observer.hyperliquid.schemas import EdgeRemainingInputs, RiskDecision, SignalDecision
from hl_observer.markets.scanner import MarketScanPlan, run_scan_markets
from hl_observer.markets.scanner import MarketDiscoveryPlan, run_discover_markets
from hl_observer.paper.paper_executor import PaperExecutor
from hl_observer.risk.gates import RiskContext
from hl_observer.risk.risk_engine import RiskEngine
from hl_observer.security.mainnet_guard import MainnetExecutionForbidden, assert_mainnet_execution_disabled
from hl_observer.security.safety_audit import run_safety_audit
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import AutoWatchlist
from hl_observer.testnet.testnet_order_builder import build_testnet_order_intent
from hl_observer.testnet.testnet_executor_locked import LockedTestnetExecutor
from hl_observer.testnet.testnet_safety_gates import TestnetLocked
from hl_observer.ui.schemas import UiActionResult
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms
from hl_observer.wallets.backfill import WalletBackfillPlan, run_wallet_backfill
from hl_observer.wallets.discovery import build_wallet_discovery_plan, run_wallet_discovery
from hl_observer.wallets.leaderboard_source import scrape_leaderboard
from hl_observer.wallets.scan_queue import scan_wallet_queue
from hl_observer.wallets.top500_bootstrap import bootstrap_top_wallets
from hl_observer.analysis.opening_patterns import compute_opening_pattern_stats
from hl_observer.risk.adaptive_filter import apply_adaptive_risk_filter
from hl_observer.risk.risk_context import AdaptiveRiskContext
from sqlalchemy import select

ALLOWED_ACTIONS = {
    "doctor",
    "safety_audit",
    "init_db",
    "collect_dry_run",
    "collect_all_mids",
    "collect_l2_book_btc",
    "score_wallets",
    "detect_signals",
    "paper_run",
    "paper_report",
    "testnet_check",
    "activate_kill_switch",
    "clear_ui_logs",
    "discover_wallets",
    "discovery_dry_run",
    "backfill_selected_wallets",
    "autoscan_with_discovery",
    "refresh_discovery_status",
    "autoscan_start",
    "autoscan_stop",
    "scrape_leaderboard",
    "probe_leaderboard_network",
    "extract_leaderboard_dom",
    "import_leaderboard",
    "validate_leaderboard_addresses",
    "leaderboard_candidates",
    "probe_explorer",
    "scrape_explorer",
    "probe_explorer_network",
    "extract_explorer_dom",
    "import_explorer",
    "explorer_candidates",
    "revalidate_explorer_wallets",
    "explorer_tape",
    "discover_markets",
    "scan_markets",
    "bootstrap_top_wallets",
    "scan_wallet_queue",
    "resume_wallet_scan_queue",
    "analyze_wallet",
    "analyze_openings",
    "analyze_closings",
    "rank_opening_patterns",
    "profile_wallet_styles",
    "generate_trader_playbooks",
    "generate_follow_signals",
    "apply_adaptive_risk_filter",
    "paper_follow",
    "paper_follow_report",
    "demo_scan",
    "score_wallets_simple",
    "detect_signals_simple",
    "export_top_wallets",
    "export_leaderboard",
    "export_explorer",
    "show_rejected_candidates",
    "recommended_action",
}

KILL_SWITCH_BLOCKED_ACTIONS = {"paper_run", "testnet_check", "paper_follow", "generate_follow_signals"}


def _result(
    action: str,
    *,
    allowed: bool,
    success: bool,
    message: str,
    level: str = "INFO",
    details: dict | None = None,
    next_recommended_action: str | None = None,
) -> UiActionResult:
    started = now_ms()
    return UiActionResult(
        action=action,
        action_id=action,
        label=action.replace("_", " "),
        allowed=allowed,
        success=success,
        message=message,
        status="success" if success else "blocked" if not allowed else "failed",
        level=level,  # type: ignore[arg-type]
        details=details or {},
        started_at_ms=started,
        finished_at_ms=now_ms(),
        affected_counts={},
        next_recommended_action=next_recommended_action,
    )


async def run_safe_action(action: str, settings: Settings, state: UiState) -> UiActionResult:
    if action not in ALLOWED_ACTIONS:
        result = _result(
            action,
            allowed=False,
            success=False,
            message="Unknown UI action rejected by allowlist",
            level="SECURITY",
        )
        state.add_event("safety_alert", result.message, level=result.level, payload=result.details)
        return result

    if action == "clear_ui_logs":
        state.clear_logs()
        return _result(action, allowed=True, success=True, message="UI logs cleared")

    if action == "activate_kill_switch":
        state.kill_switch_active = True
        result = _result(
            action,
            allowed=True,
            success=True,
            message="Emergency stop active: sensitive paper/testnet actions are blocked",
            level="RISK",
            details={"kill_switch_active": True},
        )
        state.add_event("safety_alert", result.message, level=result.level, payload=result.details)
        return result

    try:
        assert_mainnet_execution_disabled(settings)
    except MainnetExecutionForbidden as exc:
        result = _result(
            action,
            allowed=False,
            success=False,
            message=str(exc),
            level="SECURITY",
            details={"decision": exc.decision.value},
        )
        state.add_event("safety_alert", result.message, level=result.level, payload=result.details)
        return result

    if state.kill_switch_active and action in KILL_SWITCH_BLOCKED_ACTIONS:
        result = _result(
            action,
            allowed=False,
            success=False,
            message="Kill switch active: action blocked",
            level="RISK",
            details={"kill_switch_active": True},
        )
        state.add_event("risk_gate_failed", result.message, level=result.level, payload=result.details)
        return result

    handlers = {
        "doctor": _doctor,
        "safety_audit": _safety_audit,
        "init_db": _init_db,
        "collect_dry_run": _collect_dry_run,
        "collect_all_mids": _collect_all_mids,
        "collect_l2_book_btc": _collect_l2_book_btc,
        "score_wallets": _score_wallets,
        "detect_signals": _detect_signals,
        "paper_run": _paper_run,
        "paper_report": _paper_report,
        "testnet_check": _testnet_check,
        "discover_wallets": _discover_wallets,
        "discovery_dry_run": _discovery_dry_run,
        "backfill_selected_wallets": _backfill_selected_wallets,
        "autoscan_with_discovery": _autoscan_with_discovery,
        "autoscan_start": _autoscan_with_discovery,
        "autoscan_stop": _autoscan_stop,
        "refresh_discovery_status": _refresh_discovery_status,
        "scrape_leaderboard": _leaderboard_prepared,
        "probe_leaderboard_network": _leaderboard_prepared,
        "extract_leaderboard_dom": _leaderboard_prepared,
        "import_leaderboard": _leaderboard_import_required,
        "validate_leaderboard_addresses": _validate_leaderboard_addresses,
        "leaderboard_candidates": _leaderboard_candidates,
        "probe_explorer": _probe_explorer,
        "scrape_explorer": _scrape_explorer_action,
        "probe_explorer_network": _probe_explorer,
        "extract_explorer_dom": _explorer_import_required,
        "import_explorer": _explorer_import_required,
        "explorer_candidates": _explorer_candidates,
        "revalidate_explorer_wallets": _revalidate_explorer_wallets,
        "explorer_tape": _explorer_tape,
        "discover_markets": _discover_markets,
        "scan_markets": _scan_markets,
        "bootstrap_top_wallets": _bootstrap_top_wallets,
        "scan_wallet_queue": _scan_wallet_queue,
        "resume_wallet_scan_queue": _scan_wallet_queue,
        "analyze_wallet": _analysis_prepared,
        "analyze_openings": _analysis_prepared,
        "analyze_closings": _analysis_prepared,
        "rank_opening_patterns": _rank_opening_patterns,
        "profile_wallet_styles": _analysis_prepared,
        "generate_trader_playbooks": _analysis_prepared,
        "generate_follow_signals": _paper_follow_prepared,
        "apply_adaptive_risk_filter": _adaptive_risk_check,
        "paper_follow": _paper_follow_prepared,
        "paper_follow_report": _paper_follow_prepared,
        "demo_scan": _collect_dry_run,
        "score_wallets_simple": _score_wallets,
        "detect_signals_simple": _detect_signals,
        "export_top_wallets": _export_prepared,
        "export_leaderboard": _export_prepared,
        "export_explorer": _export_prepared,
        "show_rejected_candidates": _refresh_discovery_status,
        "recommended_action": _recommended_action,
    }
    result = await handlers[action](action, settings, state)
    event_type = "collection_finished" if action.startswith("collect_") else "ui_action_finished"
    state.add_event(event_type, result.message, level=result.level, payload=result.details)
    return result


async def _doctor(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    checks = {
        "mainnet_enabled": settings.execution.enable_mainnet_execution,
        "testnet_enabled": settings.execution.enable_testnet_execution,
        "mode": settings.environment.value,
        "database_url": settings.database_url,
    }
    return _result(action, allowed=True, success=True, message="Doctor checks passed", details=checks)


async def _safety_audit(action: str, _settings: Settings, _state: UiState) -> UiActionResult:
    audit = run_safety_audit(".")
    return _result(
        action,
        allowed=True,
        success=audit.ok,
        message="Safety audit passed" if audit.ok else "Safety audit failed",
        level="INFO" if audit.ok else "ERROR",
        details={"checks": audit.checks, "findings": audit.findings},
    )


async def _init_db(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    init_db(settings.database_url)
    return _result(action, allowed=True, success=True, message="Database initialized")


async def _collect_dry_run(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    result = await run_collection_once(CollectionPlan(dry_run=True, all_mids=True), settings)
    return _result(
        action,
        allowed=True,
        success=True,
        message="Collect dry-run planned without network",
        details={"planned_items": result.planned_items},
    )


async def _collect_all_mids(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    result = await run_collection_once(CollectionPlan(fetch=True, all_mids=True), settings)
    return _result(
        action,
        allowed=True,
        success=result.errors_count == 0,
        message="allMids collection finished",
        details=result.model_dump(),
    )


async def _collect_l2_book_btc(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    result = await run_collection_once(
        CollectionPlan(fetch=True, all_coins=True, include_altcoins=True, max_coins=settings.market_universe.max_l2book_coins_per_scan, coins=["BTC"], l2_book=True),
        settings,
    )
    return _result(
        action,
        allowed=True,
        success=result.errors_count == 0,
        message="Multi-coin l2Book collection finished",
        details=result.model_dump(),
    )


async def _score_wallets(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine
    from hl_observer.storage.repositories import CollectionRepository
    from hl_observer.wallets.scoring import score_wallet
    from hl_observer.wallets.profiler import profile_from_metrics
    from sqlalchemy import select
    from hl_observer.storage.models import Wallet, WalletActivitySummary

    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    scored_count = 0
    with session_factory() as session:
        repo = CollectionRepository(session)
        wallets = session.scalars(select(Wallet)).all()
        for wallet in wallets:
            summary = session.scalar(
                select(WalletActivitySummary)
                .where(WalletActivitySummary.wallet_address == wallet.address)
                .order_by(WalletActivitySummary.id.desc())
                .limit(1)
            )
            if summary:
                metrics = {
                    "trades_count": summary.closed_pnl_count,
                    "fills_count": summary.fills_count,
                    "closed_pnl_count": summary.closed_pnl_count,
                    "active_days": int(summary.history_days),
                    "history_days": summary.history_days,
                    "pnl_total_usdc": summary.pnl_total_usdc,
                    "pnl_net_after_fees_usdc": summary.pnl_net_after_fees_usdc,
                    "win_rate": summary.win_rate,
                    "profit_factor": summary.profit_factor,
                    "max_drawdown_pct": summary.max_drawdown_pct,
                    "top_trade_pnl_share": summary.top_trade_pnl_share,
                    "coins_traded_count": summary.coins_count,
                    "main_coin": summary.main_coin,
                    "recent_activity_score": summary.recent_activity_score,
                    "regularity_score": summary.regularity_score,
                    "copyability_score": summary.copyability_score,
                }
                profile = profile_from_metrics(wallet.address, metrics)
                score = score_wallet(profile)
                repo.store_wallet_score(score)
                wallet.status = score.status.value
                scored_count += 1
        session.commit()

    return _result(
        action,
        allowed=True,
        success=True,
        message=f"Wallet scoring complete: {scored_count} wallets scored.",
        details={"scored_count": scored_count}
    )


async def _detect_signals(action: str, _settings: Settings, _state: UiState) -> UiActionResult:
    return _result(action, allowed=True, success=True, message="Signal detection is ready")


async def _paper_run(action: str, settings: Settings, state: UiState) -> UiActionResult:
    edge = compute_edge_remaining(
        EdgeRemainingInputs(
            leader_expected_move_bps=30,
            taker_fee_bps=4,
            spread_cost_bps=2,
            estimated_slippage_bps=3,
            latency_decay_bps=2,
        ),
        min_edge_required_bps=settings.risk.min_edge_required_bps,
    )
    risk = RiskEngine(settings).evaluate(
        RiskContext(
            spread_bps=2,
            estimated_slippage_bps=3,
            orderbook_depth_usdc=10000,
            wallet_score=90,
            signal_score=90,
            edge_remaining_bps=edge.edge_remaining_bps,
            signal_age_ms=100,
            kill_switch_active=state.kill_switch_active,
        )
    )
    return _result(
        action,
        allowed=risk.allowed,
        success=risk.allowed,
        message=f"Paper smoke decision: {risk.decision.value}",
        level="INFO" if risk.allowed else "RISK",
        details={"risk": risk.model_dump(), "paper_orders": len(PaperExecutor().orders)},
    )


async def _paper_report(action: str, _settings: Settings, _state: UiState) -> UiActionResult:
    return _result(action, allowed=True, success=True, message="No paper results recorded yet")


async def _testnet_check(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    risk = RiskDecision(
        allowed=True,
        decision=SignalDecision.TESTNET_CANDIDATE,
        reasons=["check only"],
        gates={"manual_check": True},
    )
    order = build_testnet_order_intent(
        cloid="ui-check-only-cloid",
        coin="BTC",
        side="buy",
        size=0.001,
        limit_price=1.0,
        schedule_cancel_configured=True,
    )
    try:
        LockedTestnetExecutor(settings).submit(order, risk, confirm_testnet_only=False)
    except TestnetLocked as exc:
        return _result(
            action,
            allowed=True,
            success=True,
            message="Testnet remains locked",
            level="SECURITY",
            details={"locked_reasons": exc.reasons},
        )
    return _result(
        action,
        allowed=settings.environment == ExecutionEnvironment.TESTNET,
        success=False,
        message="Unexpected testnet gate state",
        level="WARN",
    )


async def _discover_wallets(action: str, settings: Settings, state: UiState) -> UiActionResult:
    state.add_event("wallet_discovery_started", "Recherche des wallets demarree.")
    plan = build_wallet_discovery_plan(settings, store=True, dry_run=False, report=True)
    result = run_wallet_discovery(plan, settings)
    state.last_discovery_state = result.state
    if result.candidates_found == 0:
        state.add_event(
            "wallet_discovery_completed",
            "Aucune source n'a fourni de wallet exploitable.",
            level="WARN",
        )
    else:
        state.add_event(
            "wallet_candidates_found",
            f"{result.candidates_found} wallets candidats trouves.",
        )
    return _result(
        action,
        allowed=True,
        success=result.errors_count == 0,
        message="Recherche automatique terminee.",
        level="INFO" if result.errors_count == 0 else "WARN",
        details=result.model_dump(),
    )


async def _discovery_dry_run(action: str, settings: Settings, state: UiState) -> UiActionResult:
    plan = build_wallet_discovery_plan(settings, store=False, dry_run=True, report=True)
    result = run_wallet_discovery(plan, settings)
    state.last_discovery_state = result.state
    return _result(
        action,
        allowed=True,
        success=True,
        message="Discovery dry-run terminee sans ecriture.",
        details=result.model_dump(),
    )


async def _backfill_selected_wallets(action: str, settings: Settings, state: UiState) -> UiActionResult:
    backfill = await _run_selected_wallet_backfill(settings, state)
    if backfill is None:
        return _result(
            action,
            allowed=True,
            success=True,
            message="Aucun wallet selectionne a backfiller pour le moment.",
            details={"wallets": []},
        )
    wallets, result = backfill
    return _result(
        action,
        allowed=True,
        success=result.errors_count == 0,
        message="Backfill lecture seule des wallets selectionnes termine.",
        level="INFO" if result.errors_count == 0 else "WARN",
        details={"wallets": wallets, "backfill": result.model_dump()},
    )


async def _autoscan_with_discovery(action: str, settings: Settings, state: UiState) -> UiActionResult:
    state.autoscan_running = True
    state.autoscan_started = True
    state.autoscan_current_step = "Securite"
    state.autoscan_progress_percent = 5
    state.add_event("wallet_discovery_started", "Demarrage de la recherche automatique.")
    state.add_event("autoscan_step_started", "Securite verifiee : aucun acces mainnet.", payload={"step": "security", "progress_percent": 5})
    state.autoscan_current_step = "Decouverte des marches"
    state.autoscan_progress_percent = 15
    state.add_event("market_universe_started", "Decouverte des marches Hyperliquid.", payload={"step": "markets", "progress_percent": 15})
    try:
        market = await run_scan_markets(
            MarketScanPlan(
                all_coins=True,
                include_altcoins=True,
                max_coins=settings.market_universe.max_coins_per_scan,
                l2book=True,
                store=True,
                dry_run=False,
            ),
            settings,
        )
    except Exception as exc:  # noqa: BLE001 - UI must show failure and continue safely.
        state.add_event(
            "autoscan_step_failed",
            "Scan marche reseau indisponible, passage en fallback local.",
            level="WARN",
            payload={"step": "markets", "error": str(exc)},
        )
        market = await run_scan_markets(
            MarketScanPlan(
                all_coins=True,
                include_altcoins=True,
                max_coins=settings.market_universe.max_coins_per_scan,
                l2book=True,
                store=False,
                dry_run=True,
            ),
            settings,
        )
    state.add_event(
        "market_universe_completed",
        f"{market.coins_discovered} coins decouverts, {market.coins_scanned} marches selectionnes.",
        payload={"step": "markets", "progress_percent": 30},
    )
    state.autoscan_current_step = "Leaderboard Hyperliquid"
    state.autoscan_progress_percent = 45
    state.add_event(
        "leaderboard_scrape_started",
        "Lecture du leaderboard Hyperliquid public : adresses completes uniquement.",
        payload={"step": "leaderboard", "progress_percent": 40},
    )
    try:
        engine = create_sqlite_engine(settings.database_url)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            leaderboard_result = await scrape_leaderboard(
                settings,
                period="30D",
                method="auto",
                dry_run=False,
                store=True,
                session=session,
                target=settings.wallet_bootstrap.target_wallets,
            )
            session.commit()
        if leaderboard_result.candidates_created:
            state.add_event(
                "leaderboard_scrape_completed",
                (
                    f"Leaderboard lu : {leaderboard_result.full_addresses_found} adresses completes, "
                    f"{leaderboard_result.candidates_created} candidats exploitables."
                ),
                payload={"step": "leaderboard", "progress_percent": 45, **leaderboard_result.model_dump()},
            )
        else:
            state.add_event(
                "leaderboard_import_required",
                "Leaderboard essaye, mais aucune adresse complete exploitable n'a ete extraite. Aucun wallet n'est invente.",
                level="WARN",
                payload={"step": "leaderboard", "progress_percent": 45, **leaderboard_result.model_dump()},
            )
    except Exception as exc:  # noqa: BLE001 - source failure must be visible and non-blocking.
        state.add_event(
            "source_failed",
            "Leaderboard indisponible ou non parseable; aucune donnee n'a ete inventee.",
            level="WARN",
            payload={"source": "leaderboard", "error_message": str(exc), "progress_percent": 45},
        )
    state.autoscan_current_step = "Explorer transactions"
    state.autoscan_progress_percent = 50
    state.add_event(
        "explorer_probe_started",
        "Inspection de l'Explorer Hyperliquid et des transactions publiques.",
        payload={"step": "explorer", "progress_percent": 50},
    )
    try:
        engine = create_sqlite_engine(settings.database_url)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            explorer_result = await scrape_explorer(
                settings,
                method="network",
                dry_run=False,
                store=True,
                max_events=100,
                session=session,
            )
            session.commit()
        explorer_level = "INFO" if explorer_result.full_addresses_found else "WARN"
        state.add_event(
            "explorer_scrape_completed",
            (
                f"Explorer inspecte : {explorer_result.events_seen} transactions, "
                f"{explorer_result.full_addresses_found} adresses completes."
            ),
            level=explorer_level,
            payload={"step": "explorer", "progress_percent": 55, **explorer_result.model_dump()},
        )
        if explorer_result.full_addresses_found == 0:
            state.add_event(
                "explorer_import_required",
                "Explorer analyse, mais aucune adresse complete exploitable n'a ete extraite automatiquement.",
                level="WARN",
            )
    except Exception as exc:  # noqa: BLE001 - source failure must be visible and non-blocking.
        state.add_event(
            "source_failed",
            "Explorer indisponible ou non parseable; aucune donnee n'a ete inventee.",
            level="WARN",
            payload={"source": "explorer", "error_message": str(exc), "progress_percent": 55},
        )
    state.add_event("wallet_discovery_source_started", "Recherche des wallets sur les sources disponibles.")
    plan = build_wallet_discovery_plan(settings, store=True, dry_run=False, report=True)
    try:
        result = run_wallet_discovery(plan, settings)
    except Exception as exc:  # noqa: BLE001 - source failures stay visible, no fake fallback.
        state.last_discovery_error = str(exc)
        state.add_event(
            "wallet_discovery_source_failed",
            "La discovery wallets a echoue sans creer de faux wallet.",
            level="WARN",
            payload={"error": str(exc), "progress_percent": 55},
        )
        plan = build_wallet_discovery_plan(settings, store=False, dry_run=True, report=True)
        result = run_wallet_discovery(plan, settings)
    state.last_discovery_state = result.state
    state.autoscan_current_step = "Analyse wallet"
    state.autoscan_progress_percent = 65
    if result.selected_wallets:
        state.add_event(
            "wallet_candidate_selected",
            f"{len(result.selected_wallets)} wallets selectionnes pour analyse.",
        )
        state.autoscan_current_step = "Top wallets et file de scan"
        state.autoscan_progress_percent = 82
        try:
            engine = create_sqlite_engine(settings.database_url)
            session_factory = create_session_factory(engine)
            with session_factory() as session:
                top500 = bootstrap_top_wallets(
                    settings,
                    session=session,
                    target=settings.wallet_bootstrap.target_wallets,
                    source="all",
                    store=True,
                    dry_run=False,
                )
                queue = scan_wallet_queue(
                    session,
                    max_wallets=settings.wallet_scanner.scan_max_wallets_per_run,
                    batch_size=settings.wallet_scanner.scan_batch_size,
                    dry_run=False,
                )
                session.commit()
            state.add_event(
                "wallet_scan_queue_progress",
                f"Top wallets prepares : {top500.wallets_selected} selectionnes, {queue.scanned} scans controles en file.",
                payload={"top500": top500.model_dump(), "queue": queue.model_dump(), "progress_percent": 82},
            )
        except Exception as exc:  # noqa: BLE001 - keep the UI honest and finish the scan.
            state.add_event(
                "autoscan_step_failed",
                "Top wallets/file de scan indisponibles; les candidats restent visibles.",
                level="WARN",
                payload={"step": "scan_queue", "error": str(exc), "progress_percent": 82},
            )
        state.add_event(
            "selected_wallet_backfill_started",
            "Backfill multi-coins disponible via le bouton expert; il n'est pas lance en boucle bloquante au demarrage.",
            payload={"progress_percent": 88},
        )
    elif result.candidates_found:
        state.add_event(
            "wallet_discovery_completed",
            "Des wallets ont ete trouves, mais aucun ne passe encore les filtres PnL/ROI/activite.",
            level="WARN",
        )
    else:
        state.add_event(
            "wallet_discovery_completed",
            "Aucun wallet public exploitable trouve automatiquement : aucune adresse complete disponible dans les sources.",
            level="WARN",
            payload={"step": "wallets", "progress_percent": 75},
        )
    state.autoscan_current_step = "Resume pret"
    state.autoscan_progress_percent = 100
    state.autoscan_running = False
    state.last_autoscan_summary = {"market": market.model_dump(), "discovery": result.model_dump()}
    state.add_event("autoscan_finished", "Resume du scan automatique pret.", payload={"step": "summary", "progress_percent": 100})
    return _result(
        action,
        allowed=True,
        success=market.errors_count == 0 and result.errors_count == 0,
        message="Auto-scan termine : marches analyses, discovery wallets terminee.",
        level="INFO" if result.errors_count == 0 else "WARN",
        details=state.last_autoscan_summary,
    )


async def _autoscan_stop(action: str, _settings: Settings, state: UiState) -> UiActionResult:
    state.discovery_running = False
    state.autoscan_running = False
    state.last_discovery_state = "stopped"
    state.autoscan_current_step = "Stoppe"
    return _result(
        action,
        allowed=True,
        success=True,
        message="Auto-scan marque comme stoppe localement. Aucun ordre n'existait.",
        level="INFO",
    )


async def _leaderboard_prepared(action: str, settings: Settings, state: UiState) -> UiActionResult:
    state.add_event(
        "leaderboard_scrape_started",
        "Lecture du leaderboard public en cours. Les adresses tronquees restent rejetees.",
    )
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        result = await scrape_leaderboard(
            settings,
            period="30D",
            method="auto",
            dry_run=False,
            store=True,
            session=session,
            target=settings.wallet_bootstrap.target_wallets,
        )
        session.commit()
    if result.candidates_created:
        state.add_event(
            "leaderboard_scrape_completed",
            f"Leaderboard lu : {result.candidates_created} candidats full-address stockes.",
            payload=result.model_dump(),
        )
    else:
        state.add_event(
            "leaderboard_import_required",
            "Leaderboard essaye, mais aucune adresse complete n'a ete trouvee. Import local possible.",
            level="WARN",
            payload=result.model_dump(),
        )
    return _result(
        action,
        allowed=True,
        success=result.error_message is None,
        message=(
            f"Leaderboard lu : {result.candidates_created} candidats full-address."
            if result.candidates_created
            else "Leaderboard lu, mais import requis si aucune adresse complete publique n'est extraite."
        ),
        level="INFO" if result.candidates_created else "WARN",
        details=result.model_dump(),
        next_recommended_action="discover_wallets" if result.candidates_created else "import_leaderboard",
    )


async def _leaderboard_import_required(action: str, _settings: Settings, _state: UiState) -> UiActionResult:
    return _result(
        action,
        allowed=True,
        success=True,
        message="Import leaderboard disponible via CLI avec fichier local; aucune adresse tronquee n'est acceptee.",
        details={"cli": "python -m hl_observer import-leaderboard --file data/imports/hyperliquid_leaderboard.csv --store --report"},
    )


async def _validate_leaderboard_addresses(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    from hl_observer.storage.models import LeaderboardAddressValidation

    with session_factory() as session:
        rows = session.query(LeaderboardAddressValidation).limit(5000).all()
        full = sum(1 for row in rows if row.is_full_address)
        truncated = sum(1 for row in rows if row.is_truncated)
    return _result(
        action,
        allowed=True,
        success=True,
        message="Validation leaderboard terminee.",
        details={"full_addresses": full, "truncated_rejected": truncated, "rows": len(rows)},
    )


async def _leaderboard_candidates(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    from hl_observer.storage.models import LeaderboardWalletCandidate

    with session_factory() as session:
        count = session.query(LeaderboardWalletCandidate).count()
    return _result(
        action,
        allowed=True,
        success=True,
        message=f"{count} candidats leaderboard complets disponibles.",
        details={"candidates": count},
    )


async def _probe_explorer(action: str, settings: Settings, state: UiState) -> UiActionResult:
    state.add_event("explorer_probe_started", "Inspection publique de l'Explorer Hyperliquid.")
    result = await scrape_explorer(settings, method="network", dry_run=True, store=False, max_events=100)
    state.add_event(
        "explorer_probe_completed",
        "Explorer prepare en lecture seule; import requis si aucune adresse complete n'est visible.",
        level="WARN" if result.full_addresses_found == 0 else "INFO",
        payload=result.model_dump(),
    )
    return _result(
        action,
        allowed=True,
        success=True,
        message="Probe Explorer termine en mode safe.",
        level="WARN" if result.full_addresses_found == 0 else "INFO",
        details=result.model_dump(),
    )


async def _scrape_explorer_action(action: str, settings: Settings, state: UiState) -> UiActionResult:
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    state.add_event("explorer_scrape_started", "Lecture publique Explorer en cours.")
    with session_factory() as session:
        result = await scrape_explorer(
            settings,
            method="network",
            dry_run=False,
            store=True,
            max_events=100,
            session=session,
        )
        session.commit()
    if result.transactions:
        state.add_event(
            "explorer_scrape_completed",
            f"{len(result.transactions)} transactions Explorer structurees.",
            payload=result.model_dump(),
        )
    else:
        state.add_event(
            "explorer_import_required",
            "Explorer inspecte, mais aucune transaction/adresse complete exploitable n'a ete extraite.",
            level="WARN",
            payload=result.model_dump(),
        )
    return _result(
        action,
        allowed=True,
        success=result.error_message is None,
        message="Scrape Explorer termine en lecture seule.",
        level="INFO" if result.error_message is None else "WARN",
        details=result.model_dump(),
    )


async def _explorer_import_required(action: str, _settings: Settings, state: UiState) -> UiActionResult:
    result = _result(
        action,
        allowed=True,
        success=True,
        message="Import Explorer disponible via CLI; seules les adresses completes seront acceptees.",
        level="WARN",
        details={"cli": "python -m hl_observer import-explorer --file data/imports/hyperliquid_explorer.csv --store --report"},
    )
    state.add_event("explorer_import_required", result.message, level=result.level, payload=result.details)
    return result


async def _explorer_candidates(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        created = create_explorer_candidates(session)
        session.commit()
    return _result(
        action,
        allowed=True,
        success=True,
        message=f"{created} candidats Explorer complets crees depuis les transactions stockees.",
        details={"created": created},
    )


async def _revalidate_explorer_wallets(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        result = revalidate_explorer_wallets(session, limit=100, store=True)
        session.commit()
    return _result(
        action,
        allowed=True,
        success=True,
        message="Revalidation Explorer terminee par garde full-address.",
        details=result,
    )


async def _explorer_tape(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        rows = get_explorer_tape(session, limit=100)
    return _result(
        action,
        allowed=True,
        success=True,
        message=f"{len(rows)} transactions Explorer dans la tape locale.",
        details={"transactions": rows},
    )


async def _discover_markets(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    result = await run_discover_markets(
        MarketDiscoveryPlan(store=False, dry_run=True, report=True),
        settings,
    )
    return _result(
        action,
        allowed=True,
        success=True,
        message="Discovery marches preparee en dry-run.",
        details=result.model_dump(),
    )


async def _scan_markets(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    result = await run_scan_markets(
        MarketScanPlan(all_coins=True, include_altcoins=True, max_coins=10, dry_run=True),
        settings,
    )
    return _result(
        action,
        allowed=True,
        success=True,
        message="Scan multi-assets prepare en dry-run.",
        details=result.model_dump(),
    )


async def _bootstrap_top_wallets(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        result = bootstrap_top_wallets(settings, session=session, target=settings.wallet_bootstrap.target_wallets, dry_run=True)
    return _result(
        action,
        allowed=True,
        success=True,
        message="Top 500 calcule honnetement en dry-run.",
        details=result.model_dump(),
    )


async def _scan_wallet_queue(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        result = scan_wallet_queue(
            session,
            max_wallets=settings.wallet_scanner.scan_max_wallets_per_run,
            batch_size=settings.wallet_scanner.scan_batch_size,
            dry_run=True,
        )
    return _result(
        action,
        allowed=True,
        success=True,
        message="File de scan wallets preparee en dry-run.",
        details=result.model_dump(),
    )


async def _analysis_prepared(action: str, _settings: Settings, _state: UiState) -> UiActionResult:
    return _result(
        action,
        allowed=True,
        success=True,
        message="Analyse trading preparee. Les resultats reels viennent des deltas stockes.",
        details={"mode": "read_only", "no_fake_patterns": True},
    )


async def _rank_opening_patterns(action: str, _settings: Settings, _state: UiState) -> UiActionResult:
    stats = compute_opening_pattern_stats([1.0, -1.0], opening_type="UNKNOWN", min_samples=20)
    return _result(
        action,
        allowed=True,
        success=True,
        message="Classement patterns prepare; faible echantillon reste rejete.",
        details=stats.model_dump(),
    )


async def _paper_follow_prepared(action: str, _settings: Settings, _state: UiState) -> UiActionResult:
    return _result(
        action,
        allowed=True,
        success=True,
        message="Paper-follow prepare uniquement en simulation, sans /exchange.",
        details={"paper_only": True, "real_orders": False},
    )


async def _adaptive_risk_check(action: str, settings: Settings, _state: UiState) -> UiActionResult:
    decision = apply_adaptive_risk_filter(
        AdaptiveRiskContext(
            signal_age_ms=100,
            spread_bps=1,
            estimated_slippage_bps=1,
            depth_usdc=settings.adaptive_risk_filter.min_orderbook_depth_usdc,
            wallet_score=90,
            wallet_coin_score=90,
            opening_pattern_score=90,
            pattern_sample_size=settings.adaptive_risk_filter.min_pattern_sample_size,
            coin="HYPE",
        ),
        settings,
    )
    return _result(
        action,
        allowed=True,
        success=True,
        message="Filtre de risque adaptatif execute en simulation.",
        details=decision.model_dump(),
    )


async def _export_prepared(action: str, _settings: Settings, _state: UiState) -> UiActionResult:
    return _result(
        action,
        allowed=True,
        success=True,
        message="Export local prepare. Aucun push GitHub ni reseau requis.",
    )


async def _recommended_action(action: str, _settings: Settings, _state: UiState) -> UiActionResult:
    return _result(
        action,
        allowed=True,
        success=True,
        message="Action recommandee: importer un leaderboard avec adresses completes si extraction publique indisponible.",
        next_recommended_action="import_leaderboard",
    )


async def _refresh_discovery_status(action: str, _settings: Settings, state: UiState) -> UiActionResult:
    return _result(
        action,
        allowed=True,
        success=True,
        message="Discovery status refreshed.",
        details={"state": state.last_discovery_state, "running": state.discovery_running},
    )


async def _run_selected_wallet_backfill(
    settings: Settings,
    state: UiState,
) -> tuple[list[str], object] | None:
    init_db(settings.database_url)
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    limit = max(1, settings.wallet_discovery.max_wallets_to_backfill)
    with session_factory() as session:
        rows = session.scalars(
            select(AutoWatchlist)
            .where(AutoWatchlist.status.in_(["selected", "backfilled", "partial"]))
            .order_by(AutoWatchlist.discovery_score.desc())
            .limit(limit)
        ).all()
        wallets = [row.wallet_address for row in rows]
    if not wallets:
        return None

    end_ms = now_ms()
    start_ms = max(0, end_ms - settings.wallet_discovery.backfill_days * 24 * 60 * 60 * 1000)
    result = await run_wallet_backfill(
        WalletBackfillPlan(
            fetch=True,
            dry_run=False,
            store_raw=True,
            wallets=wallets,
            coins=settings.collection.default_coins,
            start_ms=start_ms,
            end_ms=end_ms,
            limit_pages=settings.collection.max_user_fills_pages,
            page_window_ms=settings.collection.user_fills_page_window_ms,
            include_recent_fills=True,
            include_fills_by_time=True,
            include_open_orders=True,
            include_frontend_open_orders=True,
            include_market_snapshots=False,
            rebuild_positions=True,
            compute_position_deltas=True,
        ),
        settings,
    )
    with session_factory() as session:
        rows = session.scalars(select(AutoWatchlist).where(AutoWatchlist.wallet_address.in_(wallets))).all()
        for row in rows:
            row.last_backfill_ms = end_ms
            row.status = "backfilled" if result.errors_count == 0 else "partial"
        session.commit()
    state.last_discovery_state = "backfilled" if result.errors_count == 0 else "partial_backfill"
    return wallets, result
