"""ALPHA P32 — courbes de DÉCROISSANCE d'alpha : half_life, max_signal_age, break_even_latency.

Pour chaque famille de signal, l'edge net décroît avec l'âge du signal (0/50/100/250/500ms, 1/2/5/10/30s).
On mesure :
  * `half_life_alpha` — âge où le net tombe à la moitié de son pic ;
  * `break_even_latency` — âge où le net exécutable croise 0 (au-delà, NO_TRADE) ;
  * `max_signal_age` — âge max exploitable = break-even (borne dure).

Au-delà de `max_signal_age` : **NO_TRADE** (le signal est mort, on ne le paie pas).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"
AGES_MS_DEFAUT = (0, 50, 100, 250, 500, 1000, 2000, 5000, 10000, 30000)


def _interp_croisement(pts: list[tuple[float, float]], cible: float) -> float | None:
    """Premier âge (x croissant) où y descend au niveau `cible` (interpolation linéaire)."""
    for i in range(1, len(pts)):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        if (y0 - cible) >= 0 >= (y1 - cible) and y0 != y1:
            return round(x0 + (x1 - x0) * (y0 - cible) / (y0 - y1), 4)
    return None


def courbe_decay(net_par_age_ms: Mapping[float, Any]) -> dict[str, Any]:
    """Depuis {age_ms: net_bps}, calcule pic, half_life, break_even_latency (net=0), max_signal_age."""
    pts = sorted((float(a), float(v)) for a, v in net_par_age_ms.items()
                 if isinstance(v, (int, float)) and not isinstance(v, bool))
    if len(pts) < 2:
        return {"pic_bps": UNMEASURABLE, "age_pic_ms": UNMEASURABLE, "half_life_ms": UNMEASURABLE,
                "break_even_latency_ms": UNMEASURABLE, "max_signal_age_ms": UNMEASURABLE}
    age_pic, pic = max(pts, key=lambda p: p[1])
    apres = [p for p in pts if p[0] >= age_pic]
    half_life = _interp_croisement(apres, pic / 2.0) if pic > 0 else None
    break_even = _interp_croisement(apres, 0.0) if pic > 0 else None
    return {"pic_bps": round(pic, 4), "age_pic_ms": age_pic,
            "half_life_ms": (half_life if half_life is not None else UNMEASURABLE),
            "break_even_latency_ms": (break_even if break_even is not None else UNMEASURABLE),
            "max_signal_age_ms": (break_even if break_even is not None else UNMEASURABLE)}


def _prix_proche(serie: tuple[Sequence[int], Sequence[float]], t_cible: float, tol_ms: float) -> float | None:
    """Prix (mid) le plus proche de `t_cible` dans ±tol_ms, None sinon. Réutilise la logique 'closest' (FIX-16)."""
    ts_list, mid_list = serie
    if not ts_list:
        return None
    i = bisect.bisect_left(ts_list, t_cible)
    best_d: float | None = None
    best: float | None = None
    for j in (i - 1, i):
        if 0 <= j < len(ts_list):
            d = abs(float(ts_list[j]) - t_cible)
            if best_d is None or d < best_d:
                best_d, best = d, float(mid_list[j])
    if best is None or best_d is None or best_d > tol_ms:
        return None
    return best


def mesurer_decay_par_age(signaux: Sequence[Mapping[str, Any]], prix_par_coin: Mapping[str, Any], *,
                          ages_ms: Sequence[int] = AGES_MS_DEFAUT, holding_ms: int = 5000,
                          cout_bps: float = 9.0, tol_ms: float = 1000.0) -> dict[str, Any]:
    """FIX-39 — mesure la courbe de decay RÉELLE d'une famille : pour chaque signal (`ts_ms`, `coin`, `sens`),
    l'edge net si on ENTRE à `ts+age` et on SORT à `ts+age+holding_ms`, pour chaque `age`. Moyenne du net par
    âge → `courbe_decay` (half_life / break_even_latency / max_signal_age). `sens` = +1 long / −1 short.
    `prix_par_coin[coin]` = (liste_ts triée, liste_mid). Aucune donnée exploitable → courbe UNMEASURABLE."""
    nets: dict[int, list[float]] = {}
    for s in signaux:
        serie = prix_par_coin.get(s.get("coin"))
        if not serie or s.get("ts_ms") is None:
            continue
        ts = float(s["ts_ms"])
        sens = float(s.get("sens", 1.0))
        for age in ages_ms:
            p_in = _prix_proche(serie, ts + age, tol_ms)
            p_out = _prix_proche(serie, ts + age + holding_ms, tol_ms)
            if p_in is None or p_out is None or p_in <= 0:
                continue
            gross = sens * (p_out / p_in - 1.0) * 1e4
            nets.setdefault(int(age), []).append(gross - float(cout_bps))
    net_par_age = {age: sum(v) / len(v) for age, v in nets.items() if v}
    courbe = courbe_decay(net_par_age)
    return {"n_signaux": len(signaux), "holding_ms": holding_ms, "cout_bps": cout_bps,
            "net_par_age_ms": {a: round(n, 4) for a, n in sorted(net_par_age.items())}, **courbe}


def no_trade(signal_age_ms: float, courbe: Mapping[str, Any]) -> bool:
    """True si l'âge du signal dépasse le break-even (signal mort) → NO_TRADE."""
    m = courbe.get("max_signal_age_ms")
    if not isinstance(m, (int, float)):
        return True                                   # inconnu -> prudence : NO_TRADE
    return signal_age_ms > m


__all__ = ["courbe_decay", "mesurer_decay_par_age", "no_trade", "AGES_MS_DEFAUT", "UNMEASURABLE"]
