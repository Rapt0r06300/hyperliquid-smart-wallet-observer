"""[LANCEUR item 11] Stockage durable BORNÉ — quota, alarme pré-saturation, rétention EXPLICITE (jamais
de suppression silencieuse). Prouvé sans réseau.
"""
from __future__ import annotations

from pathlib import Path

from hl_observer.ops import quota_stockage as QS


def test_evaluer_quota_seuils_et_alerte_operateur():
    ok, alerte, satur = QS.evaluer_quota(50, 100), QS.evaluer_quota(85, 100), QS.evaluer_quota(120, 100)
    assert ok.etat == QS.ETAT_OK and not ok.alerte and ok.alerte_operateur() is None
    assert alerte.etat == QS.ETAT_ALERTE and alerte.alerte_operateur()["severity"] == "WARN"
    assert satur.etat == QS.ETAT_SATURATION and satur.alerte_operateur()["code"] == "STORAGE_SATURATION"


def test_garde_backpressure_refuse_le_depassement():
    g = QS.GardeStockage(quota_octets=1000)
    g.mettre_a_jour(900)
    ok, _v = g.autoriser_ecriture(50)                 # 950 <= 1000 -> autorisé
    ko, v2 = g.autoriser_ecriture(200)                # 1100 > 1000 -> REFUSÉ (backpressure)
    assert ok is True and ko is False and v2.etat == QS.ETAT_ALERTE


def test_plan_retention_vise_les_plus_vieux_avec_manifeste():
    shards = [QS.Shard("s_old.gz", 300, ts_ms=1000, sha256="aaa"),
              QS.Shard("s_mid.gz", 300, ts_ms=2000, sha256="bbb"),
              QS.Shard("s_new.gz", 300, ts_ms=3000, sha256="ccc")]
    plan = QS.plan_retention(shards, quota_octets=1000, usage_octets=900, ligne_basse=0.70)  # cible 700
    assert [s.chemin for s in plan.a_archiver] == ["s_old.gz"]      # le plus vieux d'abord
    assert plan.suffisant and plan.octets_liberes == 300 and plan.reste_octets == 600
    assert plan.manifeste[0]["sha256"] == "aaa" and plan.manifeste[0]["action"] == "ARCHIVER"


def test_plan_retention_rien_a_faire_sous_la_ligne_basse():
    plan = QS.plan_retention([QS.Shard("s.gz", 10, 1)], quota_octets=1000, usage_octets=500)
    assert plan.a_archiver == () and plan.suffisant


def test_mesurer_usage_somme_le_listing_injecte():
    u = QS.mesurer_usage(["runtime/data"], lister=lambda c: [("a.jsonl", 100, 1), ("b.gz", 250, 2)])
    assert u.octets == 350 and u.n_fichiers == 2


def test_executer_retention_archive_sans_suppression_silencieuse():
    plan = QS.PlanRetention(a_archiver=(QS.Shard("x.gz", 300, 1000, "aaa"),), octets_liberes=300,
                            reste_octets=600, suffisant=True)
    deplaces: list[str] = []
    r = QS.executer_retention(plan, dossier_archive="/arch",
                              deplaceur=lambda s, d: deplaces.append(s.chemin) or str(d / s.chemin))
    assert r["n"] == 1 and r["aucune_suppression_silencieuse"] is True
    assert r["archives"][0]["ok"] is True and deplaces == ["x.gz"]


def test_archiver_reel_deplace_le_fichier_integrite_conservee(tmp_path):
    src = tmp_path / "shard.jsonl.gz"
    src.write_bytes(b"data-immuable")
    shard = QS.Shard(str(src), 13, 1000, QS.sha256_fichier(src))
    dest = QS._archiver_reel(shard, tmp_path / "archive")
    assert dest is not None and Path(dest).is_file() and not src.exists()   # déplacé, pas supprimé
    assert shard.sha256 == QS.sha256_fichier(dest)                          # intégrité intacte
