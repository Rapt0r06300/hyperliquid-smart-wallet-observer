from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from hl_observer.storage.models import ExplorerRevalidationResult, ExplorerWalletCandidate
from hl_observer.utils.time import now_ms
from hl_observer.wallets.leaderboard_validation import is_full_wallet_address


def revalidate_explorer_wallets(session: Session, *, limit: int = 100, store: bool = False) -> dict[str, int]:
    rows = session.scalars(
        select(ExplorerWalletCandidate).order_by(ExplorerWalletCandidate.activity_score.desc()).limit(limit)
    ).all()
    ok = 0
    failed = 0
    for row in rows:
        valid = is_full_wallet_address(row.wallet_address)
        ok += int(valid)
        failed += int(not valid)
        if store:
            session.add(
                ExplorerRevalidationResult(
                    wallet_address=row.wallet_address,
                    ok=valid,
                    method="format_guard_then_info_ready",
                    checked_at_ms=now_ms(),
                    error_message=None if valid else "invalid_or_truncated_address",
                    raw_json={"read_only": True, "info_revalidation_prepared": True},
                )
            )
    return {"checked": len(rows), "ok": ok, "failed": failed}

