from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from hl_observer.storage.models import (
    LeaderboardAddressValidation,
    LeaderboardRow,
    LeaderboardRun,
    LeaderboardWalletCandidate,
)
from hl_observer.utils.time import now_ms
from hl_observer.wallets.leaderboard_models import LeaderboardResult, LeaderboardSourceStatus
from hl_observer.wallets.leaderboard_parser import parse_leaderboard_file


def import_leaderboard_file(
    path: str | Path,
    *,
    period: str = "30D",
    store: bool = False,
    session: Session | None = None,
) -> LeaderboardResult:
    rows = parse_leaderboard_file(Path(path), period=period)
    result = LeaderboardResult.from_rows(
        rows,
        period=period,
        method="import",
        status=LeaderboardSourceStatus.IMPORT_OK if any(row.address for row in rows) else LeaderboardSourceStatus.IMPORT_REQUIRED,
        notes=["import_file_parsed"],
    )
    if store:
        if session is None:
            raise ValueError("session is required when store=True")
        store_leaderboard_result(session, result, source_method="import")
    return result


def store_leaderboard_result(
    session: Session,
    result: LeaderboardResult,
    *,
    source_method: str,
) -> LeaderboardRun:
    started = result.started_at_ms
    run = LeaderboardRun(
        started_at_ms=started,
        finished_at_ms=result.finished_at_ms or now_ms(),
        status=result.status.value,
        source_method=source_method,
        period=result.period,
        rows_seen=result.rows_seen,
        full_addresses_found=result.full_addresses_found,
        truncated_addresses_seen=result.truncated_addresses_seen,
        candidates_created=result.candidates_created,
        error_message=result.error_message,
        notes=";".join(result.notes) if result.notes else None,
    )
    session.add(run)
    session.flush()
    result.run_id = run.id

    for row in result.rows:
        validation = row.validation
        if validation is not None:
            session.add(
                LeaderboardAddressValidation(
                    run_id=run.id,
                    raw_value=validation.raw_value,
                    normalized_value=validation.normalized_value,
                    is_full_address=validation.is_full_address,
                    is_truncated=validation.is_truncated,
                    validation_status=validation.validation_status.value,
                    rejection_reason=validation.rejection_reason,
                    source_method=source_method,
                    created_at_ms=now_ms(),
                )
            )
        session.add(
            LeaderboardRow(
                run_id=run.id,
                rank=row.rank,
                address=row.address,
                address_short=row.address_short,
                address_is_full=bool(validation and validation.is_full_address),
                address_validation_status=validation.validation_status.value if validation else "INVALID_ADDRESS_REJECTED",
                account_value_usdc=row.account_value_usdc,
                pnl_usdc=row.pnl_usdc,
                roi_pct=row.roi_pct,
                volume_usdc=row.volume_usdc,
                period=row.period,
                source_method=row.source_method,
                extraction_method=row.extraction_method,
                source_payload_hash=row.source_payload_hash,
                imported_at_ms=now_ms(),
                validation_status=validation.validation_status.value if validation else "INVALID_ADDRESS_REJECTED",
                source_confidence_score=row.source_confidence_score,
                rejection_reason=validation.rejection_reason if validation else "invalid",
            )
        )
    for candidate in result.candidates:
        session.add(
            LeaderboardWalletCandidate(
                run_id=run.id,
                wallet_address=candidate.wallet_address,
                rank=candidate.rank,
                period=candidate.period,
                account_value_usdc=candidate.account_value_usdc,
                pnl_usdc=candidate.pnl_usdc,
                roi_pct=candidate.roi_pct,
                volume_usdc=candidate.volume_usdc,
                leaderboard_score=candidate.leaderboard_score,
                selected_for_revalidation=candidate.selected_for_revalidation,
                selected_for_backfill=candidate.selected_for_backfill,
                source_confidence=candidate.source_confidence,
                notes=candidate.notes,
            )
        )
    return run


def format_leaderboard_report(result: LeaderboardResult) -> str:
    lines = [
        "leaderboard report",
        f"periode: {result.period}",
        f"methode: {result.method}",
        f"lignes vues: {result.rows_seen}",
        f"adresses completes trouvees: {result.full_addresses_found}",
        f"adresses tronquees rejetees: {result.truncated_addresses_seen}",
        f"candidats crees: {result.candidates_created}",
        f"statut: {result.status.value}",
    ]
    if result.status in {
        LeaderboardSourceStatus.IMPORT_REQUIRED,
        LeaderboardSourceStatus.ONLY_TRUNCATED_ADDRESSES,
        LeaderboardSourceStatus.NO_FULL_ADDRESS,
    }:
        lines.append(
            "IMPORT_REQUIRED - la page affiche uniquement des adresses tronquees ou l'extraction automatique n'a pas trouve les adresses completes. "
            "Importe un CSV/JSON/TXT contenant les adresses completes."
        )
    if result.candidates:
        lines.append("top 10 candidats valides:")
        for candidate in sorted(result.candidates, key=lambda row: row.leaderboard_score, reverse=True)[:10]:
            lines.append(
                f"- {candidate.wallet_address} rank={candidate.rank} pnl={candidate.pnl_usdc} roi={candidate.roi_pct} score={candidate.leaderboard_score:.1f}"
            )
    if result.rejected:
        lines.append("top 10 rejetes:")
        for rejected in result.rejected[:10]:
            lines.append(f"- {rejected.get('raw_value', '')}: {rejected.get('reason')}")
    if result.notes:
        lines.append(f"notes: {'; '.join(result.notes)}")
    return "\n".join(lines)
