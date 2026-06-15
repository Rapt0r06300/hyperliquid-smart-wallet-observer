"""
Analyse de marche dYdX v4 pour filtrer les mauvais signaux paper.

Ce module est volontairement pur: aucun reseau, aucun ordre, aucune cle.
Il transforme des candles publiques en contexte exploitable par le moteur:
tendance 5m/1h, regime, ATR relatif et multiplicateur d'edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field


TREND_UP = "UP"
TREND_DOWN = "DOWN"
TREND_FLAT = "FLAT"
TREND_UNKNOWN = "UNKNOWN"

REGIME_TRENDING = "TRENDING"
REGIME_RANGING = "RANGING"
REGIME_CHOPPY = "CHOPPY"
REGIME_UNKNOWN = "UNKNOWN"

VOLUME_SPIKE = "VOLUME_SPIKE"


@dataclass(frozen=True)
class CandlePoint:
    """Candle OHLCV minimale normalisee."""

    started_at: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class MarketContext:
    """Contexte de marche lu par les gates paper-only."""

    market_id: str
    trend_5m: str = TREND_UNKNOWN
    trend_1h: str = TREND_UNKNOWN
    regime: str = REGIME_UNKNOWN
    atr: float = 0.0
    atr_pct: float = 0.0
    efficiency_ratio: float = 0.0
    volume_zscore: float = 0.0
    edge_multiplier: float = 1.0
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return self.confidence > 0.0


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_candles(raw: list[dict] | dict | None) -> list[CandlePoint]:
    """Normaliser les candles Indexer en ordre chronologique."""
    if isinstance(raw, dict):
        rows = raw.get("candles", [])
    else:
        rows = raw or []

    candles: list[CandlePoint] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        close = _to_float(item.get("close"))
        high = _to_float(item.get("high"), close)
        low = _to_float(item.get("low"), close)
        open_ = _to_float(item.get("open"), close)
        if close <= 0 or high <= 0 or low <= 0:
            continue
        volume = _to_float(
            item.get("baseTokenVolume")
            or item.get("usdVolume")
            or item.get("volume")
            or item.get("trades"),
            0.0,
        )
        candles.append(
            CandlePoint(
                started_at=str(item.get("startedAt") or item.get("createdAt") or ""),
                open=open_,
                high=max(high, low, close),
                low=min(high, low, close),
                close=close,
                volume=max(0.0, volume),
            )
        )

    candles.sort(key=lambda c: c.started_at)
    return candles


def _trend(candles: list[CandlePoint], min_move_pct: float) -> str:
    if len(candles) < 3:
        return TREND_UNKNOWN
    first = candles[0].close
    last = candles[-1].close
    if first <= 0:
        return TREND_UNKNOWN
    move_pct = (last - first) / first
    if move_pct >= min_move_pct:
        return TREND_UP
    if move_pct <= -min_move_pct:
        return TREND_DOWN
    return TREND_FLAT


def _atr(candles: list[CandlePoint], period: int) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs: list[float] = []
    prev_close = candles[0].close
    for c in candles[1:]:
        tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        trs.append(tr)
        prev_close = c.close
    recent = trs[-period:]
    return sum(recent) / len(recent) if recent else 0.0


def _efficiency_ratio(candles: list[CandlePoint]) -> float:
    if len(candles) < 3:
        return 0.0
    net = abs(candles[-1].close - candles[0].close)
    path = 0.0
    for i in range(1, len(candles)):
        path += abs(candles[i].close - candles[i - 1].close)
    if path <= 0:
        return 0.0
    return max(0.0, min(1.0, net / path))


def _volume_zscore(candles: list[CandlePoint], lookback: int = 30) -> float:
    if len(candles) < 5:
        return 0.0
    vols = [c.volume for c in candles[-lookback:] if c.volume > 0]
    if len(vols) < 5:
        return 0.0
    latest = vols[-1]
    hist = vols[:-1]
    mean = sum(hist) / len(hist)
    var = sum((v - mean) ** 2 for v in hist) / len(hist)
    if var <= 0:
        if mean > 0 and latest >= mean * 1.5:
            return 10.0
        return 0.0
    return (latest - mean) / (var ** 0.5)


def side_opposes_trend(side: str, ctx: MarketContext) -> bool:
    """True si la tendance 5m ET 1h contredit le cote du signal."""
    side_u = side.upper()
    if side_u == "LONG":
        return ctx.trend_5m == TREND_DOWN and ctx.trend_1h == TREND_DOWN
    if side_u == "SHORT":
        return ctx.trend_5m == TREND_UP and ctx.trend_1h == TREND_UP
    return True


def is_volume_spike(
    ctx: MarketContext,
    imbalance: float,
    *,
    min_zscore: float = 2.0,
    min_imbalance: float = 0.62,
) -> bool:
    """True si volume anormal ET flux franchement desequilibre."""
    return ctx.volume_zscore >= min_zscore and abs(imbalance) >= min_imbalance


def correlation_group(market_id: str) -> str:
    """
    Groupe de correlation grossier pour gate d'exposition paper.

    Le but n'est pas de modeliser finement les correlations, mais d'eviter
    d'empiler plusieurs longs/shorts tres proches quand le marche crypto bouge
    en bloc. UNKNOWN revient au marche lui-meme pour ne pas surbloquer.
    """
    base = market_id.split("-")[0].upper()
    if base in {"BTC", "ETH"}:
        return "MAJORS"
    if base in {"SOL", "AVAX", "SUI", "APT", "NEAR", "TIA", "LINK"}:
        return "HIGH_BETA_L1"
    if base in {"ARB", "OP"}:
        return "L2_BETA"
    if base in {"DOGE", "WLD"}:
        return "HIGH_BETA_SPEC"
    return market_id.upper()


def analyze_market_context(
    market_id: str,
    candles_5m_raw: list[dict] | dict | None,
    candles_1h_raw: list[dict] | dict | None,
    *,
    atr_period: int = 14,
    trend_min_move_pct: float = 0.0015,
    choppy_efficiency_max: float = 0.18,
    choppy_atr_pct_min: float = 0.001,
) -> MarketContext:
    """Construire le contexte marche depuis candles 5m et 1h publiques."""
    c5 = normalize_candles(candles_5m_raw)
    c1h = normalize_candles(candles_1h_raw)
    primary = c5 if len(c5) >= atr_period + 1 else c1h

    trend_5m = _trend(c5, trend_min_move_pct)
    trend_1h = _trend(c1h, trend_min_move_pct)
    atr = _atr(primary, atr_period)
    last_close = primary[-1].close if primary else 0.0
    atr_pct = atr / last_close if last_close > 0 else 0.0
    efficiency = _efficiency_ratio(primary)
    z = _volume_zscore(c5 or c1h)

    notes: list[str] = [
        f"trend_5m={trend_5m}",
        f"trend_1h={trend_1h}",
        f"atr_pct={atr_pct:.4f}",
        f"efficiency={efficiency:.2f}",
        f"volume_z={z:.2f}",
    ]

    if not primary:
        return MarketContext(market_id=market_id, notes=["NO_CANDLES"])

    if efficiency <= choppy_efficiency_max and atr_pct >= choppy_atr_pct_min:
        regime = REGIME_CHOPPY
        multiplier = 0.0
    elif efficiency >= 0.45 and trend_5m == trend_1h and trend_5m in (TREND_UP, TREND_DOWN):
        regime = REGIME_TRENDING
        multiplier = 1.12
    elif atr_pct < choppy_atr_pct_min:
        regime = REGIME_RANGING
        multiplier = 0.90
    else:
        regime = REGIME_RANGING
        multiplier = 1.0

    if trend_5m == trend_1h and trend_5m in (TREND_UP, TREND_DOWN):
        multiplier *= 1.05
    elif TREND_UNKNOWN not in (trend_5m, trend_1h) and trend_5m != trend_1h:
        multiplier *= 0.85

    confidence = min(1.0, (len(c5) + len(c1h)) / 80.0)
    return MarketContext(
        market_id=market_id,
        trend_5m=trend_5m,
        trend_1h=trend_1h,
        regime=regime,
        atr=atr,
        atr_pct=atr_pct,
        efficiency_ratio=efficiency,
        volume_zscore=z,
        edge_multiplier=max(0.0, multiplier),
        confidence=confidence,
        notes=notes,
    )
