"""[DATA lot2 #32] VALIDATION STRICTE DES SEQUENCE NUMBERS : sur chaque feed qui les expose, on valide STRICTEMENT
les numéros de séquence : le suivant doit être exactement prev+1 (ou dans l'intervalle attendu). Tout saut (perte)
ou recul (rejeu/désordre) est signalé — on ne « laisse pas passer » un delta manquant. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

OK = "OK"
GAP = "GAP"
RECUL = "RECUL"


def valider(seq_precedent: Any, seq_recu: Any, *, pas: int = 1) -> dict[str, Any]:
    """Attendu = précédent + pas. Reçu > attendu → GAP (perte). Reçu < attendu → RECUL (rejeu/désordre).
    Séquence non entière → GAP présumé (prudence)."""
    if not all(isinstance(x, (int, float)) for x in (seq_precedent, seq_recu)):
        return {"etat": GAP, "raison": "SEQUENCE_INVALIDE"}
    attendu = int(seq_precedent) + int(pas)
    r = int(seq_recu)
    if r == attendu:
        return {"etat": OK, "attendu": attendu}
    if r > attendu:
        return {"etat": GAP, "manques": r - attendu, "attendu": attendu, "raison": "SAUT_DE_SEQUENCE"}
    return {"etat": RECUL, "attendu": attendu, "raison": "SEQUENCE_EN_ARRIERE"}


__all__ = ["valider", "OK", "GAP", "RECUL"]
