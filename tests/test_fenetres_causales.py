"""La fenetre causale du Copy-Vault : ce qui a le droit d'etre lu APRES un signal.

POURQUOI CE FICHIER EXISTE. `copy_vault_fenetres_causales.py` a ete extrait de
`copy_vault_coffre_vers_labo.py` le 21/11/2026 (809 lignes pour un plafond de 800). L'audit
l'a aussitot signale « NOUVEAU MODULE SANS TEST » -- et il avait raison : extraire du code
deja couvert par les tests du module parent le laisse couvert PAR RICOCHET, pas en propre.
Un module sans test en propre peut changer de comportement sans que rien ne rougisse.

Ces tests encodent les DEUX defauts mesures que ces fonctions corrigent, pour qu'un retour
en arriere redevienne rouge ici :

  1. une fenetre qui ne regarde que le PASSE du signal jette les carnets d'entree et de
     sortie -> 0 trade sur 4 000 signaux ;
  2. quantifier l'ancre de REFERENCE la place jusqu'a un pas AVANT le signal -> le replay
     refuse (`STALE_OR_MISSING_REFERENCE_BOOK` sur 418 candidats sur 418).
"""
from __future__ import annotations

from hl_observer.backtesting.copy_vault_fenetres_causales import (
    _fenetre_apres_signal,
    ancres_utiles,
)


def test_la_fenetre_regarde_vers_l_avant_pas_vers_l_arriere():
    """LE DEFAUT HISTORIQUE : une fenetre calibree sur le passe donnait zero trade.

    La fenetre doit couvrir le delai de copie PLUS le plus long horizon explore PLUS la
    tolerance de retard. On le verifie contre les constantes vivantes, pas contre un nombre
    recopie : un nombre recopie ne detecte pas un changement de contrat.
    """
    from hl_observer.backtesting import copy_vault_executable as cv
    from hl_observer.backtesting.copy_vault_local_lab import _PARAMETER_DOMAINS

    horizon_max = max(dict(_PARAMETER_DOMAINS)["horizon_ms"])
    attendu = int(cv.COPY_DELAY_MS) + int(horizon_max) + int(cv.MAX_TARGET_LAG_MS)
    mesure = _fenetre_apres_signal()
    assert mesure == attendu
    assert mesure > horizon_max, (
        "une fenetre plus courte que l'horizon le plus long jette le carnet de SORTIE : "
        "c'est exactement le defaut du 18/11/2026 (0 trade sur 4 000 signaux)")


def test_la_reference_et_l_entree_ne_sont_jamais_quantifiees():
    """Les deux instants qui DECIDENT de l'episode sont connus exactement : on les garde tels quels."""
    pas = 15_000
    ancres = ancres_utiles([1_000_007], delai_ms=3_000, horizons_ms=[60_000], pas_ms=pas)
    assert 1_000_007 in ancres, "l'ancre de reference a ete arrondie -> le replay refusera"
    assert 1_003_007 in ancres, "l'ancre d'entree a ete arrondie -> le replay refusera"


def test_la_sortie_est_quantifiee_au_pas():
    """La sortie depend de l'horizon ET de l'entree reelle : elle est deja approximative."""
    pas = 15_000
    ancres = ancres_utiles([0], delai_ms=3_000, horizons_ms=[60_000], pas_ms=pas)
    sorties = [a for a in ancres if a not in (0, 3_000)]
    assert sorties == [((3_000 + 60_000) // pas) * pas]


def test_chaque_horizon_explore_recoit_son_ancre():
    """Le labo cherche PLUSIEURS horizons : en oublier un rend ses candidats non mesurables."""
    horizons = [60_000, 600_000, 3_600_000]
    ancres = ancres_utiles([0], delai_ms=3_000, horizons_ms=horizons, pas_ms=1_000)
    for horizon in horizons:
        assert (3_000 + horizon) in ancres


def test_le_budget_ne_croit_pas_avec_des_signaux_voisins():
    """CE QUE LE PAS PROTEGE : deux signaux a moins d'un pas partagent le meme carnet de sortie.

    Sans quantification, 50 signaux voisins demanderaient 50 carnets de sortie pour une seule
    tranche de temps -- c'est ce qui faisait exploser la memoire et avait motive un plafond de
    240 carnets par signal, lequel detruisait la mesure.
    """
    pas = 15_000
    voisins = [100 * i for i in range(50)]          # 50 signaux en 5 s, bien moins qu'un pas
    ancres = ancres_utiles(voisins, delai_ms=3_000, horizons_ms=[60_000], pas_ms=pas)
    crans = {a for a in ancres if a not in set(voisins) | {v + 3_000 for v in voisins}}
    assert len(crans) <= 2, f"{len(crans)} ancres de sortie pour 50 signaux voisins"


def test_les_ancres_sont_triees_et_sans_doublon():
    """Le consommateur balaye les carnets dans l'ordre : un doublon le fait lire deux fois."""
    ancres = ancres_utiles([0, 0, 7_000], delai_ms=3_000, horizons_ms=[60_000, 60_000],
                           pas_ms=1_000)
    assert ancres == sorted(ancres)
    assert len(ancres) == len(set(ancres))


def test_pas_nul_ou_negatif_ne_divise_jamais_par_zero():
    """Un pas absurde doit etre ramene a 1, jamais lever ZeroDivisionError en pleine campagne."""
    for pas in (0, -5):
        ancres = ancres_utiles([0], delai_ms=1_000, horizons_ms=[2_000], pas_ms=pas)
        assert ancres == [0, 1_000, 3_000]


def test_aucun_signal_rend_une_liste_vide():
    """Entree vide -> resultat vide. Jamais une ancre inventee (regle du projet)."""
    assert ancres_utiles([], delai_ms=3_000, horizons_ms=[60_000], pas_ms=1_000) == []
