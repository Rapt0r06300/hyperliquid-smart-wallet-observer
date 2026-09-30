"""PORTEFEUILLE CARRY (idées #19/#20) — récolter le funding au niveau PANIER : tenir TOUS les
carries à net positif, sizés en risk-parity (inverse-vol), pour beaucoup de petites ouvertures
propres au lieu de 5 grosses. Rotation rapide vers les meilleurs spikes. Pur, deny-by-default.
PAPER only, aucun ordre.
"""
from __future__ import annotations

COUT_ROTATION_BPS = 22.0     # round-trip : on ne churne pas pour moins que ça (hysteresis)


def poids_risk_parity(carries: list[dict]) -> dict[str, float]:
    """Poids ~ 1/vol (risk-parity) normalisés à 1. Vol absente/nulle -> poids égal. `carries` =
    [{coin, vol}, ...] avec vol = mesure de risque (ex. pire-hausse). Panier vide -> {}."""
    valides = [c for c in carries if c.get("coin")]
    if not valides:
        return {}
    bruts = {}
    for c in valides:
        vol = c.get("vol")
        bruts[str(c["coin"])] = (1.0 / float(vol)) if isinstance(vol, (int, float)) and float(vol) > 0 else 1.0
    tot = sum(bruts.values())
    return {k: round(v / tot, 6) for k, v in bruts.items()} if tot > 0 else {}


def allouer_portefeuille(carries: list[dict], capital_total_usd: float, *, max_slots: int = 12) -> dict[str, float]:
    """Répartit le capital sur les carries NET POSITIF, en risk-parity, cappé à max_slots (les
    meilleurs nets d'abord). Renvoie {coin: capital_usd}. On n'alloue QU'aux net>0 (barre pas baissée)."""
    positifs = [c for c in carries if c.get("coin") and float(c.get("gain_net_bps") or 0.0) > 0.0]
    positifs.sort(key=lambda c: -float(c.get("gain_net_bps") or 0.0))
    retenus = positifs[: max(0, int(max_slots))]
    poids = poids_risk_parity(retenus)
    cap = max(0.0, float(capital_total_usd))
    return {coin: round(cap * w, 2) for coin, w in poids.items()}


def rotation_justifiee(gain_actuel_bps: float, gain_candidat_bps: float, *,
                       cout_rotation_bps: float = COUT_ROTATION_BPS) -> bool:
    """#19 : ne tourner vers un nouveau carry que si le gain SUPPLÉMENTAIRE dépasse le coût de
    rotation (hysteresis) — sinon on churne pour rien."""
    return (float(gain_candidat_bps) - float(gain_actuel_bps)) > float(cout_rotation_bps)


__all__ = ["poids_risk_parity", "allouer_portefeuille", "rotation_justifiee", "COUT_ROTATION_BPS"]
