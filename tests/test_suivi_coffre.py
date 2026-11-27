"""Écran de suivi coffre : rendu pur de l'avancement/ETA (lecture seule)."""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

_MOD = Path(__file__).resolve().parents[1] / "tools" / "suivi_coffre.py"
_spec = importlib.util.spec_from_file_location("suivi_coffre", _MOD)
sc = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(sc)


def test_barre():
    assert sc.barre(0, 10) == "[----------]"
    assert sc.barre(50, 10) == "[#####-----]"
    assert sc.barre(100, 10) == "[##########]"
    # bornage : valeurs hors [0,100]
    assert sc.barre(-5, 10) == "[----------]"
    assert sc.barre(999, 10) == "[##########]"


def test_fmt_duree():
    assert sc._fmt_duree(0) == "0s"
    assert sc._fmt_duree(90) == "1m30s"
    assert sc._fmt_duree(3660) == "1h01m"


def test_rendu_en_cours():
    now = time.time() * 1000
    st = {
        "stage": "CERTIFICATION", "pct": 42.0, "i": 12, "n": 50,
        "fichier": "vault_fills.jsonl", "octets_faits": 5_000_000,
        "octets_total": 12_000_000, "debit_mo_s": 3.2, "eta_s": 140,
        "termine": False, "updated_ms": now,
    }
    out = "\n".join(sc.rendre(st, maintenant_ms=now))
    assert "EN COURS" in out
    assert "42.0%" in out
    assert "12/50" in out
    assert "ETA estimée : ~2m20s" in out
    assert "vault_fills.jsonl" in out


def test_rendu_perime_sans_verification_ne_conclut_pas_a_inactif():
    now = time.time() * 1000
    st = {"stage": "CERTIFICATION", "pct": 10.0, "termine": False,
          "updated_ms": now - (sc.PERIME_S + 30) * 1000}
    out = "\n".join(sc.rendre(st, maintenant_ms=now))
    assert "SUIVI PÉRIMÉ" in out
    assert "INACTIF" not in out


def test_rendu_termine_avec_bilan():
    now = time.time() * 1000
    st = {"stage": "TERMINE", "pct": 100.0, "termine": True, "code": 0,
          "resume": {"deposes": 1234, "quarantaine": 5, "doublons": 2},
          "updated_ms": now}
    out = "\n".join(sc.rendre(st, maintenant_ms=now))
    assert "TERMINE" in out
    assert "1234" in out


def test_rendu_sans_statut():
    out = "\n".join(sc.rendre(None, maintenant_ms=time.time() * 1000))
    assert "En attente" in out


def test_statut_perime_reste_actif_si_le_verrou_confirme_le_processus():
    now = time.time() * 1000
    st = {"stage": "CERTIFICATION", "pct": 10.0, "termine": False,
          "eta_s": 120, "updated_ms": now - 90_000}
    out = "\n".join(sc.rendre(st, maintenant_ms=now, certificateur_actif=True))
    assert "EN COURS" in out
    assert "INACTIF" not in out
    assert "1m30s" in out


def test_eta_est_recomptee_depuis_la_derniere_mesure():
    now = time.time() * 1000
    st = {"stage": "CERTIFICATION", "pct": 10.0, "termine": False,
          "eta_s": 140, "updated_ms": now - 30_000}
    out = "\n".join(sc.rendre(st, maintenant_ms=now, certificateur_actif=True))
    assert "ETA estimée : ~1m50s" in out


def test_eta_reste_ancree_a_la_mesure_pendant_les_heartbeat():
    mesure_ms = time.time() * 1000 - 20_000
    now = mesure_ms + 20_000
    st = {"stage": "COMPRESSION", "pct": 10.0, "termine": False,
          "eta_s": 100, "eta_updated_ms": mesure_ms, "updated_ms": now}
    out = "\n".join(sc.rendre(st, maintenant_ms=now, certificateur_actif=True))
    assert "ETA estimée : ~1m20s" in out


def test_rendu_compression_affiche_compte_volume_et_fichiers_actifs():
    now = time.time() * 1000
    st = {"stage": "COMPRESSION", "termine": False,
          "compression_faits": 1, "compression_candidats": 3,
          "compression_octets_traites": 1000, "compression_octets_total": 6000,
          "compression_octets_compressees": 500,
          "compression_en_traitement": 2, "eta_s": 80,
          "eta_updated_ms": now, "updated_ms": now}
    out = "\n".join(sc.rendre(st, maintenant_ms=now, certificateur_actif=True))
    assert "Compression : 1/3 fichiers terminés" in out
    assert "Volume compressé confirmé" in out
    assert "Fichiers actuellement traités : 2" in out
    assert "ETA estimée : ~1m20s" in out


def test_rendu_debit_io_processus_est_distinct_du_volume_certifie():
    now = time.time() * 1000
    st = {"stage": "CERTIFICATION", "pct": 50.0, "termine": False,
          "octets_faits": 5_000_000, "octets_total": 10_000_000, "updated_ms": now}
    io = {"pid": 1234, "read_bytes": 20_000_000, "read_mo_s": 3.5}
    out = "\n".join(sc.rendre(st, maintenant_ms=now, certificateur_actif=True,
                             lecture_processus=io))
    assert "3.5 Mo/s" in out
    assert "Volume source confirmé" in out


def test_rendu_signale_un_calcul_actif_meme_si_les_lectures_disque_sont_nulles():
    now = time.time() * 1000
    st = {"stage": "CERTIFICATION", "pct": 50.0, "termine": False, "updated_ms": now}
    io = {"pid": 1234, "read_bytes": 100, "read_mo_s": 0.0, "cpu_percent": 96.0,
          "cpu_window_s": 5.0, "process_count": 1}
    out = "\n".join(sc.rendre(st, maintenant_ms=now, certificateur_actif=True,
                             lecture_processus=io))
    assert "0.0 Mo/s" in out
    assert "Activité CPU observée : 96% d'un cœur" in out


def test_rendu_distingue_debit_confirme_et_debit_disque():
    now = time.time() * 1000
    st = {"stage": "CERTIFICATION", "pct": 50.0, "termine": False, "updated_ms": now}
    progression = {"stage": "CERTIFICATION", "mo_s": 1.2,
                   "nouveaux_octets": int(1.2 * 1048576), "window_s": 5.0}
    out = "\n".join(sc.rendre(st, maintenant_ms=now, certificateur_actif=True,
                             progression_lot=progression))
    assert "Débit confirmé des fichiers terminés : 1.2 Mo/s" in out


def test_rendu_explique_quand_aucun_fichier_n_est_termine_dans_la_fenetre():
    now = time.time() * 1000
    st = {"stage": "CERTIFICATION", "pct": 50.0, "termine": False, "updated_ms": now}
    progression = {"stage": "CERTIFICATION", "mo_s": 0.0,
                   "nouveaux_octets": 0, "window_s": 3.0}
    out = "\n".join(sc.rendre(st, maintenant_ms=now, certificateur_actif=True,
                             progression_lot=progression))
    assert "Aucun fichier terminé dans cette fenêtre" in out


def test_sonde_debit_lecture_mesure_une_fenetre_reelle():
    sonde = sc._SondeDebitLecture(fenetre_s=5)
    premier = sonde.actualiser({"pid": 1234, "read_bytes": 0}, maintenant=10)
    assert "read_mo_s" not in premier
    mesure = sonde.actualiser({"pid": 1234, "read_bytes": 10 * 1048576}, maintenant=15)
    assert mesure["read_mo_s"] == 2.0
    assert mesure["window_s"] == 5


def test_sonde_mesure_le_calcul_cpu_quand_les_octets_disque_sont_stables():
    sonde = sc._SondeDebitLecture(fenetre_s=5)
    sonde.actualiser({"pid": 1234, "read_bytes": 100, "cpu_seconds": 10.0}, maintenant=10)
    mesure = sonde.actualiser({"pid": 1234, "read_bytes": 100, "cpu_seconds": 12.0}, maintenant=12)
    assert mesure["read_mo_s"] == 0.0
    assert mesure["cpu_percent"] == 100.0


def test_sonde_debit_confirme_est_calcule_sur_une_fenetre_de_statuts():
    sonde = sc._SondeAvancementStatut(fenetre_s=10)
    st = {"batch_id": "b1", "stage": "CERTIFICATION", "octets_faits": 10 * 1048576}
    assert sonde.actualiser(st, maintenant=10) is None
    st = {**st, "octets_faits": 14 * 1048576}
    mesure = sonde.actualiser(st, maintenant=14)
    assert mesure["nouveaux_octets"] == 4 * 1048576
    assert mesure["mo_s"] == 1.0
    mesure = sonde.actualiser(st, maintenant=25)
    assert mesure["mo_s"] == 0.0


def test_etape_terminee_ne_clot_pas_le_suivi_si_processus_encore_actif():
    now = time.time() * 1000
    st = {"stage": "TERMINE", "pct": 100.0, "termine": True, "code": 0,
          "updated_ms": now}
    out = "\n".join(sc.rendre(st, maintenant_ms=now, certificateur_actif=True))
    assert "toujours actif" in out.lower()
    assert "TERMINE (code 0)" not in out


def test_rendu_progression_interne_du_fichier_courant():
    now = time.time() * 1000
    st = {"stage": "CERTIFICATION", "pct": 50.0, "termine": False,
          "fichier": "bbo_tape.jsonl.gz", "fichier_phase": "LECTURE JSONL",
          "fichier_octets_lus": 25 * 1048576, "fichier_octets_total": 100 * 1048576,
          "fichier_lignes_lues": 500_000, "fichier_debit_mo_s": 8.0,
          "updated_ms": now}
    out = "\n".join(sc.rendre(st, maintenant_ms=now, certificateur_actif=True))
    assert "25.0 Mo / 100.0 Mo (25.0%)" in out
    assert "500 000" in out
    assert "8.0 Mo/s" in out


def test_barre_du_lot_ne_recycle_pas_le_pourcentage_estime_du_fichier():
    now = time.time() * 1000
    st = {"stage": "CERTIFICATION", "pct": 92.0, "pct_confirme": 87.0,
          "pct_estime": 92.0, "fichier_pct": 50.0, "fichier_phase": "HASH SOURCE",
          "termine": False, "updated_ms": now}
    out = "\n".join(sc.rendre(st, maintenant_ms=now, certificateur_actif=True))
    assert "Progression confirmée du lot" in out and "87.0%" in out
    assert "Fichier courant" in out and "50.0% (HASH SOURCE)" in out
