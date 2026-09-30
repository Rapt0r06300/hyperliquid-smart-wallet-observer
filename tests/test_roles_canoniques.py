"""AUD-051 — ROLE CANONIQUE PAR JOB : la VALEUR du role, pas seulement sa presence.

Deux tables donnent le role d'un job, aucune n'etait verrouillee sur sa VALEUR :
  * `registre_pids.COMPOSANTS` — pour chaque composant du lanceur (cmd, moniteur, ui, poller, stream...),
    un role canonique lisible qui sert d'etiquette dans le registre PID et l'arret cible ;
  * `superviseur_collecteurs.profil_collecteur(nom)` — pour chaque collecteur, sa classe
    core / maintenance / research.
"""
from __future__ import annotations

import pytest

from hl_observer.ops import registre_pids as RP
from hl_observer.ops import superviseur_collecteurs as SC

ROLES_ATTENDUS = {
    "cmd": "lanceur",
    "resource-policy": "veille-ressources",
    "moniteur": "moniteur-sante",
    "ui": "moteur-ui",
    "poller": "poller",
    "stream": "stream-userfills",
    "ia-shadow": "ia-shadow",
}

PARTITION_PROFILS = frozenset({"core", "maintenance", "research"})

PROFIL_ATTENDU = {
    "allmids-collector": "core",
    "bbo-collector": "core",
    "userfills-live": "core",
    "copy-whitelist": "maintenance",
    "rapport-quotidien": "maintenance",
    "marks-collector": "research",
    "research-lab": "research",
    "lab-microstructure": "research",
    "dydx-live": "research",
}

_NOMS_REGISTRE = tuple(c["nom"] for c in SC.REGISTRE)


def test_composants_couvrent_exactement_les_roles_attendus():
    cles = {cle for cle, _role, _sigs in RP.COMPOSANTS}
    assert cles == set(ROLES_ATTENDUS), (
        "l'ensemble des composants du lanceur a derive: %s" % (cles ^ set(ROLES_ATTENDUS))
    )
    assert len(RP.COMPOSANTS) == len(cles), "cles de composants dupliquees"


@pytest.mark.parametrize("cle,role,sigs", list(RP.COMPOSANTS))
def test_role_canonique_par_composant(cle, role, sigs):
    assert role == ROLES_ATTENDUS[cle], (
        "role de %s : attendu %r, obtenu %r" % (cle, ROLES_ATTENDUS[cle], role)
    )
    assert sigs, "un composant sans signature ne serait jamais retrouve dans la table des process"


@pytest.mark.parametrize("nom", _NOMS_REGISTRE)
def test_profil_collecteur_reste_dans_la_partition(nom):
    p = SC.profil_collecteur(nom)
    assert p in PARTITION_PROFILS, "%s -> profil hors partition: %r" % (nom, p)
    assert p in SC.PROFILS_VALIDES, "la partition doit rester un sous-ensemble des profils valides"


def test_les_trois_profils_partitionnent_le_REGISTRE():
    noms = set(_NOMS_REGISTRE)
    par_classe = {r: {n for n in noms if SC.profil_collecteur(n) == r} for r in PARTITION_PROFILS}
    assert set().union(*par_classe.values()) == noms, "la partition ne couvre pas tout le REGISTRE"
    assert sum(len(v) for v in par_classe.values()) == len(noms), "classes non disjointes"
    assert all(par_classe[r] for r in PARTITION_PROFILS), (
        "chaque role doit exister: %s" % {r: len(v) for r, v in par_classe.items()}
    )
    assert par_classe["core"] == set(SC.COLLECTEURS_CORE)
    assert par_classe["maintenance"] == set(SC.COLLECTEURS_MAINTENANCE)


@pytest.mark.parametrize("nom,attendu", sorted(PROFIL_ATTENDU.items()))
def test_valeur_de_profil_ancree_par_nom(nom, attendu):
    assert nom in set(_NOMS_REGISTRE), "collecteur ancre disparu du REGISTRE: %s" % nom
    assert SC.profil_collecteur(nom) == attendu, (
        "%s : profil attendu %r, obtenu %r" % (nom, attendu, SC.profil_collecteur(nom))
    )
