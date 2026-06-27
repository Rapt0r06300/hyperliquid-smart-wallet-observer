from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from sqlalchemy.exc import OperationalError, SQLAlchemyError
import typer

from hl_observer.autoscan import format_autoscan_report, run_autoscan
from hl_observer.collection.collector import (
    InvalidWalletAddress,
    build_default_collection_plan,
    run_collection_once,
    validate_wallet_address,
)
from hl_observer.collection.weight_budgeter import (
    ReadOnlyBudgetRequest,
    format_budget_plan,
    plan_readonly_collection_budget,
)
from hl_observer.config.loader import load_settings
from hl_observer.config.settings import ExecutionEnvironment, Settings
from hl_observer.copying.leaderboard_autoselect import (
    CopyLeaderAutoSelectConfig,
    select_copy_leaders,
)
from hl_observer.copying.consensus_leader_selector import (
    ConsensusLeaderSelectionReport,
    format_consensus_leader_report,
    select_consensus_leaders_from_deltas,
)
from hl_observer.copying.reports import (
    format_copy_run_report,
    format_copy_status_report,
)
from hl_observer.copying.realtime_magic_score import RealtimeCopyRiskConfig
from hl_observer.copying.signal_detector import CopySourceMode, detect_copy_signals_from_deltas
from hl_observer.simulation.live_filters import DEFAULT_SIMULATION_MIN_EDGE_BPS, calibrated_float_env
from hl_observer.dashboard_truth.dashboard_truth_audit import (
    format_dashboard_truth_audit,
    run_dashboard_truth_audit,
)
from hl_observer.edge.edge_remaining import compute_edge_remaining
from hl_observer.explorer.explorer_revalidation import revalidate_explorer_wallets
from hl_observer.explorer.explorer_source import (
    create_explorer_candidates,
    format_explorer_report,
    import_and_store_explorer,
    scrape_explorer,
)
from hl_observer.explorer.explorer_transaction_tape import format_explorer_tape, get_explorer_tape
from hl_observer.hyperliquid.endpoints import info_url_for_settings
from hl_observer.hyperliquid.schemas import EdgeRemainingInputs, RiskDecision, SignalDecision
from hl_observer.data_sources.provider_registry import provider_registry_report
from hl_observer.data_sources.acquisition_engine import (
    DataQualityConfig,
    DataQualityGate,
    FetchRequest,
    FetchResult,
    RequestBudgetManager,
    format_data_quality_assessment,
)
from hl_observer.data_sources.historical_backfill_engine import (
    HistoricalBackfillConfig,
    HistoricalBackfillEngine,
    TtlPageCache,
    format_historical_backfill_result,
)
from hl_observer.data_sources.fresh_data_plan import (
    FreshDataPlanRequest,
    build_fresh_data_plan,
    format_fresh_data_plan,
)
from hl_observer.data_sources.warehouse_coverage import (
    build_warehouse_coverage_report,
    format_warehouse_coverage_report,
)
from hl_observer.local_index.index_benchmark import format_benchmark_report, run_local_scan_benchmark
from hl_observer.local_index.query_engine import scan_wallet_index
from hl_observer.local_index.wallet_index import WalletLocalIndex, fake_wallet  # fake-data-scan: allow benchmark-only import (scan-local research command)
from hl_observer.markets.scanner import (
    MarketDiscoveryPlan,
    MarketScanPlan,
    format_market_discovery_report,
    format_market_scan_report,
    run_discover_markets,
    run_scan_markets,
)
from hl_observer.opportunities.fresh_opportunity import (
    find_fresh_opportunities,
    format_fresh_opportunity_report,
)
from hl_observer.paper.paper_executor import PaperExecutor
from hl_observer.risk.gates import RiskContext
from hl_observer.risk.risk_engine import RiskEngine
from hl_observer.runtime.hygiene import format_runtime_hygiene_report, scan_runtime_hygiene
from hl_observer.runtime.write_diagnostics import (
    check_runtime_write_readiness,
    format_runtime_write_readiness,
)
from hl_observer.runtime.session_logs import (
    format_prepared_session_logs,
    format_purged_logs,
    prepare_fresh_simulation_logs,
    purge_stale_top_level_logs,
)
from hl_observer.scanner.missed_opportunity_logger import write_missed_opportunity_reports
from hl_observer.scanner.priority_queue import select_wallets_for_warm_scan
from hl_observer.scanner.scan_budget import evaluate_warm_scan_budget
from hl_observer.scanner.scanner_models import ScanBudget, WalletPriorityInput
from hl_observer.scanner.throughput_planner import (
    ThroughputRequest,
    format_throughput_plan,
    plan_safe_high_throughput_scan,
)
from hl_observer.scanner.fresh_scan_strategy import (
    FreshScanStrategyRequest,
    format_fresh_scan_strategy,
    plan_fresh_scan_strategy,
)
from hl_observer.scanner.wallet_priority import score_wallet_priority
from hl_observer.realtime_monitor.hot_watch_rotation import rotate_hot_watch
from hl_observer.realtime.realtime_health import check_realtime_health, format_realtime_health
from hl_observer.realtime.recovery_engine import (
    RealtimeRecoveryEngine,
    ReconnectPolicy,
    StreamEventType,
    WatchStreamEvent,
    format_recovery_decision,
)
from hl_observer.realtime.latency_report import build_latency_report, format_latency_report
from hl_observer.realtime.replay import format_replay_result, replay_events_from_logs
from hl_observer.realtime.freshness_diagnostics import (
    build_freshness_diagnostics,
    format_freshness_diagnostics,
)
from hl_observer.metagraph.metagraph_export import export_metagraph_from_logs, format_metagraph_export
from hl_observer.research.manual_research_classifier import (
    classify_manual_research,
    format_classified_research,
    format_feature_map,
    write_research_to_feature_map,
)
from hl_observer.research.manual_research_importer import (
    format_manual_research_import,
    import_manual_research,
    write_manual_research_template,
)
from hl_observer.release.closeout import write_closeout_report
from hl_observer.release.prompt_coverage import (
    evaluate_prompt_coverage,
    format_coverage_summary,
    verify_non_deletion,
)
from hl_observer.release.quality_gates import format_quality_gates, run_quality_gates
from hl_observer.security.mainnet_guard import assert_mainnet_execution_disabled
from hl_observer.security.safety_audit import run_safety_audit
from hl_observer.simulation.decision_replay_analyzer import (
    analyze_decision_logs,
    analyze_decision_logs_summary,
    default_logs_to_send_dir,
    format_replay_analysis,
    load_recent_decision_events,
)
from hl_observer.simulation.diagnostic_reports import (
    build_action_loss_diagnostics,
    build_coin_loss_diagnostics,
    build_cost_drag_diagnostics,
    build_edge_distribution_diagnostics,
    build_position_matching_diagnostics,
    build_profitability_diagnostics,
    build_refusal_breakdown,
    build_root_cause_from_logs,
    build_stale_signal_diagnostics,
    build_timing_distribution_diagnostics,
    build_wallet_loss_diagnostics,
    format_diagnostic_report,
)
from hl_observer.simulation.log_metrics import analyze_logs_streaming, format_logs_analysis
from hl_observer.simulation.loss_attribution import (
    build_loss_attribution_report,
    format_loss_attribution_report,
)
from hl_observer.simulation.readiness import (
    build_simulation_readiness_report,
    format_simulation_readiness,
)
from hl_observer.simulation.tuning_report import (
    build_simulation_tuning_report,
    format_simulation_tuning_report,
)
from hl_observer.optimization.profit_optimizer import (
    format_optimization_report,
    run_strategy_tournament,
    write_optimization_reports,
)
from hl_observer.storage.database import init_db as initialize_database
from hl_observer.storage.database import create_session_factory, create_sqlite_engine
from hl_observer.storage.models import (
    FollowDecision,
    FollowSignal,
    LeaderboardAddressValidation,
    LeaderboardWalletCandidate,
    MarketSnapshot,
    MarketUniverseModel,
    PaperFollowOrder,
    PositionDeltaModel,
    TopWallet,
    WalletClosing,
    WalletMethodologyProfile,
    WalletOpening,
    WalletOpeningPatternStats,
    WalletPlaybook,
)
from hl_observer.testnet.testnet_order_builder import build_testnet_order_intent
from hl_observer.testnet.testnet_executor_locked import LockedTestnetExecutor
from hl_observer.testnet.testnet_safety_gates import TestnetLocked
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.persistent_state import reset_simulation_state, simulation_state_path
from hl_observer.utils.logging import configure_logging
from hl_observer.utils.time import now_ms
from hl_observer.wallets.backfill import (
    WalletBackfillPlan,
    build_wallet_backfill_plan,
    format_wallet_backfill_report,
    run_wallet_backfill,
)
from hl_observer.wallets.discovery import (
    build_wallet_discovery_plan,
    discovery_result_json,
    format_discovery_report,
    run_wallet_discovery,
)
from hl_observer.wallets.leaderboard_import import (
    format_leaderboard_report,
    import_leaderboard_file,
    store_leaderboard_result,
)
from hl_observer.wallets.leaderboard_models import LeaderboardCandidate
from hl_observer.wallets.leaderboard_source import scrape_leaderboard
from hl_observer.wallets.leaderboard_validation import validate_leaderboard_wallet_address
from hl_observer.wallets.public_trades_live import (
    format_public_trade_scan_report,
    normalize_coin_list,
    scan_public_trades_ws,
    store_public_trade_scan,
)
from hl_observer.wallets.user_fills_live import (
    format_user_fills_live_report,
    scan_user_fills_ws,
    store_user_fills_live_result,
    stream_user_fills_ws,
)
from hl_observer.wallets.snapshot_service import record_robust_snapshot
from hl_observer.wallets.top500_bootstrap import bootstrap_top_wallets, format_top500_report
from hl_observer.wallets.scan_queue import format_scan_queue_report, scan_wallet_queue
from hl_observer.analysis.opening_detector import detect_openings_from_deltas
from hl_observer.analysis.closing_detector import detect_closings_from_deltas
from hl_observer.analysis.opening_patterns import compute_opening_pattern_stats
from hl_observer.analysis.methodology_profiler import build_methodology_profile
from hl_observer.analysis.trader_playbook import generate_trader_playbook
from hl_observer.following.follow_decision_engine import decide_follow_signal
from hl_observer.following.follow_signal_builder import build_follow_signal_from_opening
from hl_observer.following.paper_follow import create_paper_follow_orders
from hyper_smart_observer.audit.archive_audit import write_archive_audit_report
from hyper_smart_observer.app.config import load_config as load_hypersmart_config
from hyper_smart_observer.copy_mode.preflight import (
    format_copy_preflight_report,
    run_copy_preflight,
    write_copy_preflight_report,
)
from hyper_smart_observer.dashboard.exporter import export_dashboard as export_hypersmart_dashboard
from hyper_smart_observer.runtime.archive import create_clean_archive

app = typer.Typer(
    name="hl_observer",
    help="Hyperliquid Smart-Wallet Observer. Read-only, paper-first, testnet locked.",
    no_args_is_help=True,
)


def _settings() -> Settings:
    settings = load_settings()
    configure_logging(settings.log_level)
    assert_mainnet_execution_disabled(settings)
    return settings


def _session_factory(settings: Settings):
    initialize_database(settings.database_url)
    return create_session_factory(create_sqlite_engine(settings.database_url))


def _store_with_sqlite_retry(
    settings: Settings,
    *,
    label: str,
    store_func,
    attempts: int = 6,
) -> None:
    """Replay a complete local store transaction when SQLite is briefly busy."""

    delay_seconds = 0.15
    for attempt in range(1, attempts + 1):
        session_factory = _session_factory(settings)
        try:
            with session_factory() as session:
                store_func(session)
                session.commit()
            return
        except OperationalError as exc:
            message = str(exc).lower()
            if "database is locked" not in message or attempt >= attempts:
                raise
            typer.echo(
                f"{label}: SQLite busy, retrying safe local store {attempt}/{attempts}..."
            )
            time.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 1.8, 2.0)


def _read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _record_local_snapshots(settings: Settings, wallets: list[str], *, run_id: int | None, source: str) -> None:
    if not wallets:
        return
    session_factory = _session_factory(settings)
    with session_factory() as session:
        for wallet in wallets:
            record_robust_snapshot(session, wallet, run_id=run_id, source=source, echo_func=typer.echo)
        session.commit()


def _leaderboard_model_to_candidate(row: LeaderboardWalletCandidate) -> LeaderboardCandidate:
    return LeaderboardCandidate(
        wallet_address=row.wallet_address,
        rank=row.rank,
        period=row.period,
        account_value_usdc=row.account_value_usdc,
        pnl_usdc=row.pnl_usdc,
        roi_pct=row.roi_pct,
        volume_usdc=row.volume_usdc,
        leaderboard_score=row.leaderboard_score,
        selected_for_revalidation=row.selected_for_revalidation,
        selected_for_backfill=row.selected_for_backfill,
        source_confidence=row.source_confidence,
        notes=row.notes,
    )


def _unique_top_wallet_rows(rows: list[TopWallet], *, limit: int, offset: int = 0) -> list[TopWallet]:
    """Return unique selected wallets while preserving ranking order.

    Public-trades discovery can promote the same active wallet repeatedly across
    scan cycles. The copy loop must spend its bounded /info budget on distinct
    wallets, otherwise a "50 leaders" run may effectively scan the same few
    wallets many times.
    """

    unique: list[TopWallet] = []
    seen: set[str] = set()
    for row in rows:
        address = str(row.wallet_address or "").lower()
        if not address or address in seen:
            continue
        seen.add(address)
        unique.append(row)
    if not unique or limit <= 0:
        return []
    normalized_offset = max(0, offset) % len(unique)
    rotated = unique[normalized_offset:] + unique[:normalized_offset]
    return rotated[: max(0, limit)]


def _resolve_public_trade_scan_coins(settings: Settings, raw_coins: str, *, max_coins: int) -> list[str]:
    requested = str(raw_coins or "").strip()
    max_coins = max(1, min(int(max_coins), 200))
    if requested.upper() not in {"AUTO", "ALL", "*"}:
        return normalize_coin_list(requested)[:max_coins]

    session_factory = _session_factory(settings)
    with session_factory() as session:
        db_coins = [
            str(row.coin or "").upper()
            for row in (
                session.query(MarketUniverseModel)
                .filter(MarketUniverseModel.is_active.is_(True))
                .filter(MarketUniverseModel.is_spot.is_(False))
                .order_by(MarketUniverseModel.coin.asc())
                .limit(max_coins * 2)
                .all()
            )
            if not str(row.coin or "").startswith(("@", "#"))
        ]
    default_priority = normalize_coin_list("BTC,ETH,SOL,HYPE,DOGE,XRP,BNB,ENA,AVAX,LINK")
    merged = default_priority + [coin for coin in db_coins if coin not in default_priority]
    return normalize_coin_list(merged)[:max_coins]


def _apply_leader_quality_gate(session, rows, *, limit):
    """V9 — ne copie QUE les leaders dont la qualite REALISEE est prouvee.
    Warmup-safe: tant qu'aucun leader n'est qualifie, ne gele pas la shortlist.
    Pilotable par HYPERSMART_LEADER_QUALITY_GATE (defaut actif). Jamais d'exception bloquante."""
    if not rows:
        return rows
    if os.environ.get("HYPERSMART_LEADER_QUALITY_GATE", "1") != "1":
        return rows
    try:
        from hl_observer.scoring.leader_realized_history import wallet_round_trip_moves_from_session
        from hl_observer.scoring.shortlist_quality_filter import filter_to_qualified
        wallets = [w for w in (getattr(r, "wallet_address", None) for r in rows) if w]
        moves = wallet_round_trip_moves_from_session(session, wallets)
        kept, _qualified = filter_to_qualified(rows, moves)
        return kept[: int(limit)] if kept else rows
    except Exception:
        return rows


def _selected_top_wallet_rows(
    session,
    *,
    limit: int,
    offset: int = 0,
    active_window_ms: int = 5 * 60_000,
) -> list[TopWallet]:
    """Select fresh active leaders first, then fall back to the broader pool.

    The live simulation should spend its 10 user-specific WebSocket slots on
    wallets that just appeared in public trade flow. Older high-score wallets
    remain useful as fallback, but they should not block fresh opportunities.
    """

    limit = max(1, int(limit))
    offset = max(0, int(offset))
    active_cutoff = now_ms() - max(30_000, active_window_ms)
    active_rows = (
        session.query(TopWallet)
        .filter(TopWallet.status == "selected")
        .filter(TopWallet.selected_at_ms >= active_cutoff)
        .order_by(TopWallet.selected_at_ms.desc(), TopWallet.score.desc())
        .limit(max(100, limit * 20 + offset))
        .all()
    )
    selected = _unique_top_wallet_rows(active_rows, limit=limit, offset=offset)
    if selected:
        return _apply_leader_quality_gate(session, selected, limit=limit)
    fallback_rows = (
        session.query(TopWallet)
        .filter(TopWallet.status == "selected")
        .order_by(TopWallet.selected_at_ms.desc(), TopWallet.score.desc())
        .limit(max(100, limit * 20 + offset))
        .all()
    )
    return _apply_leader_quality_gate(session, _unique_top_wallet_rows(fallback_rows, limit=limit, offset=offset), limit=limit)


def _latest_market_mids(session) -> dict[str, float]:
    row = (
        session.query(MarketSnapshot)
        .order_by(MarketSnapshot.id.desc())
        .limit(1)
        .first()
    )
    if row is None:
        return {}
    raw = row.raw_json or {}
    if not isinstance(raw, dict):
        return {}
    candidates: Any = raw
    for key in ("mids", "allMids", "data", "prices"):
        value = raw.get(key)
        if isinstance(value, dict):
            candidates = value
            break
    mids: dict[str, float] = {}
    if isinstance(candidates, dict):
        for coin, value in candidates.items():
            try:
                price = float(value)
            except (TypeError, ValueError):
                continue
            if price > 0:
                mids[str(coin).upper()] = price
    return mids


def _consensus_top_wallet_rows(
    session,
    *,
    limit: int,
    offset: int = 0,
    active_window_ms: int = 5 * 60_000,
    consensus_window_ms: int = 4_000,
    min_wallets: int = 2,
    max_deltas: int = 5_000,
) -> tuple[list[TopWallet], ConsensusLeaderSelectionReport]:
    """Select follow leaders from fresh same-coin/same-direction clusters."""

    current_ms = now_ms()
    cutoff = current_ms - max(consensus_window_ms, active_window_ms)
    top_rows = (
        session.query(TopWallet)
        .filter(TopWallet.status == "selected")
        .order_by(TopWallet.score.desc(), TopWallet.selected_at_ms.desc())
        .limit(max(200, limit * 20 + offset))
        .all()
    )
    deltas = (
        session.query(PositionDeltaModel)
        .filter(PositionDeltaModel.detected_at_ms >= cutoff)
        .order_by(PositionDeltaModel.detected_at_ms.desc())
        .limit(max(100, max_deltas))
        .all()
    )
    report = select_consensus_leaders_from_deltas(
        deltas,
        top_rows,
        now_timestamp_ms=current_ms,
        max_leaders=limit + offset,
        active_window_ms=active_window_ms,
        consensus_window_ms=consensus_window_ms,
        min_wallets=min_wallets,
    )
    by_wallet = {str(row.wallet_address or "").lower(): row for row in top_rows}
    selected_rows: list[TopWallet] = []
    for rank, wallet in enumerate(report.selected_wallets[offset : offset + limit], start=1):
        existing = by_wallet.get(wallet)
        if existing is not None:
            selected_rows.append(existing)
            continue
        selected_rows.append(
            TopWallet(
                wallet_address=wallet,
                rank=rank,
                source="consensus_delta_cluster",
                score=75.0,
                selected_at_ms=current_ms,
                status="selected",
                notes="selected_from_fresh_consensus_cluster;research_only",
            )
        )
    return _unique_top_wallet_rows(selected_rows, limit=limit), report


@app.command()
def doctor() -> None:
    """Check local configuration and safety posture."""
    settings = load_settings()
    configure_logging(settings.log_level)
    checks = {
        "python_3_11_plus": sys.version_info >= (3, 11),
        "readme_present": Path("README.md").exists(),
        "agents_present": Path("AGENTS.md").exists(),
        "env_example_present": Path(".env.example").exists(),
        "mainnet_execution_disabled": not settings.execution.enable_mainnet_execution,
        "testnet_execution_disabled_by_default": not settings.execution.enable_testnet_execution,
        "database_url_configured": bool(settings.database_url),
        "logs_dir_configured": bool(settings.logs_dir),
        "info_endpoint_read_only": info_url_for_settings(settings).endswith("/info"),
    }
    audit = run_safety_audit(".")
    checks["safety_audit_ok"] = audit.ok
    for name, ok in checks.items():
        typer.echo(f"{name}: {'ok' if ok else 'FAIL'}")
    if not all(checks.values()):
        raise typer.Exit(1)


@app.command("init-db")
def init_db() -> None:
    """Initialize the SQLite schema."""
    settings = _settings()
    initialize_database(settings.database_url)
    typer.echo(f"database initialized: {settings.database_url}")


@app.command("safety-audit")
def safety_audit() -> None:
    """Run local safety checks for secrets and forbidden execution paths."""
    result = run_safety_audit(".")
    for name, ok in result.checks.items():
        typer.echo(f"{name}: {'ok' if ok else 'FAIL'}")
    for finding in result.findings:
        typer.echo(f"finding: {finding}")
    if not result.ok:
        raise typer.Exit(1)


@app.command("audit-safety")
def audit_safety() -> None:
    """Alias for safety-audit, kept for HyperSmart prompt compatibility."""
    safety_audit()


@app.command("runtime-check")
def runtime_check() -> None:
    """Report runtime files that must stay out of source archives."""
    settings = _settings()
    typer.echo(format_runtime_hygiene_report(scan_runtime_hygiene(settings)))


@app.command("runtime-clean-report")
def runtime_clean_report() -> None:
    """Explain clean archive policy without deleting or copying runtime files."""
    settings = _settings()
    report = scan_runtime_hygiene(settings)
    typer.echo(format_runtime_hygiene_report(report))
    typer.echo("clean archive command: .\\CREER_ARCHIVE_PROPRE.cmd or python -m hl_observer create-clean-archive")
    typer.echo("clean archive output: Desktop\\Projet_invest_clean_YYYYMMDD_HHMMSS.zip")
    typer.echo("no runtime file is deleted, killed, copied or zipped by this report")


@app.command("runtime-write-check")
def runtime_write_check(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing local simulation logs."),
    stale_after_seconds: int = typer.Option(60, "--stale-after-seconds", min=1, max=3600),
) -> None:
    """Check whether simulation/replay log outputs can refresh without killing processes."""
    _settings()
    report = check_runtime_write_readiness(from_logs, stale_after_seconds=stale_after_seconds)
    typer.echo(format_runtime_write_readiness(report))


@app.command("prepare-simulation-logs")
def prepare_simulation_logs(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be archived without moving files."),
    purge_top_level: bool = typer.Option(
        True,
        "--purge-top-level/--no-purge-top-level",
        help="Reset bloated top-level logs/ (truncate *.log, delete heavy archives). "
        "AI intelligence (runtime/ model + training samples) is never touched.",
    ),
) -> None:
    """Prepare a fresh logs/logs a envoyer evidence bundle for the current session.

    Also resets the bloated top-level logs/ directory at each launch (user request),
    while strictly preserving the AI's learned intelligence under runtime/.
    """
    _settings()
    report = prepare_fresh_simulation_logs(Path(".").resolve(), dry_run=dry_run)
    typer.echo(format_prepared_session_logs(report))
    if purge_top_level:
        purged = purge_stale_top_level_logs(Path(".").resolve(), dry_run=dry_run)
        typer.echo(format_purged_logs(purged))


@app.command("live-user-fills-stream")
def live_user_fills_stream(
    duration_seconds: int = typer.Option(0, "--duration-seconds", help="0 = run forever (always-on real-time engine)."),
    max_leaders: int = typer.Option(10, "--max-leaders", min=1, max=10, help="HL userFills caps at 10 wallets; we stream the BEST 10."),
    network_read: bool = typer.Option(False, "--network-read/--no-network-read", help="Open the public HL WebSocket (read-only)."),
    max_reconnects: int = typer.Option(-1, "--max-reconnects", help="-1 = unlimited reconnects (always-on)."),
) -> None:
    """V16 — PERSISTENT real-time userFills stream on the top quality-gated leaders.

    Stays connected to the FREE public Hyperliquid WebSocket and stores each FRESH fill the
    instant it arrives (sub-second) so copy-run sees it immediately — instead of the ~10s
    polled snapshot. Read-only / paper-only: never an order, signature, deposit or key.
    """
    import asyncio as _asyncio
    import threading as _threading
    import time as _time
    from sqlalchemy import select as _select
    from hl_observer.storage.models import TopWallet as _TopWallet

    settings = _settings()
    session_factory = _session_factory(settings)
    with session_factory() as session:
        rows = session.scalars(_select(_TopWallet).order_by(_TopWallet.score.desc()).limit(50)).all()
        try:
            rows = _apply_leader_quality_gate(session, rows, limit=max_leaders)
        except Exception:
            pass
        wallets = [r.wallet_address for r in rows[: max_leaders] if getattr(r, "wallet_address", None)]
    if not wallets:
        typer.echo("live_user_fills_stream=no_leaders_available")
        return
    stop = _threading.Event()
    deadline = None if duration_seconds <= 0 else (_time.time() + float(duration_seconds))

    async def _runner():
        async def _watch():
            while not stop.is_set():
                if deadline is not None and _time.time() >= deadline:
                    stop.set()
                    return
                await _asyncio.sleep(1.0)
        watcher = _asyncio.ensure_future(_watch())
        try:
            return await stream_user_fills_ws(
                settings, wallets=wallets, session_factory=session_factory,
                max_users=max_leaders, network_read=network_read, stop_event=stop,
                max_reconnects=None if max_reconnects < 0 else max_reconnects,
            )
        finally:
            watcher.cancel()

    stats = _asyncio.run(_runner())
    typer.echo(
        f"live_user_fills_stream wallets={len(wallets)} connects={stats.connects} "
        f"reconnects={stats.reconnects} fresh_fills_stored={stats.fresh_fills_stored} "
        f"deltas_stored={stats.deltas_stored} last_fill_age_ms={stats.last_fill_age_ms} "
        f"stopped={stats.stopped_reason}"
    )
    typer.echo("mode: read-only persistent userFills stream; no exchange, no signature, no order")


@app.command("simulation-readiness")
def simulation_readiness(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing local simulation logs."),
    fresh_window_seconds: int = typer.Option(
        20,
        "--fresh-window-seconds",
        min=1,
        max=300,
        help="Freshness window for leaders/deltas used by the virtual position engine.",
    ),
) -> None:
    """Explain whether the local simulation can open/close virtual positions right now."""
    settings = _settings()
    report = build_simulation_readiness_report(
        settings,
        log_dir=from_logs,
        fresh_window_ms=fresh_window_seconds * 1000,
    )
    typer.echo(format_simulation_readiness(report))


@app.command("archive-audit")
def archive_audit() -> None:
    """Audit archive hygiene and write the release archive audit report."""
    report_path = write_archive_audit_report(Path(".").resolve())
    typer.echo(f"archive-audit report: {report_path}")


@app.command("create-clean-archive")
def create_clean_archive_command() -> None:
    """Create a clean source archive on the Desktop, never inside the project."""
    root = Path(".").resolve()
    result = create_clean_archive(root)
    report_path = write_archive_audit_report(root)
    typer.echo(f"clean archive created: {result.archive_path}")
    typer.echo(f"files copied: {result.files_copied}")
    typer.echo(f"zip entries: {result.entries}")
    typer.echo(f"archive-audit report: {report_path}")


@app.command("scanner-priority-report")
def scanner_priority_report(
    network_read: bool = typer.Option(False, "--network-read", help="Allow read-only scan planning to select warm-scan wallets."),
    max_leaders: int = typer.Option(3, "--max-leaders", min=1, max=10, help="Max leaders for the next warm scan plan."),
    output_dir: Path = typer.Option(Path("data/reports"), "--output-dir", help="Runtime report directory."),
) -> None:
    """Plan the next read-only scanner rotation and log skipped opportunities."""
    settings = _settings()
    session_factory = _session_factory(settings)
    current_ms = now_ms()
    with session_factory() as session:
        rows = _selected_top_wallet_rows(session, limit=max(50, max_leaders * 10), offset=0)
    candidates = [
        score_wallet_priority(
            WalletPriorityInput(
                wallet_address=row.wallet_address,
                source=row.source,
                trades_count=max(1, int(row.score // 10)),
                observed_notional_usdt=max(0.0, float(row.score) * 1000.0),
                last_seen_ms=row.selected_at_ms,
                now_ms=current_ms,
                wallet_quality_score=float(row.score),
                consistency_score=min(100.0, float(row.score)),
                copyability_score=min(100.0, float(row.score)),
                source_health_score=1.0,
            )
        )
        for row in rows
    ]
    budget = ScanBudget(
        max_leaders_per_run=max_leaders,
        max_ws_unique_users=10,
        rest_weight_remaining=1200,
        network_read_enabled=network_read,
    )
    selection = select_wallets_for_warm_scan(candidates, budget)
    cost = evaluate_warm_scan_budget(budget, requested_wallets=len(selection.selected_wallets))
    typer.echo("scanner_priority_report=research_only")
    typer.echo(f"network_read={'enabled' if network_read else 'disabled'}")
    typer.echo(f"candidates={len(candidates)} selected={len(selection.selected_wallets)} skipped={len(selection.skipped)}")
    typer.echo(f"budget={cost.reason} estimated_rest_weight={cost.estimated_weight} max_leaders={max_leaders}")
    for item in selection.selected_wallets:
        typer.echo(f"SELECT {item.wallet_address} score={item.priority_score:.2f} source={item.source}")
    paths = write_missed_opportunity_reports(selection.skipped, output_dir=output_dir, stem="scanner_priority_missed_opportunities")
    typer.echo(f"missed_opportunity_report={paths['markdown']}")


@app.command("research-magic-bot")
def research_magic_bot() -> None:
    """Print the local research documents that separate claims from implementable logic."""
    docs = [
        "docs/research/MAGIC_BOT_OSINT_RESEARCH.md",
        "docs/research/MAGIC_BOT_CLAIMS_MATRIX.md",
        "docs/research/MAGIC_BOT_LOGIC_RECONSTRUCTION.md",
        "docs/research/POLYMARKET_TO_HYPERLIQUID_TRANSLATION.md",
    ]
    typer.echo("magic_bot_research=research_only_no_profit_claim")
    for doc in docs:
        typer.echo(f"doc={doc} exists={Path(doc).exists()}")


@app.command("research-data-sources")
def research_data_sources() -> None:
    """Show the read-only/local data provider registry."""
    typer.echo(provider_registry_report())


@app.command("data-quality-check")
def data_quality_check(
    network_read: bool = typer.Option(False, "--network-read", help="Allow budget reservation for read-only network requests."),
    source_confidence: float = typer.Option(0.95, "--source-confidence", min=0.0, max=1.0),
    age_ms: int = typer.Option(1_000, "--age-ms", min=0, help="Synthetic exchange data age to evaluate."),
    latency_ms: int = typer.Option(200, "--latency-ms", min=0, help="Synthetic transport latency to evaluate."),
    payload_items: int = typer.Option(1, "--payload-items", min=0, help="Synthetic payload size."),
    request_weight: int = typer.Option(1, "--request-weight", min=1, help="Conservative /info weight estimate."),
    proves_pnl: bool = typer.Option(False, "--proves-pnl", help="Require high confidence because data would support PnL/simulation decisions."),
) -> None:
    """Evaluate whether read-only acquired data is good enough for simulation."""
    request = FetchRequest(
        request_id="cli-data-quality-check",
        provider_name="OfficialInfoProvider",
        endpoint="/info",
        request_type="userFillsByTime",
        wallet_address="0x" + "1" * 40,
        weight=request_weight,
        network_required=True,
        created_at_ms=now_ms(),
    )
    budget = RequestBudgetManager(network_read_enabled=network_read, rest_weight_remaining=1200)
    budget_decision = budget.reserve(request)
    current_ms = now_ms()
    result = FetchResult(
        request=request,
        success=payload_items > 0,
        payload=[{"row": index} for index in range(payload_items)],
        fetched_at_ms=current_ms,
        local_received_at_ms=current_ms + latency_ms,
        exchange_ts_ms=current_ms - age_ms,
        source_confidence_score=source_confidence,
        transport_latency_ms=latency_ms,
        error_message=None if payload_items > 0 else "EMPTY_PAYLOAD",
        source_url="https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint",
    )
    assessment = DataQualityGate(DataQualityConfig()).assess(result, now_ms=current_ms, proves_pnl=proves_pnl)
    typer.echo("request_budget=read_only")
    typer.echo(f"budget_allowed={str(budget_decision.allowed).lower()}")
    typer.echo(f"budget_reason={budget_decision.reason}")
    typer.echo(f"remaining_after={budget_decision.remaining_after}")
    typer.echo(format_data_quality_assessment(assessment))


@app.command("historical-backfill-plan")
def historical_backfill_plan(
    network_read: bool = typer.Option(False, "--network-read", help="Reserve read-only network budget; command still uses a local fake fetcher."),
    wallet: str = typer.Option("0x" + "1" * 40, "--wallet", help="Wallet address used for the local dry-run plan."),
    max_pages: int = typer.Option(2, "--max-pages", min=1, max=20),
    page_window_ms: int = typer.Option(1_000, "--page-window-ms", min=1),
    page_items: int = typer.Option(1, "--page-items", min=0, max=2_000),
    rest_weight_remaining: int = typer.Option(1200, "--rest-weight-remaining", min=0),
) -> None:
    """Run a bounded historical backfill dry-run with budget/cache/quality gates."""

    async def _fake_fetch(_wallet: str, start_ms: int, _end_ms: int, _aggregate: bool) -> list[dict[str, Any]]:
        return [
            {
                "user": _wallet,
                "coin": "BTC",
                "time": start_ms + index + 1,
                "px": "50000",
                "sz": "0.01",
            }
            for index in range(page_items)
        ]

    current_ms = now_ms()
    engine = HistoricalBackfillEngine(
        fetch_page=_fake_fetch,
        budget=RequestBudgetManager(network_read_enabled=network_read, rest_weight_remaining=rest_weight_remaining),
        cache=TtlPageCache(ttl_ms=30_000),
        config=HistoricalBackfillConfig(max_pages_per_wallet=max_pages, page_window_ms=page_window_ms),
    )
    result = asyncio.run(
        engine.run_user_fills_by_time(
            wallet_address=wallet,
            start_time_ms=current_ms - max_pages * page_window_ms,
            end_time_ms=current_ms,
            now_ms=current_ms,
        )
    )
    typer.echo(format_historical_backfill_result(result))


@app.command("benchmark-local-scan")
def benchmark_local_scan(
    wallets: int = typer.Option(2000, "--wallets", min=0, max=200_000, help="Fake local wallets to generate and scan."),
) -> None:
    """Benchmark local wallet scanning without network access."""
    result = run_local_scan_benchmark(wallets)
    typer.echo(format_benchmark_report(result))


@app.command("scan-local")
def scan_local(
    limit: int = typer.Option(2000, "--limit", min=0, max=200_000, help="Fake local wallets to scan without network."),
) -> None:
    """Run a local-only scan over a generated wallet index."""
    index = WalletLocalIndex()
    for i in range(max(0, limit)):
        index.upsert(fake_wallet(i + 1))  # fake-data-scan: allow benchmark fixture (research_only_no_network)
    summary = scan_wallet_index(index, limit=limit)
    typer.echo("scan_local=research_only_no_network")
    typer.echo(f"wallets_scanned={summary.wallets_scanned}")
    typer.echo(f"rejected_count={summary.rejected_count}")
    for wallet in summary.top_wallets[:5]:
        typer.echo(f"TOP {wallet.wallet_address} priority={wallet.priority_hint:.2f} trades={wallet.trades_count}")


@app.command("throughput-plan")
def throughput_plan_command(
    requested_wallets: int = typer.Option(50, "--requested-wallets", min=0, help="Wallets the user would like to cover this cycle."),
    network_read: bool = typer.Option(False, "--network-read", help="Required for real read-only /info planning."),
    ws: bool = typer.Option(False, "--ws", help="Include read-only WebSocket user slots in the plan."),
    rest_weight_remaining: int = typer.Option(1200, "--rest-weight-remaining", min=0, help="Estimated REST weight remaining this minute."),
    max_leaders_per_run: int = typer.Option(50, "--max-leaders-per-run", min=0, help="Local maximum leaders per bounded scan run."),
    fills_expected_per_wallet: int = typer.Option(200, "--fills-expected-per-wallet", min=0, help="Conservative fills estimate per wallet."),
    public_trade_wallets: int = typer.Option(10_000, "--public-trade-wallets", min=0, help="Public trade wallets to retain in local candidate pool."),
    bypass_requested: bool = typer.Option(False, "--bypass-requested", help="Test guard: refuse any attempt to bypass API limits."),
    aggressive_scraping_requested: bool = typer.Option(False, "--aggressive-scraping-requested", help="Test guard: refuse aggressive scraping."),
) -> None:
    """Plan maximum safe read-only coverage without bypassing limits."""
    _settings()
    plan = plan_safe_high_throughput_scan(
        ThroughputRequest(
            requested_wallets=requested_wallets,
            network_read_enabled=network_read,
            ws_enabled=ws,
            bypass_requested=bypass_requested,
            aggressive_scraping_requested=aggressive_scraping_requested,
            rest_weight_remaining=rest_weight_remaining,
            max_leaders_per_run=max_leaders_per_run,
            fills_expected_per_wallet=fills_expected_per_wallet,
            requested_public_trade_wallets=public_trade_wallets,
        )
    )
    typer.echo(format_throughput_plan(plan))
    if plan.refusal_reasons:
        raise typer.Exit(2)


@app.command("collection-budget-plan")
def collection_budget_plan_command(
    network_read: bool = typer.Option(False, "--network-read", help="Authorize official read-only Hyperliquid data planning."),
    all_mids_calls: int = typer.Option(1, "--all-mids-calls", min=0),
    light_info_calls: int = typer.Option(0, "--light-info-calls", min=0),
    default_info_calls: int = typer.Option(0, "--default-info-calls", min=0),
    explorer_calls: int = typer.Option(0, "--explorer-calls", min=0),
    time_range_items: int = typer.Option(0, "--time-range-items", min=0, help="Expected userFillsByTime / time-range returned items."),
    ws_connections: int = typer.Option(1, "--ws-connections", min=0),
    ws_new_connections_per_minute: int = typer.Option(1, "--ws-new-connections-per-minute", min=0),
    ws_subscriptions: int = typer.Option(0, "--ws-subscriptions", min=0),
    ws_unique_users: int = typer.Option(0, "--ws-unique-users", min=0),
    ws_messages_per_minute: int = typer.Option(0, "--ws-messages-per-minute", min=0),
    egress_count: int = typer.Option(1, "--egress-count", min=1, help="Controlled egress shards; never a bypass/proxy evasion switch."),
    target_utilization: float = typer.Option(0.70, "--target-utilization", min=0.10, max=0.90),
    bypass_requested: bool = typer.Option(False, "--bypass-requested", help="Test guard: refused."),
    aggressive_scraping_requested: bool = typer.Option(False, "--aggressive-scraping-requested", help="Test guard: refused."),
) -> None:
    """Audit one Hyperliquid read-only collection budget before scanning."""
    _settings()
    plan = plan_readonly_collection_budget(
        ReadOnlyBudgetRequest(
            network_read_enabled=network_read,
            all_mids_calls=all_mids_calls,
            light_info_calls=light_info_calls,
            default_info_calls=default_info_calls,
            explorer_calls=explorer_calls,
            time_range_items_expected=time_range_items,
            ws_connections=ws_connections,
            ws_new_connections_per_minute=ws_new_connections_per_minute,
            ws_subscriptions=ws_subscriptions,
            ws_unique_users=ws_unique_users,
            ws_messages_per_minute=ws_messages_per_minute,
            egress_count=egress_count,
            target_utilization=target_utilization,
            bypass_requested=bypass_requested,
            aggressive_scraping_requested=aggressive_scraping_requested,
        )
    )
    typer.echo(format_budget_plan(plan))
    if plan.refusal_reasons:
        raise typer.Exit(2)


@app.command("fresh-scan-plan")
def fresh_scan_plan(
    requested_wallets: int = typer.Option(50_000, "--requested-wallets", min=0, help="Target wallet universe size before safe rotation."),
    network_read: bool = typer.Option(False, "--network-read", help="Authorize read-only network scan planning."),
    cycle_seconds: int = typer.Option(15, "--cycle-seconds", min=5, max=300, help="Launcher/poller cycle duration."),
    rest_weight_remaining: int = typer.Option(1200, "--rest-weight-remaining", min=0),
    public_trade_wallets: int = typer.Option(10_000, "--public-trade-wallets", min=0, max=100_000),
    leaders_per_stream: int = typer.Option(10, "--leaders-per-stream", min=1, max=50),
    bypass_requested: bool = typer.Option(False, "--bypass-requested", help="Test guard: refuse API/rate-limit bypass."),
    aggressive_scraping_requested: bool = typer.Option(False, "--aggressive-scraping-requested", help="Test guard: refuse aggressive scraping."),
) -> None:
    """Plan a high-freshness scan loop without bypassing Hyperliquid limits."""
    settings = _settings()
    current_ms = now_ms()
    analysis = analyze_decision_logs_summary(default_logs_to_send_dir())
    stale_count = sum(count for reason, count in analysis.top_refusal_reasons if "STALE_SIGNAL" in reason)
    session_factory = _session_factory(settings)
    with session_factory() as session:
        fresh_leaders = int(
            session.query(TopWallet)
            .filter(TopWallet.status == "selected")
            .filter(TopWallet.selected_at_ms >= current_ms - 60_000)
            .count()
        )
        fresh_deltas = int(
            session.query(PositionDeltaModel)
            .filter(PositionDeltaModel.detected_at_ms >= current_ms - 20_000)
            .count()
        )
    plan = plan_fresh_scan_strategy(
        FreshScanStrategyRequest(
            requested_wallet_universe=requested_wallets,
            network_read_enabled=network_read,
            cycle_seconds=cycle_seconds,
            rest_weight_remaining=rest_weight_remaining,
            leaders_per_user_stream=leaders_per_stream,
            public_trade_wallet_cap_requested=public_trade_wallets,
            stale_signal_count=stale_count,
            fresh_leader_count=fresh_leaders,
            fresh_delta_count=fresh_deltas,
            bypass_requested=bypass_requested,
            aggressive_scraping_requested=aggressive_scraping_requested,
        )
    )
    typer.echo(format_fresh_scan_strategy(plan))
    if plan.refusal_reasons:
        raise typer.Exit(2)


@app.command("fresh-data-plan")
def fresh_data_plan_command(
    network_read: bool = typer.Option(False, "--network-read", help="Authorize read-only public/official data reads."),
    requested_wallets: int = typer.Option(50_000, "--requested-wallets", min=0, help="Target local wallet universe size."),
    coins: str = typer.Option("AUTO", "--coins", help="Coins to monitor, comma separated or AUTO."),
    max_coins: int = typer.Option(40, "--max-coins", min=1, max=200),
    max_hot_wallets: int = typer.Option(10, "--max-hot-wallets", min=1, max=50),
    rest_weight_remaining: int = typer.Option(1200, "--rest-weight-remaining", min=0),
    max_items: int = typer.Option(128, "--max-items", min=1, max=1000),
    gap_recovery: bool = typer.Option(False, "--gap-recovery", help="Include bounded REST recovery snapshots for hot leaders."),
) -> None:
    """Plan the freshest safe read-only acquisition batch for the next cycle."""
    settings = _settings()
    current_ms = now_ms()
    active_coins = tuple(_resolve_public_trade_scan_coins(settings, coins, max_coins=max_coins))
    analysis = analyze_decision_logs_summary(default_logs_to_send_dir())
    stale_count = sum(count for reason, count in analysis.top_refusal_reasons if "STALE_SIGNAL" in reason)
    stale_pressure = "CRITICAL" if stale_count >= 1000 else "HIGH" if stale_count else "LOW"
    session_factory = _session_factory(settings)
    with session_factory() as session:
        hot_wallets = tuple(row.wallet_address for row in _selected_top_wallet_rows(session, limit=min(10, max_hot_wallets)))
    plan = build_fresh_data_plan(
        FreshDataPlanRequest(
            network_read_enabled=network_read,
            active_coins=active_coins,
            hot_wallets=hot_wallets,
            requested_wallet_universe=requested_wallets,
            rest_weight_remaining=rest_weight_remaining,
            max_hot_wallets=max_hot_wallets,
            max_items=max_items,
            now_ms=current_ms,
            gap_recovery=gap_recovery or stale_pressure in {"HIGH", "CRITICAL"},
            stale_pressure=stale_pressure,
        )
    )
    typer.echo(format_fresh_data_plan(plan))
    budget_plan = plan_readonly_collection_budget(
        ReadOnlyBudgetRequest(
            network_read_enabled=network_read,
            all_mids_calls=sum(1 for item in plan.selected_requests if item.request_type == "allMids"),
            light_info_calls=sum(
                1
                for item in plan.selected_requests
                if item.endpoint == "/info" and item.request_type != "allMids" and item.weight <= 2
            ),
            default_info_calls=sum(
                1
                for item in plan.selected_requests
                if item.endpoint == "/info" and item.weight > 2
            ),
            ws_connections=1 if plan.public_streams or plan.hot_user_streams else 0,
            ws_new_connections_per_minute=1 if plan.public_streams or plan.hot_user_streams else 0,
            ws_subscriptions=plan.public_streams + plan.hot_user_streams,
            ws_unique_users=plan.hot_user_streams,
            ws_messages_per_minute=0,
        )
    )
    typer.echo("")
    typer.echo(format_budget_plan(budget_plan))


@app.command("consensus-leader-report")
def consensus_leader_report_command(
    leaders: int = typer.Option(10, "--leaders", min=1, max=50),
    active_window_seconds: int = typer.Option(300, "--active-window-seconds", min=4),
    consensus_window_seconds: int = typer.Option(4, "--consensus-window-seconds", min=1, max=60),
    min_wallets: int = typer.Option(2, "--min-wallets", min=2, max=10),
    max_deltas: int = typer.Option(5_000, "--max-deltas", min=100),
) -> None:
    """Rank leaders by fresh same-coin/same-direction consensus clusters."""
    settings = _settings()
    session_factory = _session_factory(settings)
    with session_factory() as session:
        _, report = _consensus_top_wallet_rows(
            session,
            limit=leaders,
            active_window_ms=active_window_seconds * 1_000,
            consensus_window_ms=consensus_window_seconds * 1_000,
            min_wallets=min_wallets,
            max_deltas=max_deltas,
        )
    typer.echo(format_consensus_leader_report(report))


@app.command("hot-watch")
def hot_watch(
    network_read: bool = typer.Option(False, "--network-read", help="Required for real read-only websocket watching; this command plans only."),
    duration_seconds: int = typer.Option(60, "--duration-seconds", min=1, max=3600, help="Bounded hot-watch duration."),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Keep as dry-run planning."),
) -> None:
    """Plan a bounded read-only hot-watch rotation; never opens orders."""
    if not dry_run:
        typer.echo("Safety refused: hot-watch remains dry-run/read-only in this build.")
        raise typer.Exit(2)
    settings = _settings()
    session_factory = _session_factory(settings)
    current_ms = now_ms()
    with session_factory() as session:
        rows = _selected_top_wallet_rows(session, limit=50)
    candidates = [(row.wallet_address, float(row.score), row.selected_at_ms) for row in rows]
    slots = rotate_hot_watch(candidates, now_ms=current_ms, max_slots=10, slot_ttl_ms=duration_seconds * 1000)
    typer.echo("hot_watch_plan=read_only_dry_run")
    typer.echo(f"network_read={'enabled' if network_read else 'disabled'}")
    typer.echo(f"duration_seconds={duration_seconds}")
    typer.echo(f"slots={len(slots)} max_unique_users=10")
    for slot in slots:
        typer.echo(f"SLOT {slot.slot_id} {slot.wallet_address} priority={slot.priority:.2f} expires_at_ms={slot.expires_at_ms}")


@app.command("realtime-recovery-plan")
def realtime_recovery_plan(
    wallet: str = typer.Option("0x" + "1" * 40, "--wallet"),
    stale_after_ms: int = typer.Option(20_000, "--stale-after-ms", min=1),
    event_gap_ms: int = typer.Option(5_000, "--event-gap-ms", min=1),
    sequence_gap: int = typer.Option(3, "--sequence-gap", min=1),
) -> None:
    """Plan reconnect/backfill after a stale or gapped read-only realtime stream."""
    current_ms = now_ms()
    engine = RealtimeRecoveryEngine(
        ReconnectPolicy(
            stale_after_ms=stale_after_ms,
            max_event_gap_ms=event_gap_ms,
            max_sequence_gap=1,
            max_pages=3,
        )
    )
    first = WatchStreamEvent(
        event_id="cli:first",
        wallet_address=wallet,
        observed_at_ms=current_ms - 10_000,
        received_at_ms=current_ms - 10_000,
        event_type=StreamEventType.NEW,
        sequence=1,
        payload_hash="first",
    )
    second = WatchStreamEvent(
        event_id="cli:gapped",
        wallet_address=wallet,
        observed_at_ms=current_ms,
        received_at_ms=current_ms + stale_after_ms + 1,
        event_type=StreamEventType.NEW,
        sequence=1 + sequence_gap,
        payload_hash="gapped",
    )
    engine.process_event(first)
    decision = engine.process_event(second)
    typer.echo(format_recovery_decision(decision))


@app.command("missed-opportunities")
def missed_opportunities(
    period: str = typer.Option("24h", "--period", help="Display label only; report is local runtime."),
) -> None:
    """Show the latest local missed-opportunity report path and summary."""
    path = Path("data/reports/scanner_priority_missed_opportunities.md")
    typer.echo("missed_opportunities=research_only")
    typer.echo(f"period={period}")
    typer.echo(f"report={path}")
    if path.exists():
        text = path.read_text(encoding="utf-8")
        first_total = next((line for line in text.splitlines() if line.startswith("Total:")), "Total: unknown")
        typer.echo(first_total)
    else:
        typer.echo("Total: 0")


@app.command("opportunity-report")
def opportunity_report(
    period: str = typer.Option("1h", "--period", help="Display period label."),
    active_window_seconds: int = typer.Option(120, "--active-window-seconds", min=1, max=3600, help="Only analyze fresh deltas inside this window."),
    consensus_window_seconds: int = typer.Option(4, "--consensus-window-seconds", min=1, max=60, help="Same coin/same direction grouping window."),
    min_wallets: int = typer.Option(2, "--min-wallets", min=1, max=10, help="Minimum wallets needed for a cluster."),
    max_deltas: int = typer.Option(5_000, "--max-deltas", min=10, max=100_000),
    max_opportunities: int = typer.Option(20, "--max-opportunities", min=1, max=100),
) -> None:
    """Rank fresh same-coin/same-direction clusters for virtual simulation only."""
    settings = _settings()
    session_factory = _session_factory(settings)
    current_ms = now_ms()
    with session_factory() as session:
        leaders = (
            session.query(TopWallet)
            .filter(TopWallet.status == "selected")
            .order_by(TopWallet.selected_at_ms.desc(), TopWallet.score.desc())
            .limit(5_000)
            .all()
        )
        deltas = (
            session.query(PositionDeltaModel)
            .order_by(PositionDeltaModel.detected_at_ms.desc())
            .limit(max_deltas)
            .all()
        )
        mids = _latest_market_mids(session)
    simulation_min_edge_bps = calibrated_float_env(
        "HYPERSMART_SIMULATION_MIN_EDGE_BPS",
        DEFAULT_SIMULATION_MIN_EDGE_BPS,
    )
    report = find_fresh_opportunities(
        deltas,
        leaders,
        now_timestamp_ms=current_ms,
        current_mids=mids,
        active_window_ms=active_window_seconds * 1_000,
        consensus_window_ms=consensus_window_seconds * 1_000,
        min_wallets=min_wallets,
        max_opportunities=max_opportunities,
        risk_config=RealtimeCopyRiskConfig(
            min_edge_required_bps=max(1.0, simulation_min_edge_bps),
            max_signal_age_ms=active_window_seconds * 1_000,
            starting_equity_usdt=1000.0,
        ),
    )
    typer.echo(format_fresh_opportunity_report(report))
    typer.echo(f"period={period}")


@app.command("warehouse-report")
def warehouse_report(
    fresh_window_seconds: int = typer.Option(20, "--fresh-window-seconds", min=1, max=3600),
) -> None:
    """Explain which local data layers are fresh enough for paper simulation."""
    settings = _settings()
    session_factory = _session_factory(settings)
    current_ms = now_ms()
    with session_factory() as session:
        report = build_warehouse_coverage_report(
            session,
            now_ms=current_ms,
            fresh_window_ms=fresh_window_seconds * 1_000,
        )
    typer.echo(format_warehouse_coverage_report(report))


@app.command("consensus-report")
def consensus_report(
    period: str = typer.Option("1h", "--period", help="Display period label."),
) -> None:
    """Report consensus policy used by local simulation."""
    typer.echo("consensus_report=research_only")
    typer.echo(f"period={period}")
    typer.echo("policy=same coin + same direction + short fresh window")
    typer.echo("safety=consensus alone never bypasses edge_remaining_bps")


@app.command("simulate-magic-bot")
def simulate_magic_bot(
    capital: float = typer.Option(1000.0, "--capital", min=1.0, help="Virtual local starting capital."),
    scenario: str = typer.Option("conservative", "--scenario", help="Simulation scenario label."),
) -> None:
    """Start/report a local simulation plan; no order, no network."""
    if abs(capital - 1000.0) > 0.001:
        typer.echo("Safety warning: product default is 1000 USDT fictive; custom capital is report-only.")
    typer.echo("simulate_magic_bot=local_simulation_without_money")
    typer.echo(f"capital={capital:.2f}")
    typer.echo(f"scenario={scenario}")
    typer.echo("max_position_notional=50.00")
    typer.echo("max_total_exposure=200.00")
    typer.echo("execution=forbidden")


@app.command("simulation-report")
def simulation_report(
    period: str = typer.Option("24h", "--period", help="Display period label."),
) -> None:
    """Show where the live local simulation state is stored."""
    settings = _settings()
    typer.echo("simulation_report=local_without_money")
    typer.echo(f"period={period}")
    typer.echo(f"state_path={simulation_state_path(settings)}")
    typer.echo("starting_equity_usdt=1000.00")


@app.command("simulation-loss-report")
def simulation_loss_report(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Explain why the local simulation gains, loses or refuses decisions."""
    _settings()
    report = build_loss_attribution_report(from_logs)
    typer.echo(format_loss_attribution_report(report))


@app.command("simulation-tuning-report")
def simulation_tuning_report(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Recommend stricter local simulation tuning from observed losses/refusals."""
    _settings()
    typer.echo(format_simulation_tuning_report(build_simulation_tuning_report(from_logs)))


@app.command("logs-analyze")
def logs_analyze(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Stream all simulation decision logs and report PnL/root metrics."""
    _settings()
    typer.echo(format_logs_analysis(analyze_logs_streaming(from_logs)))


@app.command("root-cause-from-logs")
def root_cause_from_logs(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Explain the dominant local simulation loss causes from logs."""
    _settings()
    typer.echo(format_diagnostic_report(build_root_cause_from_logs(from_logs)))


@app.command("profitability-diagnostics")
def profitability_diagnostics(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Report gross/net PnL after costs from simulation logs."""
    _settings()
    typer.echo(format_diagnostic_report(build_profitability_diagnostics(from_logs)))


@app.command("refusal-breakdown")
def refusal_breakdown(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Rank no-trade/refusal reasons from simulation logs."""
    _settings()
    typer.echo(format_diagnostic_report(build_refusal_breakdown(from_logs)))


@app.command("cost-drag-diagnostics")
def cost_drag_diagnostics(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Diagnose fees and cost drag in local simulation logs."""
    _settings()
    typer.echo(format_diagnostic_report(build_cost_drag_diagnostics(from_logs)))


@app.command("position-matching-diagnostics")
def position_matching_diagnostics(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Diagnose orphan reduce/close and ADD-without-OPEN issues."""
    _settings()
    typer.echo(format_diagnostic_report(build_position_matching_diagnostics(from_logs)))


@app.command("stale-signal-diagnostics")
def stale_signal_diagnostics(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Diagnose signal-age and stale-copy problems."""
    _settings()
    typer.echo(format_diagnostic_report(build_stale_signal_diagnostics(from_logs)))


@app.command("wallet-loss-diagnostics")
def wallet_loss_diagnostics(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Rank wallets by net PnL contribution in local simulation logs."""
    _settings()
    typer.echo(format_diagnostic_report(build_wallet_loss_diagnostics(from_logs)))


@app.command("coin-loss-diagnostics")
def coin_loss_diagnostics(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Rank coins by net PnL contribution in local simulation logs."""
    _settings()
    typer.echo(format_diagnostic_report(build_coin_loss_diagnostics(from_logs)))


@app.command("action-loss-diagnostics")
def action_loss_diagnostics(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Rank OPEN/ADD/REDUCE/CLOSE actions by net PnL contribution."""
    _settings()
    typer.echo(format_diagnostic_report(build_action_loss_diagnostics(from_logs)))


@app.command("edge-distribution-diagnostics")
def edge_distribution_diagnostics(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Report edge_remaining_bps distribution and sentinels."""
    _settings()
    typer.echo(format_diagnostic_report(build_edge_distribution_diagnostics(from_logs)))


@app.command("timing-distribution-diagnostics")
def timing_distribution_diagnostics(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Report timing/freshness distribution for copy signals."""
    _settings()
    typer.echo(format_diagnostic_report(build_timing_distribution_diagnostics(from_logs)))


def _try_write_optimization_reports(report, output_dir: Path) -> None:
    try:
        write_optimization_reports(report, output_dir)
    except OSError as exc:
        typer.echo(
            f"optimization_report_write=unavailable path={output_dir} reason={exc.__class__.__name__}: {exc}",
            err=True,
        )
        typer.echo("optimization_report_write_policy=analysis_printed_without_runtime_file_mutation", err=True)


@app.command("strategy-tournament")
def strategy_tournament(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
    output_dir: Path = typer.Option(Path("data/reports"), "--output-dir", help="Runtime report output directory."),
) -> None:
    """Compare strategy families on train/validation/holdout without fake gains."""
    _settings()
    report = run_strategy_tournament(from_logs)
    _try_write_optimization_reports(report, output_dir)
    typer.echo(format_optimization_report(report))


@app.command("optimize-profit-config")
def optimize_profit_config(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
    output_dir: Path = typer.Option(Path("data/reports"), "--output-dir", help="Runtime report output directory."),
) -> None:
    """Select the most robust net-PnL configuration from simulation logs."""
    _settings()
    report = run_strategy_tournament(from_logs)
    _try_write_optimization_reports(report, output_dir)
    typer.echo(format_optimization_report(report))


@app.command("walk-forward-profit-validation")
def walk_forward_profit_validation(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
    output_dir: Path = typer.Option(Path("data/reports"), "--output-dir", help="Runtime report output directory."),
) -> None:
    """Validate best config on train/validation/holdout windows."""
    _settings()
    report = run_strategy_tournament(from_logs)
    _try_write_optimization_reports(report, output_dir)
    typer.echo(format_optimization_report(report))


@app.command("out-of-sample-report")
def out_of_sample_report(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
    output_dir: Path = typer.Option(Path("data/reports"), "--output-dir", help="Runtime report output directory."),
) -> None:
    """Report holdout behavior for strategy candidates."""
    _settings()
    report = run_strategy_tournament(from_logs)
    _try_write_optimization_reports(report, output_dir)
    typer.echo(format_optimization_report(report))


@app.command("anti-overfit-audit")
def anti_overfit_audit(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
    output_dir: Path = typer.Option(Path("data/reports"), "--output-dir", help="Runtime report output directory."),
) -> None:
    """Audit whether candidate configs only win on train and fail holdout."""
    _settings()
    report = run_strategy_tournament(from_logs)
    _try_write_optimization_reports(report, output_dir)
    typer.echo("anti_overfit_audit=simulation_only")
    for result in report.strategies:
        typer.echo(f"{result.config.name}: overfit_rejected={str(result.overfit_rejected).lower()}")
    typer.echo("future_profit_guarantee=false")


@app.command("best-config-report")
def best_config_report(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
    output_dir: Path = typer.Option(Path("data/reports"), "--output-dir", help="Runtime report output directory."),
) -> None:
    """Print the current best robust config from local logs."""
    _settings()
    report = run_strategy_tournament(from_logs)
    _try_write_optimization_reports(report, output_dir)
    typer.echo(format_optimization_report(report))


@app.command("explain-loss-fr")
def explain_loss_fr(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing logs to send."),
) -> None:
    """Explain simulation losses in beginner-friendly French."""
    _settings()
    report = build_loss_attribution_report(from_logs)
    typer.echo("explain_loss_fr=simulation_only")
    for item in report.root_causes.plain_french:
        typer.echo(f"- {item}")


@app.command("realtime-health")
def realtime_health(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing local replay logs."),
    stale_after_seconds: int = typer.Option(30, "--stale-after-seconds", min=1, max=3600),
) -> None:
    """Check whether the local realtime simulation feed is fresh enough."""
    _settings()
    typer.echo(format_realtime_health(check_realtime_health(from_logs, stale_after_seconds=stale_after_seconds)))


@app.command("realtime-replay")
def realtime_replay(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing local replay logs."),
    speed: str = typer.Option("5x", "--speed", help="Display/replay speed label; no sleeping or network."),
    limit: int = typer.Option(100, "--limit", min=1, max=10_000, help="Max recent events to export into replay."),
) -> None:
    """Create a fresh read-only replay stream from local logs."""
    _settings()
    typer.echo(format_replay_result(replay_events_from_logs(from_logs, speed=speed, limit=limit)))


@app.command("realtime-latency-report")
def realtime_latency_report(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing local replay logs."),
) -> None:
    """Measure local signal-age latency from simulation logs."""
    _settings()
    typer.echo(format_latency_report(build_latency_report(from_logs)))


@app.command("freshness-diagnostics")
def freshness_diagnostics(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing local replay logs."),
) -> None:
    """Diagnose stale signals and recommend safer scanner settings."""
    _settings()
    typer.echo(format_freshness_diagnostics(build_freshness_diagnostics(from_logs)))


@app.command("live-pnl")
def live_pnl(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing local replay logs."),
) -> None:
    """Print current local simulated PnL from logs; no network and no orders."""
    _settings()
    snapshot = _read_json_file(from_logs / "simulation_snapshot_latest.json")
    equity = snapshot.get("equity") if isinstance(snapshot.get("equity"), dict) else {}
    analysis = analyze_decision_logs_summary(from_logs)
    typer.echo("live_pnl=local_simulation_only")
    typer.echo(f"source_dir={from_logs}")
    typer.echo(f"starting_equity_usdt={equity.get('starting_equity_usdt', snapshot.get('starting_equity_usdt'))}")
    typer.echo(f"current_equity_usdt={equity.get('current_equity_usdt')}")
    typer.echo(f"current_pnl_usdc={equity.get('current_pnl_usdc')}")
    typer.echo(f"realized_pnl_usdc={equity.get('realized_pnl_usdc')}")
    typer.echo(f"unrealized_pnl_usdc={equity.get('unrealized_pnl_usdc')}")
    typer.echo(f"events={analysis.event_count}")
    typer.echo(f"closed_log_event_pnl_usdc={analysis.total_estimated_pnl_usdc}")
    typer.echo(f"closed_log_fees_usdc={analysis.total_fees_usdc}")
    typer.echo("pnl_scope=session_balance_is_fresh_launcher_state; closed_log_event_pnl_is_complete_local_decision_log")
    typer.echo("orders_created=0")


@app.command("pnl-stream")
def pnl_stream(
    replay: Path = typer.Option(default_logs_to_send_dir(), "--replay", help="Folder containing local replay logs."),
    limit: int = typer.Option(20, "--limit", min=1, max=500),
) -> None:
    """Replay recent PnL events from local logs; this is not a network stream."""
    _settings()
    events = load_recent_decision_events(replay, limit=limit)
    typer.echo("pnl_stream=local_replay_only")
    typer.echo(f"source_dir={replay}")
    for event in events:
        typer.echo(
            " | ".join(
                [
                    str(event.timestamp_ms),
                    str(event.coin),
                    event.bot_decision,
                    f"pnl={event.estimated_net_pnl_usdc}",
                    f"fee={event.fee_cost_usdc}",
                    f"reason={event.reason}",
                ]
            )
        )


@app.command("metagraph-export")
def metagraph_export(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing local replay logs."),
    output_dir: Path = typer.Option(Path("data/reports"), "--output-dir", help="Runtime report output directory."),
) -> None:
    """Export PnL/equity metagraph data from local simulation logs."""
    _settings()
    typer.echo(format_metagraph_export(export_metagraph_from_logs(from_logs, output_dir=output_dir)))


@app.command("dashboard-export")
def dashboard_export() -> None:
    """Export the read-only HyperSmart dashboard HTML; no network and no actions."""
    _settings()
    config = load_hypersmart_config()
    path = export_hypersmart_dashboard(config)
    typer.echo("dashboard_export=read_only")
    typer.echo(f"path={path}")
    typer.echo("orders_created=0")
    typer.echo("network_required=false")


@app.command("dashboard-state")
def dashboard_state(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing dashboard logs."),
) -> None:
    """Report dashboard state provenance and current simulation snapshot."""
    settings = _settings()
    truth = run_dashboard_truth_audit(from_logs)
    health = check_realtime_health(from_logs)
    typer.echo("dashboard_state=local_read_only")
    typer.echo(f"state_path={simulation_state_path(settings)}")
    typer.echo(f"logs_dir={from_logs}")
    typer.echo(f"truth_ok={str(truth.ok).lower()}")
    typer.echo(f"realtime_status={health.status}")
    typer.echo(f"events_seen={health.events_seen}")


@app.command("copy-preflight")
def copy_preflight(
    network_read: bool = typer.Option(False, "--network-read", help="Plan bounded /info reads; no orders."),
    copy_max_leaders: int | None = typer.Option(None, "--copy-max-leaders", min=1),
) -> None:
    """Check whether copy-run can perform a bounded read-only collection."""
    _settings()
    config = load_hypersmart_config()
    report = run_copy_preflight(config, network_read=network_read, max_leaders=copy_max_leaders)
    json_path, md_path = write_copy_preflight_report(report, config.reports_dir)
    typer.echo(format_copy_preflight_report(report))
    typer.echo(f"copy_preflight_json={json_path}")
    typer.echo(f"copy_preflight_md={md_path}")
    typer.echo("orders_created=0")
    typer.echo("testnet_executor_active=false")


@app.command("dashboard-truth-audit")
def dashboard_truth_audit(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing dashboard logs."),
) -> None:
    """Audit that dashboard metrics have local provenance and are not placeholders."""
    _settings()
    audit = run_dashboard_truth_audit(from_logs)
    typer.echo(format_dashboard_truth_audit(audit))
    if not audit.ok:
        raise typer.Exit(1)


@app.command("prompt-coverage-audit")
def prompt_coverage_audit() -> None:
    """Write MEGA V1 prompt coverage and traceability reports."""
    _settings()
    audit = evaluate_prompt_coverage(Path("."))
    typer.echo(format_coverage_summary(audit))


@app.command("non-deletion-check")
def non_deletion_check() -> None:
    """Verify every major MEGA V1 requirement family is still tracked."""
    _settings()
    audit = evaluate_prompt_coverage(Path("."))
    ok, missing = verify_non_deletion(audit.rows)
    typer.echo("non_deletion_check=tracked")
    typer.echo(f"families={audit.total}")
    typer.echo(f"todo_or_partial={len(missing)}")
    typer.echo(f"report={audit.non_deletion_path}")
    if not ok:
        typer.echo("missing=" + ",".join(missing))
        raise typer.Exit(1)


@app.command("quality-gates")
def quality_gates(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing dashboard logs."),
) -> None:
    """Run release quality gates without executing trades."""
    _settings()
    report = run_quality_gates(Path("."), log_dir=from_logs)
    typer.echo(format_quality_gates(report))
    if report.hard_failed:
        raise typer.Exit(1)


@app.command("closeout-sprint")
def closeout_sprint(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing dashboard logs."),
) -> None:
    """Write a closeout report with quality gates and safe next actions."""
    _settings()
    report = write_closeout_report(Path("."), log_dir=from_logs)
    typer.echo(f"closeout_report={report.report_path}")
    typer.echo(format_quality_gates(report.quality))
    if report.quality.hard_failed:
        raise typer.Exit(1)


@app.command("explain-latest-decision-fr")
def explain_latest_decision_fr(
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing local replay logs."),
) -> None:
    """Explain the latest local simulation decision in simple French."""
    _settings()
    events = load_recent_decision_events(from_logs, limit=1)
    typer.echo("explain_latest_decision_fr=simulation_only")
    if not events:
        typer.echo("- Aucune decision locale enregistree.")
        return
    event = events[-1]
    typer.echo(f"- Ce que le bot a vu: {event.leader_action or 'action inconnue'} sur {event.coin or 'coin inconnu'} par {event.wallet_address or 'wallet inconnu'}.")
    typer.echo(f"- Decision locale: {event.bot_decision}, statut {event.status}.")
    typer.echo(f"- Raison: {event.reason or 'aucune raison detaillee'}")
    typer.echo(f"- Impact PnL fictif: {event.estimated_net_pnl_usdc}")
    typer.echo("- Securite: simulation locale seulement, aucun ordre reel.")


@app.command("explain-no-trade-fr")
def explain_no_trade_fr(
    latest: bool = typer.Option(False, "--latest", help="Explain latest no-trade only."),
    from_logs: Path = typer.Option(default_logs_to_send_dir(), "--from-logs", help="Folder containing local replay logs."),
) -> None:
    """Explain no-trade decisions in French."""
    _settings()
    events = load_recent_decision_events(from_logs, limit=500 if latest else 2_000)
    refused = [event for event in events if event.status.upper() == "REFUSED" or event.bot_decision == "NO_TRADE"]
    typer.echo("explain_no_trade_fr=simulation_only")
    if not refused:
        typer.echo("- Aucun refus local enregistre.")
        return
    rows = refused[-1:] if latest else refused[-10:]
    for event in rows:
        typer.echo(f"- {event.coin or 'coin inconnu'}: refus `{event.reason or 'raison inconnue'}`. Action suivante: verifier edge_remaining, fraicheur du signal et position papier correspondante.")


@app.command("research-import-manual")
def research_import_manual(
    path: Path = typer.Option(Path("docs/research/MEGA_V1_MANUAL_RESEARCH_INBOX.md"), "--path", help="Manual research inbox path."),
    output: Path = typer.Option(Path("data/reports/manual_research_items.json"), "--output", help="Runtime JSON output."),
) -> None:
    """Import manual research notes into a structured local JSON file."""
    _settings()
    if not path.exists():
        write_manual_research_template(path)
    typer.echo(format_manual_research_import(import_manual_research(path, output_path=output)))


@app.command("research-classify-manual")
def research_classify_manual(
    path: Path = typer.Option(Path("docs/research/MEGA_V1_MANUAL_RESEARCH_INBOX.md"), "--path", help="Manual research inbox path."),
) -> None:
    """Classify manual research; never treats user-provided claims as truth."""
    _settings()
    typer.echo(format_classified_research(classify_manual_research(path)))


@app.command("research-to-feature-map")
def research_to_feature_map(
    path: Path = typer.Option(Path("docs/research/MEGA_V1_MANUAL_RESEARCH_INBOX.md"), "--path", help="Manual research inbox path."),
) -> None:
    """Write a source-to-feature map for manual research."""
    _settings()
    typer.echo(format_feature_map(write_research_to_feature_map(path)))


@app.command("autoscan")
def autoscan_command(
    sources: str = typer.Option(
        "leaderboard,explorer,local,imports",
        "--sources",
        help="Comma-separated sources to attempt.",
    ),
    store: bool = typer.Option(False, "--store", help="Store successful read-only observations."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan and report without network writes."),
    report: bool = typer.Option(False, "--report", help="Print detailed autoscan report."),
) -> None:
    """Run the honest read-only startup scan pipeline."""
    settings = _settings()
    source_list = [item.strip() for item in sources.split(",") if item.strip()]
    result = run_autoscan(
        settings,
        dry_run=dry_run or not store,
        store=store,
        sources=source_list,
        report=report,
    )
    typer.echo(format_autoscan_report(result))


@app.command("collect-once")
def collect_once(
    coin: list[str] | None = typer.Option(None, "--coin", help="Coin to collect, repeatable."),
    all_coins: bool = typer.Option(False, "--all-coins", help="Resolve and scan multiple Hyperliquid coins."),
    include_altcoins: bool = typer.Option(True, "--include-altcoins/--majors-only", help="Include altcoins in multi-asset scans."),
    max_coins: int | None = typer.Option(None, "--max-coins", help="Maximum coins to scan."),
    coins_from_meta: bool = typer.Option(False, "--coins-from-meta", help="Resolve coins from Hyperliquid meta."),
    coins_from_all_mids: bool = typer.Option(False, "--coins-from-all-mids", help="Resolve coins from allMids keys."),
    wallet: list[str] | None = typer.Option(None, "--wallet", help="Public wallet address, repeatable."),
    fetch: bool = typer.Option(False, help="Actually call read-only /info endpoints."),
    all_mids: bool = typer.Option(False, "--all-mids", help="Collect allMids."),
    l2_book: bool = typer.Option(False, "--l2-book", help="Collect l2Book for selected coins."),
    open_orders: bool = typer.Option(False, "--open-orders", help="Collect openOrders for wallets."),
    frontend_open_orders: bool = typer.Option(
        False,
        "--frontend-open-orders",
        help="Collect frontendOpenOrders for wallets.",
    ),
    user_fills: bool = typer.Option(False, "--user-fills", help="Collect recent userFills."),
    user_fills_by_time: bool = typer.Option(
        False,
        "--user-fills-by-time",
        help="Collect paginated userFillsByTime.",
    ),
    candles: bool = typer.Option(False, "--candles", help="Collect candleSnapshot for selected coins."),
    interval: str = typer.Option("1m", "--interval", help="Candle interval."),
    start_ms: int | None = typer.Option(None, "--start-ms", help="Start timestamp in ms."),
    end_ms: int | None = typer.Option(None, "--end-ms", help="End timestamp in ms."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan only: no network and no DB writes."),
    store_raw: bool | None = typer.Option(None, "--store-raw/--no-store-raw", help="Store raw_events."),
    limit_pages: int | None = typer.Option(None, "--limit-pages", help="Max userFillsByTime pages."),
    oid_or_cloid: str | None = typer.Option(None, "--oid-or-cloid", help="Order id or cloid."),
) -> None:
    """Run one read-only collection pass. Defaults to dry-run unless --fetch is set."""
    settings = _settings()
    try:
        for address in wallet or []:
            validate_wallet_address(address)
        plan = build_default_collection_plan(
            settings=settings,
            fetch=fetch,
            dry_run=dry_run,
            store_raw=store_raw,
            coins=coin,
            all_coins=all_coins,
            include_altcoins=include_altcoins,
            max_coins=max_coins,
            coins_from_meta=coins_from_meta,
            coins_from_all_mids=coins_from_all_mids,
            wallets=wallet,
            all_mids=all_mids,
            l2_book=l2_book,
            open_orders=open_orders,
            frontend_open_orders=frontend_open_orders,
            user_fills=user_fills,
            user_fills_by_time=user_fills_by_time,
            candles=candles,
            interval=interval,
            start_ms=start_ms,
            end_ms=end_ms,
            oid_or_cloid=oid_or_cloid,
            limit_pages=limit_pages,
        )
    except InvalidWalletAddress as exc:
        typer.echo(f"invalid wallet: {exc}")
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(f"invalid collect-once options: {exc}")
        raise typer.Exit(1) from exc

    result = asyncio.run(run_collection_once(plan, settings))
    if result.dry_run:
        typer.echo("dry-run: no network and no database writes")
        typer.echo("planned_items:")
        for item in result.planned_items:
            typer.echo(f"- {item}")
        return
    typer.echo(
        "collect-once complete: "
        f"run_id={result.run_id} fetched={result.fetched_items} "
        f"raw_events={result.raw_events_stored} errors={result.errors_count}"
    )
    _record_local_snapshots(settings, plan.wallets, run_id=result.run_id, source="collect-once")


@app.command("discover-markets")
def discover_markets(
    source: list[str] | None = typer.Option(None, "--source", help="Universe source: meta or all-mids."),
    include_altcoins: bool = typer.Option(True, "--include-altcoins/--majors-only", help="Include altcoins."),
    max_coins: int | None = typer.Option(None, "--max-coins", help="Maximum coins shown in report."),
    store: bool = typer.Option(False, "--store", help="Store market_universe rows."),
    dry_run: bool = typer.Option(False, "--dry-run", help="No network and no database writes."),
    report: bool = typer.Option(False, "--report", help="Print report."),
    json_output: bool = typer.Option(False, "--json", help="Reserved for future JSON output."),
) -> None:
    """Discover Hyperliquid markets through read-only /info meta/allMids."""
    settings = _settings()
    plan = MarketDiscoveryPlan(
        sources=source or ["meta", "all-mids"],
        include_altcoins=include_altcoins,
        max_coins=max_coins,
        store=store,
        dry_run=dry_run or not store,
        report=report,
        json_output=json_output,
    )
    result = asyncio.run(run_discover_markets(plan, settings))
    typer.echo(format_market_discovery_report(result))


@app.command("scan-markets")
def scan_markets(
    all_markets: bool = typer.Option(False, "--all", help="Scan selected universe coins."),
    coin: list[str] | None = typer.Option(None, "--coin", help="Coin to scan, repeatable."),
    include_altcoins: bool = typer.Option(True, "--include-altcoins/--majors-only", help="Include altcoins."),
    max_coins: int | None = typer.Option(None, "--max-coins", help="Maximum coins to scan."),
    l2book: bool = typer.Option(True, "--l2book/--no-l2book", help="Collect l2Book for selected coins."),
    candles: bool = typer.Option(False, "--candles/--no-candles", help="Reserve candle scan slots."),
    store: bool = typer.Option(False, "--store", help="Store raw events and market metrics."),
    dry_run: bool = typer.Option(False, "--dry-run", help="No network and no database writes."),
    report: bool = typer.Option(False, "--report", help="Print report."),
) -> None:
    """Scan multiple Hyperliquid markets in read-only mode."""
    settings = _settings()
    plan = MarketScanPlan(
        coins=coin or [],
        all_coins=all_markets or not coin,
        include_altcoins=include_altcoins,
        max_coins=max_coins,
        l2book=l2book,
        candles=candles,
        store=store,
        dry_run=dry_run or not store,
        report=report,
    )
    result = asyncio.run(run_scan_markets(plan, settings))
    typer.echo(format_market_scan_report(result))


@app.command("score-wallets")
def score_wallets() -> None:
    """Placeholder for deterministic wallet scoring."""
    _settings()
    typer.echo("score-wallets ready: deterministic wallet scoring modules are available")


@app.command("wallet-backfill")
def wallet_backfill(
    wallet: list[str] | None = typer.Option(None, "--wallet", help="Public wallet address, repeatable."),
    coin: list[str] | None = typer.Option(None, "--coin", help="Coin for optional market snapshots, repeatable."),
    all_coins: bool = typer.Option(False, "--all-coins", help="Analyze all coins present in wallet fills."),
    include_altcoins: bool = typer.Option(True, "--include-altcoins/--majors-only", help="Keep altcoin fills and reports."),
    fetch: bool = typer.Option(True, "--fetch/--no-fetch", help="Call read-only /info endpoints."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan only: no network and no DB writes."),
    store_raw: bool | None = typer.Option(None, "--store-raw/--no-store-raw", help="Store raw_events."),
    start_ms: int | None = typer.Option(None, "--start-ms", help="Backfill start timestamp in ms."),
    end_ms: int | None = typer.Option(None, "--end-ms", help="Backfill end timestamp in ms."),
    limit_pages: int | None = typer.Option(None, "--limit-pages", help="Max userFillsByTime pages."),
    page_window_ms: int | None = typer.Option(None, "--page-window-ms", help="Page window in ms."),
    recent_fills: bool = typer.Option(True, "--recent-fills/--no-recent-fills", help="Collect userFills."),
    fills_by_time: bool = typer.Option(
        True,
        "--fills-by-time/--no-fills-by-time",
        help="Collect paginated userFillsByTime.",
    ),
    include_open_orders: bool = typer.Option(
        True,
        "--include-open-orders/--no-include-open-orders",
        help="Collect openOrders.",
    ),
    frontend_open_orders: bool = typer.Option(
        True,
        "--include-frontend-open-orders/--no-include-frontend-open-orders",
        help="Collect frontendOpenOrders.",
    ),
    include_market_snapshots: bool = typer.Option(
        False,
        "--include-market-snapshots/--no-include-market-snapshots",
        help="Collect allMids and l2Book for selected coins.",
    ),
    rebuild_positions: bool = typer.Option(
        True,
        "--rebuild-positions/--no-rebuild-positions",
        help="Rebuild approximate positions from fills.",
    ),
    compute_deltas: bool = typer.Option(
        True,
        "--compute-deltas/--no-compute-deltas",
        help="Compute and store position_deltas from reconstructed positions.",
    ),
    report: bool = typer.Option(False, "--report", help="Print a wallet-backfill summary report."),
) -> None:
    """Backfill one or more public wallets through read-only Hyperliquid /info endpoints."""
    settings = _settings()
    _ = (all_coins, include_altcoins)
    try:
        plan = build_wallet_backfill_plan(
            settings=settings,
            wallets=wallet,
            coins=coin,
            fetch=fetch,
            dry_run=dry_run,
            store_raw=store_raw,
            start_ms=start_ms,
            end_ms=end_ms,
            limit_pages=limit_pages,
            page_window_ms=page_window_ms,
            recent_fills=recent_fills,
            fills_by_time=fills_by_time,
            open_orders=include_open_orders,
            frontend_open_orders=frontend_open_orders,
            market_snapshots=include_market_snapshots,
            rebuild_positions=rebuild_positions,
            position_deltas=compute_deltas,
            report=report,
        )
    except InvalidWalletAddress as exc:
        typer.echo(f"invalid wallet-backfill options: {exc}")
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(f"invalid wallet-backfill options: {exc}")
        raise typer.Exit(1) from exc

    result = asyncio.run(run_wallet_backfill(plan, settings))
    if result.dry_run:
        typer.echo("dry-run: no network and no database writes")
        typer.echo("planned_items:")
        for item in result.planned_items:
            typer.echo(f"- {item}")
        if report:
            typer.echo(format_wallet_backfill_report(result, plan))
        return
    _record_local_snapshots(settings, plan.wallets, run_id=result.run_id, source="wallet-backfill")
    if report:
        typer.echo(format_wallet_backfill_report(result, plan))
        return
    typer.echo(
        "wallet-backfill complete: "
        f"run_id={result.run_id} wallets={result.wallets_count} fetched={result.fetched_items} "
        f"fills={result.fills_stored} positions={result.positions_rebuilt} "
        f"deltas={result.position_deltas_created} "
        f"raw_events={result.raw_events_stored} errors={result.errors_count}"
    )


@app.command("discover-wallets")
def discover_wallets(
    source: list[str] | None = typer.Option(None, "--source", help="Discovery source, repeatable."),
    coin: list[str] | None = typer.Option(None, "--coin", help="Coin filter, use ANY for all markets."),
    all_coins: bool = typer.Option(False, "--all-coins", help="Keep candidates from all coins."),
    include_altcoins: bool = typer.Option(True, "--include-altcoins/--majors-only", help="Keep altcoin-positive wallets."),
    min_altcoin_liquidity_score: float = typer.Option(0.0, "--min-altcoin-liquidity-score", help="Reserved altcoin liquidity floor."),
    max_coins_per_wallet: int = typer.Option(20, "--max-coins-per-wallet", help="Maximum coins tracked per wallet."),
    max_candidates: int | None = typer.Option(None, "--max-candidates", help="Maximum candidates to score."),
    min_discovery_score: float | None = typer.Option(None, "--min-discovery-score", help="Minimum score."),
    require_positive_pnl: bool | None = typer.Option(
        None,
        "--require-positive-pnl/--allow-missing-or-negative-pnl",
        help="Require positive external PnL when available.",
    ),
    require_positive_roi: bool | None = typer.Option(
        None,
        "--require-positive-roi/--allow-missing-or-negative-roi",
        help="Require positive external ROI when available.",
    ),
    store: bool = typer.Option(False, "--store", help="Store discovery run, sources and candidates."),
    backfill_selected: bool = typer.Option(False, "--backfill-selected", help="Backfill selected wallets read-only."),
    backfill_limit: int | None = typer.Option(None, "--backfill-limit", help="Maximum selected wallets to backfill."),
    dry_run: bool = typer.Option(False, "--dry-run", help="No database writes and no backfill."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON result."),
    report: bool = typer.Option(False, "--report", help="Print discovery report."),
) -> None:
    """Discover public Hyperliquid wallets through safe read-only sources."""
    settings = _settings()
    plan = build_wallet_discovery_plan(
        settings,
        sources=source,
        coins=["ANY"] if all_coins else coin,
        include_altcoins=include_altcoins,
        max_candidates=max_candidates,
        min_discovery_score=min_discovery_score,
        require_positive_pnl=require_positive_pnl,
        require_positive_roi=require_positive_roi,
        store=store,
        dry_run=dry_run or not store,
        backfill_selected=backfill_selected,
        backfill_limit=backfill_limit,
        min_altcoin_liquidity_score=min_altcoin_liquidity_score,
        max_coins_per_wallet=max_coins_per_wallet,
        report=report,
        json_output=json_output,
    )
    result = run_wallet_discovery(plan, settings)
    if backfill_selected and not plan.dry_run and result.selected_wallets:
        wallets = [item.candidate.address for item in result.selected_wallets if item.candidate.address]
        backfill_result = asyncio.run(
            run_wallet_backfill(
                WalletBackfillPlan(
                    fetch=True,
                    wallets=wallets[: plan.backfill_limit],
                    limit_pages=1,
                    include_recent_fills=False,
                    include_open_orders=True,
                    include_frontend_open_orders=True,
                    include_market_snapshots=False,
                    rebuild_positions=True,
                    compute_position_deltas=True,
                ),
                settings,
            )
        )
        typer.echo(
            f"backfill-selected complete: wallets={len(wallets)} "
            f"fills={backfill_result.fills_stored} deltas={backfill_result.position_deltas_created}"
        )
    if json_output:
        typer.echo(discovery_result_json(result))
    elif report or True:
        typer.echo(format_discovery_report(result))


@app.command("scrape-leaderboard")
def scrape_leaderboard_command(
    period: str = typer.Option("30D", "--period", help="Leaderboard period: 1D, 7D, 30D or ALL."),
    method: str = typer.Option("auto", "--method", help="Extraction method: auto, network, dom, browser."),
    target: int = typer.Option(500, "--target", help="Target rows to inspect when supported."),
    max_pages: int = typer.Option(1, "--max-pages", help="Maximum pages when pagination is supported."),
    store: bool = typer.Option(False, "--store", help="Store rows and full-address candidates."),
    dry_run: bool = typer.Option(False, "--dry-run", help="No network and no database writes."),
    report: bool = typer.Option(False, "--report", help="Print report."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON result."),
) -> None:
    """Read the public Hyperliquid leaderboard without accepting truncated addresses."""
    settings = _settings()
    _ = max_pages
    session_factory = _session_factory(settings)
    with session_factory() as session:
        result = asyncio.run(
            scrape_leaderboard(
                settings,
                period=period,
                method=method,
                dry_run=dry_run or not store,
                store=store,
                session=session,
                target=target,
            )
        )
        if store and not (dry_run or not store):
            session.commit()
    if json_output:
        import json

        typer.echo(json.dumps(result.model_dump(), indent=2, default=str))
    else:
        typer.echo(format_leaderboard_report(result))


@app.command("import-leaderboard")
def import_leaderboard_command(
    file: Path = typer.Option(..., "--file", help="CSV/JSON/TXT containing complete wallet addresses."),
    period: str = typer.Option("30D", "--period"),
    store: bool = typer.Option(False, "--store"),
    report: bool = typer.Option(False, "--report"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Import leaderboard rows from a local file; truncated addresses are rejected."""
    settings = _settings()
    session_factory = _session_factory(settings)
    with session_factory() as session:
        result = import_leaderboard_file(file, period=period, store=store, session=session if store else None)
        if store:
            session.commit()
    if json_output:
        import json

        typer.echo(json.dumps(result.model_dump(), indent=2, default=str))
    elif report or True:
        typer.echo(format_leaderboard_report(result))


@app.command("validate-leaderboard-addresses")
def validate_leaderboard_addresses_command(report: bool = typer.Option(False, "--report")) -> None:
    """Validate stored leaderboard raw values and report rejected truncated addresses."""
    settings = _settings()
    session_factory = _session_factory(settings)
    with session_factory() as session:
        rows = session.query(LeaderboardAddressValidation).order_by(LeaderboardAddressValidation.id.desc()).limit(5000).all()
    full = sum(1 for row in rows if row.is_full_address)
    truncated = sum(1 for row in rows if row.is_truncated)
    invalid = len(rows) - full - truncated
    typer.echo("leaderboard address validation report")
    typer.echo(f"validations: {len(rows)}")
    typer.echo(f"full addresses: {full}")
    typer.echo(f"truncated rejected: {truncated}")
    typer.echo(f"invalid rejected: {invalid}")
    if report and truncated:
        typer.echo("Les adresses contenant ... restent rejetees et ne deviennent jamais candidates.")


@app.command("leaderboard-candidates")
def leaderboard_candidates_command(
    period: str = typer.Option("30D", "--period"),
    min_pnl: float | None = typer.Option(None, "--min-pnl"),
    min_roi: float | None = typer.Option(None, "--min-roi"),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Show complete-address leaderboard candidates only."""
    settings = _settings()
    session_factory = _session_factory(settings)
    with session_factory() as session:
        query = session.query(LeaderboardWalletCandidate).filter(LeaderboardWalletCandidate.period == period)
        if min_pnl is not None:
            query = query.filter(LeaderboardWalletCandidate.pnl_usdc >= min_pnl)
        if min_roi is not None:
            query = query.filter(LeaderboardWalletCandidate.roi_pct >= min_roi)
        rows = query.order_by(LeaderboardWalletCandidate.leaderboard_score.desc()).limit(100).all()
    typer.echo("leaderboard candidates report")
    typer.echo(f"periode: {period}")
    typer.echo(f"candidats complets: {len(rows)}")
    for row in rows[:10]:
        typer.echo(f"- {row.wallet_address} rank={row.rank} pnl={row.pnl_usdc} roi={row.roi_pct} score={row.leaderboard_score:.1f}")


@app.command("probe-explorer")
def probe_explorer_command(
    method: str = typer.Option("network", "--method", help="Probe method: network, dom or auto."),
    dry_run: bool = typer.Option(False, "--dry-run", help="No network in dry-run."),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Probe the public Hyperliquid Explorer without accepting truncated addresses."""
    settings = _settings()
    result = asyncio.run(
        scrape_explorer(
            settings,
            method=method,
            dry_run=dry_run,
            store=False,
            max_events=100,
            session=None,
        )
    )
    typer.echo(format_explorer_report(result))


@app.command("scrape-explorer")
def scrape_explorer_command(
    method: str = typer.Option("network", "--method", help="Scrape method: network, dom or auto."),
    max_events: int = typer.Option(500, "--max-events", help="Maximum explorer events to normalize."),
    store: bool = typer.Option(False, "--store", help="Store explorer transactions and candidates."),
    dry_run: bool = typer.Option(False, "--dry-run", help="No network and no database writes."),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Scrape public Explorer observations in read-only mode."""
    settings = _settings()
    session_factory = _session_factory(settings)
    with session_factory() as session:
        result = asyncio.run(
            scrape_explorer(
                settings,
                method=method,
                dry_run=dry_run or not store,
                store=store,
                max_events=max_events,
                session=session,
            )
        )
        if store and not dry_run:
            session.commit()
    typer.echo(format_explorer_report(result))


@app.command("import-explorer")
def import_explorer_command(
    file: Path = typer.Option(..., "--file", help="CSV/JSON/TXT containing explorer rows or full addresses."),
    store: bool = typer.Option(False, "--store"),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Import Explorer rows locally; truncated addresses are rejected."""
    settings = _settings()
    session_factory = _session_factory(settings)
    with session_factory() as session:
        result = import_and_store_explorer(file, store=store, session=session if store else None)
        if store:
            session.commit()
    typer.echo(format_explorer_report(result))


@app.command("explorer-candidates")
def explorer_candidates_command(
    store: bool = typer.Option(False, "--store"),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Create Explorer wallet candidates from stored full-address transactions."""
    settings = _settings()
    session_factory = _session_factory(settings)
    with session_factory() as session:
        created = create_explorer_candidates(session)
        if store:
            session.commit()
        else:
            session.rollback()
    typer.echo("explorer candidates report")
    typer.echo(f"candidats crees: {created}")
    typer.echo(f"dry-run: {not store}")


@app.command("revalidate-explorer-wallets")
def revalidate_explorer_wallets_command(
    limit: int = typer.Option(100, "--limit"),
    store: bool = typer.Option(False, "--store"),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Revalidate Explorer candidates through strict full-address guards."""
    settings = _settings()
    session_factory = _session_factory(settings)
    with session_factory() as session:
        result = revalidate_explorer_wallets(session, limit=limit, store=store)
        if store:
            session.commit()
        else:
            session.rollback()
    typer.echo("explorer revalidation report")
    typer.echo(f"checked: {result['checked']}")
    typer.echo(f"ok: {result['ok']}")
    typer.echo(f"failed: {result['failed']}")


@app.command("explorer-tape")
def explorer_tape_command(
    limit: int = typer.Option(100, "--limit"),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Show the local Explorer transaction tape."""
    settings = _settings()
    session_factory = _session_factory(settings)
    with session_factory() as session:
        rows = get_explorer_tape(session, limit=limit)
    typer.echo(format_explorer_tape(rows))


@app.command("bootstrap-top-wallets")
def bootstrap_top_wallets_command(
    target: int = typer.Option(500, "--target"),
    source: str = typer.Option("all", "--source"),
    revalidate: bool = typer.Option(False, "--revalidate/--no-revalidate"),
    backfill_selected: bool = typer.Option(False, "--backfill-selected/--no-backfill-selected"),
    backfill_limit: int = typer.Option(25, "--backfill-limit"),
    store: bool = typer.Option(False, "--store"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Build an honest Top 500 from available complete-address candidates."""
    settings = _settings()
    _ = (revalidate, backfill_selected, backfill_limit, report)
    session_factory = _session_factory(settings)
    with session_factory() as session:
        result = bootstrap_top_wallets(
            settings,
            session=session,
            target=target,
            source=source,
            store=store,
            dry_run=dry_run or not store,
        )
        if store and not dry_run:
            session.commit()
    typer.echo(format_top500_report(result))


@app.command("scan-wallet-queue")
def scan_wallet_queue_command(
    max_wallets: int = typer.Option(500, "--max-wallets"),
    batch_size: int = typer.Option(25, "--batch-size"),
    resume: bool = typer.Option(False, "--resume/--no-resume"),
    store: bool = typer.Option(False, "--store"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Scan the queued complete wallets progressively; never creates orders."""
    settings = _settings()
    _ = (resume, report)
    session_factory = _session_factory(settings)
    with session_factory() as session:
        result = scan_wallet_queue(
            session,
            max_wallets=min(max_wallets, settings.wallet_scanner.scan_max_wallets_per_run),
            batch_size=min(batch_size, settings.wallet_scanner.scan_batch_size),
            dry_run=dry_run or not store,
        )
        if store and not dry_run:
            session.commit()
    typer.echo(format_scan_queue_report(result))


@app.command("analyze-openings")
def analyze_openings_command(
    all_wallets: bool = typer.Option(False, "--all-wallets"),
    max_wallets: int = typer.Option(500, "--max-wallets"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Detect OPEN/ADD/FLIP opening events from stored position_deltas."""
    settings = _settings()
    _ = (all_wallets, max_wallets, report)
    session_factory = _session_factory(settings)
    with session_factory() as session:
        deltas = session.query(PositionDeltaModel).order_by(PositionDeltaModel.detected_at_ms.desc()).limit(max_wallets * 20).all()
        openings = detect_openings_from_deltas(deltas)
        if not dry_run:
            for opening in openings:
                session.add(
                    WalletOpening(
                        wallet_address=opening.wallet_address,
                        coin=opening.coin,
                        opening_type=opening.opening_type.value,
                        side=opening.side,
                        detected_at_ms=opening.detected_at_ms or now_ms(),
                        confidence_score=opening.confidence_score,
                    )
                )
            session.commit()
    typer.echo("opening analysis report")
    typer.echo(f"openings detected: {len(openings)}")
    typer.echo(f"dry-run: {dry_run}")


@app.command("analyze-closings")
def analyze_closings_command(
    all_wallets: bool = typer.Option(False, "--all-wallets"),
    max_wallets: int = typer.Option(500, "--max-wallets"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Detect REDUCE/CLOSE/FLIP closing events from stored position_deltas."""
    settings = _settings()
    _ = (all_wallets, max_wallets, report)
    session_factory = _session_factory(settings)
    with session_factory() as session:
        deltas = session.query(PositionDeltaModel).order_by(PositionDeltaModel.detected_at_ms.desc()).limit(max_wallets * 20).all()
        closings = detect_closings_from_deltas(deltas)
        if not dry_run:
            for closing in closings:
                session.add(
                    WalletClosing(
                        wallet_address=closing.wallet_address,
                        coin=closing.coin,
                        closing_type=closing.closing_type.value,
                        detected_at_ms=closing.detected_at_ms or now_ms(),
                        confidence_score=closing.confidence_score,
                    )
                )
            session.commit()
    typer.echo("closing analysis report")
    typer.echo(f"closings detected: {len(closings)}")
    typer.echo(f"dry-run: {dry_run}")


@app.command("opening-patterns")
def opening_patterns_command(
    all_wallets: bool = typer.Option(False, "--all-wallets"),
    min_samples: int = typer.Option(20, "--min-samples"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Rank opening patterns; low sample sizes stay rejected/observe-only."""
    settings = _settings()
    _ = (all_wallets, report)
    session_factory = _session_factory(settings)
    with session_factory() as session:
        openings = session.query(WalletOpening).limit(5000).all()
        grouped: dict[str, list[float]] = {}
        for opening in openings:
            grouped.setdefault(opening.opening_type, []).append(0.0)
        stats = [
            compute_opening_pattern_stats(values, opening_type=key, min_samples=min_samples)
            for key, values in grouped.items()
        ]
        if not dry_run:
            for item in stats:
                session.add(
                    WalletOpeningPatternStats(
                        opening_type=item.opening_type,
                        sample_size=item.sample_size,
                        win_rate=item.win_rate,
                        expectancy=item.expectancy,
                        profit_factor=item.profit_factor,
                        opening_pattern_score=item.score,
                        decision=item.decision.value,
                        reasons_json=item.reasons,
                    )
                )
            session.commit()
    typer.echo("opening patterns report")
    typer.echo(f"patterns ranked: {len(stats)}")
    typer.echo(f"min samples: {min_samples}")
    typer.echo(f"dry-run: {dry_run}")


@app.command("trader-playbooks")
def trader_playbooks_command(
    all_wallets: bool = typer.Option(False, "--all-wallets"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Generate observe-only methodology summaries from stored openings."""
    settings = _settings()
    _ = (all_wallets, report)
    session_factory = _session_factory(settings)
    with session_factory() as session:
        openings = session.query(WalletOpening).limit(5000).all()
        by_wallet: dict[str, list[WalletOpening]] = {}
        for opening in openings:
            by_wallet.setdefault(opening.wallet_address, []).append(opening)
        playbooks = []
        for wallet_address, items in by_wallet.items():
            profile = build_methodology_profile(
                wallet_address=wallet_address,
                coins=[item.coin for item in items],
                opening_types=[item.opening_type for item in items],
                copyability_score=50.0,
            )
            playbook = generate_trader_playbook(profile)
            playbooks.append(playbook)
            if not dry_run:
                session.add(
                    WalletMethodologyProfile(
                        wallet_address=profile.wallet_address,
                        primary_style=profile.primary_style.value,
                        best_coins_json=profile.best_coins,
                        worst_coins_json=[],
                        best_opening_types_json=profile.best_opening_types,
                        worst_opening_types_json=[],
                        best_closing_types_json=[],
                        copyability_score=profile.copyability_score,
                        risk_score=profile.risk_score,
                        methodology_summary=profile.methodology_summary,
                        confidence_score=profile.confidence_score,
                    )
                )
                session.add(
                    WalletPlaybook(
                        wallet_address=playbook.wallet_address,
                        coin=playbook.coin,
                        playbook_type=playbook.playbook_type,
                        rule_summary=playbook.rule_summary,
                        opening_rules_json=playbook.opening_rules,
                        closing_rules_json=playbook.closing_rules,
                        risk_rules_json=playbook.risk_rules,
                        copy_rules_json=playbook.copy_rules,
                        rejected_rules_json=playbook.rejected_rules,
                        confidence_score=playbook.confidence_score,
                        status=playbook.status,
                    )
                )
        if not dry_run:
            session.commit()
    typer.echo("trader playbooks report")
    typer.echo(f"playbooks generated: {len(playbooks)}")
    typer.echo(f"dry-run: {dry_run}")


@app.command("follow-signals")
def follow_signals_command(
    paper: bool = typer.Option(False, "--paper/--observe-only"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Build paper-follow signals from fresh openings and apply basic safety checks."""
    settings = _settings()
    _ = report
    session_factory = _session_factory(settings)
    created = 0
    allowed = 0
    with session_factory() as session:
        openings = session.query(WalletOpening).order_by(WalletOpening.detected_at_ms.desc()).limit(100).all()
        for opening in openings:
            signal = build_follow_signal_from_opening(opening)
            decision = decide_follow_signal(
                signal_age_ms=signal.signal_age_ms,
                wallet_action="OPEN",
                spread_bps=0.0,
                slippage_bps=0.0,
                wallet_score=100.0,
                pattern_score=100.0,
            )
            created += 1
            allowed += int(decision.allowed and paper)
            if not dry_run:
                session.merge(
                    FollowSignal(
                        id=signal.signal_id,
                        wallet_address=signal.wallet_address,
                        coin=signal.coin,
                        side=signal.side,
                        opening_type=signal.opening_type,
                        created_at_ms=signal.created_at_ms,
                        signal_age_ms=signal.signal_age_ms,
                        raw_json=signal.raw,
                    )
                )
                session.add(
                    FollowDecision(
                        signal_id=signal.signal_id,
                        decision=decision.decision.value,
                        allowed=decision.allowed and paper,
                        reasons_json=decision.reasons,
                        risk_level="PAPER" if decision.allowed and paper else "OBSERVE_ONLY",
                        computed_at_ms=now_ms(),
                    )
                )
        if not dry_run:
            session.commit()
    typer.echo("follow signals report")
    typer.echo(f"signals created: {created}")
    typer.echo(f"paper allowed: {allowed}")
    typer.echo(f"dry-run: {dry_run}")


@app.command("paper-follow")
def paper_follow_command(
    max_signals: int = typer.Option(20, "--max-signals"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    report: bool = typer.Option(False, "--report"),
) -> None:
    """Create simulated paper follow orders only; no exchange endpoint exists."""
    settings = _settings()
    _ = report
    session_factory = _session_factory(settings)
    with session_factory() as session:
        created = 0 if dry_run else create_paper_follow_orders(session, max_signals=max_signals)
        if not dry_run:
            session.commit()
    typer.echo("paper follow report")
    typer.echo(f"simulated orders created: {created}")
    typer.echo(f"dry-run: {dry_run}")


@app.command("copy-run")
def copy_run_command(
    interval: int = typer.Option(300, "--interval", help="Polling interval in seconds; default 5 minutes."),
    source_mode: str = typer.Option("polling", "--source-mode", help="polling or ws-dry-run."),
    leaders: int = typer.Option(50, "--leaders", "--copy-max-leaders", help="Maximum leaders to auto-select."),
    leader_offset: int = typer.Option(0, "--leader-offset", help="Skip this many ranked leaders before selecting the current bounded batch."),
    max_deltas: int = typer.Option(500, "--max-deltas", help="Recent position deltas to inspect."),
    network_read: bool = typer.Option(False, "--network-read", help="Explicitly allow bounded read-only /info collection before detection."),
    backfill_days: int = typer.Option(1, "--backfill-days", help="Bounded recent history window for --network-read."),
    fresh_window_minutes: int = typer.Option(15, "--fresh-window-minutes", help="Fresh read window for live simulation; set 0 to use --backfill-days."),
    consensus_window_seconds: int = typer.Option(4, "--consensus-window-seconds", min=1, max=300, help="Same coin/side leader clustering window for wallet selection."),
    consensus_min_wallets: int = typer.Option(3, "--consensus-min-wallets", min=2, max=10, help="Minimum independent wallets for consensus-prioritized selection."),
    max_pages: int = typer.Option(2, "--max-pages", help="Maximum userFillsByTime pages per wallet for --network-read."),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Batch 1 is dry-run only."),
    report: bool = typer.Option(True, "--report/--no-report", help="Print copy-run report."),
) -> None:
    """Run the copy detector in paper/mock-USDC dry-run mode only."""
    settings = _settings()
    if not dry_run:
        typer.echo("copy-run refused: Batch 1 is dry-run only; no orders and no testnet execution.")
        raise typer.Exit(1)
    session_factory = _session_factory(settings)
    consensus_selection_report: ConsensusLeaderSelectionReport | None = None
    with session_factory() as session:
        leaders = max(1, min(leaders, settings.copy_trading.top_leaders))
        leader_offset = max(0, leader_offset)
        leaderboard_rows = (
            session.query(LeaderboardWalletCandidate)
            .order_by(LeaderboardWalletCandidate.leaderboard_score.desc())
            .limit(settings.wallet_bootstrap.max_candidates_total)
            .all()
        )
        leaderboard_candidates = [
            _leaderboard_model_to_candidate(row)
            for row in leaderboard_rows
        ]
        leader_offset = max(0, leader_offset)
        selection_limit = max(leaders, leaders + leader_offset)
        leader_report = select_copy_leaders(
            leaderboard_candidates,
            config=CopyLeaderAutoSelectConfig(
                top_n=selection_limit,
                min_history_days=settings.copy_trading.min_history_days,
                min_score=settings.copy_trading.min_copy_leader_score,
                max_drawdown_pct=settings.copy_trading.max_drawdown_pct,
                min_consistency_score=settings.copy_trading.min_consistency_score,
                max_pnl_concentration=settings.copy_trading.max_pnl_concentration,
                require_positive_pnl=settings.copy_trading.require_positive_pnl,
                require_positive_roi=settings.copy_trading.require_positive_roi,
            ),
        )
        accepted_batch = leader_report.accepted[leader_offset : leader_offset + leaders]
        followed = [
            TopWallet(
                wallet_address=item.wallet_address,
                rank=item.rank,
                source="copy_auto_select",
                score=item.score,
                selected_at_ms=now_ms(),
                status="selected",
                notes=";".join(item.reasons),
            )
            for item in accepted_batch
        ]
        followed = _unique_top_wallet_rows(followed, limit=leaders)
        consensus_followed, consensus_selection_report = _consensus_top_wallet_rows(
            session,
            limit=leaders,
            offset=leader_offset,
            active_window_ms=max(60_000, fresh_window_minutes * 60_000 if fresh_window_minutes > 0 else 5 * 60_000),
            consensus_window_ms=consensus_window_seconds * 1_000,
            min_wallets=consensus_min_wallets,
            max_deltas=max(1_000, max_deltas * 10),
        )
        if consensus_followed:
            followed = consensus_followed
        elif not followed:
            followed = _selected_top_wallet_rows(session, limit=leaders, offset=leader_offset)
        followed = _unique_top_wallet_rows(followed, limit=leaders)
        followed_addresses = {wallet.wallet_address.lower() for wallet in followed}

    pre_backfill_signals = None
    throughput_plan = None
    if network_read:
        throughput_plan = plan_safe_high_throughput_scan(
            ThroughputRequest(
                requested_wallets=len(followed),
                network_read_enabled=True,
                ws_enabled=source_mode.lower() in {"ws", "websocket", "ws-dry-run"},
                rest_weight_remaining=1200,
                max_leaders_per_run=leaders,
                fills_expected_per_wallet=max(200, min(2_000, max_pages * 500)),
                ws_requested_unique_users=min(10, leaders),
            )
        )
        if throughput_plan.selected_wallets < len(followed):
            followed = followed[: throughput_plan.selected_wallets]
            followed_addresses = {wallet.wallet_address.lower() for wallet in followed}
    if network_read and followed:
        with session_factory() as session:
            delta_query = session.query(PositionDeltaModel).order_by(PositionDeltaModel.detected_at_ms.desc())
            delta_query = delta_query.filter(PositionDeltaModel.wallet_address.in_(followed_addresses))
            pre_deltas = delta_query.limit(max_deltas).all()
        mode = CopySourceMode.WEBSOCKET_DRY_RUN if source_mode.lower() in {"ws", "websocket", "ws-dry-run"} else CopySourceMode.POLLING
        pre_backfill_signals = detect_copy_signals_from_deltas(
            pre_deltas,
            settings=settings,
            followed_wallets=followed,
            interval_seconds=interval,
            source_mode=mode,
            now_timestamp_ms=now_ms(),
        )

    backfill_result = None
    backfill_plan = None
    if network_read:
        if not followed:
            typer.echo("copy-run observation-only: no safely scannable leaders this cycle; scanner remains active for next rotation.")
        end_ms = now_ms()
        if followed:
            if fresh_window_minutes > 0:
                start_ms = max(0, end_ms - max(1, fresh_window_minutes) * 60_000)
            else:
                start_ms = max(0, end_ms - max(1, backfill_days) * 86_400_000)
            backfill_plan = build_wallet_backfill_plan(
                settings=settings,
                wallets=[wallet.wallet_address for wallet in followed],
                fetch=True,
                dry_run=False,
                store_raw=True,
                start_ms=start_ms,
                end_ms=end_ms,
                limit_pages=max(1, max_pages),
                page_window_ms=settings.collection.user_fills_page_window_ms,
                recent_fills=True,
                fills_by_time=True,
                open_orders=True,
                frontend_open_orders=True,
                market_snapshots=True,
                rebuild_positions=True,
                position_deltas=True,
                report=report,
            )
            try:
                backfill_result = asyncio.run(run_wallet_backfill(backfill_plan, settings))
            except SQLAlchemyError as exc:
                typer.echo(
                    "copy-run observation-only: runtime database is not writable; "
                    f"network read/backfill skipped without stopping scanner. reason={exc.__class__.__name__}"
                )
                backfill_result = None
                backfill_plan = None

    with session_factory() as session:
        followed_addresses = {wallet.wallet_address.lower() for wallet in followed}
        delta_query = session.query(PositionDeltaModel).order_by(PositionDeltaModel.detected_at_ms.desc())
        if followed_addresses:
            delta_query = delta_query.filter(PositionDeltaModel.wallet_address.in_(followed_addresses))
        deltas = delta_query.limit(max_deltas).all()
        mode = CopySourceMode.WEBSOCKET_DRY_RUN if source_mode.lower() in {"ws", "websocket", "ws-dry-run"} else CopySourceMode.POLLING
        post_backfill_signals = detect_copy_signals_from_deltas(
            deltas,
            settings=settings,
            followed_wallets=followed,
            interval_seconds=interval,
            source_mode=mode,
        )
        signals = (
            pre_backfill_signals
            if pre_backfill_signals is not None and pre_backfill_signals.paper_candidates > 0
            else post_backfill_signals
        )
    if report:
        if throughput_plan is not None:
            typer.echo(format_throughput_plan(throughput_plan))
            typer.echo("")
        if backfill_result is not None and backfill_plan is not None:
            typer.echo(format_wallet_backfill_report(backfill_result, backfill_plan))
            typer.echo("")
        if consensus_selection_report is not None:
            typer.echo(format_consensus_leader_report(consensus_selection_report))
            typer.echo("")
        typer.echo(format_copy_run_report(leaders=leader_report, signals=signals))
    else:
        suffix = f" network_read_fetched={backfill_result.fetched_items}" if backfill_result is not None else ""
        if throughput_plan is not None and throughput_plan.warnings:
            suffix += f" throughput={throughput_plan.status}:{throughput_plan.selected_wallets}/{throughput_plan.requested_wallets}"
        typer.echo(
            "copy-run dry-run complete: "
            f"leaders_scanned={len(followed)} signals={signals.signals_created} "
            f"virtual_entries_accepted={signals.paper_candidates}{suffix}"
        )


@app.command("live-public-scan")
def live_public_scan_command(
    coins: str = typer.Option("BTC,ETH,SOL,HYPE,DOGE,XRP,BNB,ENA,AVAX,LINK", "--coins"),
    max_coins: int = typer.Option(40, "--max-coins", help="Maximum trade subscriptions when --coins AUTO/ALL is used."),
    duration_seconds: int = typer.Option(45, "--duration-seconds"),
    max_wallets: int = typer.Option(500, "--max-wallets"),
    min_notional_usdc: float = typer.Option(0.0, "--min-notional-usdc"),
    promote_top: int = typer.Option(50, "--promote-top"),
    network_read: bool = typer.Option(False, "--network-read"),
    store: bool = typer.Option(False, "--store/--dry-run"),
    report: bool = typer.Option(True, "--report/--no-report"),
) -> None:
    """Discover active wallets from public read-only trades WebSocket streams."""
    settings = _settings()
    if not network_read:
        typer.echo("live-public-scan refused: --network-read is required for WebSocket reads.")
        raise typer.Exit(1)
    scan_coins = _resolve_public_trade_scan_coins(settings, coins, max_coins=max_coins)
    result = asyncio.run(
        scan_public_trades_ws(
            settings,
            coins=scan_coins,
            duration_seconds=duration_seconds,
            max_wallets=max_wallets,
            min_notional_usdc=min_notional_usdc,
            network_read=True,
        )
    )
    if store:
        _store_with_sqlite_retry(
            settings,
            label="live-public-scan",
            store_func=lambda session: store_public_trade_scan(
                session,
                result,
                promote_top=promote_top,
            ),
        )
    if report:
        typer.echo(format_public_trade_scan_report(result))
    else:
        typer.echo(
            "live-public-scan complete: "
            f"trades={result.trades_seen} wallets={len(result.wallet_stats)} "
            f"promoted={result.wallets_stored} stopped_reason={result.stopped_reason}"
        )


@app.command("live-user-fills-scan")
def live_user_fills_scan_command(
    duration_seconds: int = typer.Option(12, "--duration-seconds"),
    max_users: int = typer.Option(10, "--max-users"),
    leader_offset: int = typer.Option(0, "--leader-offset"),
    max_live_fill_age_ms: int = typer.Option(
        20_000,
        "--max-live-fill-age-ms",
        help="Ignore userFills updates older than this local receipt age; 0 disables the guard.",
    ),
    wallets: str = typer.Option("", "--wallets", help="Comma-separated complete wallet addresses; defaults to selected top wallets."),
    network_read: bool = typer.Option(False, "--network-read"),
    store: bool = typer.Option(False, "--store/--dry-run"),
    report: bool = typer.Option(True, "--report/--no-report"),
) -> None:
    """Watch shortlist userFills over read-only WebSocket; no orders."""
    settings = _settings()
    if not network_read:
        typer.echo("live-user-fills-scan refused: --network-read is required for WebSocket reads.")
        raise typer.Exit(1)
    max_users = max(1, min(int(max_users), 10))
    selected_wallets = [item.strip() for item in wallets.split(",") if item.strip()]
    if not selected_wallets:
        session_factory = _session_factory(settings)
        with session_factory() as session:
            selected_wallets = [
                row.wallet_address
                for row in _selected_top_wallet_rows(session, limit=max_users, offset=leader_offset)
            ]
    result = asyncio.run(
        scan_user_fills_ws(
            settings,
            wallets=selected_wallets,
            duration_seconds=duration_seconds,
            max_users=max_users,
            network_read=True,
        )
    )
    if store:
        _store_with_sqlite_retry(
            settings,
            label="live-user-fills-scan",
            store_func=lambda session: store_user_fills_live_result(
                session,
                result,
                max_live_fill_age_ms=max_live_fill_age_ms,
            ),
        )
    if report:
        typer.echo(format_user_fills_live_report(result))
    else:
        typer.echo(
            "live-user-fills-scan complete: "
            f"wallets={len(result.wallets)} fills={result.fills_seen} "
            f"stale_ignored={result.stale_fills_ignored} "
            f"deltas={result.deltas_stored} stopped_reason={result.stopped_reason}"
        )


@app.command("copy-report")
def copy_report_command(
    period: str = typer.Option("7d", "--period", help="Report period label, e.g. 7d."),
) -> None:
    """Report current copy research status; no network and no orders."""
    settings = _settings()
    session_factory = _session_factory(settings)
    with session_factory() as session:
        top_wallets = session.query(TopWallet).order_by(TopWallet.score.desc()).limit(50).all()
        decisions = session.query(FollowDecision).order_by(FollowDecision.computed_at_ms.desc()).limit(500).all()
        paper_orders = session.query(PaperFollowOrder).order_by(PaperFollowOrder.created_at_ms.desc()).limit(500).all()
    typer.echo(
        format_copy_status_report(
            period=period,
            top_wallets=top_wallets,
            decisions=decisions,
            paper_orders=paper_orders,
        )
    )


@app.command("detect-signals")
def detect_signals() -> None:
    """Placeholder for position-delta signal detection."""
    _settings()
    typer.echo("detect-signals ready: position delta detector and signal scoring are available")


@app.command("paper-run")
def paper_run() -> None:
    """Run a minimal safe paper-trading smoke path."""
    settings = _settings()
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
    context = RiskContext(
        spread_bps=2,
        estimated_slippage_bps=3,
        orderbook_depth_usdc=10000,
        wallet_score=90,
        signal_score=90,
        edge_remaining_bps=edge.edge_remaining_bps,
        signal_age_ms=100,
    )
    decision = RiskEngine(settings).evaluate(context)
    PaperExecutor().orders
    typer.echo(f"paper-run smoke decision={decision.decision.value} allowed={decision.allowed}")


@app.command("paper-report")
def paper_report() -> None:
    """Report placeholder for paper trading results."""
    _settings()
    typer.echo("paper-report ready: no paper results recorded yet")


@app.command("testnet-check")
def testnet_check(
    confirm_testnet_only: bool = typer.Option(False, "--confirm-testnet-only"),
) -> None:
    """Check locked testnet execution gates without placing any order."""
    settings = _settings()
    risk = RiskDecision(
        allowed=True,
        decision=SignalDecision.TESTNET_CANDIDATE,
        reasons=["check only"],
        gates={"manual_check": True},
    )
    order = build_testnet_order_intent(
        cloid="check-only-cloid",
        coin="BTC",
        side="buy",
        size=0.001,
        limit_price=1.0,
        schedule_cancel_configured=True,
    )
    try:
        result = LockedTestnetExecutor(settings).submit(
            order,
            risk,
            confirm_testnet_only=confirm_testnet_only,
        )
    except TestnetLocked as exc:
        typer.echo(f"testnet locked: {', '.join(exc.reasons)}")
        return
    if settings.environment != ExecutionEnvironment.TESTNET:
        typer.echo("testnet not active")
        return
    typer.echo(f"testnet gates validated: {result['cloid']}")


@app.command("reset-simulation-state")
def reset_simulation_state_command(
    starting_equity: float = typer.Option(1000.0, "--starting-equity", help="Fresh local simulated USDT balance for the next UI session."),
) -> None:
    """Reset the local UI simulation session; no orders, no network, no testnet."""
    settings = _settings()
    state = reset_simulation_state(settings, starting_equity_usdt=starting_equity)
    typer.echo("simulation state reset")
    typer.echo(f"starting_equity_usdt={state.simulation_starting_equity_usdt:.2f}")
    typer.echo(f"simulation_started_at_ms={state.simulation_started_at_ms}")
    typer.echo(f"state_path={simulation_state_path(settings)}")
    typer.echo("paper_local_only=true")
    typer.echo("orders_created=0")


@app.command("ui")
def ui(
    host: str = typer.Option("127.0.0.1", "--host", help="Local bind host."),
    port: int = typer.Option(8765, "--port", help="Local dashboard port."),
    reload: bool = typer.Option(False, "--reload/--no-reload", help="Reload server on code changes."),
) -> None:
    """Launch the local command center dashboard."""
    if host == "0.0.0.0":
        typer.echo("Refusing to expose the dashboard on 0.0.0.0 in the MVP")
        raise typer.Exit(1)
    settings = _settings()
    typer.echo(f"Command Center UI: http://{host}:{port}")
    import uvicorn

    uvicorn.run(create_ui_app(settings), host=host, port=port, reload=reload, log_level=settings.log_level.lower())


if __name__ == "__main__":
    app()
