"""
CLI dYdX v4 — commandes de diagnostic et d'observation.

AUCUNE commande de trading. AUCUNE clé privée. READ-ONLY / PAPER-ONLY.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from hyper_smart_observer.dydx_v4.config import DydxV4Config, DydxNetwork, load_config_from_env
from hyper_smart_observer.dydx_v4.rest_client import DydxIndexerRestClient, RestError
from hyper_smart_observer.dydx_v4.safety import audit_config
from hyper_smart_observer.dydx_v4.storage import DydxStorage
from hyper_smart_observer.dydx_v4.dashboard_adapter import DydxDashboardAdapter

DISCLAIMER = (
    "dYdX v4 CLI — READ-ONLY / PAPER-ONLY / TESTNET-FIRST. "
    "Aucun ordre réel. Aucun argent réel. Aucune clé privée."
)


def cmd_runtime_check(args: argparse.Namespace) -> int:
    """Vérifier l'environnement runtime."""
    print(DISCLAIMER)
    print("\n--- Runtime Check ---")
    errors = []

    try:
        import requests
        print("  [OK] requests disponible")
    except ImportError:
        errors.append("requests manquant — pip install requests")
        print("  [WARN] requests manquant")

    try:
        import websocket
        print("  [OK] websocket-client disponible")
    except ImportError:
        print("  [WARN] websocket-client manquant (WS désactivé)")

    try:
        import sqlite3
        print(f"  [OK] sqlite3 disponible (version {sqlite3.sqlite_version})")
    except ImportError:
        errors.append("sqlite3 manquant")

    config = load_config_from_env()
    print(f"\n  Network: {config.network.value}")
    print(f"  Paper-only: {config.paper_only}")
    print(f"  Read-only: {config.read_only}")
    print(f"  Allow-trading: {config.allow_trading} (DOIT être False)")
    print(f"  Allow-private-key: {config.allow_private_key} (DOIT être False)")

    if errors:
        print(f"\n[ERRORS] {len(errors)} problème(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("\n[OK] Runtime prêt")
    return 0


def cmd_safety_check(args: argparse.Namespace) -> int:
    """Audit de sécurité de la configuration."""
    print(DISCLAIMER)
    print("\n--- Safety Audit ---")
    config = load_config_from_env()
    issues = audit_config(config)
    if not issues:
        print("[OK] Configuration sûre — 0 problème de sécurité détecté")
        return 0
    print(f"[WARN] {len(issues)} problème(s) détecté(s):")
    for issue in issues:
        print(f"  {issue}")
    return 1 if any("CRITICAL" in i for i in issues) else 0


def cmd_endpoints(args: argparse.Namespace) -> int:
    """Afficher les endpoints disponibles."""
    print(DISCLAIMER)
    config = load_config_from_env()
    print(f"\nNetwork: {config.network.value}")
    print(f"REST URL: {config.indexer_rest_url}")
    print(f"WS URL:   {config.indexer_ws_url}")
    print("\n[INFO] Ces endpoints sont publics en lecture seule.")
    return 0


def cmd_rest_health(args: argparse.Namespace) -> int:
    """Vérifier la santé du REST Indexer."""
    print(DISCLAIMER)
    config = load_config_from_env()
    client = DydxIndexerRestClient(
        base_url=config.indexer_rest_url,
        timeout_s=config.rest_timeout_s,
        max_retries=2,
    )
    try:
        health = client.get_health()
        print(f"\n[OK] REST Indexer accessible")
        print(json.dumps(health, indent=2))
        return 0
    except RestError as e:
        print(f"\n[ERROR] REST Indexer inaccessible: {e}")
        return 1


def cmd_markets(args: argparse.Namespace) -> int:
    """Lister les marchés dYdX v4."""
    print(DISCLAIMER)
    config = load_config_from_env()
    client = DydxIndexerRestClient(base_url=config.indexer_rest_url)
    try:
        resp = client.get_markets()
        markets = resp.get("markets", {})
        print(f"\n{len(markets)} marchés disponibles:")
        for ticker, mkt in sorted(markets.items()):
            status = mkt.get("status", "?")
            oracle = mkt.get("oraclePrice", "?")
            print(f"  {ticker:<15} status={status:<8} oracle={oracle}")
        return 0
    except RestError as e:
        print(f"\n[ERROR] {e}")
        return 1


def cmd_backfill(args: argparse.Namespace) -> int:
    """Backfiller les données depuis l'Indexer REST."""
    print(DISCLAIMER)
    config = load_config_from_env()
    storage = DydxStorage(config.db_path, config.network.value)
    client = DydxIndexerRestClient(base_url=config.indexer_rest_url)

    from hyper_smart_observer.dydx_v4.indexer import DydxIndexer
    indexer = DydxIndexer(config=config, rest_client=client, storage=storage)

    print("\nBackfill marchés...")
    n_markets = indexer.backfill_markets()
    print(f"  {n_markets} marchés mis à jour")

    if args.address:
        print(f"\nBackfill subaccount {args.address}/{args.subaccount}...")
        ok = indexer.backfill_subaccount(args.address, args.subaccount)
        print(f"  {'OK' if ok else 'FAILED'}")

        print(f"\nBackfill fills {args.address}/{args.subaccount}...")
        n_fills = indexer.backfill_fills(args.address, args.subaccount)
        print(f"  {n_fills} nouveaux fills")

    print("\n[OK] Backfill terminé")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Afficher le dashboard READ-ONLY."""
    print(DISCLAIMER)
    config = load_config_from_env()
    storage = DydxStorage(config.db_path, config.network.value)
    adapter = DydxDashboardAdapter(config=config, storage=storage)
    print(adapter.render_text_report())
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    """Afficher le statut du paper trading."""
    print(DISCLAIMER)
    config = load_config_from_env()
    storage = DydxStorage(config.db_path, config.network.value)

    open_trades = storage.get_open_paper_trades("live")
    print(f"\nPaper trades ouverts (LIVE): {len(open_trades)}")
    for t in open_trades[:10]:
        print(
            f"  {t['market_id']} {t['side']} size={t['size']:.6f} "
            f"entry={t['entry_price']:.4f} net_pnl={t['net_pnl']:.4f}"
        )

    stats = storage.get_stats()
    print(f"\nDB stats:")
    print(f"  paper_trades: {stats.get('dydx_paper_trades', 0)}")
    print(f"  no_trade_decisions: {stats.get('dydx_no_trade_decisions', 0)}")
    print(f"  signal_candidates: {stats.get('dydx_signal_candidates', 0)}")
    return 0


def cmd_leaderboard(args: argparse.Namespace) -> int:
    """
    Construire/rafraîchir le leaderboard dYdX (Job A du bot viral).
    READ-ONLY: historicalPnl + fills publics. Aucun ordre.
    """
    print(DISCLAIMER)
    config = load_config_from_env()

    from hyper_smart_observer.dydx_v4.leaderboard import DydxLeaderboardBuilder

    rest = DydxIndexerRestClient(base_url=config.indexer_rest_url)
    cosmos = None
    try:
        from hyper_smart_observer.dydx_v4.cosmos_client import DydxCosmosLcdClient
        cosmos = DydxCosmosLcdClient()
    except Exception as e:
        print(f"Cosmos LCD indisponible ({e}) — énumération via base seulement")

    builder = DydxLeaderboardBuilder(
        rest=rest,
        cosmos=cosmos,
        db_path=config.db_path,
    )
    result = builder.build(
        max_candidates=args.max_candidates,
        max_scan_pages=args.scan_pages,
    )

    print(f"\n--- Leaderboard {result.run_id} ---")
    print(f"Candidats évalués : {result.candidates_evaluated}")
    print(f"Classés           : {len(result.entries)}")
    print(f"Copiables         : {len(result.shortlist)} (ELITE+STANDARD)")
    print(f"Promotions        : {len(result.promotions)} | Démotions: {len(result.demotions)}")
    print(f"\n{'rang':<5}{'tier':<10}{'score':<8}{'WR':<7}{'PF':<7}{'Sharpe':<8}{'trades':<8}adresse")
    for e in result.entries[:args.top]:
        m = e.metrics
        print(
            f"{e.rank:<5}{e.tier.value:<10}{e.score:<8.1f}{m.winrate:<7.0%}"
            f"{m.profit_factor:<7.2f}{m.sharpe:<8.2f}{m.closed_trades:<8}{e.address[:24]}"
        )
    if args.export:
        builder.export_shortlist_json(result, args.export)
        print(f"\nShortlist exportée → {args.export}")
    print(f"\n{result.disclaimer}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dydx",
        description=DISCLAIMER,
    )
    subs = parser.add_subparsers(dest="command")

    subs.add_parser("runtime-check", help="Vérifier l'environnement runtime")
    subs.add_parser("safety-check", help="Audit de sécurité")
    subs.add_parser("endpoints", help="Afficher les endpoints")
    subs.add_parser("rest-health", help="Santé REST Indexer")
    subs.add_parser("markets", help="Lister les marchés")
    subs.add_parser("dashboard", help="Dashboard READ-ONLY")
    subs.add_parser("paper", help="Statut paper trading")

    backfill = subs.add_parser("backfill", help="Backfiller les données REST")
    backfill.add_argument("--address", default=None, help="Adresse dYdX à backfiller")
    backfill.add_argument("--subaccount", type=int, default=0, help="Numéro de subaccount")

    lb = subs.add_parser(
        "leaderboard",
        help="Construire le leaderboard dYdX (historicalPnl + fills, READ-ONLY)",
    )
    lb.add_argument("--max-candidates", type=int, default=100, dest="max_candidates")
    lb.add_argument("--scan-pages", type=int, default=5, dest="scan_pages")
    lb.add_argument("--top", type=int, default=20, help="Lignes affichées")
    lb.add_argument(
        "--export", default="data/leaderboard_shortlist.json",
        help="Chemin d'export JSON de la shortlist copiable",
    )

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    dispatch = {
        "runtime-check": cmd_runtime_check,
        "safety-check": cmd_safety_check,
        "endpoints": cmd_endpoints,
        "rest-health": cmd_rest_health,
        "markets": cmd_markets,
        "backfill": cmd_backfill,
        "dashboard": cmd_dashboard,
        "paper": cmd_paper,
        "leaderboard": cmd_leaderboard,
    }

    if not args.command or args.command not in dispatch:
        parser.print_help()
        return 0

    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
