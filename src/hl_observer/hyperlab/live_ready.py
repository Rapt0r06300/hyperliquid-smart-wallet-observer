"""[Bloc 13-14 / AUD-276, AUD-320] Gate LIVE_READY.

Principe NON negociable : `OFFLINE_READY` (un adaptateur + des tests offline existent) ne vaut JAMAIS
`LIVE_READY`. Une venue n'est LIVE_READY que si une PREUVE runtime existe pour les 6 criteres :
  connexion etablie, messages recus, fraicheur (last_useful_event_ts recent), sequences sans trou non
  resolu, stockage Bronze effectif, parite replay verifiee.
Sans preuve (cas d'un sandbox sans reseau) -> not ready, avec la liste EXACTE des criteres manquants.
On ne declare jamais live sur la seule presence d'un adaptateur. stdlib pure, 0 reseau, deterministe.
"""
from __future__ import annotations

from typing import Mapping, Optional, Sequence

CRITERES = ("connexion", "messages", "fraicheur", "sequences", "stockage", "replay")


class PreuveLive:
    """Preuve runtime collectee pour une venue. Tous les defauts sont 'absents' : rien n'est suppose."""

    def __init__(self, venue: str, *, connexion: bool = False, n_messages: int = 0,
                 last_useful_event_ts: Optional[float] = None, sequences_ok: bool = False,
                 bronze_lignes_ecrites: int = 0, replay_parite: bool = False) -> None:
        self.venue = venue
        self.connexion = bool(connexion)
        self.n_messages = int(n_messages)
        self.last_useful_event_ts = last_useful_event_ts
        self.sequences_ok = bool(sequences_ok)
        self.bronze_lignes_ecrites = int(bronze_lignes_ecrites)
        self.replay_parite = bool(replay_parite)


def offline_ready_implique_live_ready() -> bool:
    """Invariant explicite : NON. La presence d'un adaptateur offline n'implique jamais le live."""
    return False


def evaluer_live_ready(preuve: PreuveLive, *, maintenant: float, seuil_fraicheur_s: float,
                       min_messages: int = 1) -> dict:
    """Retourne {venue, live_ready, manquants:[criteres]}. live_ready=True SEULEMENT si les 6 criteres
    sont prouves. Chaque critere manquant est nomme (jamais masque)."""
    manquants = []
    if not preuve.connexion:
        manquants.append("connexion")
    if preuve.n_messages < min_messages:
        manquants.append("messages")
    ts = preuve.last_useful_event_ts
    if ts is None or (maintenant - float(ts)) > seuil_fraicheur_s:
        manquants.append("fraicheur")
    if not preuve.sequences_ok:
        manquants.append("sequences")
    if preuve.bronze_lignes_ecrites <= 0:
        manquants.append("stockage")
    if not preuve.replay_parite:
        manquants.append("replay")
    return {"venue": preuve.venue, "live_ready": not manquants, "manquants": manquants}


def venues_live_ready(preuves: Sequence[PreuveLive], *, maintenant: float, seuil_fraicheur_s: float,
                      requises: Sequence[str] = ()) -> dict:
    """Agrege l'etat LIVE_READY multi-venue. ready_global=True seulement si toutes les venues REQUISES
    sont live_ready. Corrige AUD-276/320 : OFFLINE_READY != LIVE_READY."""
    details = {p.venue: evaluer_live_ready(p, maintenant=maintenant, seuil_fraicheur_s=seuil_fraicheur_s)
               for p in preuves}
    req = set(requises)
    requises_non_pretes = sorted(v for v in req if not details.get(v, {}).get("live_ready", False))
    if req:
        ready_global = len(requises_non_pretes) == 0
    else:
        ready_global = bool(details) and all(d["live_ready"] for d in details.values())
    return {"ready_global": ready_global,
            "requises_non_pretes": requises_non_pretes,
            "live_ready": sorted(v for v, d in details.items() if d["live_ready"]),
            "details": details}
