"""V26 L8 — Forager : sélection dynamique des marchés (passivbot coin_selection + filtres freqtrade).

Score de qualité composite par marché, uniquement à partir de données réelles déjà
observées dans le runtime :

* volatilité (range bps, via MidVolEstimator) : bornes min (marché mort — RangeStabilityFilter)
  et max (marché panique — VolatilityFilter) ;
* liquidité (liquidity_score du candidat) : plancher ;
* mémoire de performance du marché chez NOUS (PerformanceFilter) : pénalité si PnL cumulé négatif.

Top-K avec HYSTÉRÉSIS : un marché entre dans l'univers s'il est top-K, n'en sort que
s'il tombe sous K+buffer (pas d'oscillation). Inconnu = non noté = ne bloque PAS
(le filtre ne s'applique qu'aux marchés notés, état honnête).
Opt-in : ``HYPERSMART_V26_MARKET_QUALITY=1``. Étend ``is_exotic_market``, ne le remplace pas.
"""

from __future__ import annotations

import os
import threading
import time

MASTER_FLAG = "HYPERSMART_V26_MARKET_QUALITY"
TOP_K_ENV = "HYPERSMART_V26_MQ_TOP_K"
BUFFER_ENV = "HYPERSMART_V26_MQ_HYSTERESIS_BUFFER"
VOL_MIN_ENV = "HYPERSMART_V26_MQ_RANGE_MIN_BPS"
VOL_MAX_ENV = "HYPERSMART_V26_MQ_RANGE_MAX_BPS"
LIQ_MIN_ENV = "HYPERSMART_V26_MQ_LIQ_MIN"
STALE_ENV = "HYPERSMART_V26_MQ_STALE_S"

_DEF = {
    TOP_K_ENV: 12.0, BUFFER_ENV: 4.0,
    VOL_MIN_ENV: 5.0,    # < 5 bps de range 15min = marché mort
    VOL_MAX_ENV: 250.0,  # > 250 bps = panique
    LIQ_MIN_ENV: 0.22,
    STALE_ENV: 1800.0,   # note périmée après 30 min sans observation
}

REASON_MQ = "MARKET_QUALITY_LOW"


def _f(name: str, env: dict | None = None) -> float:
    e = env if env is not None else os.environ
    try:
        return float(e.get(name, _DEF[name]) or _DEF[name])
    except (TypeError, ValueError):
        return float(_DEF[name])


def flag_on(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(MASTER_FLAG, "0")).strip().lower() in ("1", "true", "yes", "on")


def quality_score(*, range_bps: float | None, liquidity_score: float | None,
                  market_pnl_usd: float | None, env: dict | None = None) -> float | None:
    """Score [0..100]. None si aucune donnée réelle (jamais noté au hasard)."""
    if range_bps is None and liquidity_score is None and market_pnl_usd is None:
        return None
    score = 50.0
    if range_bps is not None:
        lo, hi = _f(VOL_MIN_ENV, env), _f(VOL_MAX_ENV, env)
        if range_bps < lo:
            score -= 30.0          # mort
        elif range_bps > hi:
            score -= 35.0          # panique
        else:
            score += 15.0          # régime sain
    if liquidity_score is not None:
        if liquidity_score < _f(LIQ_MIN_ENV, env):
            score -= 25.0
        else:
            score += min(20.0, liquidity_score * 20.0)
    if market_pnl_usd is not None:
        if market_pnl_usd < 0:
            score -= min(25.0, abs(market_pnl_usd))   # 1 pt par $ perdu, plafonné
        elif market_pnl_usd > 0:
            score += min(10.0, market_pnl_usd)
    return max(0.0, min(100.0, score))


class MarketQualityBook:
    """Notes par marché + univers top-K avec hystérésis. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scores: dict[str, tuple[float, float]] = {}   # coin -> (score, ts)
        self._universe: set[str] = set()

    def observe(self, coin: str, *, range_bps: float | None = None,
                liquidity_score: float | None = None, market_pnl_usd: float | None = None,
                env: dict | None = None, now: float | None = None) -> float | None:
        key = (coin or "").strip().upper()
        if not key:
            return None
        s = quality_score(range_bps=range_bps, liquidity_score=liquidity_score,
                          market_pnl_usd=market_pnl_usd, env=env)
        if s is None:
            return None
        t = float(now) if now is not None else time.time()
        with self._lock:
            self._scores[key] = (s, t)
        self._refresh_universe(env=env, now=t)
        return s

    def _refresh_universe(self, *, env: dict | None, now: float) -> None:
        stale = _f(STALE_ENV, env)
        k = int(_f(TOP_K_ENV, env))
        buffer_ = int(_f(BUFFER_ENV, env))
        with self._lock:
            fresh = {c: s for c, (s, t) in self._scores.items() if now - t <= stale}
            ranked = sorted(fresh.items(), key=lambda kv: kv[1], reverse=True)
            top_k = {c for c, _ in ranked[:k]}
            top_k_buf = {c for c, _ in ranked[: k + buffer_]}
            # hystérésis : entre si top-K ; ne sort que s'il quitte top-(K+buffer)
            self._universe = (self._universe & top_k_buf) | top_k

    def allowed(self, coin: str, env: dict | None = None) -> bool | None:
        """True/False si le marché est noté ; None si jamais noté (ne bloque pas)."""
        key = (coin or "").strip().upper()
        with self._lock:
            if key not in self._scores:
                return None
            return key in self._universe

    def status(self) -> dict:
        with self._lock:
            return {
                "scored_markets": len(self._scores),
                "universe_size": len(self._universe),
                "universe": sorted(self._universe),
                "read_only": True,
            }

    def clear(self) -> None:
        with self._lock:
            self._scores.clear()
            self._universe.clear()


DEFAULT_MARKET_QUALITY_BOOK = MarketQualityBook()

__all__ = [
    "MASTER_FLAG", "REASON_MQ", "flag_on", "quality_score",
    "MarketQualityBook", "DEFAULT_MARKET_QUALITY_BOOK",
]
