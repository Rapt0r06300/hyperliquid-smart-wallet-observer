from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from hl_observer.models import Fill, SourceMeta


@dataclass(frozen=True, slots=True)
class NormalizedFillResult:
    fill: Fill | None
    dedupe_key: str | None
    signed_size_delta: float | None
    resulting_position: float | None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    raw_ref: str | None = None

    @property
    def usable(self) -> bool:
        return self.fill is not None and not self.warnings


def normalize_hyperliquid_fill(
    raw: dict[str, Any],
    *,
    wallet: str,
    meta: SourceMeta,
) -> NormalizedFillResult:
    """Normalize one real Hyperliquid fill payload.

    No defaults are fabricated: missing coin/size/price/time returns a warning
    and ``fill=None`` so upstream can emit NO_TRADE with evidence.
    """

    warnings: list[str] = []
    coin = _text(_first(raw, "coin", "coinName", "asset"))
    direction = _text(_first(raw, "dir", "direction"))
    side = _text(_first(raw, "side"))
    size = _float(_first(raw, "sz", "size"))
    price = _float(_first(raw, "px", "price"))
    time_ms = _int(_first(raw, "time", "timestamp", "ts"))
    start_position = _float(_first(raw, "startPosition", "start_position"))
    closed_pnl = _float(_first(raw, "closedPnl", "closed_pnl"))
    fee = _float(_first(raw, "fee"))
    oid = _text(_first(raw, "oid", "orderId"))
    tid = _text(_first(raw, "tid", "tradeId"))
    fill_hash = _text(_first(raw, "hash", "fillHash"))

    if not coin:
        warnings.append("FILL_COIN_MISSING")
    if not direction and not side:
        warnings.append("FILL_DIRECTION_MISSING")
    if size is None or size <= 0:
        warnings.append("FILL_SIZE_INVALID")
    if price is None or price <= 0:
        warnings.append("FILL_PRICE_INVALID")
    if time_ms is None or time_ms <= 0:
        warnings.append("FILL_TIME_MISSING")

    signed_delta = _signed_delta(direction=direction, side=side, size=size)
    if signed_delta is None:
        warnings.append("FILL_SIGN_UNDETERMINED")

    resulting_position = None
    if signed_delta is not None and start_position is not None:
        resulting_position = start_position + signed_delta

    raw_ref = _raw_ref(wallet, coin or "UNKNOWN", raw)
    dedupe_key = _dedupe_key(
        wallet=wallet,
        coin=coin,
        time_ms=time_ms,
        size=size,
        price=price,
        oid=oid,
        tid=tid,
        fill_hash=fill_hash,
    )
    if warnings:
        return NormalizedFillResult(
            fill=None,
            dedupe_key=dedupe_key,
            signed_size_delta=signed_delta,
            resulting_position=resulting_position,
            warnings=tuple(dict.fromkeys(warnings)),
            raw_ref=raw_ref,
        )

    fill = Fill(
        wallet=wallet,
        coin=coin,
        direction=direction,
        side=side,
        size=float(size),
        price=float(price),
        time_ms=int(time_ms),
        start_position=start_position,
        closed_pnl=closed_pnl,
        fee=fee,
        oid=oid,
        tid=tid,
        fill_hash=fill_hash,
        meta=meta,
    )
    return NormalizedFillResult(
        fill=fill,
        dedupe_key=dedupe_key,
        signed_size_delta=signed_delta,
        resulting_position=resulting_position,
        raw_ref=raw_ref,
    )


def fill_dedupe_key(fill: Fill) -> str:
    return _dedupe_key(
        wallet=fill.wallet,
        coin=fill.coin,
        time_ms=fill.time_ms,
        size=fill.size,
        price=fill.price,
        oid=fill.oid,
        tid=fill.tid,
        fill_hash=fill.fill_hash,
    )


def _signed_delta(*, direction: str | None, side: str | None, size: float | None) -> float | None:
    if size is None or size <= 0:
        return None
    text = (direction or "").strip().lower()
    if "open long" in text or "close short" in text:
        return abs(float(size))
    if "open short" in text or "close long" in text:
        return -abs(float(size))
    side_text = (side or "").strip().lower()
    if side_text in {"b", "buy", "bid"}:
        return abs(float(size))
    if side_text in {"a", "s", "sell", "ask"}:
        return -abs(float(size))
    return None


def _dedupe_key(
    *,
    wallet: str,
    coin: str | None,
    time_ms: int | None,
    size: float | None,
    price: float | None,
    oid: str | None,
    tid: str | None,
    fill_hash: str | None,
) -> str:
    if fill_hash:
        return f"hash:{fill_hash}"
    material = "|".join(
        str(part or "")
        for part in (
            wallet.lower(),
            (coin or "").upper(),
            tid,
            oid,
            time_ms,
            size,
            price,
        )
    )
    return "fill:" + sha256(material.encode("utf-8")).hexdigest()


def _raw_ref(wallet: str, coin: str, raw: dict[str, Any]) -> str:
    material = f"{wallet.lower()}|{coin.upper()}|{raw!r}"
    return "rawfill:" + sha256(material.encode("utf-8")).hexdigest()[:24]


def _first(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value is not None:
            return value
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return None if value in (None, "") else int(float(value))
    except (TypeError, ValueError):
        return None


__all__ = ["NormalizedFillResult", "fill_dedupe_key", "normalize_hyperliquid_fill"]
