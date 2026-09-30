"""MARQUER TOUT L'UNIVERS — « augmenter le nombre » (21/07).

« Ce chiffre ne grandit jamais » : le pool de marks croissait (~1 240/h) mais 0,43 %/h sur une
base de 384 000 est invisible à l'œil. Cause du débit : le runtime ne marquait que la shortlist
viable (6 coins) alors que le scanner tient le prix perp frais de tout l'univers perp∩spot
(~100-200 coins) — et le jetait pour les non-viables.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.ops import marks_univers as mu


# ─────────────── on ne garde que des prix RÉELS ───────────────

def test_un_instantane_devient_des_lignes_de_marks():
    lignes = mu.lignes_marks({"BTC": 61000.0, "ETH": 3400.5, "SOL": 150.0}, ts_s=1000.0)
    assert len(lignes) == 3
    assert all(set(l) == {"coin", "ts", "mid"} for l in lignes)
    assert {l["coin"] for l in lignes} == {"BTC", "ETH", "SOL"}
    assert all(l["ts"] == 1000.0 for l in lignes)


def test_un_prix_invalide_est_ECARTE_jamais_comble():
    """Un mid absent, nul, négatif, NaN ou grotesque n'est pas un prix : on l'ignore, on ne
    fabrique rien. Un zéro marqué fausserait tout markout calculé dessus."""
    lignes = mu.lignes_marks(
        {"BTC": 61000.0, "A": 0.0, "B": -5.0, "C": None, "D": float("nan"),
         "E": float("inf"), "F": 1e15, "G": "pas un nombre"}, ts_s=1000.0)
    assert [l["coin"] for l in lignes] == ["BTC"]


def test_un_mid_en_chaine_numerique_est_accepte():
    """HL renvoie les mids en chaînes ('61000.0'). Les refuser jetterait tout l'univers."""
    lignes = mu.lignes_marks({"BTC": "61000.0", "ETH": "3400.5"}, ts_s=1000.0)
    assert len(lignes) == 2 and lignes[0]["mid"] == 61000.0


def test_les_doublons_intra_lot_sont_ecrases():
    lignes = mu.lignes_marks({"BTC": 61000.0, "btc": 61001.0}, ts_s=1000.0)
    assert len(lignes) == 1, "un coin deux fois dans un instantane = incoherence, on garde 1"


def test_un_horodatage_absent_ne_produit_rien():
    for ts in (0.0, -1.0, None, float("nan")):
        assert mu.lignes_marks({"BTC": 61000.0}, ts_s=ts) == []


def test_un_instantane_vide_ne_produit_rien():
    for m in (None, {}, {"": 1.0}):
        assert mu.lignes_marks(m, ts_s=1000.0) == []


# ─────────────── l'écriture large, sur le vrai flux ───────────────

def test_enregistrer_univers_ecrit_bien_le_flux(tmp_path):
    """Le point : ~200 coins écrits en une passe, contre ~6 avec la seule shortlist."""
    univers = {"COIN%03d" % i: 100.0 + i for i in range(200)}
    n = mu.enregistrer_univers(str(tmp_path), univers, ts_s=1000.0)
    assert n == 200
    from hl_observer.runtime.replay_recorder import read_replay_lines
    rows = read_replay_lines(str(tmp_path) + "/runtime/replay", "marks.jsonl")
    assert len(rows) == 200
    assert {r["coin"] for r in rows} == set(univers)


def test_enregistrer_univers_ne_LEVE_jamais(tmp_path):
    """Un marquage qui casse le scanner serait pire que l'absence de marks."""
    assert mu.enregistrer_univers(str(tmp_path), {"BTC": 61000.0}, ts_s=float("nan")) == 0
    assert mu.enregistrer_univers("/chemin/interdit/\x00", {"BTC": 1.0}, ts_s=1000.0) == 0


def test_aucun_prix_inutile_ecrit(tmp_path):
    """Un instantané tout invalide écrit 0 ligne — pas un fichier de zéros."""
    assert mu.enregistrer_univers(str(tmp_path), {"A": 0.0, "B": None}, ts_s=1000.0) == 0


# ─────────────── LE SCANNER EST-IL BRANCHÉ DESSUS ? ───────────────

def test_le_scanner_marque_bien_tout_l_univers():
    """« mention ≠ porte » : le module ne sert à rien si le scanner ne l'appelle pas. On
    vérifie que la boucle collecte les prix ET que l'enregistrement large est câblé."""
    import inspect
    from pathlib import Path
    src = Path(inspect.getsourcefile(
        __import__("tools.ecrire_carry_spot_inputs",
                   fromlist=["scanner"]))).read_text(encoding="utf-8")
    assert "univers_mids" in src, "la boucle doit collecter le prix de chaque coin"
    assert "enregistrer_univers" in src, "l'enregistrement large doit etre cable"


def test_la_fusion_publie_le_DELTA_pour_rendre_la_croissance_visible(tmp_path):
    """« Ce chiffre ne grandit jamais » : un total cumulé de 384 k cache sa propre croissance.
    La fusion publie donc le delta depuis la dernière fois — c'est lui qu'on regarde."""
    from hl_observer.runtime.replay_recorder import append_replay_lines, merge_replay
    base = tmp_path / "runtime" / "replay"
    base.mkdir(parents=True)
    append_replay_lines(str(base), "marks.jsonl",
                        [{"coin": "BTC", "ts": 1.0, "mid": 1.0}], max_bytes=10**9, max_lines=10**9)
    r1 = merge_replay(base)
    assert r1["depuis_la_derniere_fois"] == {}, "premiere fois : aucun point de comparaison"
    append_replay_lines(str(base), "marks.jsonl",
                        [{"coin": "ETH", "ts": 2.0, "mid": 2.0},
                         {"coin": "SOL", "ts": 3.0, "mid": 3.0}], max_bytes=10**9, max_lines=10**9)
    r2 = merge_replay(base)
    assert r2["depuis_la_derniere_fois"]["marks.jsonl"] == 2, "+2 marks depuis la fusion precedente"


def test_aucune_execution_reelle(tmp_path):
    mu.enregistrer_univers(str(tmp_path), {"BTC": 61000.0}, ts_s=1000.0)
    from hl_observer.runtime.replay_recorder import read_replay_lines
    rows = read_replay_lines(str(tmp_path) + "/runtime/replay", "marks.jsonl")
    assert rows and all("real_execution" not in r or r["real_execution"] is False for r in rows)
