"""AUD-050 — RECONCILIATION SOURCES_HARVEST <-> REGISTRE (la BONNE relation, pas une egalite naive).

Deux structures separees decrivaient les collecteurs :
  * `superviseur_collecteurs.REGISTRE`  — les collecteurs REELS (nom + script/runner sur le disque) ;
  * `preuve_de_vie.SOURCES_HARVEST`     — les sources ATTENDUES du profil HARVEST (dont certaines
                                          declarees `non_implementee=True` : aucun collecteur reel).

Elles n'etaient jamais reconciliees par un test. Une egalite naive des deux ensembles serait FAUSSE :
  * SOURCES_HARVEST contient des entrees `non_implementee=True` volontairement ABSENTES du REGISTRE ;
  * le REGISTRE contient des collecteurs (overshoot, pipeline-reel, geler-prelim...) absents de
    SOURCES_HARVEST — legitime aussi.

L'invariant REEL, verrouille ici :
  toute source IMPLEMENTEE (non `non_implementee`) — a fortiori toute source OBLIGATOIRE — doit
  correspondre a un collecteur REEL du REGISTRE : meme `nom` (cle de correspondance) ET un
  `script`/runner qui existe sur le disque. Reciproquement, une source `non_implementee` ne doit
  PAS avoir de collecteur (sinon la declaration ment).

Lecture seule / paper : on inspecte des structures et l'existence de fichiers, aucun reseau.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hl_observer.ops import preuve_de_vie as PV
from hl_observer.ops import superviseur_collecteurs as SC

RACINE = Path(__file__).resolve().parents[1]

# Partitions de SOURCES_HARVEST (calculees a la collecte pour parametrer les tests, cle = nom).
SOURCES_IMPL_OBLIG = tuple(
    s.nom for s in PV.SOURCES_HARVEST if (not s.non_implementee) and s.obligatoire
)
SOURCES_IMPL = tuple(s.nom for s in PV.SOURCES_HARVEST if not s.non_implementee)
SOURCES_NON_IMPL = tuple(s.nom for s in PV.SOURCES_HARVEST if s.non_implementee)


def _registre_par_nom() -> dict[str, dict]:
    return {c["nom"]: c for c in SC.REGISTRE}


def test_il_y_a_bien_de_quoi_reconcilier():
    """Garde anti-test-vacant : les deux facettes (implementee+obligatoire, non_implementee) existent."""
    assert SOURCES_IMPL_OBLIG, "aucune source implementee+obligatoire : invariant central vacant"
    assert SOURCES_NON_IMPL, "aucune source non_implementee : la nuance testee aurait disparu"


@pytest.mark.parametrize("nom", SOURCES_IMPL_OBLIG)
def test_source_obligatoire_implementee_a_un_collecteur_reel(nom):
    """INVARIANT CENTRAL AUD-050 : une source OBLIGATOIRE et IMPLEMENTEE doit correspondre a un
    collecteur REEL du REGISTRE (nom present + script/runner existant sur le disque)."""
    par_nom = _registre_par_nom()
    assert nom in par_nom, "source obligatoire+implementee %s ABSENTE du REGISTRE" % nom
    script = par_nom[nom].get("script")
    assert isinstance(script, str) and script, "collecteur %s sans script reel" % nom
    assert (RACINE / script).is_file(), "runner introuvable pour %s : %s" % (nom, script)


@pytest.mark.parametrize("nom", SOURCES_IMPL)
def test_toute_source_implementee_est_un_collecteur_reel(nom):
    """Dents supplementaires : TOUTE source implementee (obligatoire OU secondaire) a un collecteur
    reel. Les entrees non_implementee sont exclues (testees separement)."""
    par_nom = _registre_par_nom()
    assert nom in par_nom, "source implementee %s ABSENTE du REGISTRE" % nom
    script = par_nom[nom].get("script")
    assert isinstance(script, str) and (RACINE / script).is_file(), (
        "runner introuvable pour %s : %s" % (nom, script)
    )


@pytest.mark.parametrize("nom", SOURCES_NON_IMPL)
def test_une_source_non_implementee_n_a_PAS_de_collecteur(nom):
    """Difference LEGITIME : une source `non_implementee=True` n'a par definition aucun collecteur
    reel -> elle DOIT etre absente du REGISTRE (sinon « non implementee » serait un mensonge)."""
    assert nom not in _registre_par_nom(), (
        "%s est declaree non_implementee mais figure dans le REGISTRE" % nom
    )


def test_la_reconciliation_n_est_PAS_une_egalite_naive():
    """La BONNE relation, dans les deux sens :
      sens source->registre : les SEULES sources absentes du REGISTRE sont les non_implementee ;
      sens registre->source : des collecteurs reels hors SOURCES_HARVEST sont attendus (asymetrie).
    """
    noms_sources = {s.nom for s in PV.SOURCES_HARVEST}
    noms_registre = {c["nom"] for c in SC.REGISTRE}

    absentes_du_registre = noms_sources - noms_registre
    assert absentes_du_registre == set(SOURCES_NON_IMPL), (
        "seules les sources non_implementee peuvent manquer au REGISTRE ; ecart: %s"
        % (absentes_du_registre ^ set(SOURCES_NON_IMPL))
    )
    # Une egalite naive des deux ensembles serait fausse : le REGISTRE a des collecteurs en plus.
    assert noms_registre - noms_sources, (
        "au moins un collecteur reel hors SOURCES_HARVEST est attendu (relation asymetrique)"
    )
