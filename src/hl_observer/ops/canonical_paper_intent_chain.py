"""AUD-110 / AUD-111 — chaine UNIFIEE : chaque famille active -> PaperIntent CANONIQUE -> executeur.

Le repo avait trois representations d'intent. Ce module fixe UN point d'unification : toute famille
active passe par le PaperIntent CANONIQUE (ops.paper_canonique), converti en ORDRE paper puis en
enregistrement de FILL/ledger. Prouve la chaine de bout en bout pour les 3 familles actives.
Paper only : real_execution=False partout, aucun ordre reel.
"""
from __future__ import annotations

import hashlib
from typing import Any

from hl_observer.ops.paper_canonique import STRATEGIES_ACTIVES, PaperIntent


def intent_canonique(*, strategy: str, coin: str, side: int, notional_usd: float,
                     signal_observable_at_ms: int = 1, **kw: Any) -> PaperIntent:
    """Point d'unification UNIQUE : construit LE PaperIntent canonique (valide le scope actif)."""
    options = dict(kw)
    if not options.get("intent_id"):
        seed = "%s|%s|%s|%s|%s|%s|%s" % (
            strategy,
            str(coin).upper(),
            int(side),
            float(notional_usd),
            int(signal_observable_at_ms),
            options.get("venue", "HL"),
            options.get("cohort", "STRICT"),
        )
        options["intent_id"] = "paper-intent:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]
    return PaperIntent(strategy=strategy, coin=coin, side=side, notional_usd=notional_usd,
                       signal_observable_at_ms=signal_observable_at_ms, **options)


def intent_vers_ordre_paper(intent: PaperIntent) -> dict:
    """PaperIntent canonique -> ORDRE paper (dict connecteur). real_execution TOUJOURS False."""
    d = intent.as_dict()
    order_seed = "%s|%s|%s|%s|%s" % (
        d["strategy"], d["coin"], d["side"], d["notional_usd"], d["signal_observable_at_ms"]
    )
    return {"order_id": "paper-order:" + hashlib.sha256(order_seed.encode("utf-8")).hexdigest()[:20],
            "intent_id": d["intent_id"],
            "coin": d["coin"], "side": d["side"], "notional_usd": d["notional_usd"],
            "strategy": d["strategy"], "venue": d["venue"], "cohort": d.get("cohort", "STRICT"),
            "signal_observable_at_ms": d["signal_observable_at_ms"],
            "paper_only": True, "real_execution": False}


def ordre_vers_fill_ledger(ordre: dict, *, prix: float) -> dict:
    """ORDRE paper -> enregistrement de FILL pour le ledger (paper)."""
    position_seed = "%s|%s|%s" % (ordre["order_id"], ordre["coin"], ordre["side"])
    position_id = "paper-position:" + hashlib.sha256(position_seed.encode("utf-8")).hexdigest()[:20]
    return {"fill_id": "paper-fill:" + ordre["order_id"].split(":", 1)[-1],
            "intent_id": ordre["intent_id"], "order_id": ordre["order_id"], "position_id": position_id,
            "coin": ordre["coin"], "side": ordre["side"], "prix": float(prix),
            "notional_usd": ordre["notional_usd"], "strategy": ordre["strategy"],
            "cohort": ordre.get("cohort", "STRICT"),
            "signal_observable_at_ms": ordre.get("signal_observable_at_ms"),
            "type": "FILL", "real_execution": False}


def fill_vers_position_ledger_open(fill: dict, *, lane: str = "MAIN") -> tuple[dict, dict]:
    """PaperFill -> position paper -> evenement OPEN, sans aucune voie d'execution externe."""
    size = float(fill["notional_usd"]) / float(fill["prix"])
    position = {
        "position_id": fill["position_id"],
        "strategy": fill["strategy"],
        "lane": str(lane).upper(),
        "coin": fill["coin"],
        "side": fill["side"],
        "size": size,
        "entry_price": float(fill["prix"]),
        "paper_only": True,
        "real_execution": False,
    }
    ledger_open = {
        "kind": "OPEN",
        "intent_id": fill["intent_id"],
        "order_id": fill["order_id"],
        "position_id": fill["position_id"],
        "fill_id": fill["fill_id"],
        "strategy": fill["strategy"],
        "lane": str(lane).upper(),
        "coin": fill["coin"],
        "side": fill["side"],
        "size": size,
        "entry_price": float(fill["prix"]),
        "real_execution": False,
    }
    return position, ledger_open


def chaine_famille(strategy: str, *, coin: str = "BTC", side: int = 1, notional_usd: float = 50.0,
                   prix: float = 60000.0) -> dict:
    """Chaine complete pour UNE famille : intent canonique -> ordre -> fill/ledger."""
    intent = intent_canonique(strategy=strategy, coin=coin, side=side, notional_usd=notional_usd)
    ordre = intent_vers_ordre_paper(intent)
    fill = ordre_vers_fill_ledger(ordre, prix=prix)
    position, ledger_open = fill_vers_position_ledger_open(fill)
    return {"intent": intent.as_dict(), "ordre": ordre, "fill": fill,
            "position": position, "ledger_open": ledger_open}


__all__ = ["intent_canonique", "intent_vers_ordre_paper", "ordre_vers_fill_ledger",
           "fill_vers_position_ledger_open", "chaine_famille",
           "STRATEGIES_ACTIVES"]
