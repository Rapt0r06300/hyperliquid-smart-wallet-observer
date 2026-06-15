from __future__ import annotations

import math
from typing import Any

try:
    import hyper_smart_observer.dydx_v4.fresh_signal_patch  # noqa: F401
except Exception:
    pass

try:
    import hyper_smart_observer.dydx_v4.edge_freshness_patch  # noqa: F401
except Exception:
    pass

try:
    import hyper_smart_observer.dydx_v4.signal_enhancer  # noqa: F401
except Exception:
    pass

try:
    from hyper_smart_observer.dydx_v4.wallet_pool_ranker import pool_stats, wallet_pool_batch
except Exception:
    pool_stats = None
    wallet_pool_batch = None


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def whale_score(wallet: Any) -> float:
    pnl = max(0.0, _num(getattr(wallet, "net_pnl_usdc", 0.0)))
    balance = max(0.0, _num(getattr(wallet, "usdc_balance", 0.0)))
    score = 0.0
    score += min(1.0, math.log10(1.0 + pnl) / 6.0) * 55.0
    score += min(1.0, math.log10(1.0 + balance) / 6.0) * 30.0
    score += min(10.0, math.log10(1.0 + max(0.0, _num(getattr(wallet, "activity_count", 0.0)))) * 5.0)
    if _num(getattr(wallet, "profit_factor", 0.0)) >= 1.5:
        score += 3.0
    if _num(getattr(wallet, "winrate", 0.0)) >= 0.5:
        score += 2.0
    return round(score, 4)


def blended_whale_top(index: Any, limit: int, whale_share: float = 0.65) -> list[tuple[str, float]]:
    wallets = list(index.all()) if hasattr(index, "all") else []
    for w in wallets:
        try:
            if hasattr(w, "score"):
                w.score = max(float(getattr(w, "score", 0.0) or 0.0), 0.0)
        except Exception:
            pass
    if wallet_pool_batch is not None:
        def _blend_score(wallet: Any) -> float:
            whale = whale_score(wallet)
            has_whale_evidence = (
                _num(getattr(wallet, "net_pnl_usdc", 0.0)) > 0.0
                or _num(getattr(wallet, "usdc_balance", 0.0)) > 0.0
            )
            if has_whale_evidence:
                return 10_000.0 + whale
            return _num(getattr(wallet, "score", 0.0))

        return wallet_pool_batch(wallets, limit=limit, scorer=_blend_score, anchor_share=0.55)
    whale_n = max(0, min(limit, int(limit * whale_share)))
    general_n = max(0, limit - whale_n)
    whales = sorted(wallets, key=lambda w: (whale_score(w), _num(getattr(w, "score", 0.0))), reverse=True)[:whale_n]
    general = sorted(wallets, key=lambda w: _num(getattr(w, "score", 0.0)), reverse=True)[:general_n]
    out: dict[str, float] = {}
    for w in whales:
        addr = getattr(w, "address", None)
        if isinstance(addr, str):
            out[addr] = max(out.get(addr, 0.0), whale_score(w) + 5.0)
    for w in general:
        addr = getattr(w, "address", None)
        if isinstance(addr, str):
            out[addr] = max(out.get(addr, 0.0), _num(getattr(w, "score", 0.0)))
    return sorted(out.items(), key=lambda x: x[1], reverse=True)[:limit]


def whale_stats(index: Any) -> dict:
    wallets = list(index.all()) if hasattr(index, "all") else []
    scores = [whale_score(w) for w in wallets]
    out = {
        "whale_candidates": sum(1 for s in scores if s >= 45.0),
        "max_whale_score": round(max(scores, default=0.0), 4),
        "top_pnl_usdc": round(max((_num(getattr(w, "net_pnl_usdc", 0.0)) for w in wallets), default=0.0), 2),
        "read_only": True,
        "paper_only": True,
    }
    if pool_stats is not None:
        out["wallet_pool"] = pool_stats()
    return out


__all__ = ["blended_whale_top", "whale_score", "whale_stats"]
