"""Calibration ALGORITHMIQUE des barrières SL/TP depuis la vraie volatilité + l'espérance.

Problème: des bps FIXES sont incohérents — la range 15 min d'un coin va de ~4 bps (ETH)
à ~135 bps (KAITO), un facteur 34×. Un SL fixe à 120 bps est 30× la range d'ETH (ne se
déclenche jamais) et ~1× celle de KAITO (trop serré). D'où des sorties au bruit.

Méthode (triple-barrier hummingbot + ATR-stop + espérance nette Kelly-friendly) :
  1. range réalisée d'un coin sur la fenêtre W :  r = (max−min)/last × 1e4  (bps).
  2. barrière = k × range  → exprimée en UNITÉS DE VOLATILITÉ du coin (s'adapte seule :
     coin calme ⇒ barrière serrée ; coin volatil ⇒ barrière large). Bornée par un clamp.
  3. ref_range = médiane robuste des ranges coins ⇒ le facteur vol ≈ 1 pour un coin typique
     (le moteur multiplie déjà la barrière de base par clamp(range/ref, fmin, fmax)).
  4. ESPÉRANCE nette par trade (bps) :  E = p·(TP−c) − (1−p)·(SL+c),  c = coût round-trip.
     On EXIGE E > 0 et on expose le winrate d'équilibre p* = (SL+c)/(TP+SL) : en dessous,
     le bracket perd de l'argent. Aucune promesse de PnL — juste la condition mathématique.

Pur, déterministe, lecture seule. Ne décide rien ; produit une reco calibrée + l'espérance.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass


def realized_range_bps(mids: list[float]) -> float | None:
    """Range réalisée (bps) d'une série de mids : (max−min)/dernier × 1e4."""
    xs = [float(m) for m in mids if m and float(m) > 0]
    if len(xs) < 2:
        return None
    lo, hi, last = min(xs), max(xs), xs[-1]
    if last <= 0:
        return None
    return (hi - lo) / last * 10_000.0


def per_coin_median_range_bps(marks: list[dict], *, window_s: float = 900.0,
                              min_obs: int = 5) -> dict[str, float]:
    """Médiane des ranges glissantes (fenêtre W) par coin, depuis des marks {ts,coin,mid}."""
    by: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for d in marks:
        try:
            by[str(d["coin"]).upper()].append((float(d["ts"]), float(d["mid"])))
        except (KeyError, TypeError, ValueError):
            continue
    out: dict[str, float] = {}
    for coin, series in by.items():
        series.sort()
        if len(series) < min_obs:
            continue
        ranges: list[float] = []
        for i in range(len(series)):
            t_end = series[i][0]
            win = [m for (t, m) in series if t_end - window_s <= t <= t_end]
            if len(win) >= min_obs:
                r = realized_range_bps(win)
                if r is not None:
                    ranges.append(r)
        if ranges:
            out[coin] = statistics.median(ranges)
    return out


def calibrate_ref_range_bps(marks: list[dict], *, window_s: float = 900.0,
                            fallback: float = 40.0, min_coins: int = 4) -> float:
    """ref_range robuste = médiane des ranges-coins (facteur vol ≈1 pour un coin typique).

    Retombe sur ``fallback`` si trop peu de coins ont assez d'observations (honnête :
    on ne calibre pas sur du vent).
    """
    ranges = per_coin_median_range_bps(marks, window_s=window_s)
    vals = sorted(ranges.values())
    if len(vals) < min_coins:
        return float(fallback)
    return round(float(statistics.median(vals)), 1)


def expectancy_bps(p_win: float, tp_bps: float, sl_bps: float, cost_bps: float) -> float:
    """Espérance nette par trade (bps) : E = p·(TP−c) − (1−p)·(SL+c)."""
    p = max(0.0, min(1.0, float(p_win)))
    return p * (tp_bps - cost_bps) - (1.0 - p) * (sl_bps + cost_bps)


def breakeven_winrate(tp_bps: float, sl_bps: float, cost_bps: float) -> float:
    """Winrate d'équilibre p* tel que E=0 : p* = (SL+c)/(TP+SL) (avec coût des deux côtés)."""
    denom = (tp_bps - cost_bps) + (sl_bps + cost_bps)
    if denom <= 0:
        return 1.0
    return (sl_bps + cost_bps) / denom


@dataclass(frozen=True, slots=True)
class BarrierRecommendation:
    ref_range_bps: float
    base_stop_loss_bps: float       # ×facteur vol → SL effectif par coin
    base_take_profit_bps: float
    base_trailing_bps: float
    base_trailing_activation_bps: float
    factor_min: float
    factor_max: float
    breakeven_winrate: float
    expectancy_bps_at_assumed: float
    assumed_winrate: float

    def env(self) -> dict[str, str]:
        """Variables launcher correspondantes (le moteur multiplie par le facteur vol)."""
        return {
            "HYPERSMART_V26_VOL_BARRIERS": "1",
            "HYPERSMART_V26_VOL_REF_RANGE_BPS": f"{self.ref_range_bps:g}",
            "HYPERSMART_V26_VOL_FACTOR_MIN": f"{self.factor_min:g}",
            "HYPERSMART_V26_VOL_FACTOR_MAX": f"{self.factor_max:g}",
            "HYPERSMART_SLTP_STOP_LOSS_BPS": f"{self.base_stop_loss_bps:g}",
            "HYPERSMART_SLTP_TAKE_PROFIT_BPS": f"{self.base_take_profit_bps:g}",
            "HYPERSMART_SLTP_TRAILING_BPS": f"{self.base_trailing_bps:g}",
            "HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS": f"{self.base_trailing_activation_bps:g}",
        }


def recommend_barriers(
    ref_range_bps: float, *,
    k_sl: float = 2.0, k_tp: float = 4.0, k_trail: float = 1.0, k_trail_act: float = 1.5,
    cost_bps: float = 12.0, assumed_winrate: float = 0.55,
    factor_min: float = 0.5, factor_max: float = 2.5,
) -> BarrierRecommendation:
    """Barrières de base = k × ref_range (⇒ k × range_coin après scaling vol), + espérance.

    k_sl≈2 (le coin doit bouger 2× sa range typique CONTRE nous pour couper → filtre le
    bruit), k_tp≈4 (R:R favorable 2:1 ; on laisse courir, le trailing verrouille). Le
    moteur applique ensuite ×clamp(range_coin/ref, fmin, fmax) par coin.
    """
    sl = round(k_sl * ref_range_bps, 1)
    tp = round(k_tp * ref_range_bps, 1)
    trail = round(k_trail * ref_range_bps, 1)
    trail_act = round(k_trail_act * ref_range_bps, 1)
    return BarrierRecommendation(
        ref_range_bps=round(ref_range_bps, 1),
        base_stop_loss_bps=sl, base_take_profit_bps=tp,
        base_trailing_bps=trail, base_trailing_activation_bps=trail_act,
        factor_min=factor_min, factor_max=factor_max,
        breakeven_winrate=round(breakeven_winrate(tp, sl, cost_bps), 4),
        expectancy_bps_at_assumed=round(expectancy_bps(assumed_winrate, tp, sl, cost_bps), 3),
        assumed_winrate=assumed_winrate,
    )


def calibrate_from_marks_file(path: str, **kw) -> BarrierRecommendation:
    marks = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            marks.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    ref = calibrate_ref_range_bps(marks)
    return recommend_barriers(ref, **kw)


__all__ = [
    "realized_range_bps", "per_coin_median_range_bps", "calibrate_ref_range_bps",
    "expectancy_bps", "breakeven_winrate", "BarrierRecommendation",
    "recommend_barriers", "calibrate_from_marks_file",
]
