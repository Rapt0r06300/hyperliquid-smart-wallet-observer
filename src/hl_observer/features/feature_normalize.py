"""J2 + J3 — NORMALISATION roulante CAUSALE + OUTLIERS + MANQUANTS.

J2 : z-score sur fenêtre glissante n'utilisant QUE le passé+présent (jamais de stats globales =
lookahead). J3 : clamp des outliers à ±k·sigma (roulant) et comblage borné des trous. On ne
fabrique aucune donnée : trop de trous -> None. PAPER only.
"""
from __future__ import annotations

from typing import Sequence


def zscore_roulant(serie: Sequence[float], fenetre: int = 20) -> list[float | None]:
    """z_t = (x_t − moyenne(fenêtre causale)) / écart-type. None pendant le warmup (< 2 points)."""
    xs = list(serie or [])
    out: list[float | None] = []
    for i in range(len(xs)):
        deb = max(0, i - int(fenetre) + 1)
        w = [float(v) for v in xs[deb:i + 1] if isinstance(v, (int, float))]
        if len(w) < 2:
            out.append(None)
            continue
        m = sum(w) / len(w)
        sd = (sum((v - m) ** 2 for v in w) / len(w)) ** 0.5
        out.append(0.0 if sd <= 1e-12 else (float(xs[i]) - m) / sd)
    return out


def clamp_outliers(serie: Sequence[float], *, k_sigma: float = 4.0, fenetre: int = 50) -> list[float]:
    """Borne chaque point à moyenne ± k·sigma (fenêtre CAUSALE). Écrête les ticks aberrants sans les inventer."""
    xs = [float(v) for v in serie or []]
    out: list[float] = []
    for i in range(len(xs)):
        deb = max(0, i - int(fenetre))
        w = xs[deb:i]                                 # PASSÉ seul : le point courant ne contamine pas son bord
        if len(w) < 2:
            out.append(xs[i])                         # pas assez d'historique -> on garde tel quel
            continue
        m = sum(w) / len(w)
        sd = (sum((v - m) ** 2 for v in w) / len(w)) ** 0.5
        if sd <= 1e-12:
            out.append(xs[i])
        else:
            out.append(max(m - k_sigma * sd, min(xs[i], m + k_sigma * sd)))
    return out


def combler_manquants(serie: Sequence, *, max_trous_consecutifs: int = 3) -> list | None:
    """Forward-fill CAUSAL des None (dernière valeur connue). None global si > max trous consécutifs
    (données trop dégradées -> on NE devine pas)."""
    out: list = []
    dernier = None
    trous = 0
    for v in serie or []:
        if v is None:
            trous += 1
            if trous > int(max_trous_consecutifs):
                return None
            out.append(dernier)                    # peut rester None au tout début
        else:
            trous = 0
            dernier = v
            out.append(v)
    return out


__all__ = ["zscore_roulant", "clamp_outliers", "combler_manquants"]
