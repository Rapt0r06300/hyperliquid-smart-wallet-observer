from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hl_observer.config.settings import Settings
from hl_observer.explorer.explorer_importer import import_explorer_file
from hl_observer.explorer.explorer_models import ExplorerResult, ExplorerSourceStatus
from hl_observer.explorer.explorer_network_probe import probe_explorer_network
from hl_observer.storage.models import (
    ExplorerEndpoint,
    ExplorerEvent,
    ExplorerRun,
    ExplorerTransaction as ExplorerTransactionModel,
    ExplorerTransactionTape,
    ExplorerWalletCandidate,
)
from hl_observer.utils.time import now_ms


async def scrape_explorer(
    settings: Settings,
    *,
    method: str = "network",
    dry_run: bool = True,
    store: bool = False,
    max_events: int = 500,
    session: Session | None = None,
) -> ExplorerResult:
    method = method.lower()
    if method in {"network", "auto"}:
        result = await probe_explorer_network(
            timeout_seconds=settings.wallet_discovery.source_timeout_seconds,
            dry_run=dry_run,
            max_events=max_events,
        )
    elif method == "dom":
        result = ExplorerResult(
            method="dom",
            status=ExplorerSourceStatus.IMPORT_REQUIRED,
            notes=["dom_extractor_requires_public_html_fixture_or_network_payload"],
        ).finish()
    else:
        result = ExplorerResult(
            method=method,
            status=ExplorerSourceStatus.IMPORT_REQUIRED,
            notes=["unsupported_method_import_required"],
        ).finish()
    if store and session is not None and not dry_run:
        store_explorer_result(session, result)
    return result


def import_and_store_explorer(path: str | Path, *, store: bool, session: Session | None = None) -> ExplorerResult:
    result = import_explorer_file(path)
    if store:
        if session is None:
            raise ValueError("session is required when store=True")
        store_explorer_result(session, result)
    return result


def store_explorer_result(session: Session, result: ExplorerResult) -> ExplorerRun:
    run = ExplorerRun(
        started_at_ms=result.started_at_ms,
        finished_at_ms=result.finished_at_ms or now_ms(),
        status=result.status.value,
        method=result.method,
        endpoints_found=len(result.endpoints_found),
        events_seen=result.events_seen,
        transactions_stored=len(result.transactions),
        full_addresses_found=result.full_addresses_found,
        truncated_addresses_rejected=result.truncated_addresses_rejected,
        candidates_created=result.candidates_created,
        error_message=result.error_message,
        notes=";".join(result.notes) if result.notes else None,
    )
    session.add(run)
    session.flush()
    for endpoint in result.endpoints_found:
        session.add(
            ExplorerEndpoint(
                run_id=run.id,
                endpoint_url=endpoint.endpoint_url,
                method=endpoint.method,
                status=endpoint.status.value,
                http_status=endpoint.http_status,
                error_message=endpoint.error_message,
                notes=";".join(endpoint.notes) if endpoint.notes else None,
                created_at_ms=now_ms(),
            )
        )
    tx_model_by_wallet: dict[str, list[ExplorerTransactionModel]] = {}
    for tx in result.transactions:
        tx_model = ExplorerTransactionModel(
            run_id=run.id,
            tx_hash=tx.tx_hash,
            block=tx.block,
            timestamp_ms=tx.timestamp_ms,
            action_type=tx.action_type,
            wallet_address=tx.wallet_address,
            address_short=tx.address_short,
            coin=tx.coin,
            side=tx.side,
            size=tx.size,
            price=tx.price,
            value_usdc=tx.value_usdc,
            raw_payload_hash=tx.raw_payload_hash,
            source_url=tx.source_url,
            confidence_score=tx.confidence_score,
            validation_status=tx.validation_status.value,
            raw_json=tx.raw_payload,
            created_at_ms=now_ms(),
        )
        session.add(tx_model)
        session.flush()
        candidate_created = bool(tx.wallet_address)
        session.add(
            ExplorerEvent(
                run_id=run.id,
                event_type=tx.action_type or "UNKNOWN",
                wallet_address=tx.wallet_address,
                coin=tx.coin,
                status=tx.validation_status.value,
                raw_json=tx.raw_payload,
                created_at_ms=now_ms(),
            )
        )
        session.add(
            ExplorerTransactionTape(
                transaction_id=tx_model.id,
                tx_hash=tx.tx_hash,
                block=tx.block,
                action_type=tx.action_type,
                wallet_address=tx.wallet_address,
                coin=tx.coin,
                value_usdc=tx.value_usdc,
                status=tx.validation_status.value,
                candidate_created=candidate_created,
                reason=None if candidate_created else tx.validation_status.value,
                created_at_ms=now_ms(),
            )
        )
        if tx.wallet_address:
            tx_model_by_wallet.setdefault(tx.wallet_address, []).append(tx_model)
    for wallet_address, rows in tx_model_by_wallet.items():
        coins = sorted({row.coin for row in rows if row.coin})
        session.add(
            ExplorerWalletCandidate(
                run_id=run.id,
                wallet_address=wallet_address,
                source="explorer",
                first_tx_hash=rows[0].tx_hash,
                events_count=len(rows),
                coins_json=coins,
                activity_score=min(100.0, 50.0 + len(rows) * 5.0),
                selected_for_revalidation=True,
                validation_status="FULL_ADDRESS_OK",
                created_at_ms=now_ms(),
                notes="created_from_explorer_full_address",
            )
        )
    return run


def create_explorer_candidates(session: Session) -> int:
    rows = session.scalars(
        select(ExplorerTransactionModel).where(ExplorerTransactionModel.wallet_address.is_not(None)).limit(5000)
    ).all()
    created = 0
    existing = {
        value
        for (value,) in session.query(ExplorerWalletCandidate.wallet_address).all()
    }
    by_wallet: dict[str, list[ExplorerTransactionModel]] = {}
    for row in rows:
        if row.wallet_address:
            by_wallet.setdefault(row.wallet_address, []).append(row)
    for wallet_address, wallet_rows in by_wallet.items():
        if wallet_address in existing:
            continue
        session.add(
            ExplorerWalletCandidate(
                wallet_address=wallet_address,
                source="explorer",
                first_tx_hash=wallet_rows[0].tx_hash,
                events_count=len(wallet_rows),
                coins_json=sorted({row.coin for row in wallet_rows if row.coin}),
                activity_score=min(100.0, 50.0 + len(wallet_rows) * 5.0),
                selected_for_revalidation=True,
                validation_status="FULL_ADDRESS_OK",
                created_at_ms=now_ms(),
                notes="created_from_stored_transactions",
            )
        )
        created += 1
    return created


def explorer_status(session: Session) -> dict[str, object]:
    run = session.scalar(select(ExplorerRun).order_by(ExplorerRun.id.desc()).limit(1))
    candidates = int(session.scalar(select(func.count()).select_from(ExplorerWalletCandidate)) or 0)
    transactions = int(session.scalar(select(func.count()).select_from(ExplorerTransactionModel)) or 0)
    rejected = int(
        session.scalar(
            select(func.count())
            .select_from(ExplorerTransactionModel)
            .where(ExplorerTransactionModel.validation_status == "TRUNCATED_ADDRESS_REJECTED")
        )
        or 0
    )
    return {
        "status": run.status if run else "IMPORT_REQUIRED",
        "method": run.method if run else None,
        "endpoints_found": run.endpoints_found if run else 0,
        "events_seen": run.events_seen if run else 0,
        "transactions_stored": transactions,
        "full_addresses_found": run.full_addresses_found if run else 0,
        "truncated_addresses_rejected": run.truncated_addresses_rejected if run else rejected,
        "candidates_created": candidates,
        "error_message": run.error_message if run else None,
        "next_action": "import_explorer_csv" if candidates == 0 else "revalidate_explorer_wallets",
    }


def format_explorer_report(result: ExplorerResult) -> str:
    lines = [
        "explorer report",
        f"methode: {result.method}",
        f"endpoints publics trouves: {len(result.endpoints_found)}",
        f"evenements vus: {result.events_seen}",
        f"transactions structurees: {len(result.transactions)}",
        f"adresses completes trouvees: {result.full_addresses_found}",
        f"adresses tronquees rejetees: {result.truncated_addresses_rejected}",
        f"candidats crees: {result.candidates_created}",
        f"statut: {result.status.value}",
    ]
    if result.error_message:
        lines.append(f"erreur: {result.error_message}")
    if result.full_addresses_found == 0:
        lines.append(
            "Explorer analyse, mais aucune adresse complete exploitable n'a ete trouvee automatiquement. "
            "Aucun wallet n'a ete invente; utilise import-explorer avec un CSV/JSON/TXT si besoin."
        )
    if result.notes:
        lines.append(f"notes: {'; '.join(result.notes)}")
    return "\n".join(lines)
