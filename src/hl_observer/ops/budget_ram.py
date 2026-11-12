"""[MEMOIRE item 6] Budget RAM AUTOMATIQUE et BORNE — jamais « illimité par défaut ».

Le replay/fusion/backtest chargeait une FENETRE d'événements dont le plafond valait 0 = illimité :
sur un gros jeu de données, la RAM explosait. Ici, un plafond `<= 0` ne veut plus dire « tout charger »
mais « calcule un budget AUTOMATIQUE borné » à partir de la RAM disponible (psutil si présent, sinon un
défaut conservateur), avec un plancher et un plafond durs. Quelle que soit la taille des données, la
fenêtre en mémoire reste bornée. Un plafond explicite (> 0) est toujours respecté.

[M0 — GOUVERNEUR DE MEMOIRE, 2026-11-12] Deuxième couche, ADDITIVE : le budget d'événements ci-dessus
répond « combien je peux charger AU DEPART ». Il ne répond pas « suis-je en danger MAINTENANT ? », ni
« ai-je de quoi allouer ce bloc ? », ni « que faire si la RAM se resserre EN COURS de route ? ». Sans
cette couche, un module calcule un budget une fois puis se fait tuer par l'OS 20 minutes plus tard —
c'est exactement ce qui est arrivé deux fois au labo le 12/11 (16 Go demandés, 6 Go libres).

Le gouverneur publie un NIVEAU DE PRESSION (VERT / ORANGE / ROUGE) et une DECISION
(CONTINUER / RALENTIR / REDUIRE / PAUSER) que tout module lourd consulte AVANT d'allouer et
PENDANT une boucle longue. Principe non négociable : on RALENTIT ou on RETRECIT, on ne CRASHE JAMAIS.
Le gouverneur lui-même ne lève jamais d'exception (fail-open : en cas de doute il répond prudemment).

Pur, 0 réseau, testable partout (psutil, RAM dispo, horloge et sommeil sont tous injectables).
"""
from __future__ import annotations

import logging
import os

_LOG = logging.getLogger(__name__)

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
            import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
            _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
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


# ----------------------------------------------------------------------------------------------------
# M0 — GOUVERNEUR DE MEMOIRE : niveau de pression, décision, dégradation progressive
# ----------------------------------------------------------------------------------------------------

VERT = "VERT"
ORANGE = "ORANGE"
ROUGE = "ROUGE"

CONTINUER = "CONTINUER"     # rien à signaler, on travaille à pleine ampleur
RALENTIR = "RALENTIR"       # on souffle un peu (céder la main, vider les caches opportunistes)
REDUIRE = "REDUIRE"         # on rétrécit l'ampleur du lot (moitié / quart)
PAUSER = "PAUSER"           # on attend BRIEVEMENT que ça respire, puis on continue en mode dégradé

# DEUX critères, et c'est volontaire : on prend le PIRE des deux.
# - un seuil ABSOLU en Go : 3 Go libres est critique quelle que soit la machine ;
# - un seuil RELATIF : sur une machine de 128 Go, 6 Go libres (4,7 %) est critique aussi.
# Un seul des deux critères se trompe systématiquement sur l'autre classe de machine.
SEUIL_ORANGE_GO = 6.0
SEUIL_ROUGE_GO = 3.0
SEUIL_ORANGE_FRACTION = 0.25
SEUIL_ROUGE_FRACTION = 0.12

ENV_SEUIL_ORANGE_GO = "ALINA_RAM_SEUIL_ORANGE_GO"
ENV_SEUIL_ROUGE_GO = "ALINA_RAM_SEUIL_ROUGE_GO"

# Facteur d'ampleur appliqué à un lot selon le niveau : on rétrécit, on n'abandonne pas.
FACTEURS_AMPLEUR = {VERT: 1.0, ORANGE: 0.5, ROUGE: 0.25}

# Marge de sécurité sur une demande d'allocation : on exige 1,5x le besoin estimé, parce qu'une
# estimation de besoin mémoire est TOUJOURS optimiste (surcoût objet, fragmentation, pics transitoires).
MARGE_ALLOCATION = 1.5

# Attente bornée : on ne bloque JAMAIS indéfiniment un pipeline pour de la RAM.
ATTENTE_MAX_S = 30.0
ATTENTE_PAS_S = 1.0

_GO = float(1024 ** 3)


def _env_float(nom: str, defaut: float) -> float:
    """Lit un seuil depuis l'environnement. Valeur absente/illisible/<=0 => défaut (fail-open)."""
    brut = os.environ.get(nom)
    if not brut:
        return defaut
    try:
        val = float(str(brut).strip().replace(",", "."))
    except (TypeError, ValueError):
        _LOG.debug("seuil %s illisible (%r), defaut %s utilise", nom, brut, defaut)
        return defaut
    return val if val > 0 else defaut


def memoire_totale_octets(*, psutil_mod=None, defaut_mo: int = DEFAUT_RAM_DISPO_MO * 4) -> int:
    """RAM TOTALE en octets. Sert au critère relatif. Jamais 0 ; ne lève jamais."""
    mod = psutil_mod
    if mod is None:
        try:
            import psutil as mod  # type: ignore
        except Exception:  # noqa: BLE001
            mod = None
    if mod is not None:
        try:
            total = int(mod.virtual_memory().total)
            if total > 0:
                return total
        except Exception:  # noqa: BLE001
            _LOG.debug("lecture RAM totale impossible", exc_info=True)
    return int(defaut_mo) * 1024 * 1024


def memoire_du_processus_octets(*, psutil_mod=None) -> int:
    """RSS du processus courant : ce que NOUS tenons déjà. 0 si indéterminable. Ne lève jamais."""
    mod = psutil_mod
    if mod is None:
        try:
            import psutil as mod  # type: ignore
        except Exception:  # noqa: BLE001
            return 0
    try:
        return int(mod.Process().memory_info().rss)
    except Exception:  # noqa: BLE001
        _LOG.debug("lecture RSS impossible", exc_info=True)
        return 0


def niveau_pression(*, dispo_octets: int | None = None, total_octets: int | None = None,
                    psutil_mod=None) -> str:
    """VERT / ORANGE / ROUGE. Prend le PIRE du critère absolu (Go libres) et du critère relatif
    (fraction libre). Ne lève jamais : en cas de doute, renvoie le niveau le plus prudent connu."""
    dispo = dispo_octets if dispo_octets is not None else memoire_disponible_octets(psutil_mod=psutil_mod)
    total = total_octets if total_octets is not None else memoire_totale_octets(psutil_mod=psutil_mod)
    dispo_go = max(0.0, float(dispo)) / _GO
    fraction = (float(dispo) / float(total)) if total and total > 0 else 1.0

    seuil_rouge_go = _env_float(ENV_SEUIL_ROUGE_GO, SEUIL_ROUGE_GO)
    seuil_orange_go = _env_float(ENV_SEUIL_ORANGE_GO, SEUIL_ORANGE_GO)
    if seuil_orange_go < seuil_rouge_go:          # réglage incohérent => on garde l'ordre, prudemment
        seuil_orange_go = seuil_rouge_go

    if dispo_go <= seuil_rouge_go or fraction <= SEUIL_ROUGE_FRACTION:
        return ROUGE
    if dispo_go <= seuil_orange_go or fraction <= SEUIL_ORANGE_FRACTION:
        return ORANGE
    return VERT


def facteur_d_ampleur(niveau: str) -> float:
    """Fraction de l'ampleur nominale à conserver pour ce niveau. Niveau inconnu => le plus prudent."""
    return FACTEURS_AMPLEUR.get(str(niveau).upper(), FACTEURS_AMPLEUR[ROUGE])


def reduire_ampleur(valeur: int, *, niveau: str | None = None, mini: int = 1,
                    dispo_octets: int | None = None, total_octets: int | None = None,
                    psutil_mod=None) -> int:
    """Rétrécit un lot/une ampleur selon la pression. Reste toujours >= `mini` : on travaille en mode
    dégradé, on ne descend jamais à zéro (zéro = blocage déguisé, pire qu'une lenteur)."""
    niv = niveau or niveau_pression(dispo_octets=dispo_octets, total_octets=total_octets,
                                    psutil_mod=psutil_mod)
    try:
        base = int(valeur)
    except (TypeError, ValueError):
        return max(1, int(mini))
    if base <= 0:
        return max(1, int(mini))
    return max(max(1, int(mini)), int(base * facteur_d_ampleur(niv)))


def assez_de_memoire_pour(besoin_octets: int, *, marge: float = MARGE_ALLOCATION,
                          dispo_octets: int | None = None, psutil_mod=None) -> bool:
    """Y a-t-il de quoi allouer `besoin_octets` AVEC la marge de sécurité ? Un besoin <= 0 est toujours
    permis. Ne lève jamais."""
    try:
        besoin = int(besoin_octets)
    except (TypeError, ValueError):
        return True
    if besoin <= 0:
        return True
    dispo = dispo_octets if dispo_octets is not None else memoire_disponible_octets(psutil_mod=psutil_mod)
    return float(dispo) >= float(besoin) * max(1.0, float(marge))


def etat_memoire(*, dispo_octets: int | None = None, total_octets: int | None = None,
                 psutil_mod=None) -> dict:
    """Photo complète et sans exception : dispo, total, RSS du processus, fraction libre, niveau."""
    dispo = dispo_octets if dispo_octets is not None else memoire_disponible_octets(psutil_mod=psutil_mod)
    total = total_octets if total_octets is not None else memoire_totale_octets(psutil_mod=psutil_mod)
    rss = memoire_du_processus_octets(psutil_mod=psutil_mod)
    fraction = (float(dispo) / float(total)) if total and total > 0 else 1.0
    return {
        "dispo_octets": int(dispo),
        "total_octets": int(total),
        "rss_octets": int(rss),
        "dispo_go": round(float(dispo) / _GO, 2),
        "total_go": round(float(total) / _GO, 2),
        "rss_go": round(float(rss) / _GO, 2),
        "fraction_libre": round(fraction, 4),
        "niveau": niveau_pression(dispo_octets=dispo, total_octets=total, psutil_mod=psutil_mod),
    }


def decision(*, besoin_octets: int | None = None, dispo_octets: int | None = None,
             total_octets: int | None = None, psutil_mod=None) -> dict:
    """LE point d'entrée des modules lourds. Renvoie quoi faire, pourquoi, et de combien rétrécir.

    `action` ∈ {CONTINUER, RALENTIR, REDUIRE, PAUSER} ; `facteur` est la fraction d'ampleur à garder.
    Ne lève JAMAIS et ne renvoie JAMAIS « abandonne » : la dégradation est toujours progressive.
    """
    etat = etat_memoire(dispo_octets=dispo_octets, total_octets=total_octets, psutil_mod=psutil_mod)
    niveau = etat["niveau"]
    facteur = facteur_d_ampleur(niveau)

    if niveau == ROUGE:
        action, raison = PAUSER, (
            f"RAM critique ({etat['dispo_go']} Go libres, {etat['fraction_libre'] * 100:.0f} %) : "
            f"souffler brievement puis continuer a {facteur:.0%} d'ampleur")
    elif niveau == ORANGE:
        action, raison = REDUIRE, (
            f"RAM tendue ({etat['dispo_go']} Go libres) : continuer a {facteur:.0%} d'ampleur")
    else:
        action, raison = CONTINUER, f"RAM saine ({etat['dispo_go']} Go libres)"

    # Une demande d'allocation explicite peut durcir la décision même en VERT : mieux vaut rétrécir
    # tout de suite que demander un bloc qu'on ne peut pas tenir.
    if besoin_octets and not assez_de_memoire_pour(besoin_octets, dispo_octets=etat["dispo_octets"]):
        besoin_go = round(float(besoin_octets) / _GO, 2)
        if action == CONTINUER:
            action = REDUIRE
            facteur = min(facteur, FACTEURS_AMPLEUR[ORANGE])
        raison = (f"besoin estime {besoin_go} Go (marge x{MARGE_ALLOCATION}) > {etat['dispo_go']} Go "
                  f"libres : reduire l'ampleur au lieu d'allouer")

    return {"action": action, "niveau": niveau, "facteur": facteur, "raison": raison, "etat": etat}


def attendre_que_ca_respire(*, limite_s: float = ATTENTE_MAX_S, pas_s: float = ATTENTE_PAS_S,
                            dormir=None, horloge=None, dispo_octets=None, total_octets=None,
                            psutil_mod=None) -> dict:
    """Attend que la pression retombe sous ROUGE, mais JAMAIS plus de `limite_s`. Puis on continue
    de toute façon, en mode dégradé — bloquer un pipeline indéfiniment pour de la RAM serait pire.

    `dormir`, `horloge` et les mesures sont injectables : testable sans vraie pression mémoire.
    `dispo_octets` accepte aussi un CALLABLE, pour simuler une RAM qui évolue pendant l'attente.
    """
    import time as _time
    dormir = dormir or _time.sleep
    horloge = horloge or _time.monotonic

    def _mesure():
        if callable(dispo_octets):
            return niveau_pression(dispo_octets=int(dispo_octets()), total_octets=total_octets,
                                   psutil_mod=psutil_mod)
        return niveau_pression(dispo_octets=dispo_octets, total_octets=total_octets,
                               psutil_mod=psutil_mod)

    debut = float(horloge())
    tours = 0
    niveau = _mesure()
    while niveau == ROUGE and (float(horloge()) - debut) < max(0.0, float(limite_s)):
        try:
            dormir(max(0.01, float(pas_s)))
        except Exception:  # noqa: BLE001 — un sommeil interrompu ne doit pas tuer le pipeline
            _LOG.debug("sommeil interrompu pendant l'attente memoire", exc_info=True)
            break
        tours += 1
        niveau = _mesure()

    return {"niveau": niveau, "tours": tours,
            "attendu_s": round(max(0.0, float(horloge()) - debut), 3),
            "a_respire": niveau != ROUGE}


def journal_memoire(prefixe: str = "memoire", *, dispo_octets: int | None = None,
                    total_octets: int | None = None, psutil_mod=None) -> str:
    """Une ligne d'observabilité (M5) : état + niveau, prête à journaliser à chaque étape lourde."""
    e = etat_memoire(dispo_octets=dispo_octets, total_octets=total_octets, psutil_mod=psutil_mod)
    return (f"[{prefixe}] {e['niveau']} | libre {e['dispo_go']} Go / {e['total_go']} Go "
            f"({e['fraction_libre'] * 100:.0f} %) | ce processus {e['rss_go']} Go")


__all__ = ["OCTETS_PAR_EVENT", "FRACTION_RAM", "MINI_EVENTS", "MAXI_EVENTS",
           "memoire_disponible_octets", "budget_events", "resoudre_max_events",
           # M0 — gouverneur
           "VERT", "ORANGE", "ROUGE", "CONTINUER", "RALENTIR", "REDUIRE", "PAUSER",
           "SEUIL_ORANGE_GO", "SEUIL_ROUGE_GO", "SEUIL_ORANGE_FRACTION", "SEUIL_ROUGE_FRACTION",
           "ENV_SEUIL_ORANGE_GO", "ENV_SEUIL_ROUGE_GO", "FACTEURS_AMPLEUR", "MARGE_ALLOCATION",
           "ATTENTE_MAX_S", "ATTENTE_PAS_S",
           "memoire_totale_octets", "memoire_du_processus_octets", "niveau_pression",
           "facteur_d_ampleur", "reduire_ampleur", "assez_de_memoire_pour", "etat_memoire",
           "decision", "attendre_que_ca_respire", "journal_memoire"]
