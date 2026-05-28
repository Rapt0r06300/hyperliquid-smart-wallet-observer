from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer

from hl_observer.autoscan import format_autoscan_report, run_autoscan
from hl_observer.collection.collector import (
    InvalidWalletAddress,
    build_default_collection_plan,
    run_collection_once,
    validate_wallet_address,
)
from hl_observer.config.loader import load_settings
from hl_observer.config.settings import ExecutionEnvironment, Settings
from hl_observer.copying.leaderboard_autoselect import (
    CopyLeaderAutoSelectConfig,
    select_copy_leaders,
)
from hl_observer.copying.reports import (
    format_copy_run_report,
    format_copy_status_report,
)
from hl_observer.copying.signal_detector import CopySourceMode, detect_copy_signals_from_deltas
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
from hl_observer.markets.scanner import (
    MarketDiscoveryPlan,
    MarketScanPlan,
    format_market_discovery_report,
    format_market_scan_report,
    run_discover_markets,
    run_scan_markets,
)
from hl_observer.paper.paper_executor import PaperExecutor
from hl_observer.risk.gates import RiskContext
from hl_observer.risk.risk_engine import RiskEngine
from hl_observer.runtime.hygiene import format_runtime_hygiene_report, scan_runtime_hygiene
from hl_observer.security.mainnet_guard import assert_mainnet_execution_disabled
from hl_observer.security.safety_audit import run_safety_audit
from hl_observer.storage.database import init_db as initialize_database
from hl_observer.storage.database import create_session_factory, create_sqlite_engine
from hl_observer.storage.models import (
    FollowDecision,
    FollowSignal,
    LeaderboardAddressValidation,
    LeaderboardWalletCandidate,
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
    max_deltas: int = typer.Option(100, "--max-deltas", help="Recent position deltas to inspect."),
    network_read: bool = typer.Option(False, "--network-read", help="Explicitly allow bounded read-only /info collection before detection."),
    backfill_days: int = typer.Option(1, "--backfill-days", help="Bounded recent history window for --network-read."),
    fresh_window_minutes: int = typer.Option(15, "--fresh-window-minutes", help="Fresh read window for live simulation; set 0 to use --backfill-days."),
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
    with session_factory() as session:
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
        if not followed:
            followed = (
                session.query(TopWallet)
                .filter(TopWallet.status == "selected")
                .order_by(TopWallet.score.desc())
                .offset(leader_offset)
                .limit(leaders)
                .all()
            )
        followed = followed[:leaders]
        followed_addresses = {wallet.wallet_address.lower() for wallet in followed}

    backfill_result = None
    backfill_plan = None
    if network_read:
        if not followed:
            typer.echo("copy-run network-read refused: no shortlisted leaders available; import or discover full wallet addresses first.")
            raise typer.Exit(1)
        end_ms = now_ms()
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
        backfill_result = asyncio.run(run_wallet_backfill(backfill_plan, settings))

    with session_factory() as session:
        followed_addresses = {wallet.wallet_address.lower() for wallet in followed}
        delta_query = session.query(PositionDeltaModel).order_by(PositionDeltaModel.detected_at_ms.desc())
        if followed_addresses:
            delta_query = delta_query.filter(PositionDeltaModel.wallet_address.in_(followed_addresses))
        deltas = delta_query.limit(max_deltas).all()

        # Load recent market metrics for accurate edge calculation
        metric_rows = session.query(MarketMetric).order_by(MarketMetric.computed_at_ms.desc()).limit(100).all()
        market_metrics = {m.coin.upper(): m for m in metric_rows}

        mode = CopySourceMode.WEBSOCKET_DRY_RUN if source_mode.lower() in {"ws", "websocket", "ws-dry-run"} else CopySourceMode.POLLING
        signals = detect_copy_signals_from_deltas(
            deltas,
            settings=settings,
            followed_wallets=followed,
            market_metrics=market_metrics,
            interval_seconds=interval,
            source_mode=mode,
        )
    if report:
        if backfill_result is not None and backfill_plan is not None:
            typer.echo(format_wallet_backfill_report(backfill_result, backfill_plan))
            typer.echo("")
        typer.echo(format_copy_run_report(leaders=leader_report, signals=signals))
    else:
        suffix = f" network_read_fetched={backfill_result.fetched_items}" if backfill_result is not None else ""
        typer.echo(f"copy-run dry-run complete: signals={signals.signals_created} paper_candidates={signals.paper_candidates}{suffix}")


@app.command("live-public-scan")
def live_public_scan_command(
    coins: str = typer.Option("BTC,ETH,SOL,HYPE,DOGE,XRP,BNB,ENA,AVAX,LINK", "--coins"),
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
    result = asyncio.run(
        scan_public_trades_ws(
            settings,
            coins=normalize_coin_list(coins),
            duration_seconds=duration_seconds,
            max_wallets=max_wallets,
            min_notional_usdc=min_notional_usdc,
            network_read=True,
        )
    )
    if store:
        session_factory = _session_factory(settings)
        with session_factory() as session:
            store_public_trade_scan(session, result, promote_top=promote_top)
            session.commit()
    if report:
        typer.echo(format_public_trade_scan_report(result))
    else:
        typer.echo(
            "live-public-scan complete: "
            f"trades={result.trades_seen} wallets={len(result.wallet_stats)} "
            f"promoted={result.wallets_stored} stopped_reason={result.stopped_reason}"
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
            edge_leader_bps=30,
            fees_bps=4,
            spread_bps=2,
            slippage_bps=3,
            delay_cost_bps=2,
            observed_price=100.0,
        ),
        min_edge_required_bps=settings.risk.min_edge_required_bps,
    )
    context = RiskContext(
        spread_bps=2,
        slippage_bps=3,
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

    uvicorn.run(create_ui_app(settings), host=host, port=port, reload=reload, log_level="info")
