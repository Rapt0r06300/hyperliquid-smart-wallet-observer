"""Multi-wallet joint replay (V12 capability R, repo 11): one portfolio timeline.

Merges several wallets' event streams into a single time-ordered timeline (each event
tagged with its wallet), so a joint portfolio backtest sees events in true chronological
order across wallets. Pure / deterministic; no lookahead introduced.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def _exact_timestamp(value: object) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError("replay event requires an exact timestamp")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("replay event requires an exact timestamp") from exc
    if not number.is_finite() or number != number.to_integral_value() or number < 0:
        raise ValueError("replay event requires an exact timestamp")
    return int(number)


def replay_multi_wallet(per_wallet_events: dict[str, list[dict]]) -> list[dict]:
    merged: list[dict] = []
    for wallet, events in (per_wallet_events or {}).items():
        for ev in events or []:
            row = dict(ev)
            row["wallet"] = wallet
            merged.append(row)
    merged.sort(key=lambda e: (_exact_timestamp(e.get("ts_ms", e.get("decision_ts_ms"))), str(e.get("wallet", ""))))
    return merged


__all__ = ["replay_multi_wallet"]
