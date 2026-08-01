"""[CABLAGE étage B] COPY STAGE : un fill leader admis devient une INTENTION de copie mise à l'échelle de NOTRE
equity (jamais 1:1 avec un leader qui a 100× notre capital). On compose la VRAIE primitive
copy_vault.equity_ratio_replication.taille_paper, puis on exprime l'intention en NOTIONAL USD SIGNÉ
({module, venue, coin, montant_signe}) — le format commun attendu par le netting/self-trade/priorité de
execution_core. equity leader ≤ 0 / donnée invalide → refus honnête (aucune intention). 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

from hl_observer.copy_vault.equity_ratio_replication import taille_paper


def intent_copie(evenement: dict[str, Any], *, notre_equity: Any, leader_equity: Any,
                 venue: str = "HYPERLIQUID", module: str = "COPY") -> dict[str, Any]:
    """evenement = {coin, px, sz, signe}. Met la taille base du leader à l'échelle de notre equity, convertit en
    notional USD signé (signe du leader). Retourne {refuse, intent?, side?, qty?, prix?, notional?, raison?}."""
    coin = evenement.get("coin")
    px = evenement.get("px")
    sz = evenement.get("sz")
    signe = evenement.get("signe")
    if not coin or not isinstance(px, (int, float)) or px <= 0 or not isinstance(sz, (int, float)):
        return {"refuse": True, "raison": "EVENEMENT_INVALIDE"}
    if not isinstance(signe, (int, float)) or signe == 0:
        return {"refuse": True, "raison": "SENS_ABSENT"}
    r = taille_paper(sz, notre_equity=notre_equity, leader_equity=leader_equity)
    if r.get("refuse"):
        return {"refuse": True, "raison": r.get("raison")}
    notre_qty = float(r["taille"])
    notional = round(notre_qty * float(px), 8)
    montant_signe = round(notional * (1.0 if signe > 0 else -1.0), 8)
    intent = {"module": module, "venue": str(venue).upper(), "coin": str(coin).upper(),
              "montant_signe": montant_signe, "type": "PROFITABLE_ENTRY"}
    return {"refuse": False, "intent": intent, "side": "BUY" if signe > 0 else "SELL",
            "qty": round(notre_qty, 12), "prix": float(px), "ratio_equity": r.get("ratio_equity"),
            "notional": notional}


__all__ = ["intent_copie"]
