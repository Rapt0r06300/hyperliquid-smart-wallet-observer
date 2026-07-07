"""DATA-1 — Garde-fous qualité données: ne jamais trader une donnée douteuse.

Prix aberrant (fat-finger vs médiane récente), gap temporel, sources qui se
contredisent → verdict REJECT + quarantaine. Cause classique de pertes bots.
Pur, honnête: donnée insuffisante ⇒ INSUFFICIENT (jamais "OK" par défaut).
"""

from __future__ import annotations

from statistics import median


def price_sanity(coin: str, price: float, recent_prices: list[float], *, max_dev_pct: float = 10.0) -> dict:
    """Un prix qui dévie de >max_dev% de la médiane récente = suspect (fat-finger)."""

    clean = [float(p) for p in (recent_prices or []) if _pos(p)]
    if not _pos(price):
        return {"ok": False, "verdict": "PRICE_INVALID", "coin": str(coin).upper()}
    if len(clean) < 3:
        return {"ok": False, "verdict": "INSUFFICIENT_HISTORY", "coin": str(coin).upper()}
    med = median(clean)
    dev_pct = abs(price - med) / med * 100.0 if med > 0 else 999.0
    ok = dev_pct <= float(max_dev_pct)
    return {
        "ok": ok,
        "verdict": "OK" if ok else "PRICE_OUTLIER_FAT_FINGER",
        "coin": str(coin).upper(),
        "deviation_pct": round(dev_pct, 3),
        "median": round(med, 8),
    }


def staleness(coin: str, last_update_ms: int, now_ms: int, *, max_gap_ms: int = 30_000) -> dict:
    gap = int(now_ms) - int(last_update_ms)
    ok = 0 <= gap <= int(max_gap_ms)
    return {
        "ok": ok,
        "verdict": "OK" if ok else ("DATA_GAP_TOO_OLD" if gap > 0 else "CLOCK_SKEW"),
        "coin": str(coin).upper(),
        "gap_ms": gap,
    }


def cross_source_agreement(coin: str, prices_by_source: dict[str, float], *, max_disagreement_pct: float = 1.5) -> dict:
    """Deux sources qui divergent trop = on ne sait pas le vrai prix → REJECT."""

    clean = {str(s): float(p) for s, p in (prices_by_source or {}).items() if _pos(p)}
    if len(clean) < 2:
        return {"ok": len(clean) == 1, "verdict": "SINGLE_SOURCE" if clean else "NO_SOURCE", "coin": str(coin).upper()}
    lo, hi = min(clean.values()), max(clean.values())
    disagreement = (hi - lo) / lo * 100.0 if lo > 0 else 999.0
    ok = disagreement <= float(max_disagreement_pct)
    return {
        "ok": ok,
        "verdict": "OK" if ok else "SOURCES_CONTRADICT",
        "coin": str(coin).upper(),
        "disagreement_pct": round(disagreement, 3),
        "sources": list(clean),
    }


def evaluate_data_quality(coin, price, recent_prices, prices_by_source, last_update_ms, now_ms, **kw) -> dict:
    """Verdict combiné: NO_TRADE si un garde échoue, avec la raison précise."""

    checks = {
        "price": price_sanity(coin, price, recent_prices, max_dev_pct=kw.get("max_dev_pct", 10.0)),
        "staleness": staleness(coin, last_update_ms, now_ms, max_gap_ms=kw.get("max_gap_ms", 30_000)),
        "agreement": cross_source_agreement(coin, prices_by_source, max_disagreement_pct=kw.get("max_disagreement_pct", 1.5)),
    }
    failed = [name for name, r in checks.items() if not r["ok"]]
    return {
        "tradeable": not failed,
        "verdict": "OK" if not failed else "NO_TRADE_DATA_QUALITY",
        "failed_checks": failed,
        "reasons": [checks[n]["verdict"] for n in failed],
        "checks": checks,
    }


def _pos(x) -> bool:
    try:
        return float(x) > 0
    except (TypeError, ValueError):
        return False


__all__ = ["price_sanity", "staleness", "cross_source_agreement", "evaluate_data_quality"]
