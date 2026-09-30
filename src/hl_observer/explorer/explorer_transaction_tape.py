from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from hl_observer.storage.models import ExplorerTransactionTape


def get_explorer_tape(session: Session, *, limit: int = 100) -> list[dict[str, object]]:
    rows = session.scalars(
        select(ExplorerTransactionTape).order_by(ExplorerTransactionTape.id.desc()).limit(limit)
    ).all()
    return [
        {
            "tx_hash": row.tx_hash,
            "block": row.block,
            "action_type": row.action_type,
            "wallet_address": row.wallet_address,
            "coin": row.coin,
            "value_usdc": row.value_usdc,
            "status": row.status,
            "candidate_created": row.candidate_created,
            "reason": row.reason,
        }
        for row in rows
    ]


def format_explorer_tape(rows: list[dict[str, object]]) -> str:
    lines = ["explorer transaction tape", f"transactions: {len(rows)}"]
    if not rows:
        lines.append(
            "Explorer inspecte, mais aucune transaction structuree exploitable n'a ete extraite automatiquement."
        )
    for row in rows[:20]:
        lines.append(
            f"- {row.get('tx_hash') or '-'} wallet={row.get('wallet_address') or '-'} "
            f"coin={row.get('coin') or '-'} status={row.get('status')}"
        )
    return "\n".join(lines)

