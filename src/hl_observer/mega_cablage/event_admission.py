"""[CABLAGE étage A] EVENT ADMISSION : porte d'intégrité à l'ingestion. Un événement live/replay normalisé
(shape de collection.userfills_live.parser_message_userfills : {coin, px, sz, signe, ts_ms, ...}) n'entre dans
le pipeline que s'il passe les VRAIES portes d'intégrité déjà écrites :
  - data_contract.adapter_conformance_suite : price>0, qty>0, side connu, ts>0 ;
  - data_contract.timestamp_unit_validator : pas de confusion s/ms/µs/ns (optionnel) ;
  - feed_integrity.crossed_book_quarantine : si un carnet accompagne l'événement, best_bid ≤ best_ask.
Toute violation → REFUSE (fail-closed) : l'événement ne produit AUCUNE intention. 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

from hl_observer.data_contract.adapter_conformance_suite import verifier_conformite
from hl_observer.data_contract.timestamp_unit_validator import valider as valider_unite_ts
from hl_observer.feed_integrity.crossed_book_quarantine import verifier as verifier_carnet

ADMIS = "ADMIS"
REFUSE = "REFUSE"


def _side_depuis_signe(signe: Any) -> Any:
    if isinstance(signe, (int, float)) and not isinstance(signe, bool):
        if signe > 0:
            return "BUY"
        if signe < 0:
            return "SELL"
    return None


def admettre(evenement: Any, *, verifier_unite: bool = True, unite_ts: str = "ms") -> dict[str, Any]:
    """Retourne {admis, etat, raison, canonique?}. `canonique` = {price, qty, side, ts} pour l'aval. Toute porte
    qui échoue → admis=False + raison (aucun fill fabriqué en aval). verifier_unite peut être désactivé pour un
    replay indexé par des ts non-epoch."""
    if not isinstance(evenement, dict):
        return {"admis": False, "etat": REFUSE, "raison": "EVENEMENT_INVALIDE"}
    side = _side_depuis_signe(evenement.get("signe"))
    canonique = {"price": evenement.get("px"), "qty": evenement.get("sz"),
                 "side": side, "ts": evenement.get("ts_ms")}
    conf = verifier_conformite(canonique)
    if not conf.get("conforme"):
        return {"admis": False, "etat": REFUSE, "raison": "NON_CONFORME", "violations": conf.get("violations")}
    if verifier_unite:
        tsv = valider_unite_ts(evenement.get("ts_ms"), unite_attendue=unite_ts)
        if not tsv.get("conforme"):
            return {"admis": False, "etat": REFUSE, "raison": "TIMESTAMP_UNITE",
                    "detail": tsv.get("raison"), "unite_detectee": tsv.get("unite_detectee")}
    book = evenement.get("book")
    if isinstance(book, dict) and book.get("bids") and book.get("asks"):
        try:
            best_bid = float(book["bids"][0][0])
            best_ask = float(book["asks"][0][0])
        except (TypeError, ValueError, IndexError):
            return {"admis": False, "etat": REFUSE, "raison": "CARNET_ILLISIBLE"}
        cb = verifier_carnet(best_bid, best_ask)
        if cb.get("etat") != "EXPLOITABLE":
            return {"admis": False, "etat": REFUSE, "raison": "CARNET_%s" % cb.get("etat"),
                    "detail": cb.get("raison")}
    return {"admis": True, "etat": ADMIS, "canonique": canonique, "side": side}


__all__ = ["admettre", "ADMIS", "REFUSE"]
