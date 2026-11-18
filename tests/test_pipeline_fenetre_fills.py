"""LA FENÊTRE SUR LES FILLS : l'étape 2 du labo demandait 31,8 Go pour les charger tous.

MESURE DU 18/11/2026 sur le ruban réellement produit par le labo : 8 464 251 fills à 3 754 octets
par ligne, soit 31,8 Go — plus 28 Go de carnets. Ce sont les ~60 Go qui ont fait couper
l'enveloppe du rejeu pendant la reconstruction des épisodes.

POURQUOI LA DÉCOUPE EST LÉGITIME. `reconstruire_episodes` recale CHAQUE fill sur son
`startPosition` natif, donc couper les fills en fenêtres ne contamine pas les événements suivants.
Mesuré sur le même ruban : 8 464 251 fills sur 8 464 251 portent le champ (100,00 %), et aucune
des 4 396 paires (vault, coin) n'en manque sur son PREMIER fill.

MAIS CE N'EST VRAI QUE PARCE QUE C'EST MESURÉ : un corpus où le champ manquerait inventerait des
ouvertures en silence. D'où `fills_retenus_sans_position_de_depart` et `decoupe_sure`.
"""
from __future__ import annotations

import json

import pytest

import tools.pipeline_copie_reel as PR

BASE = {
    "vault": "0xA", "coin": "BTC", "px": 100.0, "sz": 1.0, "signe": 1,
    "dir": "Open Long", "start_position": 0.0, "source": "LIVE_WS", "isSnapshot": False,
}


def _corpus(tmp_path, instants, *, sans_position=(), historiques=()):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True, exist_ok=True)
    lignes = []
    for instant in instants:
        row = {**BASE, "ts_ms": instant, "received_at_ms": instant + 5, "hash": f"0x{instant}"}
        if instant in sans_position:
            row.pop("start_position")
        lignes.append(row)
    (data / "vault_fills_live.jsonl").write_text(
        "\n".join(map(json.dumps, lignes)) + "\n", encoding="utf-8")
    (data / "vault_fills.jsonl").write_text(
        "".join(json.dumps({**BASE, "ts_ms": i, "hash": f"0xh{i}", "oid": i}) + "\n"
                for i in historiques),
        encoding="utf-8")
    PR.oublier_les_cycles()
    return tmp_path


def _instants(fills):
    return sorted(int(f["ts_ms"]) for f in fills)


def test_sans_fenetre_le_comportement_est_INCHANGE(tmp_path):
    _corpus(tmp_path, (1_000, 2_000, 3_000))
    fills, audit = PR._fills_canoniques(tmp_path)
    assert _instants(fills) == [1_000, 2_000, 3_000]
    assert audit["fenetre_fills"] is None
    assert audit["fills_hors_fenetre"] == 0
    assert audit["decoupe_sure"] is True, "rien n'est découpé : la découpe est trivialement sûre"


def test_la_fenetre_est_INCLUSIVE_aux_deux_bornes(tmp_path):
    _corpus(tmp_path, (999, 1_000, 2_000, 3_000, 3_001))
    fills, audit = PR._fills_canoniques(tmp_path, fenetre=(1_000, 3_000))
    assert _instants(fills) == [1_000, 2_000, 3_000]
    assert audit["fenetre_fills"] == [1_000, 3_000]
    assert audit["fills_hors_fenetre"] == 2


def test_la_fenetre_s_applique_AUSSI_aux_fills_historiques(tmp_path):
    """Les deux sources sont fusionnées : n'en borner qu'une laisserait entrer l'autre."""
    _corpus(tmp_path, (2_000,), historiques=(500, 2_500, 9_000))
    fills, audit = PR._fills_canoniques(tmp_path, fenetre=(1_000, 3_000))
    assert _instants(fills) == [2_000, 2_500], "un live et un historique, distincts"
    assert audit["fills_hors_fenetre"] == 2


def test_un_fill_SANS_position_de_depart_est_COMPTE_et_la_decoupe_declaree_NON_SURE(tmp_path):
    """Sans ce champ, une position déjà ouverte passerait pour une ouverture — en silence."""
    _corpus(tmp_path, (1_000, 2_000), sans_position=(2_000,))
    fills, audit = PR._fills_canoniques(tmp_path, fenetre=(1_000, 3_000))
    assert len(fills) == 2, "le fill est RETENU : le rejeter changerait la position"
    assert audit["fills_retenus_sans_position_de_depart"] == 1
    assert audit["decoupe_sure"] is False


def test_le_meme_corpus_sans_fenetre_reste_declare_SUR(tmp_path):
    """Sans découpe, un fill sans position de départ ne fabrique aucune fausse ouverture."""
    _corpus(tmp_path, (1_000, 2_000), sans_position=(2_000,))
    _fills, audit = PR._fills_canoniques(tmp_path)
    assert audit["fills_retenus_sans_position_de_depart"] == 0
    assert audit["decoupe_sure"] is True


def test_une_fenetre_VIDE_est_REFUSEE(tmp_path):
    """Rendre zéro fill ferait lire « aucune donnée » là où il faut lire « mauvais appel »."""
    _corpus(tmp_path, (1_000,))
    with pytest.raises(ValueError, match="fenetre de fills vide"):
        PR._fills_canoniques(tmp_path, fenetre=(3_000, 2_999))


def test_une_fenetre_MAL_FORMEE_est_REFUSEE(tmp_path):
    _corpus(tmp_path, (1_000,))
    for mauvaise in ((0, 10), (10, 0), (-1, 10), (1.0, 10), ("1", "10"), (1_000,), 1_000):
        with pytest.raises(ValueError):
            PR._fills_canoniques(tmp_path, fenetre=mauvaise)


def test_LA_MEMORISATION_NE_CONFOND_PAS_DEUX_FENETRES(tmp_path):
    """Le piège de la grandeur qui change et survit dans un cache.

    `_episodes_canoniques` mémorise sa reconstruction tant que les fichiers d'entrée ne bougent
    pas. Si la fenêtre ne faisait pas partie de la signature, la deuxième journée recevrait les
    épisodes de la première — un résultat faux, et vert.
    """
    _corpus(tmp_path, (1_000, 50_000))
    premiers, _ = PR._episodes_canoniques(tmp_path, fenetre=(1_000, 1_999))
    seconds, _ = PR._episodes_canoniques(tmp_path, fenetre=(40_000, 60_000))
    assert [int(e["ts_ms"]) for e in premiers] == [1_000]
    assert [int(e["ts_ms"]) for e in seconds] == [50_000], "la fenêtre doit être dans la signature"
    encore, _ = PR._episodes_canoniques(tmp_path, fenetre=(1_000, 1_999))
    assert [int(e["ts_ms"]) for e in encore] == [1_000], "et la mémorisation doit rester utile"


def test_la_fenetre_traverse_jusqu_a_l_entree_publique(tmp_path):
    _corpus(tmp_path, (1_000, 50_000))
    entrees, audit = PR.charger_entrees_alpha_notional_fixe_avec_audit(
        tmp_path, fenetre=(40_000, 60_000))
    assert audit["fenetre_fills"] == [40_000, 60_000]
    assert all(int(e["ts_ms"]) >= 40_000 for e in entrees)


def test_la_somme_des_fenetres_rend_les_memes_fills_que_sans_fenetre(tmp_path):
    """Le contrôle qui compte : découper ne doit ni perdre ni dupliquer un fill."""
    instants = (1_000, 2_000, 3_000, 40_000, 50_000, 90_000)
    _corpus(tmp_path, instants, historiques=(1_500, 45_000))
    entiers, _ = PR._fills_canoniques(tmp_path)
    morceaux = []
    for debut, fin in ((1, 9_999), (10_000, 59_999), (60_000, 99_999)):
        part, audit = PR._fills_canoniques(tmp_path, fenetre=(debut, fin))
        assert audit["decoupe_sure"] is True
        morceaux.extend(part)
    assert _instants(morceaux) == _instants(entiers)
    assert len(morceaux) == len(entiers), "aucun fill compté deux fois"
