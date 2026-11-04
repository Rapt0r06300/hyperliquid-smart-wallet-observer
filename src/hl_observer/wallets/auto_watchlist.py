from __future__ import annotations

from sqlalchemy.orm import Session

from hl_observer.storage.models import AutoWatchlist
from hl_observer.utils.time import now_ms


def add_to_auto_watchlist(
    session: Session,
    *,
    wallet_address: str,
    coin: str | None = None,
    label: str | None,
    source: str,
    discovery_score: float,
    notes: str | None = None,
) -> AutoWatchlist:
    existing = (
        session.query(AutoWatchlist)
        .filter(AutoWatchlist.wallet_address == wallet_address)
        .filter(AutoWatchlist.coin == (coin.upper() if coin else None))
        .order_by(AutoWatchlist.id.desc())
        .first()
    )
    if existing is not None:
        existing.discovery_score = max(existing.discovery_score, discovery_score)
        existing.status = "selected"
        existing.notes = notes or existing.notes
        session.add(existing)
        return existing
    item = AutoWatchlist(
        wallet_address=wallet_address,
        coin=coin.upper() if coin else None,
        label=label,
        source=source,
        added_at_ms=now_ms(),
        status="selected",
        discovery_score=discovery_score,
        last_backfill_ms=None,
        notes=notes,
    )
    session.add(item)
    return item


def discovery_to_scanner_receipt(*, discovered: int, selected: int, persisted: int) -> dict[str, object]:
    """Verify discovery-to-watchlist counts without asserting scanner execution."""
    values = (discovered, selected, persisted)
    if any(type(value) is not int or value < 0 for value in values) or selected > discovered or persisted > selected:
        return {"status": "UNMEASURABLE", "reason": "DISCOVERY_COUNT_INVALID", "paper_read_only": True}
    return {"status": "PROVEN", "discovered": discovered, "selected": selected, "persisted": persisted, "paper_read_only": True, "real_execution": False}
