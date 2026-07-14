"""LE VERDICT ECONOMIQUE, TESTE CONTRE LA VRAIE TABLE (2026-07-12).

POURQUOI CE FICHIER EXISTE
--------------------------
`conftest.py` fait pointer TOUS les tests vers une table TEST_FIXTURE a edge positif, pour
qu'ils puissent exercer la mecanique en aval du verrou. C'est necessaire -- mais ca cree un
angle mort : plus personne ne regarde la VRAIE table.

Ce fichier est le seul qui la regarde. Il ne teste pas du code : il teste un FAIT.

LE FAIT (mesure hors echantillon le 2026-07-11, 3 572 observations)
-------------------------------------------------------------------
    age 5-15 s    edge = -2,17 bps   (302 obs)
    age 15-60 s   edge = -0,56 bps   (1 582 obs)
    age 60-300 s  edge = -0,23 bps   (1 688 obs)

Toutes NEGATIVES. Les couts sont d'environ 13 bps. Copier un fill de whale sur Hyperliquid
ne rapporte rien -- ca coute. Le bot qui refuse a RAISON, et les 26 tests qui exigeaient une
ouverture testaient une croyance perimee.

CE QUE CE TEST DEFEND
---------------------
Si un jour quelqu'un remplace cette table par des bandes POSITIVES, ce test tombe -- et il
faudra alors PROUVER la mesure, pas la souhaiter. C'est un cliquet contre l'auto-illusion :
on ne rouvre pas les vannes parce qu'on en a envie, mais parce qu'une mesure a change.

Aucun reseau, aucun ordre : on lit un fichier JSON.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
TABLE_REELLE = RACINE / "runtime" / "calibration" / "empirical_edge.json"


def _table() -> dict:
    if not TABLE_REELLE.exists():
        pytest.skip("pas de table d'edge mesuree sur cette machine -- rien a verifier")
    return json.loads(TABLE_REELLE.read_text(encoding="utf-8"))


def test_la_vraie_table_d_edge_est_NEGATIVE_partout() -> None:
    """LE FAIT CENTRAL DU PROJET. S'il change, tout change -- et il faudra le prouver."""
    bandes = _table().get("bands") or []
    assert bandes, "une table d'edge sans bande ne mesure rien"

    positives = [b for b in bandes if float(b.get("edge_bps", 0.0)) > 0.0]
    assert not positives, (
        f"UNE BANDE D'EDGE EST DEVENUE POSITIVE : {positives}\n\n"
        "Ce n'est pas forcement une bonne nouvelle -- c'est d'abord une ALERTE.\n"
        "Le 2026-07-11, sur 24 133 signaux et hors echantillon, l'edge du copy-trading etait\n"
        "NEGATIF a tous les horizons, MEME A COUT ZERO (-7,97 bps). Si une bande devient\n"
        "positive, l'explication la plus probable n'est pas qu'on a trouve de l'or : c'est\n"
        "qu'on a fabrique un chiffre, ou fuite du futur, ou surajuste un echantillon trop court.\n\n"
        "AVANT de rouvrir les entrees : refaire la mesure hors echantillon, sur une fenetre\n"
        "differente, et montrer le t-stat. Une envie n'est pas une mesure."
    )


def test_chaque_bande_repose_sur_un_echantillon_suffisant() -> None:
    """Un edge mesure sur 12 trades n'est pas une mesure : c'est du bruit avec un decimal."""
    table = _table()
    mini = int(table.get("min_sample_size") or 200)
    maigres = [
        b for b in (table.get("bands") or [])
        if int(b.get("sample_size", 0)) < mini
    ]
    assert not maigres, (
        f"bande(s) sous le seuil de {mini} observations : {maigres}. "
        "Une bande maigre laisse passer du bruit deguise en science -- et c'est exactement "
        "comme ca qu'on se refabrique un edge."
    )


def test_la_table_reelle_n_est_JAMAIS_un_TEST_FIXTURE() -> None:
    """Le garde-fou anti-confusion : LIVE et TEST_FIXTURE ne doivent jamais se melanger.

    Si quelqu'un copie la fixture de test par-dessus la table de production, le bot se
    remettrait a ouvrir des positions sur un edge INVENTE de 60 bps. Ce test l'interdit.
    """
    table = _table()
    assert "TEST_FIXTURE" not in str(table.get("source", "")), (
        "la table de PRODUCTION porte source=TEST_FIXTURE : quelqu'un a copie la fixture "
        "de test par-dessus la mesure reelle. Le bot ouvrirait alors des positions sur un "
        "edge INVENTE. C'est exactement l'edge fabrique qu'on a passe des semaines a tuer."
    )
    assert table.get("real_execution") is False, (
        "`real_execution` doit rester false : cette table ne sert QU'A la simulation paper"
    )
