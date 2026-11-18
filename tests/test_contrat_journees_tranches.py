"""LE CONTRAT ENTRE CELUI QUI PRODUIT LES JOURNÉES ET CELUI QUI LES UNIT.

DÉFAUT RÉVÉLÉ PAR LA PREMIÈRE CONDUITE RÉELLE (18/11/2026). `signal_coverage` publiait
`distinct_utc_days: 1` — un **nombre**. Or `agregation_tranches.unir_les_jours` fait l'**union** des
journées de toutes les tranches, et pour unir il lui faut la **liste**. Elle lisait donc zéro
journée à chaque tranche, et l'agrégat affichait `jours UTC distincts (union) : 0 / 6 requis`.

Autrement dit : même avec les dix-neuf tranches, l'agrégat n'aurait **jamais** pu devenir
exploitable. Le seuil des six journées, qu'on avait pris soin de déplacer au bon niveau, était
infranchissable — non par manque de données, mais parce que personne ne publiait de quoi le
franchir.

POURQUOI AUCUN TEST NE L'AVAIT VU. Mes tests de `unir_les_jours` **fabriquaient** des rapports
contenant `utc_days`. Ils vérifiaient donc l'union sans vérifier que quelqu'un produise cette clé :
le double de test inventait l'interface qu'il consommait. Ces tests-ci branchent le **vrai**
producteur sur le **vrai** consommateur.
"""
from __future__ import annotations

from hl_observer.backtesting import agregation_tranches as AG
from hl_observer.backtesting.copy_vault_local_lab import _signal_coverage

JOUR = 86_400_000


def test_le_producteur_publie_la_LISTE_des_journees():
    couverture = _signal_coverage([10 * JOUR + 1_000, 11 * JOUR + 500])
    assert "utc_days" in couverture, "sans la liste, aucune union n'est possible"
    assert couverture["utc_days"] == ["1970-01-11", "1970-01-12"]


def test_la_liste_et_le_nombre_sont_COHERENTS():
    """Deux façons de dire la même chose : elles ne doivent jamais diverger."""
    for instants in (
        [],
        [10 * JOUR],
        [10 * JOUR, 10 * JOUR + 1, 10 * JOUR + 2],
        [10 * JOUR, 11 * JOUR, 12 * JOUR, 12 * JOUR + 9],
    ):
        couverture = _signal_coverage(instants)
        assert len(couverture["utc_days"]) == couverture["distinct_utc_days"]


def test_le_CONSOMMATEUR_lit_ce_que_le_PRODUCTEUR_ecrit():
    """Le test qui manquait : le vrai producteur branché sur le vrai consommateur."""
    tranche_a = {"signal_coverage": _signal_coverage([10 * JOUR + 1, 10 * JOUR + 2])}
    tranche_b = {"signal_coverage": _signal_coverage([11 * JOUR + 3])}
    union = AG.unir_les_jours([tranche_a, tranche_b])
    assert union["distincts"] == 2
    assert union["tranches_sans_jours_declares"] == 0, "aucune tranche ne doit être muette"


def test_DEUX_TRANCHES_DE_LA_MEME_JOURNEE_ne_font_qu_une_journee():
    """C'est tout l'intérêt de l'union : découper un jour n'en fabrique pas deux."""
    matin = {"signal_coverage": _signal_coverage([10 * JOUR + 1_000])}
    soir = {"signal_coverage": _signal_coverage([10 * JOUR + 80_000_000])}
    assert AG.unir_les_jours([matin, soir])["distincts"] == 1


def test_SIX_tranches_de_SIX_journees_franchissent_le_seuil():
    """Le cas qui doit devenir possible : c'est ce que la conduite vise."""
    rapports = [
        {"status": "MORE_DATA", "signal_coverage": _signal_coverage([(13 + i) * JOUR + 1])}
        for i in range(6)
    ]
    agregat = AG.combiner(
        rapports,
        tranches=[(1 + i * JOUR, (i + 1) * JOUR) for i in range(6)],
        jours_minimum=6,
    )
    assert agregat["jours"]["distincts"] == 6
    assert agregat["assez_de_jours"] is True
    assert agregat["exploitable"] is True


def test_SIX_tranches_de_TROIS_journees_ne_franchissent_PAS_le_seuil():
    """La contrepartie : l'union ne doit pas devenir une façon de gonfler le compte."""
    rapports = [
        {"status": "MORE_DATA", "signal_coverage": _signal_coverage([(13 + i % 3) * JOUR + 1])}
        for i in range(6)
    ]
    agregat = AG.combiner(
        rapports,
        tranches=[(1 + i * JOUR, (i + 1) * JOUR) for i in range(6)],
        jours_minimum=6,
    )
    assert agregat["jours"]["distincts"] == 3
    assert agregat["exploitable"] is False
    assert agregat["raison_non_exploitable"] == "JOURNEES_INSUFFISANTES"


def test_une_couverture_VIDE_ne_declare_aucune_journee():
    couverture = _signal_coverage([])
    assert couverture["utc_days"] == [] and couverture["distinct_utc_days"] == 0
    union = AG.unir_les_jours([{"signal_coverage": couverture}])
    assert union["distincts"] == 0
    assert union["tranches_sans_jours_declares"] == 1, (
        "une tranche sans journée doit être comptée à part, pas confondue avec une tranche absente")


def test_les_journees_sont_des_DATES_lisibles_pas_des_numeros():
    """Un numéro de jour depuis l'époque Unix serait illisible dans un rapport."""
    couverture = _signal_coverage([20_000 * JOUR + 1])
    (jour,) = couverture["utc_days"]
    assert jour.count("-") == 2 and len(jour) == 10, jour
