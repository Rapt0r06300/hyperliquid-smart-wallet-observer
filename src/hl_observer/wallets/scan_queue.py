from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from hl_observer.storage.models import TopWallet, WalletScanJob, WalletScanQueue, WalletScanResult
from hl_observer.utils.time import now_ms
from hl_observer.wallets.leaderboard_validation import is_full_wallet_address, is_truncated_wallet_display


class WalletScanStatus(StrEnum):
    QUEUED = "QUEUED"
    SCANNING = "SCANNING"
    SCANNED = "SCANNED"
    FAILED = "FAILED"
    RETRY_LATER = "RETRY_LATER"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
    SKIPPED_INVALID = "SKIPPED_INVALID"
    SKIPPED_TRUNCATED = "SKIPPED_TRUNCATED"
    SKIPPED_RATE_LIMIT = "SKIPPED_RATE_LIMIT"
    SKIPPED_LOW_SCORE = "SKIPPED_LOW_SCORE"
    SKIPPED_NO_DATA = "SKIPPED_NO_DATA"


class WalletScanQueueResult(BaseModel):
    queued: int = 0
    scanned: int = 0
    failed: int = 0
    skipped: int = 0
    dry_run: bool = True
    selected_wallets: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def enqueue_wallets(
    session: Session,
    wallets: list[tuple[str, float, str]],
    *,
    dry_run: bool = True,
) -> WalletScanQueueResult:
    result = WalletScanQueueResult(dry_run=dry_run)
    existing = {row.wallet_address.lower() for row in session.query(WalletScanQueue).all()}
    for wallet_address, score, source in wallets:
        address = wallet_address.lower()
        if is_truncated_wallet_display(wallet_address) or "..." in wallet_address:
            result.skipped += 1
            result.notes.append(f"{wallet_address}: SKIPPED_TRUNCATED")
            continue
        if not is_full_wallet_address(address):
            result.skipped += 1
            result.notes.append(f"{wallet_address}: SKIPPED_INVALID")
            continue
        if address in existing:
            result.skipped += 1
            result.notes.append(f"{wallet_address}: SKIPPED_DUPLICATE")
            continue
        result.queued += 1
        result.selected_wallets.append(address)
        existing.add(address)
        if not dry_run:
            session.add(
                WalletScanQueue(
                    wallet_address=address,
                    priority_score=score,
                    source=source,
                    status=WalletScanStatus.QUEUED.value,
                    queued_at_ms=now_ms(),
                )
            )
    return result


def enqueue_top_wallets(session: Session, *, max_wallets: int, dry_run: bool = True) -> WalletScanQueueResult:
    session.flush()
    rows = session.query(TopWallet).order_by(TopWallet.score.desc()).limit(max_wallets).all()
    return enqueue_wallets(
        session,
        [(row.wallet_address, row.score, row.source) for row in rows],
        dry_run=dry_run,
    )


def scan_wallet_queue(
    session: Session,
    *,
    max_wallets: int,
    batch_size: int,
    dry_run: bool = True,
) -> WalletScanQueueResult:
    result = enqueue_top_wallets(session, max_wallets=max_wallets, dry_run=dry_run)
    queue_rows = session.query(WalletScanQueue).filter(WalletScanQueue.status == WalletScanStatus.QUEUED.value).order_by(
        WalletScanQueue.priority_score.desc()
    ).limit(batch_size).all()
    if dry_run:
        result.notes.append("dry_run_no_backfill")
        return result
    job = WalletScanJob(
        started_at_ms=now_ms(),
        finished_at_ms=now_ms(),
        status="DRY_SCAN_RECORDED",
        wallets_requested=batch_size,
        wallets_scanned=len(queue_rows),
        failures=0,
        notes="progressive_queue_no_exchange",
    )
    session.add(job)
    session.flush()
    for row in queue_rows:
        row.status = WalletScanStatus.SCANNED.value
        row.last_attempt_ms = now_ms()
        row.attempts += 1
        session.add(
            WalletScanResult(
                job_id=job.id,
                wallet_address=row.wallet_address,
                status=WalletScanStatus.SCANNED.value,
                scanned_at_ms=now_ms(),
                fills_count=0,
                deltas_count=0,
            )
        )
    result.scanned = len(queue_rows)
    return result


def format_scan_queue_report(result: WalletScanQueueResult) -> str:
    lines = [
        "wallet scan queue report",
        f"queued: {result.queued}",
        f"scanned: {result.scanned}",
        f"failed: {result.failed}",
        f"skipped: {result.skipped}",
        f"dry-run: {result.dry_run}",
    ]
    if result.notes:
        lines.append(f"notes: {'; '.join(result.notes[:20])}")
    return "\n".join(lines)
