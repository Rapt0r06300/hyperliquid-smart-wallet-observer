"""ALPHA P22 — CHALLENGER non-linéaire : baseline simple d'abord, non-linéaire SEULEMENT s'il ajoute du NET OOS.

On refuse les gros modèles opaques sans preuve. Baseline = seuil linéaire sur la feature. Challenger = binning
(non-linéaire peu profond) : direction apprise par bin sur la découverte, mesurée en OOS. On garde le
challenger uniquement si son net OOS dépasse la baseline. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def _split(feature: Sequence[float], target: Sequence[float], frac: float = 0.5):
    n = min(len(feature), len(target))
    c = int(n * frac)
    return (feature[:c], target[:c]), (feature[c:n], target[c:n])


def _net_baseline(dec, oos, *, cout_bps):
    # direction = signe(feature) (momentum), net OOS
    nets = [(1.0 if oos[0][i] > 0 else -1.0) * oos[1][i] - cout_bps for i in range(len(oos[0]))]
    return round(sum(nets) / len(nets), 4) if nets else None


def _net_binned(dec, oos, *, n_bins=5, cout_bps):
    fd, td = dec
    if len(fd) < n_bins * 4:
        return None
    ordre = sorted(range(len(fd)), key=lambda i: fd[i])
    bornes = [fd[ordre[int(q * len(fd))]] for q in [i / n_bins for i in range(1, n_bins)]]

    def bin_de(x):
        b = 0
        for br in bornes:
            if x > br:
                b += 1
        return b
    # direction apprise par bin sur la decouverte
    somdir: dict[int, float] = {}
    for i in range(len(fd)):
        somdir[bin_de(fd[i])] = somdir.get(bin_de(fd[i]), 0.0) + td[i]
    dir_bin = {b: (1.0 if s >= 0 else -1.0) for b, s in somdir.items()}
    fo, to = oos
    nets = [dir_bin.get(bin_de(fo[i]), 0.0) * to[i] - cout_bps for i in range(len(fo))]
    return round(sum(nets) / len(nets), 4) if nets else None


def challenger(feature: Sequence[float], target_bps: Sequence[float], *, cout_bps: float = 9.0,
               n_bins: int = 5) -> dict[str, Any]:
    """Compare baseline linéaire vs binned non-linéaire en OOS. Garde le challenger seulement si net OOS supérieur."""
    if min(len(feature), len(target_bps)) < 60:
        return {"verdict": "MORE_DATA", "n": min(len(feature), len(target_bps))}
    dec, oos = _split(feature, target_bps)
    base = _net_baseline(dec, oos, cout_bps=cout_bps)
    chal = _net_binned(dec, oos, n_bins=n_bins, cout_bps=cout_bps)
    if base is None or chal is None:
        return {"verdict": "MORE_DATA", "net_baseline": base, "net_challenger": chal}
    garde = chal > base
    return {"net_baseline_bps": base, "net_challenger_bps": chal, "increment_bps": round(chal - base, 4),
            "garder_challenger": garde, "verdict": ("CHALLENGER_UTILE" if garde else "BASELINE_SUFFIT")}


__all__ = ["challenger"]
