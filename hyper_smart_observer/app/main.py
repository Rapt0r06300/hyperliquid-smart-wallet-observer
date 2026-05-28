from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from hyper_smart_observer import __version__
from hyper_smart_observer.audit.archive_audit import write_archive_audit_report
from hyper_smart_observer.audit.safety_audit import run_safety_audit, write_audit_report
from hyper_smart_observer.backtesting.backtest_report import write_backtest_report
from hyper_smart_observer.backtesting.multi_wallet_simulator import (
    simulate_multi_wallet_following,
    write_multi_wallet_simulation_report,
)
from hyper_smart_observer.backtesting.replay_engine import ReplayEngine
from hyper_smart_observer.copy_mode.candidate_importer import load_leader_candidates_from_file, write_candidate_template
from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run, shortlist_path
from hyper_smart_observer.copy_mode.leaderboard_selector import (
    LeaderboardSelectionConfig,
    load_shortlist_entries,
    select_leaderboard_shortlist,
    write_shortlist_report,
)
from hyper_smart_observer.copy_mode.preflight import format_copy_preflight_report, run_copy_preflight, write_copy_preflight_report
from hyper_smart_observer.copy_mode.reports import format_copy_period_report, format_copy_run_report, write_copy_run_report
from hyper_smart_observer.copy_mode.repository import insert_shortlist_entries, list_latest_signal_candidates, list_no_trade_decisions
from hyper_smart_observer.dashboard.exporter import export_dashboard
from hyper_smart_observer.app.config import AppConfig, load_config
from hyper_smart_observer.app.logging_config import configure_logging
from hyper_smart_observer.app.safety import SafetyViolation, validate_runtime_config
from hyper_smart_observer.paper_trading.reporting import format_paper_report
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from hyper_smart_observer.patterns.pattern_detector import PatternDetector
from hyper_smart_observer.position_lifecycle.lifecycle_builder import build_lifecycles
from hyper_smart_observer.position_lifecycle.position_reconstructor import action_from_fill_row
from hyper_smart_observer.realtime_monitor.stream_models import StreamType
from hyper_smart_observer.realtime_monitor.subscriptions import Subscription
from hyper_smart_observer.realtime_monitor.websocket_manager import WebSocketManager
from hyper_smart_observer.runtime.archive import archive_readiness, create_clean_archive, default_desktop_output_dir
from hyper_smart_observer.runtime.runtime_check import format_runtime_report, scan_runtime_files
from hyper_smart_observer.scoring.ranking_report import format_ranking_report
from hyper_smart_observer.scoring.smart_wallet_ranking import SmartWalletRankingEngine
from hyper_smart_observer.scoring.wallet_score import WalletScoreEngine
from hyper_smart_observer.hyperliquid_client.models import Wallet
from hyper_smart_observer.hyperliquid_client.validation import normalize_wallet_address
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.repositories import fills_repo, paper_trades_repo, scores_repo, wallet_repo
from hyper_smart_observer.wallet_discovery.discovery_engine import WalletDiscoveryEngine
from hyper_smart_observer.wallet_discovery.collector import HyperliquidReadOnlyCollector
from hyper_smart_observer.wallet_discovery.wallet_importer import import_wallets_from_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="HyperSmart Observer")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["copy-preflight", "copy-run", "copy-report", "promote-testnet-candidates"],
        help="Optional product command. All copy commands are dry-run/research only.",
    )
    parser.add_argument("--status", action="store_true", help="Show safe runtime status.")
    parser.add_argument("--health-summary", action="store_true", help="Show French health summary.")
    parser.add_argument("--init-db", action="store_true", help="Initialize local SQLite database.")
    parser.add_argument("--safety-check", action="store_true", help="Run safety validation.")
    parser.add_argument("--mode", default=None, help="Override runtime mode for this invocation.")
    parser.add_argument(
        "--confirm-testnet-only",
        action="store_true",
        help="Explicit future testnet-only confirmation; never enables mainnet.",
    )
    parser.add_argument("--collect-wallet", action="append", default=[], help="Collect one full wallet address.")
    parser.add_argument("--collect-wallets-file", default=None, help="Text file with one wallet address per line.")
    parser.add_argument("--start-time-ms", type=int, default=None, help="Start time in milliseconds.")
    parser.add_argument("--end-time-ms", type=int, default=None, help="End time in milliseconds.")
    parser.add_argument("--max-pages", type=int, default=None, help="Bounded max pages per wallet.")
    parser.add_argument(
        "--network-read",
        action="store_true",
        help="Explicitly allow read-only Hyperliquid info network calls for this run.",
    )
    parser.add_argument("--score-wallet", action="append", default=[], help="Score one local wallet.")
    parser.add_argument("--score-all-wallets", action="store_true", help="Score local wallets from SQLite.")
    parser.add_argument("--score-limit", type=int, default=None, help="Limit wallets/scores listed or scored.")
    parser.add_argument("--list-wallet-scores", action="store_true", help="List latest stored wallet scores.")
    parser.add_argument("--list-rejected-scores", action="store_true", help="List stored insufficient/rejected scores.")
    parser.add_argument("--paper-open", action="store_true", help="Open a local paper simulation.")
    parser.add_argument("--paper-close", action="store_true", help="Close a local paper simulation.")
    parser.add_argument("--paper-report", action="store_true", help="Show local paper report.")
    parser.add_argument("--paper-list-open", action="store_true", help="List open local paper simulations.")
    parser.add_argument("--paper-list-closed", action="store_true", help="List closed local paper simulations.")
    parser.add_argument("--runtime-check", action="store_true", help="Report runtime DB/log/archive hygiene.")
    parser.add_argument("--runtime-clean-report", action="store_true", help="Explain runtime files excluded from archives.")
    parser.add_argument("--archive-readiness", action="store_true", help="Check clean source archive readiness.")
    parser.add_argument("--archive-audit", action="store_true", help="Write the archive hygiene audit report.")
    parser.add_argument("--create-clean-archive", action="store_true", help="Create a clean source ZIP on Desktop.")
    parser.add_argument(
        "--archive-output-desktop",
        action="store_true",
        help="Force clean archive output to the current user's Desktop.",
    )
    parser.add_argument("--archive-output-dir", default=None, help="Optional clean archive output directory outside the project.")
    parser.add_argument("--dashboard-export", action="store_true", help="Export the read-only HTML dashboard.")
    parser.add_argument("--audit-safety", action="store_true", help="Run HyperSmart automated safety audit.")
    parser.add_argument("--discover-wallets", action="store_true", help="Discover wallets from local/imported sources only.")
    parser.add_argument("--import-wallets-file", default=None, help="Import wallet candidates from a local text file.")
    parser.add_argument("--build-shortlist-file", default=None, help="Build copy-mode leaderboard shortlist from local CSV/JSON/TXT candidates.")
    parser.add_argument("--write-shortlist-template", default=None, help="Write a local CSV template for leaderboard candidates.")
    parser.add_argument("--shortlist-target-count", type=int, default=None, help="Target count for local shortlist selection.")
    parser.add_argument("--copy-max-leaders", type=int, default=None, help="Maximum shortlisted leaders observed in one copy-run.")
    parser.add_argument("--shortlist-output", default=None, help="Optional shortlist JSON output path.")
    parser.add_argument("--enrich-wallet", action="append", default=[], help="Enrich one wallet from local data.")
    parser.add_argument("--rank-wallets", action="store_true", help="Build research-only smart wallet rankings from stored scores.")
    parser.add_argument("--list-top-wallets", action="store_true", help="List stored research wallet scores.")
    parser.add_argument("--detect-patterns", action="store_true", help="Detect research-only local patterns from stored fills.")
    parser.add_argument("--build-position-lifecycle", action="append", default=[], help="Build local position lifecycle for a wallet.")
    parser.add_argument("--backtest-wallet", action="append", default=[], help="Replay a wallet locally from stored closed PnL.")
    parser.add_argument("--backtest-top-wallets", action="store_true", help="Replay locally the highest stored research wallets.")
    parser.add_argument("--simulate-copy-wallet", action="append", default=[], help="Run local multi-wallet follow simulation for one wallet.")
    parser.add_argument("--simulate-copy-wallets-file", default=None, help="File with full wallet addresses for local follow simulation.")
    parser.add_argument("--simulation-max-wallets", type=int, default=5, help="Maximum wallets in one local simulation.")
    parser.add_argument("--simulation-notional", type=float, default=50.0, help="Reference notional per copied historical fill.")
    parser.add_argument("--simulation-delay-seconds", type=float, default=300.0, help="Assumed copy delay for local replay.")
    parser.add_argument("--monitor-live", action="store_true", help="Prepare a read-only WebSocket monitor plan.")
    parser.add_argument("--monitor-dry-run", action="store_true", help="Do not connect; only show read-only monitor plan.")
    parser.add_argument("--dry-run", action="store_true", help="Force a local dry-run; required for future unsafe-looking actions.")
    parser.add_argument("--interval", type=int, default=None, help="Copy loop polling interval in seconds.")
    parser.add_argument("--period", default="7d", help="Report period label for copy-report.")
    parser.add_argument("--ws", action="store_true", help="Plan read-only WebSocket shortlist observation.")
    parser.add_argument("--duration-seconds", type=int, default=None, help="Bounded duration for read-only WS copy-run.")
    parser.add_argument("--watchlist-only", action="store_true", help="Restrict copy-run to shortlist/watchlist sources.")
    parser.add_argument("--monitor-duration-seconds", type=int, default=None, help="Bounded monitor duration.")
    parser.add_argument("--monitor-coins", default="", help="Comma-separated coins for read-only public streams.")
    parser.add_argument("--monitor-watchlist-only", action="store_true", help="Use watchlist-only monitor planning.")
    parser.add_argument("--wallet", default=None, help="Wallet address for local paper simulation.")
    parser.add_argument("--coin", default=None, help="Coin for local paper simulation.")
    parser.add_argument("--side", default=None, help="BUY or SELL for local paper simulation.")
    parser.add_argument("--reference-price", type=float, default=None, help="Reference price for local paper simulation.")
    parser.add_argument("--notional", type=float, default=None, help="Requested local paper notional.")
    parser.add_argument("--trade-id", default=None, help="Local paper trade id.")
    parser.add_argument("--exit-reference-price", type=float, default=None, help="Exit reference price.")
    parser.add_argument("--close-reason", default="manual local paper close", help="Local paper close reason.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    if args.mode:
        config = replace(config, mode=args.mode.upper())
    if args.confirm_testnet_only:
        config = replace(config, confirm_testnet_only=True)
    if args.network_read:
        config = replace(config, enable_network_reads=True)
    configure_logging(config)
    try:
        validate_runtime_config(config)
    except SafetyViolation as exc:
        print(f"Safety refused: {exc.reason_code} - {exc}")
        return 2

    if args.command == "copy-run":
        interval = args.interval or config.copy_poll_interval_seconds
        if args.ws and not args.dry_run and not args.duration_seconds:
            print("Safety refused: RATE_LIMIT_GUARD - read-only WS copy-run requires --dry-run or --duration-seconds.")
            return 2
        report = run_copy_dry_run(
            config,
            interval_seconds=interval,
            network_read=args.network_read,
            ws=args.ws,
            duration_seconds=args.duration_seconds,
            max_leaders=args.copy_max_leaders,
        )
        report_path = write_copy_run_report(report, config.reports_dir)
        print(format_copy_run_report(report))
        print(f"copy_run_report: {report_path}")
        print(f"no_trade_report: {config.reports_dir / 'no_trade_report.md'}")
        print(f"leaderboard_shortlist: {shortlist_path(config)}")
        return 0

    if args.command == "copy-preflight":
        report = run_copy_preflight(
            config,
            network_read=args.network_read,
            max_leaders=args.copy_max_leaders,
        )
        json_path, md_path = write_copy_preflight_report(report, config.reports_dir)
        print(format_copy_preflight_report(report))
        print(f"copy_preflight_json: {json_path}")
        print(f"copy_preflight_md: {md_path}")
        return 0

    if args.command == "copy-report":
        initialize_database(config)
        with get_connection(config) as conn:
            signal_count = len(list_latest_signal_candidates(conn, limit=10_000))
            no_trade_count = len(list_no_trade_decisions(conn, limit=10_000))
        print(format_copy_period_report(args.period, no_trade_count=no_trade_count, signal_count=signal_count))
        return 0

    if args.command == "promote-testnet-candidates":
        print("Promote testnet candidates: LOCKED")
        print("Dry-run only. Testnet executor is not implemented in this batch.")
        print("Required future guard: --confirm-testnet-only plus explicit sprint approval.")
        print("Promoted candidates: 0")
        return 0

    if args.init_db:
        initialize_database(config)
        print(f"Database initialized: {config.database_path}")

    if args.safety_check:
        print("Safety check: OK")

    if args.runtime_check or args.runtime_clean_report:
        report = scan_runtime_files(config)
        print(format_runtime_report(report))
        if args.runtime_clean_report:
            print("Clean archive policy")
            print("logs/, data/, SQLite DB/WAL/SHM, archives, caches and secrets are excluded.")
            print("No runtime file is deleted by this report.")

    if args.archive_readiness:
        readiness = archive_readiness(Path(config.runtime_root))
        print("Clean archive readiness")
        print(json.dumps(readiness, indent=2, sort_keys=True))

    if args.archive_audit:
        archive_audit_path = write_archive_audit_report(Path(config.runtime_root).resolve())
        print("Archive audit report")
        print(str(archive_audit_path))

    if args.create_clean_archive:
        output_dir = default_desktop_output_dir() if args.archive_output_desktop or not args.archive_output_dir else Path(args.archive_output_dir)
        result = create_clean_archive(Path(config.runtime_root), output_dir)
        archive_audit_path = write_archive_audit_report(Path(config.runtime_root).resolve())
        print("Clean archive created")
        print(f"archive_path: {result.archive_path}")
        print(f"files_copied: {result.files_copied}")
        print(f"zip_entries: {result.entries}")
        print(f"archive_audit: {archive_audit_path}")

    if args.dashboard_export:
        dashboard_path = export_dashboard(config)
        print("Read-only dashboard exported")
        print(str(dashboard_path))

    if args.audit_safety:
        findings = run_safety_audit(config)
        audit_path = write_audit_report(config)
        print("HyperSmart safety audit")
        print(f"report: {audit_path}")
        for finding in findings:
            status = "OK" if finding.ok else "FAIL"
            print(f"{status} | {finding.name} | {finding.message}")

    if args.collect_wallet or args.collect_wallets_file:
        if not args.start_time_ms:
            print("Safety refused: CONFIGURATION_REFUSED - --start-time-ms is required for collection.")
            return 2
        wallet_addresses = list(args.collect_wallet)
        if args.collect_wallets_file:
            wallet_addresses.extend(
                wallet.address for wallet in import_wallets_from_text(Path(args.collect_wallets_file))
            )
        try:
            report = HyperliquidReadOnlyCollector(config).collect_wallets(
                wallet_addresses,
                start_time_ms=args.start_time_ms,
                end_time_ms=args.end_time_ms or args.start_time_ms,
                max_pages=args.max_pages,
                network_read=args.network_read,
            )
        except SafetyViolation as exc:
            print(f"Safety refused: {exc.reason_code} - {exc}")
            return 2
        except ValueError as exc:
            print(f"Collection refused: {exc}")
            return 2
        print("Read-only collection report")
        print(f"wallets requested: {report.wallets_requested}")
        print(f"wallets collected: {report.wallets_collected}")
        print(f"fills inserted: {report.fills_inserted}")
        print(f"position snapshots inserted: {report.position_snapshots_inserted}")
        print(f"errors: {len(report.errors)}")

    if args.build_shortlist_file:
        initialize_database(config)
        candidates = load_leader_candidates_from_file(Path(args.build_shortlist_file))
        report = select_leaderboard_shortlist(
            candidates,
            config=LeaderboardSelectionConfig(
                target_count=args.shortlist_target_count or config.copy_leaderboard_target_count,
                min_history_days=config.copy_min_history_days,
                min_closed_pnl_points=config.copy_min_closed_pnl_points,
            ),
        )
        output = Path(args.shortlist_output) if args.shortlist_output else shortlist_path(config)
        write_shortlist_report(report, output)
        with get_connection(config) as conn:
            insert_shortlist_entries(conn, report.entries)
            conn.commit()
        print("Leaderboard shortlist built")
        print("research only; no network call; no order")
        print(f"input_candidates: {len(candidates)}")
        print(f"shortlisted: {len(report.shortlisted)}")
        print(f"rejected: {len(report.rejected)}")
        print(f"output: {output}")

    if args.write_shortlist_template:
        output = write_candidate_template(Path(args.write_shortlist_template))
        print("Leaderboard candidate template written")
        print("research only; edit with real full wallet addresses and measured metrics")
        print(f"output: {output}")

    if args.score_wallet or args.score_all_wallets:
        initialize_database(config)
        engine = WalletScoreEngine(config)
        scores = []
        for wallet_address in args.score_wallet:
            scores.append(engine.score_and_store_wallet(wallet_address))
        if args.score_all_wallets:
            scores.extend(engine.score_and_store_all(limit=args.score_limit))
        print("Wallet scoring report")
        print("research only, not a trading signal")
        for score in scores:
            _print_score(score)

    if args.list_wallet_scores or args.list_rejected_scores:
        initialize_database(config)
        limit = args.score_limit or 50
        with get_connection(config) as conn:
            rows = (
                scores_repo.list_rejected_scores(conn, limit=limit)
                if args.list_rejected_scores
                else scores_repo.list_latest_scores(conn, limit=limit)
            )
        print("Stored wallet scores")
        print("research only, not a trading signal")
        if not rows:
            print("No stored wallet scores.")
        for row in rows:
            print(
                f"{row['wallet_address']} | status={row['status'] or 'UNKNOWN'} | "
                f"fills={row['total_trades']} | confidence={row['confidence_score']} | "
                f"final={row['final_score']} | reason={row['refusal_reason']}"
            )

    if args.discover_wallets or args.import_wallets_file or args.enrich_wallet:
        initialize_database(config)
        imported_wallets = []
        if args.import_wallets_file:
            imported_wallets = import_wallets_from_text(Path(args.import_wallets_file))
            with get_connection(config) as conn:
                for wallet in imported_wallets:
                    wallet_repo.insert_wallet(conn, wallet)
                conn.commit()
        enriched_wallets = []
        discovered = WalletDiscoveryEngine().from_wallets(
            [wallet.address for wallet in imported_wallets],
            source="local_import",
        )
        for wallet_address in args.enrich_wallet:
            try:
                enriched_wallets.append(
                    Wallet(address=normalize_wallet_address(wallet_address), source="cli_enrich")
                )
            except ValueError:
                print(f"Wallet refused: invalid full address {wallet_address}")
        discovered.extend(
            WalletDiscoveryEngine().from_wallets(
                [wallet.address for wallet in enriched_wallets],
                source="cli_enrich",
            )
        )
        print("Wallet discovery report")
        print("research only, local/import sources only")
        print(f"candidates: {len(discovered)}")
        if not discovered:
            print("No local wallet candidates. Import a local wallet file to seed discovery.")
        for candidate in discovered[:50]:
            print(
                f"{candidate.wallet_address} | source={candidate.source} | "
                f"status={candidate.status.value} | score={candidate.candidate_score:.2f}"
            )

    if args.rank_wallets or args.list_top_wallets:
        initialize_database(config)
        engine = SmartWalletRankingEngine(config)
        rankings = engine.rank_from_latest_scores(limit=args.score_limit or 50)
        print(format_ranking_report(rankings))

    if args.detect_patterns:
        initialize_database(config)
        with get_connection(config) as conn:
            wallets = wallet_repo.list_wallets(conn, limit=args.score_limit or 50)
            results = []
            for wallet in wallets:
                rows = fills_repo.list_all_fills_for_wallet(conn, wallet["address"])
                pnl_values = [float(row["closed_pnl"]) for row in rows if row["closed_pnl"] is not None]
                results.extend(PatternDetector().detect_from_pnls(wallet["address"], pnl_values))
        print("Pattern detector report")
        print("research only, no trading signal")
        if not results:
            print("No local patterns; not enough stored fills.")
        for result in results[:50]:
            print(
                f"{result.wallet} | {result.pattern_type} | confidence={result.confidence:.2f} | "
                f"evidence={result.evidence_count} | {result.research_only_message}"
            )

    if args.build_position_lifecycle:
        initialize_database(config)
        with get_connection(config) as conn:
            for wallet_address in args.build_position_lifecycle:
                rows = fills_repo.list_all_fills_for_wallet(conn, wallet_address)
                actions = [action_from_fill_row(row) for row in rows]
                lifecycles = build_lifecycles(actions)
                print(f"Position lifecycle for {wallet_address}")
                print("research only; ambiguous actions stay UNKNOWN")
                print(f"fills={len(rows)} actions={len(actions)} lifecycles={len(lifecycles)}")
                for lifecycle in lifecycles[:20]:
                    print(
                        f"{lifecycle.wallet_address} {lifecycle.coin} | actions={len(lifecycle.actions)} | "
                        f"realized_closed_pnl={lifecycle.realized_closed_pnl}"
                    )

    if args.backtest_wallet or args.backtest_top_wallets:
        initialize_database(config)
        wallets_to_backtest = list(args.backtest_wallet)
        with get_connection(config) as conn:
            if args.backtest_top_wallets:
                rows = scores_repo.list_latest_scores(conn, limit=args.score_limit or 10, status="SCORED")
                wallets_to_backtest.extend(row["wallet_address"] for row in rows)
            for wallet_address in wallets_to_backtest:
                fills = fills_repo.list_all_fills_for_wallet(conn, wallet_address)
                pnl_values = [float(row["closed_pnl"]) for row in fills if row["closed_pnl"] is not None]
                report = ReplayEngine().replay_closed_pnl(wallet_address, pnl_values)
                report_path = write_backtest_report(report, config.reports_dir)
                print(f"Backtest replay for {wallet_address}")
                print(report.disclaimer)
                print(
                    f"simulated_trades={report.simulated_trades} skipped={report.skipped_actions} "
                    f"net_pnl={report.net_pnl} max_drawdown={report.max_drawdown}"
                )
                print(f"backtest_report: {report_path}")

    if args.simulate_copy_wallet or args.simulate_copy_wallets_file:
        initialize_database(config)
        wallets_to_simulate = list(args.simulate_copy_wallet)
        if args.simulate_copy_wallets_file:
            wallets_to_simulate.extend(
                wallet.address for wallet in import_wallets_from_text(Path(args.simulate_copy_wallets_file))
            )
        normalized_wallets = []
        for wallet_address in wallets_to_simulate:
            try:
                normalized_wallets.append(normalize_wallet_address(wallet_address))
            except ValueError:
                print(f"Simulation wallet refused: invalid full address {wallet_address}")
        unique_wallets = list(dict.fromkeys(normalized_wallets))[: max(1, args.simulation_max_wallets)]
        if len(normalized_wallets) > len(unique_wallets):
            print(f"Simulation limited to {len(unique_wallets)} wallet(s).")
        with get_connection(config) as conn:
            wallet_rows = {
                wallet_address: fills_repo.list_all_fills_for_wallet(conn, wallet_address)
                for wallet_address in unique_wallets
            }
        report = simulate_multi_wallet_following(
            wallet_rows,
            notional_per_trade=args.simulation_notional,
            fee_bps=config.paper_fee_rate_bps,
            spread_bps=config.paper_spread_bps,
            slippage_bps=config.paper_slippage_bps,
            delay_seconds=args.simulation_delay_seconds,
        )
        json_path, md_path = write_multi_wallet_simulation_report(report, config.reports_dir)
        print("HyperSmart multi-wallet follow simulation")
        print("scope: local historical replay only; no order, no mainnet, no execution")
        print(f"wallets requested: {report.requested_wallets}")
        print(f"wallets simulated: {report.simulated_wallets}")
        print(f"usable trades: {report.total_usable_trades}")
        print(f"gross pnl: {report.gross_pnl:.4f}")
        print(f"costs: {report.total_costs:.4f}")
        print(f"net pnl: {report.net_pnl:.4f}")
        print(f"max drawdown: {report.max_drawdown:.4f}")
        print(f"simulation_json: {json_path}")
        print(f"simulation_md: {md_path}")

    if args.monitor_live or args.monitor_dry_run:
        coins = [coin.strip().upper() for coin in args.monitor_coins.split(",") if coin.strip()]
        subscriptions = [Subscription(StreamType.TRADES, coin=coin) for coin in coins]
        if not subscriptions:
            subscriptions = [Subscription(StreamType.ALL_MIDS)]
        plan = WebSocketManager(config).build_plan(
            subscriptions,
            dry_run=args.monitor_dry_run,
            duration_seconds=args.monitor_duration_seconds,
        )
        print("Read-only WebSocket monitor plan")
        print(f"dry_run={plan.dry_run} duration_seconds={plan.duration_seconds}")
        print(f"subscriptions={len(plan.subscriptions)} warnings={len(plan.warnings)}")
        for warning in plan.warnings:
            print(f"warning: {warning}")

    if args.paper_open:
        missing = [
            name
            for name, value in {
                "--wallet": args.wallet,
                "--coin": args.coin,
                "--side": args.side,
                "--reference-price": args.reference_price,
                "--notional": args.notional,
            }.items()
            if value is None
        ]
        if missing:
            print(f"Paper refused: CONFIGURATION_REFUSED - missing {', '.join(missing)}")
            return 2
        simulator = PaperTradingSimulator(config)
        intent = simulator.create_intent_from_wallet_score(
            args.wallet,
            args.coin,
            args.side,
            args.reference_price,
            args.notional,
        )
        result = simulator.open_paper_trade(intent)
        print("LOCAL PAPER SIMULATION ONLY")
        print(result.message)
        print(f"intent_status: {result.intent.status.value}")
        print(f"reason: {result.intent.refusal_reason or result.decision.reason_code}")
        if result.trade:
            print(f"paper_trade_id: {result.trade.trade_id}")
            print(f"entry_price: {result.trade.entry_price}")
            print(f"fee_entry: {result.trade.fee_entry}")
            print(f"spread_cost: {result.trade.spread_cost}")
            print(f"slippage_entry: {result.trade.slippage_entry}")

    if args.paper_close:
        if not args.trade_id or args.exit_reference_price is None:
            print("Paper refused: CONFIGURATION_REFUSED - --trade-id and --exit-reference-price are required")
            return 2
        result = PaperTradingSimulator(config).close_paper_trade(
            args.trade_id,
            args.exit_reference_price,
            args.close_reason,
        )
        print("LOCAL PAPER SIMULATION ONLY")
        print(result.message)
        print(f"trade_id: {result.trade_id}")
        print(f"net_pnl: {result.net_pnl}")

    if args.paper_report:
        print(format_paper_report(PaperTradingSimulator(config).generate_report()))

    if args.paper_list_open or args.paper_list_closed:
        initialize_database(config)
        with get_connection(config) as conn:
            rows = (
                paper_trades_repo.list_open_paper_trades(conn)
                if args.paper_list_open
                else paper_trades_repo.list_closed_paper_trades(conn, limit=args.score_limit or 50)
            )
        print("LOCAL PAPER SIMULATION ONLY")
        if not rows:
            print("No local paper simulations.")
        for row in rows:
            print(
                f"{row['trade_id']} | {row['coin']} | {row['side']} | "
                f"status={row['status'] or row['state']} | entry={row['entry_price']} | "
                f"exit={row['exit_price']} | net_pnl={row['net_pnl'] or row['pnl']}"
            )

    if args.health_summary:
        initialize_database(config)
        from hyper_smart_observer.reports.french_formatter import format_french_summary
        with get_connection(config) as conn:
            stats = {
                "ok": True,
                "leaders_count": len(load_shortlist_entries(shortlist_path(config))),
                "signals_count": len(list_latest_signal_candidates(conn, limit=1000)),
                "refusals_count": len(list_no_trade_decisions(conn, limit=1000)),
                "pnl": PaperTradingSimulator(config).generate_report()["realized_pnl"]
            }
        print(format_french_summary(stats))
        return 0

    if args.status or not (
        args.init_db
        or args.safety_check
        or args.collect_wallet
        or args.collect_wallets_file
        or args.score_wallet
        or args.score_all_wallets
        or args.list_wallet_scores
        or args.list_rejected_scores
        or args.paper_open
        or args.paper_close
        or args.paper_report
        or args.paper_list_open
        or args.paper_list_closed
        or args.runtime_check
        or args.runtime_clean_report
        or args.archive_readiness
        or args.archive_audit
        or args.create_clean_archive
        or args.dashboard_export
        or args.audit_safety
        or args.discover_wallets
        or args.import_wallets_file
        or args.build_shortlist_file
        or args.write_shortlist_template
        or args.enrich_wallet
        or args.rank_wallets
        or args.list_top_wallets
        or args.detect_patterns
        or args.build_position_lifecycle
        or args.backtest_wallet
        or args.backtest_top_wallets
        or args.simulate_copy_wallet
        or args.simulate_copy_wallets_file
        or args.monitor_live
        or args.monitor_dry_run
    ):
        print("HyperSmart Observer - research/paper/testnet only")
        print(f"Version: {__version__}")
        print("NO REAL LOSS PROTOCOL active")
        print("Mainnet: forbidden")
        print("Execution: disabled by default")
        print(f"Mode: {config.mode}")
        print(f"Database: {config.database_path}")
    return 0


def _print_score(score) -> None:
    print(
        f"{score.wallet_address} | status={score.status.value} | total_fills={score.total_fills} | "
        f"usable={score.usable_fills} | confidence={score.confidence_score:.2f} | "
        f"final={score.final_score if score.final_score is not None else 'N/A'} | "
        f"reason={score.refusal_reason or 'research_observation'}"
    )


if __name__ == "__main__":
    sys.exit(main())
