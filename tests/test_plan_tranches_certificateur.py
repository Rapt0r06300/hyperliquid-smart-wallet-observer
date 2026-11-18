"""LE PLAN DE TRANCHES, INTÉGRÉ AU CERTIFICATEUR.

Demande de l'opérateur le 18/11/2026 : que le découpage se fasse tout seul quand de nouvelles
données arrivent, sans commande à taper. Le certificateur est le point où les données **entrent** —
c'est donc là que le plan s'annonce.

Le plan se calcule depuis l'INDEX du coffre, qui porte `famille`, `ts_min_ms`, `ts_max_ms` et
`deposes` par shard : 0,4 seconde, sans ouvrir un seul shard, contre 32 secondes de lecture en flux
sur le ruban.

Ces tests verrouillent les trois propriétés qui rendent ce plan utilisable : il est **borné à la
fenêtre du labo**, il déclare qu'il est une **borne haute**, et il ne fait **jamais échouer** la
certification.
"""
from __future__ import annotations

import json

from tools import conduire_labo_par_tranches as CD

HEURE = 3_600_000


def _index(tmp_path, shards):
    chemin = tmp_path / "LOCAL_INDEX.json"
    chemin.write_text(json.dumps({"schema": "x", "tier": "LOCAL", "shards": shards}),
                      encoding="utf-8")
    return chemin


def _shard(famille, debut, fin, deposes):
    return {"famille": famille, "ts_min_ms": debut, "ts_max_ms": fin, "deposes": deposes,
            "shard": "s.jsonl.gz", "sha256": "a" * 64}


# ───────────────────────── la densité lue dans l'index ─────────────────────────

def test_un_shard_dans_UN_SEUL_pas_y_verse_toutes_ses_lignes(tmp_path):
    """Le cas exact : aucune approximation."""
    index = _index(tmp_path, [_shard("fills_forward", HEURE + 10, HEURE + 20, 500)])
    r = CD.densite_depuis_le_coffre(index)
    assert r["densite"] == {HEURE: 500}
    assert r["shards_repartis"] == 0 and r["part_repartie"] == 0.0


def test_un_shard_A_CHEVAL_repartit_ses_lignes_SANS_EN_PERDRE(tmp_path):
    """La somme doit rester exacte : le reste de la division va aux premiers seaux."""
    index = _index(tmp_path, [_shard("fills_forward", HEURE, 4 * HEURE - 1, 101)])
    r = CD.densite_depuis_le_coffre(index)
    assert sum(r["densite"].values()) == 101, "aucune ligne perdue dans l'arrondi"
    assert r["shards_repartis"] == 1 and len(r["densite"]) == 3


def test_les_familles_HORS_FILLS_sont_ignorees(tmp_path):
    """Ce sont les fills qui dimensionnent les tranches ; les carnets suivent."""
    index = _index(tmp_path, [
        _shard("fills_forward", HEURE, HEURE + 10, 300),
        _shard("book_l2", HEURE, HEURE + 10, 90_000),
        _shard("candle", HEURE, HEURE + 10, 5_000),
    ])
    r = CD.densite_depuis_le_coffre(index)
    assert r["lignes"] == 300 and r["shards_lus"] == 1


def test_un_shard_SANS_BORNES_est_compte_et_non_devine(tmp_path):
    index = _index(tmp_path, [
        {"famille": "fills_forward", "deposes": 10},
        _shard("fills_forward", HEURE, HEURE + 5, 7),
    ])
    r = CD.densite_depuis_le_coffre(index)
    assert r["shards_sans_bornes"] == 1 and r["lignes"] == 7


def test_un_index_ILLISIBLE_le_DIT_au_lieu_de_rendre_zero(tmp_path):
    chemin = tmp_path / "LOCAL_INDEX.json"
    chemin.write_text("{ pas du json", encoding="utf-8")
    r = CD.densite_depuis_le_coffre(chemin)
    assert r["densite"] == {} and r["raison"].startswith("INDEX_ILLISIBLE")


def test_un_index_ABSENT_le_DIT_aussi(tmp_path):
    r = CD.densite_depuis_le_coffre(tmp_path / "jamais.json")
    assert r["densite"] == {} and r["raison"].startswith("INDEX_ILLISIBLE")


def test_un_index_SANS_shards_est_distingue_d_un_index_illisible(tmp_path):
    chemin = tmp_path / "LOCAL_INDEX.json"
    chemin.write_text(json.dumps({"schema": "x"}), encoding="utf-8")
    assert CD.densite_depuis_le_coffre(chemin)["raison"] == "INDEX_SANS_SHARDS"


# ───────────────────── la fenêtre du labo, qui borne tout ─────────────────────

def test_un_shard_ENTIEREMENT_avant_la_fenetre_est_ecarte(tmp_path):
    index = _index(tmp_path, [_shard("fills_forward", HEURE, 2 * HEURE, 400)])
    r = CD.densite_depuis_le_coffre(index, depuis_ms=10 * HEURE)
    assert r["densite"] == {} and r["shards_hors_fenetre"] == 1


def test_un_shard_A_CHEVAL_sur_la_fenetre_ne_verse_QUE_dans_la_fenetre(tmp_path):
    """Le défaut corrigé : un shard de 2023 finissant après le 13/11 versait dans des milliers de
    seaux antérieurs, et le plan annonçait 14 031 heures de travail imaginaire."""
    # `ts_min_ms = 0` serait refusé comme horodatage invalide (le code a raison, et mon premier
    # essai de ce test s'y est pris) : on part donc d'un instant valide très ancien.
    index = _index(tmp_path, [_shard("fills_forward", 1, 10 * HEURE - 1, 1_000)])
    r = CD.densite_depuis_le_coffre(index, depuis_ms=8 * HEURE)
    assert all(seau >= 7 * HEURE for seau in r["densite"]), r["densite"]
    assert r["lignes_hors_fenetre"] > 0, "les lignes écartées sont COMPTÉES, pas placées ailleurs"
    assert r["lignes"] + r["lignes_hors_fenetre"] == 1_000, "rien ne disparaît"


def test_la_fenetre_est_PUBLIEE_avec_la_mesure(tmp_path):
    index = _index(tmp_path, [_shard("fills_forward", HEURE, HEURE + 5, 3)])
    r = CD.densite_depuis_le_coffre(index, depuis_ms=1, jusqu_a_ms=99 * HEURE)
    assert r["fenetre"] == [1, 99 * HEURE]


# ───────────────────── ce que le plan vaut, déclaré ─────────────────────

def test_la_part_APPROXIMEE_est_publiee(tmp_path):
    """Sans ce chiffre, on ne saurait pas si le plan vaut 99 % ou 60 %."""
    index = _index(tmp_path, [
        _shard("fills_forward", HEURE, HEURE + 5, 10),          # exact
        _shard("fills_forward", 2 * HEURE, 5 * HEURE, 30),      # réparti
    ])
    r = CD.densite_depuis_le_coffre(index)
    assert r["shards_lus"] == 2 and r["shards_repartis"] == 1
    assert r["part_repartie"] == 0.5


def test_le_decoupage_du_plan_est_CONTINU(tmp_path):
    from hl_observer.backtesting import agregation_tranches as AG

    index = _index(tmp_path, [_shard("fills_forward", h * HEURE, h * HEURE + 10, 300)
                              for h in range(1, 9)])
    r = CD.densite_depuis_le_coffre(index)
    tranches = CD.decouper(r["densite"], budget=500)
    assert len(tranches) > 1
    assert AG.couverture(tranches)["continue"] is True


# ───────────────────── l'intégration au lanceur ─────────────────────

def test_le_certificateur_ANNONCE_le_plan_apres_un_scellement_reussi():
    import pathlib

    lanceur = pathlib.Path(__file__).resolve().parents[1] / "Certificateur Coffre Fort.cmd"
    texte = lanceur.read_text(encoding="utf-8")
    assert "PLAN DU PROCHAIN REJEU DU LABO" in texte
    assert "conduire_labo_par_tranches.py" in texte and "--depuis-le-coffre" in texte
    # l'étape est DANS la branche de succès du scellement, pas avant ni après la sortie
    debut = texte.index('if "%RC%"=="0" (')
    fin = texte.index(") else (", debut)
    assert "conduire_labo_par_tranches.py" in texte[debut:fin], (
        "le plan ne doit s'annoncer qu'après un scellement réussi")


def test_le_plan_ne_fait_JAMAIS_echouer_la_certification():
    """Un coffre correctement scellé ne doit pas être déclaré en échec parce qu'un affichage a
    manqué. Et `if errorlevel 1` sans `%` est la forme qui fonctionne dans un bloc parenthésé."""
    import pathlib

    lanceur = pathlib.Path(__file__).resolve().parents[1] / "Certificateur Coffre Fort.cmd"
    texte = lanceur.read_text(encoding="utf-8")
    debut = texte.index("PLAN DU PROCHAIN REJEU DU LABO")
    bloc = texte[debut:texte.index(") else (", debut)]
    assert "if errorlevel 1 echo" in bloc, "l'échec du plan est signalé, pas propagé"
    assert "exit /b" not in bloc, "aucune sortie ne doit couper la certification"
    assert "%ERRORLEVEL%" not in bloc, (
        "dans un bloc parenthésé, `%ERRORLEVEL%` est figé au parsing : il faut `if errorlevel 1`")


def test_le_plan_ne_lance_PAS_le_labo():
    """Certifier doit rester court et sans surprise ; un rejeu dure des heures."""
    import pathlib

    lanceur = pathlib.Path(__file__).resolve().parents[1] / "Certificateur Coffre Fort.cmd"
    texte = lanceur.read_text(encoding="utf-8")
    debut = texte.index("PLAN DU PROCHAIN REJEU DU LABO")
    bloc = texte[debut:texte.index(") else (", debut)]
    assert "--depuis-le-coffre" in bloc
    assert "alina_quant_lab_console" not in bloc and "--max-trials" not in bloc
