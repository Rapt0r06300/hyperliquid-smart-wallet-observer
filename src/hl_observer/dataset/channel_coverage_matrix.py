"""[DATA pépite 261] CHANNEL COVERAGE MATRIX : par coin, le pourcentage de temps réellement couvert pour
chaque channel (BBO / L2 / trades / fills), avec les trous précis. Un backtest « BTC » n'a pas la même valeur
si le L2 n'était présent que 40% du temps ; cette matrice rend cette réalité explicite au lieu de la masquer.
Les intervalles sont clippés à la fenêtre et fusionnés (pas de double comptage). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def _fusion_clip(intervalles: list, debut: float, fin: float) -> list[tuple[float, float]]:
    propres = []
    for iv in intervalles:
        try:
            d, f = float(iv[0]), float(iv[1])
        except (TypeError, ValueError, IndexError):
            continue
        d, f = max(d, debut), min(f, fin)
        if f > d:
            propres.append((d, f))
    propres.sort()
    fusionnes: list[tuple[float, float]] = []
    for d, f in propres:
        if fusionnes and d <= fusionnes[-1][1]:
            fusionnes[-1] = (fusionnes[-1][0], max(fusionnes[-1][1], f))
        else:
            fusionnes.append((d, f))
    return fusionnes


def construire(couvertures: dict[str, dict[str, list]], debut: float, fin: float) -> dict[str, Any]:
    """couvertures = {coin: {channel: [(debut,fin), ...]}}. Rend {coin: {channel: {pct, trous}}}. pct =
    durée couverte fusionnée / durée de la fenêtre. Fenêtre invalide → matrice vide (fail-closed)."""
    if fin <= debut:
        return {"matrice": {}, "raison": "FENETRE_INVALIDE"}
    span = float(fin) - float(debut)
    matrice: dict[str, Any] = {}
    for coin, channels in couvertures.items():
        matrice[coin] = {}
        for channel, intervalles in channels.items():
            fus = _fusion_clip(intervalles, float(debut), float(fin))
            couvert = sum(f - d for d, f in fus)
            trous = []
            curseur = float(debut)
            for d, f in fus:
                if d > curseur:
                    trous.append((round(curseur, 6), round(d, 6)))
                curseur = f
            if curseur < fin:
                trous.append((round(curseur, 6), round(float(fin), 6)))
            matrice[coin][channel] = {"pct": round(couvert / span, 6), "trous": trous}
    return {"matrice": matrice, "span": round(span, 6)}


__all__ = ["construire"]
