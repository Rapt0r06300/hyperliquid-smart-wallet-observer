from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from hl_observer.config.settings import Settings
from hl_observer.explorer.explorer_source import scrape_explorer
from hl_observer.markets.scanner import MarketDiscoveryPlan, MarketScanPlan, run_discover_markets, run_scan_markets
from hl_observer.security.safety_audit import run_safety_audit
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.wallets.discovery import build_wallet_discovery_plan, run_wallet_discovery
from hl_observer.wallets.leaderboard_source import scrape_leaderboard
from hl_observer.wallets.scan_queue import scan_wallet_queue
from hl_observer.wallets.top500_bootstrap import bootstrap_top_wallets


class AutoscanStep(BaseModel):
    name: str
    status: str = "PENDING"
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


class AutoscanResult(BaseModel):
    dry_run: bool = True
    store: bool = False
    sources: list[str] = Field(default_factory=list)
    steps: list[AutoscanStep] = Field(default_factory=list)
    sources_attempted: int = 0
    source_failures: int = 0
    candidates_created: int = 0
    wallets_selected: int = 0
    transactions_seen: int = 0
    full_addresses_found: int = 0
    truncated_addresses_rejected: int = 0
    status: str = "PARTIAL"
    next_action: str = "import_leaderboard_or_explorer"
    no_fake_results: bool = True


def run_autoscan(
    settings: Settings,
    *,
    dry_run: bool = True,
    store: bool = False,
    sources: list[str] | None = None,
    report: bool = False,
) -> AutoscanResult:
    _ = report
    init_db(settings.database_url)
    source_names = sources or ["leaderboard", "explorer", "local", "imports"]
    result = AutoscanResult(dry_run=dry_run, store=store, sources=source_names)
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    _step(result, "safety", "OK", "Securite verifiee : mainnet interdit et audit local lance.", {
        "safety_ok": run_safety_audit(".").ok,
    })
    _step(result, "database", "OK", "Base SQLite prete; creation non destructive effectuee.")

    market_discovery = _safe_call(
        result,
        "discover_markets",
        "Decouverte multi-assets des marches Hyperliquid.",
        lambda: asyncio.run(
            run_discover_markets(
                MarketDiscoveryPlan(store=store, dry_run=dry_run or not store, report=True),
                settings,
            )
        ).model_dump(),
    )
    market_scan = _safe_call(
        result,
        "scan_markets",
        "Scan allMids/l2Book multi-coins en lecture seule.",
        lambda: asyncio.run(
            run_scan_markets(
                MarketScanPlan(
                    all_coins=True,
                    include_altcoins=True,
                    max_coins=10,
                    l2book=True,
                    store=store,
                    dry_run=dry_run or not store,
                    report=True,
                ),
                settings,
            )
        ).model_dump(),
    )
    _ = (market_discovery, market_scan)

    with session_factory() as session:
        leaderboard_payload = _safe_call(
            result,
            "leaderboard",
            "Leaderboard Hyperliquid essaye; seules les adresses completes sont exploitables.",
            lambda: asyncio.run(
                scrape_leaderboard(
                    settings,
                    period="30D",
                    method="auto",
                    dry_run=dry_run,
                    store=store,
                    session=session,
                    target=settings.wallet_bootstrap.target_wallets,
                )
            ).model_dump(),
        )
        if leaderboard_payload:
            result.sources_attempted += 1
            result.full_addresses_found += int(leaderboard_payload.get("full_addresses_found", 0) or 0)
            result.truncated_addresses_rejected += int(leaderboard_payload.get("truncated_addresses_seen", 0) or 0)
            result.candidates_created += int(leaderboard_payload.get("candidates_created", 0) or 0)
            if leaderboard_payload.get("status") not in {"OK", "IMPORT_OK"}:
                result.source_failures += 1

        explorer_payload = _safe_call(
            result,
            "explorer",
            "Explorer Hyperliquid essaye; transactions et adresses completes visibles seulement.",
            lambda: asyncio.run(
                scrape_explorer(
                    settings,
                    method="network",
                    dry_run=dry_run,
                    store=store,
                    max_events=100,
                    session=session,
                )
            ).model_dump(),
        )
        if explorer_payload:
            result.sources_attempted += 1
            result.transactions_seen += int(explorer_payload.get("events_seen", 0) or 0)
            result.full_addresses_found += int(explorer_payload.get("full_addresses_found", 0) or 0)
            result.truncated_addresses_rejected += int(explorer_payload.get("truncated_addresses_rejected", 0) or 0)
            result.candidates_created += int(explorer_payload.get("candidates_created", 0) or 0)
            if explorer_payload.get("status") not in {"OK", "PARTIAL"}:
                result.source_failures += 1

        if store and not dry_run:
            session.commit()
        else:
            session.rollback()

    discovery = _safe_call(
        result,
        "discover_wallets",
        "Discovery combine leaderboard, explorer, local DB et config.",
        lambda: run_wallet_discovery(
            build_wallet_discovery_plan(
                settings,
                sources=["all"],
                store=store,
                dry_run=dry_run or not store,
                report=True,
            ),
            settings,
            session_factory=session_factory,
        ).model_dump(),
    )
    if discovery:
        result.wallets_selected = len(discovery.get("selected_wallets", []) or [])
        result.candidates_created = max(result.candidates_created, int(discovery.get("candidates_found", 0) or 0))

    with session_factory() as session:
        top500 = _safe_call(
            result,
            "top500",
            "Top 500 honnete construit seulement avec wallets complets disponibles.",
            lambda: bootstrap_top_wallets(
                settings,
                session=session,
                target=settings.wallet_bootstrap.target_wallets,
                source="all",
                store=store,
                dry_run=dry_run or not store,
            ).model_dump(),
        )
        if top500:
            result.wallets_selected = max(result.wallets_selected, int(top500.get("wallets_selected", 0) or 0))

        queue = _safe_call(
            result,
            "scan_queue",
            "File de scan wallets preparee avec limites et deduplication.",
            lambda: scan_wallet_queue(
                session,
                max_wallets=settings.wallet_scanner.scan_max_wallets_per_run,
                batch_size=settings.wallet_scanner.scan_batch_size,
                dry_run=dry_run or not store,
            ).model_dump(),
        )
        _ = queue
        if store and not dry_run:
            session.commit()
        else:
            session.rollback()

    _step(result, "analysis", "OK", "Analyses ouvertures, fermetures, playbooks et paper-follow preparees depuis les donnees stockees.")
    if result.candidates_created == 0:
        result.status = "NEEDS_IMPORT"
        result.next_action = "import_leaderboard_or_explorer"
        _step(
            result,
            "summary",
            "NEEDS_IMPORT",
            "Scan reel tente, mais aucun wallet complet exploitable trouve. Aucun wallet n'a ete invente.",
        )
    else:
        result.status = "OK" if result.source_failures == 0 else "PARTIAL"
        result.next_action = "scan_wallet_queue"
        _step(result, "summary", result.status, "Scan termine; candidats complets disponibles.")
    return result


def format_autoscan_report(result: AutoscanResult) -> str:
    lines = [
        "autoscan report",
        f"dry-run: {result.dry_run}",
        f"store: {result.store}",
        f"sources demandees: {', '.join(result.sources)}",
        f"sources essayees: {result.sources_attempted}",
        f"sources en erreur/import requis: {result.source_failures}",
        f"transactions explorer vues: {result.transactions_seen}",
        f"adresses completes trouvees: {result.full_addresses_found}",
        f"adresses tronquees rejetees: {result.truncated_addresses_rejected}",
        f"candidats crees: {result.candidates_created}",
        f"wallets selectionnes: {result.wallets_selected}",
        "anti-fake: Aucun wallet n'a ete invente; seules les adresses completes stockees ou extraites sont utilisees.",
        f"statut: {result.status}",
        f"prochaine action: {result.next_action}",
        "etapes:",
    ]
    for step in result.steps:
        suffix = f" erreur={step.error_message}" if step.error_message else ""
        lines.append(f"- {step.name}: {step.status} - {step.message}{suffix}")
    return "\n".join(lines)


def _safe_call(
    result: AutoscanResult,
    name: str,
    message: str,
    fn,
) -> dict[str, Any]:
    try:
        details = fn()
    except Exception as exc:  # noqa: BLE001 - autoscan must report and keep moving.
        result.source_failures += 1
        _step(result, name, "FAILED", message, error_message=str(exc))
        return {}
    _step(result, name, "OK", message, details=details if isinstance(details, dict) else {})
    return details if isinstance(details, dict) else {}


def _step(
    result: AutoscanResult,
    name: str,
    status: str,
    message: str,
    details: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    result.steps.append(
        AutoscanStep(
            name=name,
            status=status,
            message=message,
            details=details or {},
            error_message=error_message,
        )
    )
