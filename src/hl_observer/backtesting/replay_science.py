"""SCIENCE DU REPLAY (bloc A : idées #4/#5/#9) — juger un PnL de replay HONNÊTEMENT : est-il
distinct de zéro (bootstrap), tient-il dans TOUS les régimes, et d'où vient-il. Pur, descriptif.
Ne PROMET rien. PAPER only, aucun ordre. (Sharpe dégonflé / CV purgée existent déjà : F27 / #1.)
"""
from __future__ import annotations

import random


def bootstrap_ic_pnl(pnls, *, n_reechantillons: int = 1000, niveau: float = 0.95, seed: int = 1) -> dict:
    """#4 : intervalle de confiance bootstrap sur le PnL MOYEN. `distinct_de_zero` = l'IC ne
    contient pas 0 (le PnL est crédiblement non nul). Série vide/1 point -> non concluant."""
    xs = [float(x) for x in (pnls or []) if isinstance(x, (int, float))]
    if len(xs) < 2:
        return {"moyenne": (xs[0] if xs else 0.0), "ic_bas": None, "ic_haut": None,
                "distinct_de_zero": False, "n": len(xs)}
    rng = random.Random(seed)
    moyennes = []
    for _ in range(int(n_reechantillons)):
        ech = [xs[rng.randrange(len(xs))] for _ in range(len(xs))]
        moyennes.append(sum(ech) / len(ech))
    moyennes.sort()
    a = (1.0 - float(niveau)) / 2.0
    bas = moyennes[int(a * len(moyennes))]
    haut = moyennes[min(len(moyennes) - 1, int((1.0 - a) * len(moyennes)))]
    return {"moyenne": round(sum(xs) / len(xs), 6), "ic_bas": round(bas, 6), "ic_haut": round(haut, 6),
            "distinct_de_zero": (bas > 0.0 or haut < 0.0), "n": len(xs)}


def segmenter_par_regime(trades, cle_regime: str = "regime") -> dict:
    """#5 : {régime: [pnl,...]}. Un edge qui ne tient que dans UN régime est fragile."""
    out: dict = {}
    for t in trades or []:
        if not isinstance(t, dict):
            continue
        out.setdefault(str(t.get(cle_regime) or "INCONNU"), []).append(float(t.get("pnl") or 0.0))
    return out


def attribution(trades, cle: str = "coin") -> dict:
    """#9 : somme du PnL par clé (coin/heure/stratégie) -> d'où vient réellement le PnL, triée."""
    agg: dict = {}
    for t in trades or []:
        if isinstance(t, dict):
            agg[str(t.get(cle) or "?")] = round(agg.get(str(t.get(cle) or "?"), 0.0) + float(t.get("pnl") or 0.0), 6)
    return dict(sorted(agg.items(), key=lambda kv: -kv[1]))


__all__ = ["bootstrap_ic_pnl", "segmenter_par_regime", "attribution"]
