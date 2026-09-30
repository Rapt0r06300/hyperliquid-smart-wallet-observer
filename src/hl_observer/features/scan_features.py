"""V9 / S4 §2.1 — Vecteur de features de scan riche (style polyrec, 70+ colonnes).

Construit, pour un coin/signal, un vecteur de features dérivé UNIQUEMENT des données
réelles fournies (séries de prix, trades récents, carnet, âge du fill). Toute donnée
absente reste `None` (jamais fabriquée) et fait baisser la `quality`. read-only / paper-only.

Sert le scoring, le logging et le backtest. Ce n'est pas un ordre ni une recommandation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from math import sqrt

from hl_observer.features.scan_features_schema import SCAN_FEATURE_WINDOWS

WINDOWS = SCAN_FEATURE_WINDOWS


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _ret(prices: list[float], w: int) -> float | None:
    if len(prices) <= w or prices[-1 - w] == 0:
        return None
    return (prices[-1] / prices[-1 - w]) - 1.0


def _realized_vol(prices: list[float], w: int) -> float | None:
    seg = prices[-(w + 1):]
    if len(seg) < 3:
        return None
    rets = [(seg[i] / seg[i - 1]) - 1.0 for i in range(1, len(seg)) if seg[i - 1]]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return sqrt(var)


def _range_bps(prices: list[float], w: int) -> float | None:
    seg = prices[-(w + 1):]
    if len(seg) < 2:
        return None
    hi, lo = max(seg), min(seg)
    ref = seg[-1] or 1.0
    return (hi - lo) / ref * 10_000.0


@dataclass(frozen=True, slots=True)
class ScanFeatures:
    coin: str
    schema_version: str = "hl_observer.scan_features.v12"
    feature_hash: str = ""
    ts_ms: int | None = None
    age_ms: int | None = None
    is_fresh: bool | None = None
    freshness_score: float | None = None
    mid: float | None = None
    leader_price: float | None = None
    microprice: float | None = None
    spread_bps: float | None = None
    microprice_dev_bps: float | None = None
    bid_depth_usdc: float | None = None
    ask_depth_usdc: float | None = None
    depth_total_usdc: float | None = None
    depth_imbalance: float | None = None
    vwap: float | None = None
    vwap_dev_bps: float | None = None
    cvd: float | None = None
    cvd_norm: float | None = None
    buy_vol: float | None = None
    sell_vol: float | None = None
    n_trades: int | None = None
    trade_flow_imbalance: float | None = None
    rvol: float | None = None
    leader_notional_usdc: float | None = None
    leader_score: float | None = None
    consensus_wallets: int | None = None
    windowed: dict[str, float | None] = field(default_factory=dict)
    quality: str = "BAD"
    missing_count: int = 0
    read_only: bool = True
    execution: str = "forbidden"

    def to_row(self) -> dict[str, object]:
        row: dict[str, object] = {
            k: getattr(self, k)
            for k in (
                "coin", "schema_version", "feature_hash", "ts_ms", "age_ms", "is_fresh", "freshness_score", "mid", "leader_price",
                "microprice", "spread_bps", "microprice_dev_bps", "bid_depth_usdc", "ask_depth_usdc",
                "depth_total_usdc", "depth_imbalance", "vwap", "vwap_dev_bps", "cvd", "cvd_norm",
                "buy_vol", "sell_vol", "n_trades", "trade_flow_imbalance", "rvol",
                "leader_notional_usdc", "leader_score", "consensus_wallets", "quality",
                "missing_count", "read_only", "execution",
            )
        }
        row.update(self.windowed)
        return row


def build_scan_features(
    *,
    coin: str,
    now_ms: int | None = None,
    fill_ts_ms: int | None = None,
    max_signal_age_ms: int = 30_000,
    mid: float | None = None,
    leader_price: float | None = None,
    best_bid: float | None = None,
    best_ask: float | None = None,
    bid_depth_usdc: float | None = None,
    ask_depth_usdc: float | None = None,
    recent_prices: list[float] | None = None,
    recent_trades: list[tuple[float, float]] | None = None,  # (price, signed_size)
    volume_window_usdc: float | None = None,
    avg_volume_usdc: float | None = None,
    leader_notional_usdc: float | None = None,
    leader_score: float | None = None,
    consensus_wallets: int | None = None,
) -> ScanFeatures:
    prices = [float(p) for p in (recent_prices or []) if p is not None]
    trades = recent_trades or []

    age_ms = None
    is_fresh = None
    freshness_score = None
    if now_ms is not None and fill_ts_ms is not None:
        age_ms = max(0, int(now_ms) - int(fill_ts_ms))
        is_fresh = age_ms <= max(0, int(max_signal_age_ms))
        freshness_score = round(_clamp(1.0 - age_ms / max(1, int(max_signal_age_ms))), 6)

    # carnet
    spread_bps = microprice = microprice_dev_bps = None
    if best_bid and best_ask and best_bid > 0 and best_ask > 0:
        mref = (best_bid + best_ask) / 2.0
        spread_bps = (best_ask - best_bid) / mref * 10_000.0
        if bid_depth_usdc is not None and ask_depth_usdc is not None and (bid_depth_usdc + ask_depth_usdc) > 0:
            microprice = (best_ask * bid_depth_usdc + best_bid * ask_depth_usdc) / (bid_depth_usdc + ask_depth_usdc)
            microprice_dev_bps = (microprice - mref) / mref * 10_000.0
    depth_total = None
    depth_imbalance = None
    if bid_depth_usdc is not None and ask_depth_usdc is not None:
        depth_total = float(bid_depth_usdc) + float(ask_depth_usdc)
        if depth_total > 0:
            depth_imbalance = (float(bid_depth_usdc) - float(ask_depth_usdc)) / depth_total

    # trades -> cvd, vwap, flow
    vwap = vwap_dev_bps = cvd = cvd_norm = None
    buy_vol = sell_vol = None
    trade_flow = None
    n_trades = len(trades) if trades else None
    if trades:
        notional = sum(abs(sz) * px for px, sz in trades)
        vol = sum(abs(sz) for _, sz in trades)
        if vol > 0:
            vwap = notional / vol
            ref = mid or (prices[-1] if prices else None)
            if ref:
                vwap_dev_bps = (ref - vwap) / vwap * 10_000.0
        buy_vol = sum(sz for _, sz in trades if sz > 0)
        sell_vol = -sum(sz for _, sz in trades if sz < 0)
        cvd = buy_vol - sell_vol
        if (buy_vol + sell_vol) > 0:
            cvd_norm = cvd / (buy_vol + sell_vol)
            trade_flow = cvd_norm

    rvol = None
    if volume_window_usdc is not None and avg_volume_usdc:
        rvol = float(volume_window_usdc) / float(avg_volume_usdc)

    # fenêtres : returns, vol réalisée, momentum, range
    windowed: dict[str, float | None] = {}
    for w in WINDOWS:
        windowed[f"ret_{w}"] = _ret(prices, w) if prices else None
        windowed[f"vol_{w}"] = _realized_vol(prices, w) if prices else None
        windowed[f"range_bps_{w}"] = _range_bps(prices, w) if prices else None
        windowed[f"lag_px_{w}"] = prices[-1 - w] if (prices and len(prices) > w) else None

    # qualité = part des champs principaux disponibles
    core = [age_ms, mid, spread_bps, depth_imbalance, vwap, cvd, windowed.get("ret_5"), windowed.get("vol_15")]
    available = sum(1 for v in core if v is not None)
    missing = len(core) - available
    if available >= 7:
        quality = "OK"
    elif available >= 4:
        quality = "DEGRADED"
    else:
        quality = "BAD"

    windowed = {key: (round(value, 10) if isinstance(value, float) else value) for key, value in windowed.items()}
    feature_hash = _stable_feature_hash(
        {
            "coin": str(coin or "").upper(),
            "ts_ms": int(fill_ts_ms) if fill_ts_ms is not None else None,
            "age_ms": age_ms,
            "mid": mid,
            "leader_price": leader_price,
            "spread_bps": round(spread_bps, 6) if spread_bps is not None else None,
            "depth_imbalance": round(depth_imbalance, 6) if depth_imbalance is not None else None,
            "vwap": round(vwap, 8) if vwap is not None else None,
            "cvd_norm": round(cvd_norm, 6) if cvd_norm is not None else None,
            "rvol": round(rvol, 6) if rvol is not None else None,
            "leader_score": leader_score,
            "consensus_wallets": consensus_wallets,
            "windowed": windowed,
            "quality": quality,
        }
    )

    return ScanFeatures(
        coin=str(coin or "").upper(),
        feature_hash=feature_hash,
        ts_ms=int(fill_ts_ms) if fill_ts_ms is not None else None,
        age_ms=age_ms,
        is_fresh=is_fresh,
        freshness_score=freshness_score,
        mid=mid,
        leader_price=leader_price,
        microprice=microprice,
        spread_bps=round(spread_bps, 6) if spread_bps is not None else None,
        microprice_dev_bps=round(microprice_dev_bps, 6) if microprice_dev_bps is not None else None,
        bid_depth_usdc=bid_depth_usdc,
        ask_depth_usdc=ask_depth_usdc,
        depth_total_usdc=depth_total,
        depth_imbalance=round(depth_imbalance, 6) if depth_imbalance is not None else None,
        vwap=round(vwap, 8) if vwap is not None else None,
        vwap_dev_bps=round(vwap_dev_bps, 6) if vwap_dev_bps is not None else None,
        cvd=round(cvd, 8) if cvd is not None else None,
        cvd_norm=round(cvd_norm, 6) if cvd_norm is not None else None,
        buy_vol=buy_vol,
        sell_vol=sell_vol,
        n_trades=n_trades,
        trade_flow_imbalance=round(trade_flow, 6) if trade_flow is not None else None,
        rvol=round(rvol, 6) if rvol is not None else None,
        leader_notional_usdc=leader_notional_usdc,
        leader_score=leader_score,
        consensus_wallets=consensus_wallets,
        windowed=windowed,
        quality=quality,
        missing_count=missing,
    )


def _stable_feature_hash(payload: dict[str, object]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "feat:" + sha256(material.encode("utf-8")).hexdigest()


__all__ = ["WINDOWS", "ScanFeatures", "build_scan_features"]
