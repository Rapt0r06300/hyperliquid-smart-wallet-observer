"""AUD-051 — ROLE CANONIQUE PAR JOB : la VALEUR du role, pas seulement sa presence.

Deux tables donnent le role d'un job, aucune n'etait verrouillee sur sa VALEUR :
  * `registre_pids.COMPOSANTS` — pour chaque composant du lanceur (cmd, ui, poller, stream...),
    un role canonique lisible (« lanceur », « moteur-ui »...) qui sert d'etiquette dans le
    registre PID et l'arret cible ;
  * `superviseur_collecteurs.profil_collecteur(nom)` — pour chaque collecteur, sa classe
    core / maintenance / research (partition qui pilote les profils de demarrage).

Un renommage silencieux d'un role, ou un collecteur qui tomberait hors de la partition, passait
inapercu. Ce test fixe :
  1. la VALEUR de role attendue de CHAQUE composant de COMPOSANTS ;
  2. que chaque `profil_collecteur(...)` rend une valeur de l'ensemble AUTORISE (partition
     core/maintenance/research), que cet ensemble partitionne reellement le REGISTRE, et quelques
     valeurs ancrees par nom (dents independantes des frozensets internes).
"""
from __future__ import annotations

import pytest

from hl_observer.ops import registre_pids as RP
from hl_observer.ops import superviseur_collecteurs as SC

# 1) Role canonique attendu de chaque composant du lanceur (cle -> role lisible).
ROLES_ATTENDUS = {
    "cmd": "lanceur",
    "resource-policy": "veille-ressources",
    "ui": "moteur-ui",
    "poller": "poller",
    "stream": "stream-userfills",
    "ia-shadow": "ia-shadow",
}

# 2) Partition AUTORISEE des profils de collecteur (les seules valeurs que profil_collecteur rend).
PARTITION_PROFILS = frozenset({"core", "maintenance", "research"})

# Valeurs de profil ANCREES par nom, independantes des frozensets internes -> vraies dents.
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
    """L'ensemble des composants (et donc des roles a verrouiller) ne doit pas deriver en silence."""
    cles = {cle for cle, _role, _sigs in RP.COMPOSANTS}
    assert cles == set(ROLES_ATTENDUS), (
        "l'ensemble des composants du lanceur a derive: %s" % (cles ^ set(ROLES_ATTENDUS))
    )
    assert len(RP.COMPOSANTS) == len(cles), "cles de composants dupliquees"


@pytest.mark.parametrize("cle,role,sigs", list(RP.COMPOSANTS))
def test_role_canonique_par_composant(cle, role, sigs):
    """AUD-051 : la VALEUR du role de chaque composant est verrouillee (pas seulement sa presence)."""
    assert role == ROLES_ATTENDUS[cle], (
        "role de %s : attendu %r, obtenu %r" % (cle, ROLES_ATTENDUS[cle], role)
    )
    assert sigs, "un composant sans signature ne serait jamais retrouve dans la table des process"


@pytest.mark.parametrize("nom", _NOMS_REGISTRE)
def test_profil_collecteur_reste_dans_la_partition(nom):
    """Chaque profil_collecteur(...) rend une valeur de l'ensemble AUTORISE (partition)."""
    p = SC.profil_collecteur(nom)
    assert p in PARTITION_PROFILS, "%s -> profil hors partition: %r" % (nom, p)
    assert p in SC.PROFILS_VALIDES, "la partition doit rester un sous-ensemble des profils valides"


def test_les_trois_profils_partitionnent_le_REGISTRE():
    """PARTITION reelle : chaque collecteur tombe dans EXACTEMENT une classe, les trois classes
    couvrent tout le REGISTRE, aucune n'est vide, et elles collent aux frozensets canoniques."""
    noms = set(_NOMS_REGISTRE)
    par_classe = {r: {n for n in noms if SC.profil_collecteur(n) == r} for r in PARTITION_PROFILS}
    # couverture + disjonction (fonction => une classe par nom ; somme des tailles == total)
    assert set().union(*par_classe.values()) == noms, "la partition ne couvre pas tout le REGISTRE"
    assert sum(len(v) for v in par_classe.values()) == len(noms), "classes non disjointes"
    assert all(par_classe[r] for r in PARTITION_PROFILS), (
        "chaque role doit exister: %s" % {r: len(v) for r, v in par_classe.items()}
    )
    # coherence avec les frozensets canoniques declares dans le module.
    assert par_classe["core"] == set(SC.COLLECTEURS_CORE)
    assert par_classe["maintenance"] == set(SC.COLLECTEURS_MAINTENANCE)


@pytest.mark.parametrize("nom,attendu", sorted(PROFIL_ATTENDU.items()))
def test_valeur_de_profil_ancree_par_nom(nom, attendu):
    """Dents independantes : le role de jobs precis est fixe par NOM. Si profil_collecteur
    reclassait bbo-collector hors CORE, ce test rougirait."""
    assert nom in set(_NOMS_REGISTRE), "collecteur ancre disparu du REGISTRE: %s" % nom
    assert SC.profil_collecteur(nom) == attendu, (
        "%s : profil attendu %r, obtenu %r" % (nom, attendu, SC.profil_collecteur(nom))
    )
