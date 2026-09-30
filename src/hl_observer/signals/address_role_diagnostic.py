"""AUD-116 — diagnostic adresse AGENT / MASTER / SUBACCOUNT.

Sur Hyperliquid, une adresse observee peut etre le MASTER (compte principal, porte les positions),
un AGENT WALLET (cle API qui agit POUR le master mais adresse DISTINCTE, ne porte pas de position),
ou un SUBACCOUNT (compte separe). Les confondre = observer le mauvais etat (ex: lire les fills de
l'agent au lieu des positions du master). Ce diagnostic classe une adresse observee et signale un
mismatch avec le role attendu. Read-only, aucune cle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ROLE_MASTER = "MASTER"
ROLE_AGENT = "AGENT_WALLET"
ROLE_SUBACCOUNT = "SUBACCOUNT"
ROLE_INCONNU = "INCONNU"


def _norm(a: Any) -> str:
    return str(a or "").strip().lower()


@dataclass(frozen=True)
class CarteAdresses:
    master: str
    agents: frozenset = field(default_factory=frozenset)
    subaccounts: frozenset = field(default_factory=frozenset)


def classer_adresse(observee: Any, carte: CarteAdresses) -> str:
    o = _norm(observee)
    if not o:
        return ROLE_INCONNU
    if o == _norm(carte.master):
        return ROLE_MASTER
    if o in {_norm(x) for x in carte.agents}:
        return ROLE_AGENT
    if o in {_norm(x) for x in carte.subaccounts}:
        return ROLE_SUBACCOUNT
    return ROLE_INCONNU


def diagnostic_adresse(observee: Any, carte: CarteAdresses, *, role_attendu: str = ROLE_MASTER) -> dict:
    role = classer_adresse(observee, carte)
    ok = role == role_attendu
    if role == ROLE_INCONNU:
        raison = "ADRESSE_INCONNUE (ni master, ni agent, ni subaccount connu)"
    elif not ok:
        raison = ("MISMATCH: %s observe, %s attendu (ex: on lit l'agent au lieu du master)"
                  % (role, role_attendu))
    else:
        raison = "OK"
    return {"role": role, "attendu": role_attendu, "ok": ok, "raison": raison, "observee": _norm(observee)}


__all__ = ["CarteAdresses", "classer_adresse", "diagnostic_adresse",
           "ROLE_MASTER", "ROLE_AGENT", "ROLE_SUBACCOUNT", "ROLE_INCONNU"]
