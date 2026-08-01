"""[ARB #49] PER-LEG SHORTFALL : mesurer, SÉPARÉMENT pour la jambe A et la jambe B, l'écart entre le prix
réellement obtenu et le prix exécutable ATTENDU (implementation shortfall par jambe). Agréger les deux jambes
masquerait quelle venue dégrade l'arb. Un shortfall positif = défavorable (coût). Prix manquant → UNMEASURABLE.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"
_ACHAT = ("ACHAT", "BUY", "LONG", "B", "1", "+1")
_VENTE = ("VENTE", "SELL", "SHORT", "S", "-1")


def shortfall_bps(prix_reel: Any, prix_attendu: Any, sens: Any) -> Any:
    """Shortfall d'une jambe en bps, orienté « coût » : à l'achat, payer plus cher est positif ; à la vente,
    recevoir moins est positif. Prix invalide ou sens inconnu → UNMEASURABLE (jamais 0 supposé)."""
    if not all(isinstance(x, (int, float)) for x in (prix_reel, prix_attendu)) or float(prix_attendu) <= 0:
        return UNMEASURABLE
    s = str(sens).upper()
    if s in _ACHAT:
        signe = 1.0
    elif s in _VENTE:
        signe = -1.0
    else:
        return UNMEASURABLE
    return round(signe * (float(prix_reel) - float(prix_attendu)) / float(prix_attendu) * 1e4, 4)


def shortfall_episode(jambe_a: dict[str, Any], jambe_b: dict[str, Any]) -> dict[str, Any]:
    """Shortfall par jambe + total. Chaque jambe = {prix_reel, prix_attendu, sens}. Une jambe non mesurable
    rend le total UNMEASURABLE (on ne somme jamais un coût partiel comme s'il était complet)."""
    sa = shortfall_bps(jambe_a.get("prix_reel"), jambe_a.get("prix_attendu"), jambe_a.get("sens"))
    sb = shortfall_bps(jambe_b.get("prix_reel"), jambe_b.get("prix_attendu"), jambe_b.get("sens"))
    if sa == UNMEASURABLE or sb == UNMEASURABLE:
        total = UNMEASURABLE
    else:
        total = round(sa + sb, 4)
    return {"shortfall_a_bps": sa, "shortfall_b_bps": sb, "shortfall_total_bps": total}


__all__ = ["shortfall_bps", "shortfall_episode", "UNMEASURABLE"]
