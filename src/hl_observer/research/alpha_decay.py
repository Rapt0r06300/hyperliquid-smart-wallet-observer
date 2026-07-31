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

from collections.abc import Mapping
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


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


def no_trade(signal_age_ms: float, courbe: Mapping[str, Any]) -> bool:
    """True si l'âge du signal dépasse le break-even (signal mort) → NO_TRADE."""
    m = courbe.get("max_signal_age_ms")
    if not isinstance(m, (int, float)):
        return True                                   # inconnu -> prudence : NO_TRADE
    return signal_age_ms > m


__all__ = ["courbe_decay", "no_trade", "UNMEASURABLE"]
