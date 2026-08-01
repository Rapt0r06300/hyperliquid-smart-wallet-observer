"""[ARB pépite 233] HEDGE-FALLBACK PREVALIDATION : la route de secours doit être VALIDÉE (venue trading, liquidité
suffisante, état frais) AVANT d'autoriser l'ouverture de la PREMIÈRE jambe. Ouvrir la jambe 1 en supposant que le
secours marchera, puis découvrir qu'il ne marche pas, c'est se retrouver orphelin sans issue. Pas de secours valide
→ pas d'ouverture. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def peut_ouvrir_premiere_jambe(*, secours_venue_trading: Any, secours_liquidite_ok: Any,
                               secours_etat_frais: Any) -> dict[str, Any]:
    """Autorise l'ouverture de la jambe 1 seulement si les 3 conditions du secours sont explicitement vraies.
    Toute condition fausse/inconnue → refus (on ne s'engage pas sans plan B prouvé)."""
    conditions = {"venue_trading": bool(secours_venue_trading), "liquidite": bool(secours_liquidite_ok),
                  "etat_frais": bool(secours_etat_frais)}
    manques = [k for k, v in conditions.items() if not v]
    ok = not manques
    return {"peut_ouvrir": bool(ok), "secours_manques": manques,
            "raison": ("OK" if ok else "SECOURS_NON_VALIDE_AVANT_OUVERTURE")}


__all__ = ["peut_ouvrir_premiere_jambe"]
