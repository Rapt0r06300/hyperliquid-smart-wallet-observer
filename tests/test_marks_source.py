"""LA SOURCE DES MARKS — pourquoi 97,6 % des fills n'avaient pas de prix (21/07).

La whitelist copy était vide : 12 leaders évalués, 0 qualifiés. On croyait la porte trop
stricte ; elle n'avait **rien à juger**. Instrumentation : 88,4 % des fills perdus sur « pas
de mark ». Puis la mesure décisive — les marks lus s'arrêtaient **11 h avant** le dernier
fill, parce que le pipeline lisait `_merged/` figé pendant que les shards continuaient
d'être écrits. Après correction : **173 → 1778 mesures**, 2,4 % → 24,8 %.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.copy_wallet import marks_source as ms


# ─────────────── le mark le plus proche, AVANT ou APRÈS ───────────────

def test_un_mark_AVANT_le_fill_est_desormais_accepte():
    """🔴 L'ASYMÉTRIE QUI COÛTAIT LA MOITIÉ DES APPARIEMENTS. L'ancienne règle
    (`ts <= t <= ts+300`) rejetait un mark 30 s AVANT le fill tout en acceptant un mark
    290 s APRÈS. Rien ne justifie ça : le meilleur estimé du mid à l'instant du fill est
    le mark le plus PROCHE, des deux côtés."""
    pts = [(970.0, 100.0), (1290.0, 200.0)]
    r = ms.mark_le_plus_proche(pts, 1000.0, 300.0)
    assert r is not None and r[0] == 100.0, "le mark 30 s AVANT doit gagner"
    assert r[1] == pytest.approx(30.0)


def test_le_plus_proche_gagne_meme_si_les_deux_sont_dans_la_tolerance():
    pts = [(900.0, 1.0), (1010.0, 2.0)]
    assert ms.mark_le_plus_proche(pts, 1000.0, 300.0)[0] == 2.0


def test_la_tolerance_n_a_PAS_ete_elargie():
    """Le correctif corrige une asymétrie, il n'assouplit RIEN : au-delà de 300 s un mark
    n'est plus « le prix au moment du fill »."""
    assert ms.TOLERANCE_FILL_S == 300.0
    assert ms.mark_le_plus_proche([(600.0, 1.0)], 1000.0, 300.0) is None


def test_une_liste_vide_ne_fabrique_pas_de_prix():
    assert ms.mark_le_plus_proche([], 1000.0, 300.0) is None


# ─────────────── l'appariement dit TOUJOURS pourquoi il échoue ───────────────

def test_chaque_echec_porte_une_cause_nommee():
    """Sans cause, on ne distingue pas « ce leader trade un coin exotique » de « notre
    consolidation est en retard » — et c'est cette confusion qui a coûté 11 h de mesure."""
    m = {"BTC": [(1000.0, 50.0), (2800.0, 51.0)]}
    assert ms.apparier_avec_cause(m, coin="DOGE", ts=1000.0,
                                  horizon_s=1800.0)["cause"] == "COIN_SANS_MARK"
    assert ms.apparier_avec_cause(m, coin="BTC", ts=5000.0,
                                  horizon_s=1800.0)["cause"] == "PAS_DE_MARK_AU_FILL"
    assert ms.apparier_avec_cause(m, coin="BTC", ts=1000.0,
                                  horizon_s=99999.0)["cause"] == "PAS_DE_MARK_FORWARD"
    assert ms.apparier_avec_cause(m, coin="BTC", ts=0.0,
                                  horizon_s=1800.0)["cause"] == "HORODATAGE_ABSENT"


def test_un_appariement_reussi_transporte_son_ecart_temporel():
    """L'écart voyage avec la mesure : un appariement lointain doit rester contestable
    plus tard, pas se fondre anonymement dans une moyenne."""
    m = {"BTC": [(990.0, 50.0), (2805.0, 51.0)]}
    r = ms.apparier_avec_cause(m, coin="BTC", ts=1000.0, horizon_s=1800.0)
    assert r["ok"] is True
    assert r["mid_at_fill"] == 50.0 and r["mid_forward"] == 51.0
    assert r["ecart_fill_s"] == pytest.approx(10.0)
    assert r["ecart_forward_s"] == pytest.approx(5.0)


# ─────────────── LE CONTRÔLE QUI MANQUAIT : le recouvrement ───────────────

def test_des_marks_qui_s_arretent_avant_les_fills_sont_SIGNALES():
    """🔴 LE BUG A VÉCU 11 HEURES parce que le pipeline rendait 173 lignes au lieu de 7 000
    **sans rien dire**. Une mesure qui perd 97 % de sa matière doit le déclarer."""
    marks = {"BTC": [(0.0, 1.0), (3600.0, 1.0)]}           # s'arrêtent à t=3600
    fills = [7200.0, 10800.0, 14400.0]                      # commencent après
    d = ms.diagnostic_recouvrement(marks, fills)
    assert d["rompu"] is True
    assert d["marks_finissent_avant_les_fills_h"] == pytest.approx(3.0)
    assert "consolidation" in d["motif"]


def test_un_recouvrement_sain_n_alerte_pas():
    marks = {"BTC": [(0.0, 1.0), (100000.0, 1.0)]}
    d = ms.diagnostic_recouvrement(marks, [1000.0, 5000.0, 9000.0])
    assert d["rompu"] is False and d["motif"] == ""
    assert d["recouvrement_frac"] == pytest.approx(1.0)


def test_donnees_absentes_comptent_comme_ROMPU_pas_comme_SAIN():
    """Deny-by-default : l'absence de preuve n'est pas une preuve de santé."""
    assert ms.diagnostic_recouvrement({}, [1.0])["rompu"] is True
    assert ms.diagnostic_recouvrement({"BTC": [(1.0, 1.0)]}, [])["rompu"] is True


# ─────────────── la lecture des shards frais ───────────────

def test_les_shards_frais_sont_lus_EN_PLUS_du_consolide(tmp_path):
    """La cause racine : le pipeline lisait `_merged/marks.jsonl` figé à 10:06 pendant que
    `marks.<pid>.jsonl` était écrit jusqu'à 20:38. Dépendre d'une consolidation qui peut ne
    pas avoir tourné, c'est faire reposer une mesure sur une tâche de ménage."""
    base = tmp_path / "runtime" / "replay"
    (base / "_merged").mkdir(parents=True)
    (base / "_merged" / "candidates.jsonl").write_text("", encoding="utf-8")
    (base / "_merged" / "marks.jsonl").write_text(
        json.dumps({"coin": "BTC", "ts": 1000.0, "mid": 50.0}) + "\n", encoding="utf-8")
    (base / "marks.4242.jsonl").write_text(
        json.dumps({"coin": "BTC", "ts": 9000.0, "mid": 60.0}) + "\n", encoding="utf-8")
    m = ms.charger_marks(tmp_path)
    ts = [t for t, _ in m["BTC"]]
    assert 1000.0 in ts, "le consolide doit rester lu"
    assert 9000.0 in ts, "le shard FRAIS doit etre lu aussi — c'est tout le correctif"


def test_les_doublons_entre_consolide_et_shard_sont_fusionnes(tmp_path):
    """Un shard déjà consolidé serait compté deux fois : la densité paraîtrait doublée."""
    base = tmp_path / "runtime" / "replay"
    (base / "_merged").mkdir(parents=True)
    (base / "_merged" / "candidates.jsonl").write_text("", encoding="utf-8")
    ligne = json.dumps({"coin": "BTC", "ts": 1000.0, "mid": 50.0}) + "\n"
    (base / "_merged" / "marks.jsonl").write_text(ligne, encoding="utf-8")
    (base / "marks.1.jsonl").write_text(ligne, encoding="utf-8")
    assert len(ms.charger_marks(tmp_path)["BTC"]) == 1


def test_un_repertoire_sans_replay_ne_leve_pas(tmp_path):
    assert ms.charger_marks(tmp_path) == {}


# ─────────────── le pipeline complet ───────────────

def test_le_pipeline_ecrit_son_diagnostic_a_cote(tmp_path):
    """La whitelist doit pouvoir dire si son verdict repose sur une mesure complète ou sur
    un pipeline en retard. Un verdict sans son taux de couverture est un verdict aveugle."""
    from tools.ecrire_copy_whitelist import BRUTS_DEFAUT, FILLS_DEFAUT, construire_fills_forward
    import time
    now = time.time()
    base = tmp_path / "runtime" / "replay"
    (base / "_merged").mkdir(parents=True)
    (base / "_merged" / "candidates.jsonl").write_text("", encoding="utf-8")
    t0 = now - 7200.0
    marks = [json.dumps({"coin": "BTC", "ts": t0 + i * 10, "mid": 100.0 + i * 0.01})
             for i in range(400)]
    (base / "_merged" / "marks.jsonl").write_text("\n".join(marks) + "\n", encoding="utf-8")
    bruts = tmp_path / BRUTS_DEFAUT
    bruts.parent.mkdir(parents=True, exist_ok=True)
    bruts.write_text("\n".join(
        json.dumps({"adresse": "0xabc123def456", "coin": "BTC", "side": "B",
                    "ts_ms": int((t0 + 100 + i * 20) * 1000)}) for i in range(40)
    ) + "\n", encoding="utf-8")
    n = construire_fills_forward(tmp_path, horizon_min=30.0)
    assert n > 0, "avec des marks denses, la couverture ne doit pas etre nulle"
    diag = json.loads((tmp_path / FILLS_DEFAUT).with_suffix(".diagnostic.json")
                      .read_text(encoding="utf-8"))
    assert diag["mesures"] == n and diag["fills"] == 40
    assert 0.0 < diag["couverture_pct"] <= 100.0
    assert diag["real_execution"] is False


def test_aucune_execution_reelle():
    m = {"BTC": [(1000.0, 1.0), (2800.0, 1.0)]}
    r = ms.apparier(m, coin="BTC", ts=1000.0, horizon_s=1800.0)
    assert r is not None and "mid_at_fill" in r          # lire un prix n'est pas trader
