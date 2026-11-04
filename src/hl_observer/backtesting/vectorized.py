"""Backtests vectorisés (IMPROVE-28) — numpy SI disponible, sinon fallback Python pur.
Le fallback garantit que RIEN ne casse sur une machine sans numpy (le toolkit reste sans dépendance).
Résultats identiques entre les deux chemins (testé). Paper uniquement — aucun ordre.
"""
from __future__ import annotations

try:                                   # numpy est optionnel, jamais requis
    import numpy as _np
    HAS_NUMPY = True
except ImportError:                    # pragma: no cover
    _np = None
    HAS_NUMPY = False


def fast_pnl(entries, exits, sides, *, notional: float = 500.0, cost_bps: float = 6.0,
             use_numpy: bool = True):
    """PnL net de chaque trade (coûts inclus). sides : +1 = LONG, -1 = SHORT."""
    if use_numpy and HAS_NUMPY and len(entries):
        e = _np.asarray(entries, dtype=float)
        x = _np.asarray(exits, dtype=float)
        s = _np.asarray(sides, dtype=float)
        ret = _np.where(e > 0, s * (x - e) / _np.where(e == 0, 1.0, e), 0.0)
        return (notional * ret - notional * cost_bps / 10000.0).tolist()
    out = []
    for e, x, s in zip(entries, exits, sides):
        e, x, s = float(e), float(x), float(s)
        ret = s * (x - e) / e if e > 0 else 0.0
        out.append(notional * ret - notional * cost_bps / 10000.0)
    return out


def fast_drawdown(equity, *, use_numpy: bool = True) -> float:
    """Drawdown maximal (en valeur absolue) d'une courbe d'equity."""
    if not len(equity):
        return 0.0
    if use_numpy and HAS_NUMPY:
        a = _np.asarray(equity, dtype=float)
        return float(_np.max(_np.maximum.accumulate(a) - a))
    peak, dd = float(equity[0]), 0.0
    for v in equity:
        v = float(v)
        peak = max(peak, v)
        dd = max(dd, peak - v)
    return dd


def fast_rolling_vol(prices, *, window: int = 20, use_numpy: bool = True):
    """Volatilité réalisée glissante des rendements (écart-type)."""
    n = len(prices)
    if n < 2:
        return []
    if use_numpy and HAS_NUMPY:
        p = _np.asarray(prices, dtype=float)
        r = _np.diff(p) / _np.where(p[:-1] == 0, 1.0, p[:-1])
        out = []
        for i in range(len(r)):
            lo = max(0, i - window + 1)
            seg = r[lo:i + 1]
            out.append(float(seg.std()) if len(seg) > 1 else 0.0)
        return out
    rets = []
    for i in range(1, n):
        prev = float(prices[i - 1])
        rets.append((float(prices[i]) - prev) / prev if prev else 0.0)
    out = []
    for i in range(len(rets)):
        seg = rets[max(0, i - window + 1):i + 1]
        if len(seg) > 1:
            m = sum(seg) / len(seg)
            out.append((sum((v - m) ** 2 for v in seg) / len(seg)) ** 0.5)
        else:
            out.append(0.0)
    return out


def vectorized_parity_receipt(
    entries, exits, sides, *, notional: float = 500.0, cost_bps: float = 6.0,
) -> dict[str, object]:
    """Check the optimized path against the CPU reference without promotion."""
    try:
        reference = fast_pnl(entries, exits, sides, notional=notional, cost_bps=cost_bps, use_numpy=False)
        optimized = fast_pnl(entries, exits, sides, notional=notional, cost_bps=cost_bps, use_numpy=True)
    except (TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
        return {
            "status": "UNMEASURABLE",
            "reason": f"VECTOR_INPUT_INVALID:{type(exc).__name__}",
            "paper_read_only": True,
            "real_execution": False,
        }
    parity = reference == optimized
    return {
        "status": "PROVEN" if parity else "REJECTED",
        "reason": "VECTOR_CPU_PARITY" if parity else "VECTOR_CPU_MISMATCH",
        "compared": len(reference),
        "trade_hash_reference": __import__("hashlib").sha256(repr(reference).encode()).hexdigest(),
        "trade_hash_optimized": __import__("hashlib").sha256(repr(optimized).encode()).hexdigest(),
        "paper_read_only": True,
        "real_execution": False,
    }
