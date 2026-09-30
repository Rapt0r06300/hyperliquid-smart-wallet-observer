"""[AUD-318/319/322/323/324/385] Fiabilite des flux : LIVENESS != PROGRESSION des donnees, dernier
event UTILE par source, seuils STALE par stream, Dead Letter Queue, registre de MIGRATIONS de schema,
compteur d'evenements UTILES par consommateur. stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence


def liveness_vs_progression(*, socket_connecte: bool, dernier_event_ts: float | None,
                            maintenant: float, seuil_s: float = 60.0) -> dict:
    """Un socket CONNECTE mais muet n'est PAS vivant au sens utile : liveness (connexion) !=
    progression (donnees fraiches). On refuse de dire 'OK' sur une connexion silencieuse."""
    progresse = dernier_event_ts is not None and (maintenant - dernier_event_ts) <= seuil_s
    return {"connecte": socket_connecte, "progresse": progresse,
            "vivant_utile": bool(socket_connecte and progresse)}


def last_useful_event_ts(evenements: Sequence[Mapping], *, cle_utile: str = "utile") -> float | None:
    """Dernier horodatage d'un evenement UTILE (pas un heartbeat/keepalive) : un flux qui n'emet que
    des keepalives n'a pas progresse."""
    utiles = [e.get("ts") for e in evenements if e.get(cle_utile)]
    return max(utiles) if utiles else None


def seuils_stale_par_stream(streams: Mapping[str, float], seuils: Mapping[str, float], *,
                            maintenant: float, defaut_s: float = 60.0) -> dict:
    """Chaque stream a SON seuil de fraicheur (funding 8h vs orderbook 100ms). Rend les perimes."""
    perimes = [n for n, ts in streams.items() if (maintenant - ts) > seuils.get(n, defaut_s)]
    return {"tous_frais": len(perimes) == 0, "perimes": sorted(perimes)}


class DeadLetterQueue:
    """Les messages non traitables ne sont pas JETES en silence -> DLQ pour inspection (sinon une
    panne d'ingestion perd des donnees sans trace)."""

    def __init__(self) -> None:
        self._q: list = []

    def deposer(self, message, raison: str) -> None:
        self._q.append({"message": message, "raison": raison})

    def compter(self) -> int:
        return len(self._q)

    def vider(self) -> list:
        items = list(self._q)
        self._q.clear()
        return items


class RegistreMigrationsSchema:
    """Chaque changement de schema est VERSIONNE et applique dans l'ordre (pas de schema qui derive en
    silence entre deux versions du collecteur)."""

    def __init__(self) -> None:
        self._migrations: list = []

    def enregistrer(self, version: int, description: str) -> None:
        if any(m["version"] == version for m in self._migrations):
            raise ValueError("version %d deja enregistree" % version)
        self._migrations.append({"version": version, "description": description})
        self._migrations.sort(key=lambda m: m["version"])

    def version_courante(self) -> int:
        return self._migrations[-1]["version"] if self._migrations else 0

    def plan(self, depuis: int) -> list:
        return [m for m in self._migrations if m["version"] > depuis]


def compteur_evenements_utiles(consommateurs: Mapping[str, Sequence[Mapping]], *,
                               cle_utile: str = "utile") -> dict:
    """Compte les evenements UTILES consommes PAR CONSOMMATEUR : un consommateur a 0 evenement utile
    est mort/deconnecte, meme si le producteur emet."""
    par_conso = {nom: sum(1 for e in evs if e.get(cle_utile)) for nom, evs in consommateurs.items()}
    return {"par_consommateur": par_conso,
            "consommateurs_morts": sorted(n for n, c in par_conso.items() if c == 0)}
