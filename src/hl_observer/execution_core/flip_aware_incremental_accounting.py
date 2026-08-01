"""[ALL #91] FLIP-AWARE INCREMENTAL ACCOUNTING : un trade qui DÉPASSE la taille de la position en cours ferme
d'abord toute la position (réalisant son PnL au bon prix moyen), PUIS ouvre le côté inverse avec le reliquat au prix
du trade. Comptabilité incrémentale (type orchestrateur Hummingbot) : réalisé, quantité fermée et quantité ouverte
sont séparés. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"
_TOL = 1e-12


def appliquer_trade(position_avant: Any, prix_moyen_avant: Any, trade_qte_signee: Any,
                    trade_prix: Any) -> dict[str, Any]:
    """Applique un trade signé à (position, prix moyen). Gère l'ajout, la réduction et le FLIP.
    Retourne position/prix moyen après, PnL réalisé, quantités fermée et ouverte. Entrées invalides → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (position_avant, prix_moyen_avant, trade_qte_signee, trade_prix)):
        return {"position_apres": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    pos = float(position_avant)
    avg = float(prix_moyen_avant)
    q = float(trade_qte_signee)
    px = float(trade_prix)
    realized = 0.0
    closed = 0.0
    opened = 0.0
    if abs(pos) <= _TOL or (pos > 0 and q > 0) or (pos < 0 and q < 0):
        # même sens (ou position nulle) : on AJOUTE, le prix moyen se pondère
        nouvelle = pos + q
        opened = abs(q)
        avg_apres = ((abs(pos) * avg) + (abs(q) * px)) / abs(nouvelle) if abs(nouvelle) > _TOL else 0.0
        return {"position_apres": round(nouvelle, 12), "prix_moyen_apres": round(avg_apres, 10),
                "realized_pnl": 0.0, "closed_qty": 0.0, "opened_qty": round(opened, 12), "flip": False}
    # sens opposés : on réduit / ferme / flippe
    signe_pos = 1.0 if pos > 0 else -1.0
    qte_fermable = min(abs(q), abs(pos))
    closed = qte_fermable
    realized = qte_fermable * (px - avg) * signe_pos     # PnL réalisé sur la partie fermée
    reste = abs(q) - abs(pos)
    if reste <= _TOL:
        # simple réduction (ou fermeture exacte) : prix moyen inchangé
        nouvelle = pos + q
        avg_apres = avg if abs(nouvelle) > _TOL else 0.0
        return {"position_apres": round(nouvelle, 12), "prix_moyen_apres": round(avg_apres, 10),
                "realized_pnl": round(realized, 10), "closed_qty": round(closed, 12), "opened_qty": 0.0,
                "flip": False}
    # FLIP : position fermée entièrement, reliquat ouvre le côté inverse au prix du trade
    opened = reste
    nouvelle = -signe_pos * reste
    return {"position_apres": round(nouvelle, 12), "prix_moyen_apres": round(px, 10),
            "realized_pnl": round(realized, 10), "closed_qty": round(closed, 12),
            "opened_qty": round(opened, 12), "flip": True}


__all__ = ["appliquer_trade", "UNMEASURABLE"]
