"""[EXEC pépite 223] GTD EXPIRY RECONCILIATION : l'expiration d'un ordre GTD est identifiée par la BONNE clé
(order/client/instrument) et réellement RÉPERCUTÉE dans le budget ET la position. Le bug (corrigé dans Nautilus) :
une expiration mal clée ne libérait pas le budget réservé ou laissait un ordre fantôme. On vérifie que l'expiration
cible le bon ordre et produit les effets attendus. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def reconcilier_expiration(*, order_id: Any, client_order_id: Any, instrument: Any,
                           budget_libere: Any, ordre_retire: Any) -> dict[str, Any]:
    """Une expiration GTD est correctement réconciliée si : la clé (order+client+instrument) est complète ET le
    budget réservé a été libéré ET l'ordre a été retiré des ordres actifs. Un seul manque → réconciliation
    incomplète (à corriger, pas à ignorer)."""
    cle_complete = all(x is not None and str(x) != "" for x in (order_id, client_order_id, instrument))
    manques = []
    if not cle_complete:
        manques.append("CLE_INCOMPLETE")
    if not bool(budget_libere):
        manques.append("BUDGET_NON_LIBERE")
    if not bool(ordre_retire):
        manques.append("ORDRE_NON_RETIRE")
    ok = not manques
    return {"reconcilie": bool(ok), "manques": manques,
            "raison": ("OK" if ok else "EXPIRATION_GTD_INCOMPLETE")}


__all__ = ["reconcilier_expiration"]
