"""[MEMOIRE item 6] Budget RAM AUTOMATIQUE et BORNE — jamais « illimité par défaut ».

Le replay/fusion/backtest chargeait une FENETRE d'événements dont le plafond valait 0 = illimité :
sur un gros jeu de données, la RAM explosait. Ici, un plafond `<= 0` ne veut plus dire « tout charger »
mais « calcule un budget AUTOMATIQUE borné » à partir de la RAM disponible (psutil si présent, sinon un
défaut conservateur), avec un plancher et un plafond durs. Quelle que soit la taille des données, la
fenêtre en mémoire reste bornée. Un plafond explicite (> 0) est toujours respecté.

Pur, 0 réseau, testable partout (psutil et la RAM dispo sont injectables).
"""
from __future__ import annotations

# Hypothèses volontairement CONSERVATRICES : un événement normalisé (dict jsonl) coûte ~1 Ko une fois
# désérialisé en Python (clés + valeurs + surcoût objet). On ne remplit qu'une FRACTION de la RAM libre.
OCTETS_PAR_EVENT = 1024
FRACTION_RAM = 0.25
MINI_EVENTS = 50_000            # jamais moins : un replay a besoin d'un minimum pour être utile
MAXI_EVENTS = 5_000_000         # jamais plus : garde-fou dur même sur une grosse machine
DEFAUT_RAM_DISPO_MO = 2048      # si la RAM dispo est indéterminable : on suppose 2 Go (prudent)


def memoire_disponible_octets(*, psutil_mod=None, defaut_mo: int = DEFAUT_RAM_DISPO_MO) -> int:
    """RAM disponible en octets (psutil si présent, sinon un défaut conservateur). Jamais 0."""
    mod = psutil_mod
    if mod is None:
        try:
            import psutil as mod  # type: ignore
        except Exception:  # noqa: BLE001 — psutil optionnel
            mod = None
    if mod is not None:
        try:
            dispo = int(mod.virtual_memory().available)
            if dispo > 0:
                return dispo
        except Exception:  # noqa: BLE001
            pass
    return int(defaut_mo) * 1024 * 1024


def budget_events(*, fraction: float = FRACTION_RAM, octets_par_event: int = OCTETS_PAR_EVENT,
                  mini: int = MINI_EVENTS, maxi: int = MAXI_EVENTS,
                  dispo_octets: int | None = None, psutil_mod=None) -> int:
    """Nombre MAX d'événements en RAM, borné [mini, maxi]. Toujours > 0 (jamais illimité)."""
    dispo = dispo_octets if dispo_octets is not None else memoire_disponible_octets(psutil_mod=psutil_mod)
    brut = int((dispo * max(0.0, fraction)) / max(1, octets_par_event))
    return max(mini, min(maxi, brut))


def resoudre_max_events(demande: int, *, dispo_octets: int | None = None, psutil_mod=None,
                        mini: int = MINI_EVENTS, maxi: int = MAXI_EVENTS) -> int:
    """Résout le plafond d'événements EN MEMOIRE. `demande > 0` => respecté (borné par maxi). `demande
    <= 0` => budget AUTOMATIQUE borné (jamais illimité). Le résultat est toujours dans [mini, maxi]."""
    if demande and demande > 0:
        return max(1, min(int(demande), maxi))
    return budget_events(dispo_octets=dispo_octets, psutil_mod=psutil_mod, mini=mini, maxi=maxi)


__all__ = ["OCTETS_PAR_EVENT", "FRACTION_RAM", "MINI_EVENTS", "MAXI_EVENTS",
           "memoire_disponible_octets", "budget_events", "resoudre_max_events"]
