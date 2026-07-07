"""P4 — Signaux microstructure: OBI + gros trades publics + anti-rafale.

Distillé de mlmodelpoly (order-book imbalance, seuil 0.10, cooldown) + CODEX_GOAL
item 6 (gros trades WS >$50k comme boost). Ces signaux CONFIRMENT ou BOOSTENT, ils
n'ouvrent jamais seuls (evidence-first). Pur, read-only.
"""

from __future__ import annotations


def order_book_imbalance(bid_depth_usdt: float, ask_depth_usdt: float) -> float:
    """OBI ∈ [-1, 1]: +1 = pression acheteuse totale, -1 = vendeuse."""
    b, a = max(0.0, float(bid_depth_usdt or 0.0)), max(0.0, float(ask_depth_usdt or 0.0))
    tot = b + a
    if tot <= 0:
        return 0.0
    return round((b - a) / tot, 4)


def obi_confirms(side: str, bid_depth_usdt: float, ask_depth_usdt: float, *, threshold: float = 0.10) -> dict:
    """L'OBI confirme-t-il le sens du trade ? (LONG veut OBI > +seuil)."""
    obi = order_book_imbalance(bid_depth_usdt, ask_depth_usdt)
    side = str(side).upper()
    if side == "LONG":
        confirmed = obi >= threshold
    elif side == "SHORT":
        confirmed = obi <= -threshold
    else:
        return {"confirmed": False, "obi": obi, "reason": "INVALID_SIDE"}
    return {"confirmed": confirmed, "obi": obi,
            "reason": "OBI_CONFIRMS" if confirmed else "OBI_AGAINST_OR_NEUTRAL"}


def big_trade_boost(recent_trades: list[dict], side: str, *, big_usd: float = 50_000.0, boost: float = 1.2) -> dict:
    """Un gros trade public récent dans notre sens → boost multiplicatif du signal."""
    side = str(side).upper()
    aligned = [
        t for t in (recent_trades or [])
        if isinstance(t, dict) and abs(float(t.get("notional_usd") or 0.0)) >= big_usd
        and str(t.get("side") or "").upper() == side
    ]
    return {"boost": boost if aligned else 1.0, "big_trades_aligned": len(aligned),
            "reason": "BIG_TRADE_ALIGNED" if aligned else "NO_BIG_TRADE"}


class AntiBurstGate:
    """Anti-rafale: refuse plus d'un signal par coin/side dans une fenêtre cooldown."""

    def __init__(self, cooldown_sec: float = 2.0) -> None:
        self.cooldown_ms = int(cooldown_sec * 1000)
        self._last: dict[tuple, int] = {}

    def allow(self, coin: str, side: str, now_ms: int) -> bool:
        key = (str(coin).upper(), str(side).upper())
        last = self._last.get(key, -1)
        if last >= 0 and (int(now_ms) - last) < self.cooldown_ms:
            return False
        self._last[key] = int(now_ms)
        return True


__all__ = ["order_book_imbalance", "obi_confirms", "big_trade_boost", "AntiBurstGate"]
