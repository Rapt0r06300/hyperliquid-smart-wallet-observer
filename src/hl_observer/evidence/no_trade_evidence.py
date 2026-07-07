"""NO_TRADE evidence rows (V12 capability O — DecisionLedger ↔ taxonomie §17).

Builds a ledger-ready evidence row for a refused decision, carrying the canonical
7-attribute NO_TRADE reason plus the decision context. Pure: no I/O, no order; the
actual DB insert stays in the DecisionLedger layer.
"""

from __future__ import annotations

from hl_observer.signals.no_trade_taxonomy import reason


def no_trade_evidence_row(
    code: str,
    *,
    wallet: str | None = None,
    coin: str | None = None,
    run_context: str = "LIVE",
    missing_data: tuple[str, ...] | list[str] = (),
    evidence_refs: tuple[str, ...] | list[str] = (),
    now_ms: int | None = None,
) -> dict:
    """Resolve `code` via the taxonomy and return a JSON-safe ledger row (7 attrs + context)."""
    r = reason(code, missing_data=missing_data, evidence_refs=evidence_refs)
    row = r.to_dict()
    row.update({
        "wallet": wallet,
        "coin": coin,
        "run_context": run_context,
        "recorded_at_ms": int(now_ms) if now_ms is not None else None,
    })
    return row


__all__ = ["no_trade_evidence_row"]
