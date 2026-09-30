"""RISQUE PORTEFEUILLE (bloc E : idées #34/#35) — netting inter-stratégies et capacité. Pur.
PAPER only, aucun ordre. (VaR/CVaR M1, ciblage vol M2, contribution marginale mean-variance N1
existent déjà : ici on ajoute le NETTING et la CAPACITÉ, qui manquaient.)
"""
from __future__ import annotations


def exposition_nette(positions_par_strategie: dict) -> dict:
    """#34 : exposition NETTE par coin en sommant les stratégies (carry long HYPE + liquidation
    short HYPE se compensent). `positions_par_strategie` = {strat: {coin: notional_signé}}."""
    net: dict = {}
    for _strat, positions in (positions_par_strategie or {}).items():
        for coin, notl in (positions or {}).items():
            if isinstance(notl, (int, float)):
                net[str(coin).upper()] = round(net.get(str(coin).upper(), 0.0) + float(notl), 6)
    return net


def capacite_max_usd(profondeur_carnet_usd: float | None, *, impact_max_bps: float = 20.0,
                     pente_impact_bps_par_usd: float | None = None) -> float | None:
    """#35 : capital MAX déployable avant que l'impact dépasse impact_max_bps. Sans mesure d'impact
    -> None (on ne devine pas la capacité). Modèle simple : impact ≈ pente × notional."""
    if profondeur_carnet_usd is None or float(profondeur_carnet_usd) <= 0:
        return None
    if pente_impact_bps_par_usd and float(pente_impact_bps_par_usd) > 0:
        return round(float(impact_max_bps) / float(pente_impact_bps_par_usd), 2)
    # repli : une fraction prudente de la profondeur (l'impact croît avec la part du carnet consommée)
    return round(float(profondeur_carnet_usd) * (float(impact_max_bps) / 100.0) * 0.1, 2)


__all__ = ["exposition_nette", "capacite_max_usd"]
