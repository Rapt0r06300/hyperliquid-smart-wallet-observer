"""[ARB lot2 #4] BATCH-CANCEL IMMÉDIAT DES QUOTES D'UN SPREAD INVALIDE : quand un spread devient invalide (une
jambe a bougé, le carnet s'est dérobé), TOUTES les quotes qui en dépendent doivent être annulées EN BATCH, d'un
coup, pas une par une (fenêtre pendant laquelle on reste exposé). Nautilus supporte le batch cancel sur certaines
venues. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class RegistreQuotes:
    """Associe des quotes à leur spread d'origine ; `invalider_spread` renvoie le lot complet à annuler d'un coup."""

    def __init__(self) -> None:
        self._par_spread: dict[str, list[str]] = {}

    def enregistrer(self, spread_id: str, quote_id: str) -> None:
        self._par_spread.setdefault(str(spread_id), []).append(str(quote_id))

    def invalider_spread(self, spread_id: str) -> dict[str, Any]:
        """Renvoie toutes les quotes du spread à annuler en batch et les retire du registre (annulation atomique)."""
        quotes = self._par_spread.pop(str(spread_id), [])
        return {"spread_id": str(spread_id), "a_annuler": list(quotes), "n": len(quotes),
                "batch": True, "raison": ("SPREAD_INVALIDE" if quotes else "AUCUNE_QUOTE")}


__all__ = ["RegistreQuotes"]
