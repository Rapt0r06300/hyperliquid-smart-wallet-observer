"""Paper position tracking (V12, repo 08): the paper position book (size + avg price).

Tracks net size and average entry per (coin, side) as opens/adds/reduces/closes are applied,
and computes unrealized PnL at a real mark. Pure / deterministic. No order, no fabrication.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class _Pos:
    size: float = 0.0
    avg_price: float = 0.0


@dataclass(slots=True)
class PaperPositionTracker:
    _book: dict[tuple[str, str], _Pos] = field(default_factory=dict)

    def _key(self, coin, side):
        return (str(coin).upper(), str(side).upper())

    def open_or_add(self, *, coin, side, size, price) -> None:
        p = self._book.setdefault(self._key(coin, side), _Pos())
        size = abs(float(size)); price = float(price)
        new_size = p.size + size
        if new_size > 0:
            p.avg_price = (p.avg_price * p.size + price * size) / new_size
        p.size = new_size

    def reduce_or_close(self, *, coin, side, size) -> None:
        key = self._key(coin, side)
        p = self._book.get(key)
        if p is None:
            return
        p.size = max(0.0, p.size - abs(float(size)))
        if p.size <= 0:
            self._book.pop(key, None)

    def position(self, coin, side) -> dict | None:
        p = self._book.get(self._key(coin, side))
        return None if p is None else {"coin": str(coin).upper(), "side": str(side).upper(),
                                       "size": round(p.size, 8), "avg_price": round(p.avg_price, 8)}

    def open_count(self) -> int:
        return len(self._book)

    def unrealized_pnl_usdc(self, marks: dict[str, float]) -> float:
        total = 0.0
        for (coin, side), p in self._book.items():
            mark = marks.get(coin)
            if mark is None or p.size <= 0 or p.avg_price <= 0:
                continue
            diff = (float(mark) - p.avg_price) if side == "LONG" else (p.avg_price - float(mark))
            total += diff * p.size
        return round(total, 6)


__all__ = ["PaperPositionTracker"]
