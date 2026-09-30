"""Étiquetage pour ML de trading — pur, testé. triple_barrier_labels (IDEA-24) et meta_labels
(IDEA-25). No-lookahead : chaque label n'utilise que le futur PROPRE au trade (barrières). Aucun ordre.
"""
from __future__ import annotations


def triple_barrier_labels(prices, entries, *, tp_bps: float, sl_bps: float, horizon: int) -> list:
    """Pour chaque indice d'entrée : +1 si le take-profit est touché en premier, -1 si le stop-loss
    est touché en premier, 0 si l'horizon est atteint sans toucher de barrière."""
    px = [float(p) for p in prices]
    out = []
    for i in entries:
        entry = px[i]
        up = entry * (1.0 + tp_bps / 10000.0)
        dn = entry * (1.0 - sl_bps / 10000.0)
        label = 0
        for j in range(i + 1, min(len(px), i + 1 + horizon)):
            if px[j] >= up:
                label = 1
                break
            if px[j] <= dn:
                label = -1
                break
        out.append(label)
    return out


def meta_labels(realized_pnl) -> list:
    """Meta-labeling : à partir du PnL réalisé de chaque signal primaire, 1 = agir (aurait été
    gagnant), 0 = passer. Un 2e modèle apprend ensuite QUAND suivre le signal primaire."""
    return [1 if float(p) > 0 else 0 for p in realized_pnl]
