"""AUD-110 / AUD-111 — chaine UNIFIEE : chaque famille active -> PaperIntent CANONIQUE -> executeur.

Le repo avait trois representations d'intent. Ce module fixe UN point d'unification : toute famille
active passe par le PaperIntent CANONIQUE (ops.paper_canonique), converti en ORDRE paper puis en
enregistrement de FILL/ledger. Prouve la chaine de bout en bout pour les 3 familles actives.
Paper only : real_execution=False partout, aucun ordre reel.
"""
from __future__ import annotations

from typing import Any

from hl_observer.ops.paper_canonique import STRATEGIES_ACTIVES, PaperIntent


def intent_canonique(*, strategy: str, coin: str, side: int, notional_usd: float,
                     signal_observable_at_ms: int = 1, **kw: Any) -> PaperIntent:
    """Point d'unification UNIQUE : construit LE PaperIntent canonique (valide le scope actif)."""
    return PaperIntent(strategy=strategy, coin=coin, side=side, notional_usd=notional_usd,
                       signal_observable_at_ms=signal_observable_at_ms, **kw)


def intent_vers_ordre_paper(intent: PaperIntent) -> dict:
    """PaperIntent canonique -> ORDRE paper (dict connecteur). real_execution TOUJOURS False."""
    d = intent.as_dict()
    return {"coin": d["coin"], "side": d["side"], "notional_usd": d["notional_usd"],
            "strategy": d["strategy"], "venue": d["venue"], "paper_only": True, "real_execution": False}


def ordre_vers_fill_ledger(ordre: dict, *, prix: float) -> dict:
    """ORDRE paper -> enregistrement de FILL pour le ledger (paper)."""
    return {"coin": ordre["coin"], "side": ordre["side"], "prix": float(prix),
            "notional_usd": ordre["notional_usd"], "strategy": ordre["strategy"],
            "type": "FILL", "real_execution": False}


def chaine_famille(strategy: str, *, coin: str = "BTC", side: int = 1, notional_usd: float = 50.0,
                   prix: float = 60000.0) -> dict:
    """Chaine complete pour UNE famille : intent canonique -> ordre -> fill/ledger."""
    intent = intent_canonique(strategy=strategy, coin=coin, side=side, notional_usd=notional_usd)
    ordre = intent_vers_ordre_paper(intent)
    fill = ordre_vers_fill_ledger(ordre, prix=prix)
    return {"intent": intent.as_dict(), "ordre": ordre, "fill": fill}


__all__ = ["intent_canonique", "intent_vers_ordre_paper", "ordre_vers_fill_ledger", "chaine_famille",
           "STRATEGIES_ACTIVES"]
