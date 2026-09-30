"""One-command READ-ONLY 'collect everything' to widen the leader shortlist.

Run:
    set PYTHONPATH=%cd%\\src
    python -m hl_observer.collection.run_collect_all --max-coins 200 --target 500

Chains the existing read-only collectors (V7 READ_ONLY_ALLOWED): discover markets
-> discover wallets -> bootstrap top wallets -> score the wallet queue. Each step
is isolated via run_steps (one failure never stops the others). Kept as a SMALL
standalone module so cli.py (very large, truncates on edit) is never modified.
No order, no key, no signature, no fabricated data.
"""

from __future__ import annotations

import argparse
import asyncio

from hl_observer.collection.collect_all import run_steps
from hl_observer.config.loader import load_settings
from hl_observer.markets.scanner import MarketDiscoveryPlan, run_discover_markets
from hl_observer.storage.database import create_session_factory, create_sqlite_engine
from hl_observer.wallets.discovery import build_wallet_discovery_plan, run_wallet_discovery
from hl_observer.wallets.scan_queue import scan_wallet_queue
from hl_observer.wallets.top500_bootstrap import bootstrap_top_wallets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only collect-all (widen the leader shortlist).")
    parser.add_argument("--max-coins", type=int, default=200)
    parser.add_argument("--target", type=int, default=500)
    args = parser.parse_args(argv)
    settings = load_settings()

    def _session():
        return create_session_factory(create_sqlite_engine(settings.database_url))()

    def _discover_markets() -> str:
        plan = MarketDiscoveryPlan(
            sources=["meta", "all-mids"], include_altcoins=True, max_coins=args.max_coins,
            store=True, dry_run=False, report=False, json_output=False,
        )
        res = asyncio.run(run_discover_markets(plan, settings))
        return f"coins={getattr(res, 'coins_discovered', getattr(res, 'stored', '?'))}"

    def _discover_wallets() -> str:
        plan = build_wallet_discovery_plan(settings, store=True, dry_run=False, report=False)
        res = run_wallet_discovery(plan, settings)
        return f"candidates={getattr(res, 'candidates_found', '?')}"

    def _bootstrap() -> str:
        with _session() as session:
            bootstrap_top_wallets(settings, session=session, target=args.target, source="all", store=True, dry_run=False)
            session.commit()
        return f"top_wallets target<= {args.target}"

    def _scan_queue() -> str:
        with _session() as session:
            scan_wallet_queue(
                session,
                max_wallets=settings.wallet_scanner.scan_max_wallets_per_run,
                batch_size=settings.wallet_scanner.scan_batch_size,
                dry_run=False,
            )
            session.commit()
        return "queue scored"

    report = run_steps([
        ("discover_markets", _discover_markets),
        ("discover_wallets", _discover_wallets),
        ("bootstrap_top_wallets", _bootstrap),
        ("scan_wallet_queue", _scan_queue),
    ])
    print(report.summary())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
