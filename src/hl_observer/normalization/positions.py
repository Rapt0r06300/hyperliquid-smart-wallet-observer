from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hl_observer.models import Position, SourceMeta


@dataclass(frozen=True, slots=True)
class NormalizedPositionResult:
    position: Position | None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def usable(self) -> bool:
        return self.position is not None and not self.warnings


def normalize_hyperliquid_position(
    raw: dict[str, Any],
    *,
    wallet: str,
    meta: SourceMeta,
) -> NormalizedPositionResult:
    """Normalize one Hyperliquid clearinghouseState asset position.

    Supports both direct and nested ``{"position": {...}}`` shapes.
    """

    node = raw.get("position") if isinstance(raw.get("position"), dict) else raw
    warnings: list[str] = []
    coin = _text(_first(node, "coin", "coinName", "asset"))
    size = _float(_first(node, "szi", "size", "sz", "signed_size"))
    entry_px = _float(_first(node, "entryPx", "entry_px"))
    mark_px = _float(_first(node, "markPx", "mark_px", "mid"))
    unrealized_pnl = _float(_first(node, "unrealizedPnl", "unrealized_pnl"))

    if not coin:
        warnings.append("POSITION_COIN_MISSING")
    if size is None:
        warnings.append("POSITION_SIZE_MISSING")

    if warnings:
        return NormalizedPositionResult(position=None, warnings=tuple(dict.fromkeys(warnings)))

    return NormalizedPositionResult(
        position=Position(
            wallet=wallet,
            coin=coin,
            signed_size=float(size),
            entry_px=entry_px,
            mark_px=mark_px,
            unrealized_pnl=unrealized_pnl,
            meta=meta,
        )
    )


def normalize_hyperliquid_positions(
    rows: list[dict[str, Any]],
    *,
    wallet: str,
    meta: SourceMeta,
) -> tuple[list[Position], list[str]]:
    positions: list[Position] = []
    warnings: list[str] = []
    for index, row in enumerate(rows):
        result = normalize_hyperliquid_position(row, wallet=wallet, meta=meta)
        if result.position is not None:
            positions.append(result.position)
        else:
            warnings.extend(f"row[{index}]:{warning}" for warning in result.warnings)
    return positions, warnings


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


__all__ = [
    "NormalizedPositionResult",
    "normalize_hyperliquid_position",
    "normalize_hyperliquid_positions",
]
