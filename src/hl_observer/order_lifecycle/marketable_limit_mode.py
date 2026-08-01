"""[EXEC pépite 251] MARKETABLE-LIMIT MODE : utiliser un LIMIT agressif avec prix plafond/plancher plutôt qu'un
MARKET illimité quand la rapidité reste suffisante. Un marketable-limit croise le spread (donc se remplit vite) MAIS
borne le pire prix, évitant un sweep catastrophique. On calcule le prix limit marketable = meilleur opposé ± une
marge d'agressivité, borné par le collar. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def prix_marketable(meilleur_oppose: Any, sens: Any, *, agressivite_bps: float = 5.0,
                    collar_bps: float = 30.0) -> dict[str, Any]:
    """Prix limit marketable : achat = ask×(1+agressivite) mais plafonné à ask×(1+collar) ; vente = bid×(1−agr)
    planché à bid×(1−collar). Croise le spread (rempli vite) sans dépasser le collar. Prix invalide → UNMEASURABLE."""
    if not isinstance(meilleur_oppose, (int, float)) or float(meilleur_oppose) <= 0:
        return {"prix": UNMEASURABLE, "raison": "PRIX_INVALIDE"}
    s = str(sens).upper()
    agr = float(agressivite_bps) / 1e4
    col = float(collar_bps) / 1e4
    if s in ("ACHAT", "BUY", "LONG"):
        prix = min(float(meilleur_oppose) * (1.0 + agr), float(meilleur_oppose) * (1.0 + col))
        return {"prix": round(prix, 10), "sens": "ACHAT", "borne_collar": round(float(meilleur_oppose) * (1.0 + col), 10)}
    if s in ("VENTE", "SELL", "SHORT"):
        prix = max(float(meilleur_oppose) * (1.0 - agr), float(meilleur_oppose) * (1.0 - col))
        return {"prix": round(prix, 10), "sens": "VENTE", "borne_collar": round(float(meilleur_oppose) * (1.0 - col), 10)}
    return {"prix": UNMEASURABLE, "raison": "SENS_INCONNU"}


__all__ = ["prix_marketable", "UNMEASURABLE"]
