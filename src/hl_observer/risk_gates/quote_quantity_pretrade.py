"""[RISK lot2 #91] QUOTE-QUANTITY PRETRADE VALIDATION : si une taille est exprimée en QUOTE (USD) plutôt qu'en BASE,
le contrôle de risque doit utiliser le VRAI notional APRÈS conversion, pas confondre les deux unités. Le bug (corrigé
dans Nautilus) : une taille en quote était traitée comme une taille en base, sous-évaluant ou sur-évaluant le risque.
Prix requis pour convertir une taille base ; manquant → refus. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"
QUOTE = "QUOTE"
BASE = "BASE"


def notional_reel(taille: Any, *, unite: str, prix: Any = None) -> dict[str, Any]:
    """Notional USD réel : si la taille est en QUOTE, le notional EST la taille ; si en BASE, notional = taille×prix
    (prix requis). Unité inconnue ou données invalides → UNMEASURABLE (jamais confondre base et quote)."""
    if not isinstance(taille, (int, float)):
        return {"notional": UNMEASURABLE, "raison": "TAILLE_INVALIDE"}
    u = str(unite).upper()
    if u == QUOTE:
        return {"notional": round(abs(float(taille)), 8), "unite": QUOTE}
    if u == BASE:
        if not isinstance(prix, (int, float)) or float(prix) <= 0:
            return {"notional": UNMEASURABLE, "raison": "PRIX_REQUIS_POUR_TAILLE_BASE"}
        return {"notional": round(abs(float(taille)) * float(prix), 8), "unite": BASE}
    return {"notional": UNMEASURABLE, "raison": "UNITE_INCONNUE"}


def valider(taille: Any, *, unite: str, prix: Any = None, notional_max: float) -> dict[str, Any]:
    """Valide que le notional RÉEL ≤ notional_max. Notional non mesurable → refus (fail-closed)."""
    r = notional_reel(taille, unite=unite, prix=prix)
    if r["notional"] == UNMEASURABLE:
        return {"ok": False, "raison": r["raison"]}
    ok = r["notional"] <= float(notional_max)
    return {"ok": bool(ok), "notional": r["notional"], "notional_max": float(notional_max),
            "raison": ("OK" if ok else "NOTIONAL_DEPASSE_LIMITE")}


__all__ = ["notional_reel", "valider", "QUOTE", "BASE", "UNMEASURABLE"]
