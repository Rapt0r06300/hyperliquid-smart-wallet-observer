"""L'ETA DE COLLECTE doit BOUGER avec le debit, et REFUSER plutot que rassurer.

CE QUE L'OPERATEUR A DEMANDE : << je veux voir un eta qui bouge et s'adapte au temps
restant selon le nombre de donnees collectees, pas comme une date fixe >>.

CE QUI BLOQUE REELLEMENT LE LABO, mesure le 22/11/2026 : non pas un volume d'octets, mais
le nombre de **journees UTC distinctes et DENSES** de signaux evaluables -- un signal dont
le carnet causal le precede de moins de 30 s, dans une journee portant au moins
`MIN_SIGNALS_PER_DAY` signaux. La porte exige `MINIMUM_SIGNAL_UTC_DAYS` journees.

D'OU VIENT L'ADAPTATION. Une journee UTC ne s'acquiert qu'une fois par jour calendaire, et
seulement si le debit la rend dense. Si le debit tombe, la journee en cours CESSE de
compter et l'ETA **recule** : c'est le comportement voulu, pas un defaut. Ces tests
verrouillent precisement ce recul -- sans eux, un ETA fige passerait pour correct.

ET TROIS REFUS, parce qu'un chiffre rassurant est pire que pas de chiffre :
debit nul -> `INFINI` ; debit non mesurable -> `INCONNU` ; jamais une duree inventee.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for dossier in ("tools", "src"):
    if str(RACINE / dossier) not in sys.path:
        sys.path.insert(0, str(RACINE / dossier))

import eta_donnees_labo as ETA  # noqa: E402

HEURE_S = 3600.0


def _ecrire_restore_courant(
    racine: Path, *, shards: int = 12, octets: int = 4096,
    release_assets: int | None = None,
    repository: str = "Rapt0r06300/hyperliquid-smart-wallet-observer",
) -> tuple[str, Path]:
    index = racine / "catalog" / "DATA_INDEX.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text('{"schema":"alina.index.v1","shards":[]}', encoding="utf-8")
    digest = hashlib.sha256(index.read_bytes()).hexdigest()
    recovery = racine / "runtime" / "recovery" / "full"
    recovery.mkdir(parents=True, exist_ok=True)
    (recovery / "RESTORE_REPORT.json").write_text(json.dumps({
        "status": "REPLAY_READY_COMPLETE",
        "repository": repository,
        "source_inventory_sha256": "c" * 64,
        "selection_scope": "ALL_SAFE_REPLAYABLE",
        "classification": {
            "expected_usable_shards": shards,
            "usable_shards": shards,
            "expected_usable_bytes": octets,
            "usable_bytes": octets,
            "materialization_complete": True,
            "failures": [],
        },
        "catalog_verification": {
            "safe_catalog_shards": shards,
            "required_release_assets": shards if release_assets is None else release_assets,
            "source_index_sha256": digest,
            "selection_families": ["copy_vault_fills"],
        },
    }), encoding="utf-8")
    return digest, recovery


def _cas(**ecarts):
    base = {
        "denses_acquis": 3, "requis": 6, "signaux_aujourdhui": 0,
        "seuil_par_jour": 10, "debit_par_heure": 600.0,
        "aujourdhui_deja_dense": False,
        "secondes_restantes_dans_la_journee": 10 * HEURE_S,
    }
    base.update(ecarts)
    return ETA.calculer_eta(**base)


# ------------------------------------------------------------------ les refus
def test_un_debit_NUL_rend_INFINI_jamais_une_duree():
    """La collecte eteinte ne doit pas produire un ETA : elle n'arrivera jamais."""
    verdict = _cas(debit_par_heure=0.0)
    assert verdict["statut"] == "INFINI"
    assert verdict["heures"] is None
    assert "eteinte" in verdict["motif"]


def test_un_debit_NON_MESURABLE_rend_INCONNU_et_pas_zero():
    """`None` veut dire << je n'ai pas su mesurer >>. Zero voudrait dire << rien n'arrive >>."""
    verdict = _cas(debit_par_heure=None)
    assert verdict["statut"] == "INCONNU"
    assert verdict["heures"] is None


def test_les_journees_DEJA_acquises_donnent_ATTEINT():
    verdict = _cas(denses_acquis=7, requis=6)
    assert verdict["statut"] == "ATTEINT"
    assert verdict["heures"] == 0.0
    assert verdict["manquantes"] == 0


# ------------------------------------------------------- l'ETA BOUGE avec le debit
def test_un_debit_PLUS_FAIBLE_allonge_l_ETA():
    """Le coeur de la demande : l'ETA suit le debit, il n'est pas une date fixe."""
    rapide = _cas(debit_par_heure=6_000.0, signaux_aujourdhui=0, seuil_par_jour=1_000)
    lent = _cas(debit_par_heure=600.0, signaux_aujourdhui=0, seuil_par_jour=1_000)
    assert rapide["heures"] < lent["heures"], (rapide, lent)


def test_un_debit_TROP_FAIBLE_fait_PERDRE_la_journee_en_cours_et_RECULER_l_ETA():
    """Si le seuil ne peut pas etre atteint avant minuit, la journee ne comptera pas :
    il faut une journee calendaire de PLUS. C'est le recul que l'operateur veut voir."""
    suffisant = _cas(debit_par_heure=1_000.0, seuil_par_jour=100,
                     secondes_restantes_dans_la_journee=10 * HEURE_S)
    insuffisant = _cas(debit_par_heure=1.0, seuil_par_jour=100_000,
                       secondes_restantes_dans_la_journee=HEURE_S)
    assert suffisant["statut"] == "EN_COURS"
    assert insuffisant["statut"] == "JOURNEE_EN_COURS_PERDUE"
    assert insuffisant["heures"] > suffisant["heures"]
    assert insuffisant["journees_calendaires_ensuite"] == insuffisant["manquantes"]


def test_des_signaux_DEJA_collectes_aujourdhui_raccourcissent_l_ETA():
    """<< s'adapte selon le nombre de donnees collectees >> : ce qui est deja acquis compte."""
    vide = _cas(signaux_aujourdhui=0, seuil_par_jour=1_000)
    avance = _cas(signaux_aujourdhui=900, seuil_par_jour=1_000)
    assert avance["heures"] < vide["heures"]


def test_une_journee_DEJA_dense_ne_se_refait_pas():
    deja = _cas(aujourdhui_deja_dense=True)
    assert deja["heures_pour_finir_aujourdhui"] == 0.0
    assert deja["journees_calendaires_ensuite"] == deja["manquantes"] - 1


def test_le_PLANCHER_calendaire_domine_quel_que_soit_le_debit():
    """Aucun debit ne fait apparaitre deux journees UTC le meme jour : 3 journees
    manquantes ne peuvent pas prendre moins de 2 journees calendaires."""
    verdict = _cas(denses_acquis=3, requis=6, debit_par_heure=10_000_000.0)
    assert verdict["heures"] >= 48.0, verdict


# ------------------------------------------------------- la densite, comme le labo
def test_une_journee_SOUS_le_seuil_ne_compte_pas_comme_dense():
    jour = ETA.JOUR_MS
    base = 10 * jour
    maigre = [base + i for i in range(3)]
    grasse = [base + jour + i for i in range(50)]
    bilan = ETA.jours_denses(maigre + grasse, seuil_par_jour=10)
    assert bilan["nombre_denses"] == 1, bilan
    assert bilan["denses"] == [base // jour + 1]


def test_un_horodatage_non_entier_ne_cree_pas_une_journee():
    bilan = ETA.jours_denses(["1700000000000", None, True, -5, 0], seuil_par_jour=1)
    assert bilan["nombre_denses"] == 0


# ------------------------------------------------------- l'affichage ne ment pas
def test_une_duree_INCONNUE_s_affiche_en_point_d_interrogation():
    assert ETA.duree_lisible(None) == "?"


def test_la_duree_lisible_est_juste():
    assert ETA.duree_lisible(0.5) == "30 min"
    assert ETA.duree_lisible(3.0) == "3 h 00 min"
    assert ETA.duree_lisible(49.5) == "2 j 01 h 30 min"


def test_la_duree_precise_affiche_jours_heures_minutes_secondes():
    assert ETA.duree_lisible_precise(93784) == "1 j 02 h 03 min 04 s"
    assert ETA.duree_lisible_precise(None) == "INCONNU"


def test_tous_les_besoins_live_sont_visibles_et_ne_cachent_pas_l_inconnu():
    lignes = ETA.besoins_live([
        {"statut": "MORE_DATA", "mesures": 8, "requis": 20,
         "restants": 12, "hypothese": "copy_vault_demo", "etude": "base"},
        {"statut": "MORE_DATA", "mesures": None, "requis": None,
         "restants": None, "hypothese": "copy_vault_l2", "etude": "oos"},
        {"statut": "PROVEN", "hypothese": "copy_vault_done", "etude": "base"},
    ], maintenant=datetime(2026, 11, 24, tzinfo=timezone.utc))
    texte = "\n".join(lignes)
    assert "demo [base]" in texte
    assert "8/20 j (40.0 %)" in texte
    assert "0 j 00 h 00 min 00 s" not in texte
    assert "l2 [oos]" in texte
    assert "ETA INCONNU" in texte
    assert "done [base]" in texte
    assert "PROVEN" in texte


def test_l_eta_lit_separement_alinasync_github_et_coffre(tmp_path):
    catalog_sha, recovery = _ecrire_restore_courant(tmp_path, release_assets=3)
    (recovery / "UNPACK_REPORT.json").write_text(json.dumps({
        "status": "SAFE_UNPACK_COMPLETE",
        "mode": "FULL_JSONL",
        "physical_jsonl_available": True,
        "streamable_gzip_available": True,
        "replay_read_mode": "JSONL",
        "catalog_index_sha256": catalog_sha,
        "certified_shards": 12,
        "unpacked_shards": 2,
    }), encoding="utf-8")
    (recovery / "SYNC_REPORT.json").write_text(json.dumps({
        "status": "REPLAY_READY_COMPLETE",
    }), encoding="utf-8")
    coffre = tmp_path / "runtime" / "coffre_certifie"
    coffre.mkdir(parents=True)
    (coffre / "COUVERTURE_PROJET.json").write_text(json.dumps({
        "genere_ms": 123_456,
        "complet": True, "cent_pour_cent": False,
        "couverture_pct": 92.5, "fichiers_de_donnees": 40,
    }), encoding="utf-8")

    sources = ETA.lire_sources_alinasync(tmp_path)
    lignes = "\n".join(ETA.lignes_sources_live(sources))
    assert sources["restore_verified"] is True
    assert sources["safe_shards"] == 12
    assert sources["unpacked_shards"] == 2
    assert sources["github_release_bound"] is True
    assert sources["coffre_genere_ms"] == 123_456
    assert "3 assets" in lignes
    assert "PARTIEL / À COMPLÉTER" in lignes
    assert "92.500 %" in lignes
    assert "ne deviennent des jours denses" in lignes


def test_coffre_scan_incomplet_est_affiche_explicitement(tmp_path):
    coffre = tmp_path / "runtime" / "coffre_certifie"
    coffre.mkdir(parents=True)
    (coffre / "COUVERTURE_PROJET.json").write_text(json.dumps({
        "genere_ms": 123_456,
        "complet": False, "cent_pour_cent": False,
        "couverture_pct": None, "fichiers_de_donnees": 40,
    }), encoding="utf-8")

    sources = ETA.lire_sources_alinasync(tmp_path)

    assert sources["coffre_status"] == "SCAN INCOMPLET"
    assert sources["coffre_scan_complete"] is False
    assert sources["coffre_couverture_pct"] is None
    assert "SCAN INCOMPLET" in "\n".join(ETA.lignes_sources_live(sources))


def test_coffre_refuse_un_recu_de_couverture_contradictoire(tmp_path):
    coffre = tmp_path / "runtime" / "coffre_certifie"
    coffre.mkdir(parents=True)
    (coffre / "COUVERTURE_PROJET.json").write_text(json.dumps({
        "genere_ms": 123_456,
        "complet": True, "cent_pour_cent": True,
        "couverture_pct": 92.5, "fichiers_de_donnees": 40,
    }), encoding="utf-8")

    sources = ETA.lire_sources_alinasync(tmp_path)

    assert sources["coffre_status"] == "REÇU INCOHÉRENT"
    assert sources["coffre_couverture_pct"] is None


def test_eta_ne_reparse_pas_le_gros_recu_restore_inchange_et_invalide_les_modifs(
    tmp_path, monkeypatch
):
    _ecrire_restore_courant(tmp_path)
    restore_path = tmp_path / "runtime" / "recovery" / "full" / "RESTORE_REPORT.json"
    original_read_text = Path.read_text
    restore_reads = 0

    def compter_lecture(path, *args, **kwargs):
        nonlocal restore_reads
        if path == restore_path:
            restore_reads += 1
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", compter_lecture)

    premier = ETA.lire_sources_alinasync(tmp_path)
    second = ETA.lire_sources_alinasync(tmp_path)
    assert premier["restore_verified"] is True
    assert second["safe_shards"] == 12
    assert restore_reads == 1

    report = json.loads(original_read_text(restore_path, encoding="utf-8"))
    report["classification"]["expected_usable_shards"] = 5
    report["classification"]["usable_shards"] = 5
    report["catalog_verification"]["safe_catalog_shards"] = 5
    restore_path.write_text(json.dumps(report), encoding="utf-8")
    stat = restore_path.stat()
    os.utime(restore_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))

    updated = ETA.lire_sources_alinasync(tmp_path)
    assert restore_reads == 2
    assert updated["restore_verified"] is True
    assert updated["safe_shards"] == 5


def test_un_rapport_seal_only_ne_compte_pas_comme_jsonl_deballe(tmp_path):
    catalog_sha, recovery = _ecrire_restore_courant(tmp_path)
    (recovery / "UNPACK_REPORT.json").write_text(json.dumps({
        # Ancien producteur : statut trompeur malgré le mode seal-only.
        "status": "SAFE_UNPACK_COMPLETE",
        "mode": "SEAL_ONLY",
        "physical_jsonl_available": False,
        "streamable_gzip_available": True,
        "replay_read_mode": "GZIP_STREAM",
        "catalog_index_sha256": catalog_sha,
        "certified_shards": 12,
        "unpacked_shards": 12,
    }), encoding="utf-8")

    sources = ETA.lire_sources_alinasync(tmp_path)
    texte = "\n".join(ETA.lignes_sources_live(sources))

    assert sources["unpack_verified"] is False
    assert sources["unpack_certified"] is False
    assert sources["unpacked_shards"] is None
    assert "JSONL non décompressés" in texte or "INCONNU" in texte


def test_un_recu_seal_only_courant_est_compte_comme_certifie_en_flux(tmp_path):
    catalog_sha, recovery = _ecrire_restore_courant(tmp_path)
    (recovery / "UNPACK_REPORT.json").write_text(json.dumps({
        "status": "SAFE_SEAL_CERTIFICATION_COMPLETE",
        "mode": "SEAL_ONLY",
        "physical_jsonl_available": False,
        "streamable_gzip_available": True,
        "replay_read_mode": "GZIP_STREAM",
        "catalog_index_sha256": catalog_sha,
        "certified_shards": 12,
        "unpacked_shards": 12,
    }), encoding="utf-8")

    sources = ETA.lire_sources_alinasync(tmp_path)
    texte = "\n".join(ETA.lignes_sources_live(sources))

    assert sources["unpack_certified"] is True
    assert sources["unpack_verified"] is False
    assert sources["unpacked_shards"] is None
    assert sources["certified_shards"] == 12
    assert "12 shards certifiés en flux" in texte
    assert "JSONL non décompressés" in texte


def test_un_deballage_d_un_autre_catalogue_est_refuse_par_eta(tmp_path):
    catalog_sha, recovery = _ecrire_restore_courant(tmp_path)
    (recovery / "UNPACK_REPORT.json").write_text(json.dumps({
        "status": "SAFE_UNPACK_COMPLETE",
        "mode": "FULL_JSONL",
        "physical_jsonl_available": True,
        "streamable_gzip_available": True,
        "replay_read_mode": "JSONL",
        "catalog_index_sha256": "d" * 64,
        "certified_shards": 12,
        "unpacked_shards": 12,
    }), encoding="utf-8")

    sources = ETA.lire_sources_alinasync(tmp_path)
    texte = "\n".join(ETA.lignes_sources_live(sources))

    assert sources["unpack_verified"] is False
    assert sources["unpacked_shards"] is None
    assert sources["unpack_issue"] == "CATALOG_SHA_MISMATCH"
    assert "rapport de déballage lié à un autre catalogue" in texte


def test_restore_et_unpack_d_un_catalogue_ancien_sont_refuses_par_eta(tmp_path):
    catalog = tmp_path / "catalog" / "DATA_INDEX.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"schema":"alina.index.v1","shards":[]}', encoding="utf-8")
    current_sha = hashlib.sha256(catalog.read_bytes()).hexdigest()
    stale_sha = "f" * 64
    recovery = tmp_path / "runtime" / "recovery" / "full"
    recovery.mkdir(parents=True)
    (recovery / "RESTORE_REPORT.json").write_text(json.dumps({
        "status": "REPLAY_READY_COMPLETE",
        "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "source_inventory_sha256": "c" * 64,
        "classification": {
            "expected_usable_shards": 1, "usable_shards": 1,
            "expected_usable_bytes": 100, "usable_bytes": 100,
            "materialization_complete": True, "failures": [],
        },
        "catalog_verification": {
            "safe_catalog_shards": 1,
            "required_release_assets": 1,
            "source_index_sha256": stale_sha,
            "selection_families": ["copy_vault_fills"],
        },
    }), encoding="utf-8")
    (recovery / "UNPACK_REPORT.json").write_text(json.dumps({
        "status": "SAFE_UNPACK_COMPLETE", "mode": "FULL_JSONL",
        "physical_jsonl_available": True, "replay_read_mode": "JSONL",
        "catalog_index_sha256": stale_sha,
        "certified_shards": 1, "unpacked_shards": 1,
    }), encoding="utf-8")

    sources = ETA.lire_sources_alinasync(tmp_path)

    assert sources["current_catalog_sha256"] == current_sha
    assert sources["restore_verified"] is False
    assert sources["safe_shards"] is None
    assert sources["unpack_certified"] is False
    assert sources["unpack_verified"] is False
    assert sources["unpack_issue"] == "CATALOG_SHA_MISMATCH"
    dashboard = "\n".join(ETA.lignes_dashboard_simple(
        tours=1,
        mesure={"motif": "PREMIERE_MESURE", "active_sources": 0, "source_count": 0},
        etat={"code": "INCONNU"},
        denses_acquis=0,
        requis=6,
        age_sonde_h=None,
        eta={"statut": "INCONNU", "heures": None},
        besoins=[],
        sources=sources,
        intervalle_s=2.0,
    ))
    assert "ancien catalogue" in dashboard


def test_dashboard_court_separe_safe_extraction_et_github_sans_ligne_trop_longue():
    lignes = ETA.lignes_dashboard_simple(
        tours=1,
        mesure={"motif": "PREMIERE_MESURE", "active_sources": 0, "source_count": 8},
        etat={"code": "EN_ATTENTE"},
        denses_acquis=2,
        requis=6,
        age_sonde_h=0.1,
        eta={"statut": "INCONNU", "heures": None},
        besoins=[],
        sources={
            "restore_verified": True,
            "safe_shards": 1_792_577,
            "safe_bytes": 142_923_240_926,
            "unpack_verified": False,
            "reported_unpacked_shards": 15_456,
            "unpack_issue": "UNPACK_CONTRACT_INCONSISTENT",
            "github_release_bound": True,
            "release_assets": 21_400,
            "coffre_couverture_pct": 90.75,
            "coffre_status": "PARTIEL / À COMPLÉTER",
            "coffre_fichiers": 31_601,
        },
        intervalle_s=2.0,
    )
    texte = "\n".join(lignes)

    assert any("SAFE RESTAURÉ" in ligne and "1,792,577" in ligne for ligne in lignes)
    assert any("SAFE RESTAURÉ" in ligne and "snapshot vérifié" in ligne for ligne in lignes)
    assert any("EXTRACTION" in ligne and "15,456" in ligne and "NON VÉRIFIÉS" in ligne for ligne in lignes)
    assert any("GITHUB" in ligne and "21,400" in ligne for ligne in lignes)
    assert any("COFFRE" in ligne and "31,601 fichiers" in ligne for ligne in lignes)
    assert max(map(len, lignes)) <= 100
    assert "téléchargement seul ≠ jour dense" in texte
    assert "q=quitter" in texte and "--detail=diag" in texte


def test_un_ancien_recu_incomplet_montre_son_compte_sans_le_certifier(tmp_path):
    catalog_sha, recovery = _ecrire_restore_courant(
        tmp_path, shards=1_792_577, octets=142_923_240_926,
        release_assets=21_400,
    )
    # Reproduit le reçu local : mode et compte présents, champs physiques absents.
    (recovery / "UNPACK_REPORT.json").write_text(json.dumps({
        "status": "SAFE_UNPACK_COMPLETE",
        "mode": "FULL_JSONL",
        "catalog_index_sha256": catalog_sha,
        "certified_shards": 1_792_577,
        "unpacked_shards": 15_456,
    }), encoding="utf-8")

    sources = ETA.lire_sources_alinasync(tmp_path)
    texte = "\n".join(ETA.lignes_sources_live(sources))

    assert sources["unpack_verified"] is False
    assert sources["unpacked_shards"] is None
    assert sources["reported_unpacked_shards"] == 15_456
    assert "15,456 annoncés par le reçu, non vérifiés et non comptés" in texte
    assert "REÇU NON VÉRIFIÉ (déclaré SAFE_UNPACK_COMPLETE)" in texte
    assert "| ALINASYNC DÉBALLAGE : SAFE_UNPACK_COMPLETE |" not in texte
    assert "1,792,577 shards / 133.1 Go" in texte


def test_un_restore_d_un_autre_depot_n_est_pas_compte_comme_source_safe(tmp_path):
    recovery = tmp_path / "runtime" / "recovery" / "full"
    recovery.mkdir(parents=True)
    (recovery / "RESTORE_REPORT.json").write_text(json.dumps({
        "status": "REPLAY_READY_COMPLETE",
        "repository": "example/another-repository",
        "classification": {"usable_shards": 12, "usable_bytes": 4096},
        "catalog_verification": {
            "required_release_assets": 3,
            "source_index_sha256": "f" * 64,
            "selection_families": ["copy_vault_fills"],
        },
    }), encoding="utf-8")

    sources = ETA.lire_sources_alinasync(tmp_path)

    assert sources["restore_verified"] is False
    assert sources["github_release_bound"] is False
    assert "INCONNU (restauration non certifiée)" in "\n".join(
        ETA.lignes_sources_live(sources)
    )


def test_eta_ne_declare_pas_des_shards_disponibles_sans_recu_valide(tmp_path):
    sources = ETA.lire_sources_alinasync(tmp_path)

    texte = "\n".join(ETA.lignes_sources_live(sources))

    assert "aucun shard SAFE certifié par le reçu" in texte
    assert "ces shards sont disponibles" not in texte


def test_le_resume_operateur_montre_vivant_progression_debit_et_eta(tmp_path):
    ruban = tmp_path / "fills.jsonl"
    ruban.write_text("{}\n", encoding="utf-8")
    mesure = {
        "lignes_par_minute": 12.5, "motif": None, "taille_octets": 42,
        "active_sources": 7, "source_count": 94, "recent_sources": 12,
        "active_source_paths": ["runtime/data/fills.jsonl", "runtime/data/l2.jsonl"],
    }
    etat = {"code": "ACTIF", "detail": "7/94 fichiers de données en croissance", "age_s": 0.4}
    eta = {"statut": "EN_COURS", "heures": 26.0}
    lignes = ETA.lignes_resume(
        tours=4, ruban=ruban, mesure=mesure, etat=etat,
        denses_acquis=3, requis=6, age_sonde_h=0.2, eta=eta,
        besoins=[{"statut": "MORE_DATA", "mesures": 8, "requis": 20,
                  "restants": 12, "hypothese": "copy_vault_demo"}],
    )
    texte = "\n".join(lignes)
    assert "SUIVI ACTUALISÉ" in texte
    assert "50.0 %" in texte
    assert "12.5 lignes/min" in texte
    assert "7/94 fichiers de flux locaux ont grandi entre les deux relevés" in texte
    assert "7/94 fichiers de flux ont grandi depuis le relevé précédent" in texte
    assert "94 fichiers ont grandi." not in texte
    assert "FLUX LOCAUX" in texte
    assert "FLUX EN CROISSANCE" in texte
    assert "runtime/data/fills.jsonl" in texte
    assert "runtime/data/l2.jsonl" in texte
    assert "archives et shards exclus" in texte
    assert "JSONL/NDJSON/CSV locaux seulement" in texte
    assert "12/94 modifiés récemment" in texte
    assert "ETA moteur" in texte
    assert "demo [base]" in texte


def test_eta_flux_exclut_les_json_de_etat_et_garde_les_tapes_append_only(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "collector_state.json").write_text('{"updated": true}', encoding="utf-8")
    (data / "fills.jsonl").write_text('{"fill": 1}\n', encoding="utf-8")
    (data / "pages.ndjson").write_text('{"page": 1}\n', encoding="utf-8")
    (data / "ticks.csv").write_text("ts,coin\n1,BTC\n", encoding="utf-8")
    (data / "ticks.jsonl.partial").write_text('{"partial": true}\n', encoding="utf-8")

    paths = ETA.trouver_flux_de_donnees(tmp_path)

    assert {path.name for path in paths} == {"fills.jsonl", "pages.ndjson", "ticks.csv"}


def _ecrire_suivi_collecteurs(racine: Path, payload: dict) -> None:
    journal = racine / "runtime" / "logs" / "economic-collector-watchdog.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def test_suivi_collecteurs_distingue_processus_actifs_et_gaps_causaux(tmp_path):
    now_ms = 1_800_000_000_000
    noms = ["userfills-live", "copy-vault-checkpoints"]
    _ecrire_suivi_collecteurs(tmp_path, {
        "ts_ms": now_ms - 5_000,
        "status": "ACTIVE",
        "requested": noms,
        "active": noms,
        "missing": [],
        "lease_renewal": "OK",
        "causal_protocol_status": "OK",
        "causal_evidence_reported_gaps": 1184,
        "causal_evidence_gaps_since_start": 3,
        "paper_read_only": True,
        "real_execution": False,
    })

    suivi = ETA.lire_suivi_collecteurs(tmp_path, maintenant_ms=now_ms)
    texte = "\n".join(ETA._lignes_suivi_collecteurs(suivi))

    assert suivi["code"] == "ACTIF"
    assert (suivi["actifs"], suivi["demandes"]) == (2, 2)
    assert suivi["gaps_causaux"] == 1184
    assert suivi["nouveaux_gaps"] == 3
    assert "2/2 actifs" in texte
    assert "écarts signalés: 1 184" in texte
    assert "+3" in texte


def test_eta_signale_un_heartbeat_fige_puis_redevient_actif_sans_redemarrer_watchdog(tmp_path):
    now_ms = 1_800_000_000_000
    heartbeat = tmp_path / "runtime" / "data" / "bbo_heartbeat.json"
    heartbeat.parent.mkdir(parents=True)
    heartbeat.write_text('{"ts":1800000000}', encoding="utf-8")
    os.utime(heartbeat, (now_ms / 1000 - 600, now_ms / 1000 - 600))
    _ecrire_suivi_collecteurs(tmp_path, {
        "ts_ms": now_ms - 5_000,
        "status": "ACTIVE",
        "requested": ["bbo-collector", "worker"],
        "active": ["bbo-collector", "worker"],
        "missing": [],
        "lease_renewal": "OK",
        "causal_protocol_status": "OK",
        "paper_read_only": True,
        "real_execution": False,
    })

    stale = ETA.lire_suivi_collecteurs(tmp_path, maintenant_ms=now_ms)

    assert stale["code"] == "DEGRADE"
    assert stale["flux_figes"] == ["bbo-collector"]
    lignes = "\n".join(ETA._lignes_suivi_collecteurs(stale))
    assert "ÉTATS COLLECTEURS" in lignes
    assert "ne garantit pas l'arrivée de nouvelles données" in lignes
    assert "meilleurs prix achat/vente — état non actualisé depuis (10 min)" in lignes

    os.utime(heartbeat, (now_ms / 1000 - 6_146, now_ms / 1000 - 6_146))
    old = ETA.lire_suivi_collecteurs(tmp_path, maintenant_ms=now_ms)
    lignes_anciennes = "\n".join(ETA._lignes_suivi_collecteurs(old))
    assert "meilleurs prix achat/vente — état non actualisé depuis (1 h 42 min)" in lignes_anciennes

    os.utime(heartbeat, (now_ms / 1000 - 10, now_ms / 1000 - 10))
    fresh = ETA.lire_suivi_collecteurs(tmp_path, maintenant_ms=now_ms)

    assert fresh["code"] == "ACTIF"
    assert fresh["flux_figes"] == []


def test_suivi_collecteurs_perime_ne_confirme_pas_une_activite_actuelle(tmp_path):
    now_ms = 1_800_000_000_000
    _ecrire_suivi_collecteurs(tmp_path, {
        "ts_ms": now_ms - 121_000,
        "status": "ACTIVE",
        "requested": ["worker"],
        "active": ["worker"],
        "missing": [],
        "lease_renewal": "OK",
        "causal_protocol_status": "OK",
        "paper_read_only": True,
        "real_execution": False,
    })

    suivi = ETA.lire_suivi_collecteurs(tmp_path, maintenant_ms=now_ms)

    assert suivi["code"] == "PERIME"
    assert "périmé" in "\n".join(ETA._lignes_suivi_collecteurs(suivi))


def test_suivi_collecteurs_refuse_une_derniere_ligne_tronquee(tmp_path):
    journal = tmp_path / ETA.JOURNAL_COLLECTEURS
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_bytes(b'{"status":"ACTIVE"')

    suivi = ETA.lire_suivi_collecteurs(tmp_path, maintenant_ms=1_800_000_000_000)

    assert suivi["code"] == "INCONNU"
    assert "incomplète" in suivi["motif"]


def test_suivi_collecteurs_affiche_une_erreur_de_supervision_sans_fausse_activite(tmp_path):
    now_ms = 1_800_000_000_000
    _ecrire_suivi_collecteurs(tmp_path, {
        "ts_ms": now_ms,
        "status": "WATCH_PASS_ERROR",
        "error": "OSError: lecture temporairement impossible",
        "paper_read_only": True,
        "real_execution": False,
    })

    suivi = ETA.lire_suivi_collecteurs(tmp_path, maintenant_ms=now_ms)

    assert suivi["code"] == "ERREUR"
    assert "ERREUR superviseur" in "\n".join(ETA._lignes_suivi_collecteurs(suivi))


def test_suivi_collecteurs_refuse_un_etat_non_paper_read_only(tmp_path):
    now_ms = 1_800_000_000_000
    for flags in (
        {"paper_read_only": False, "real_execution": False},
        {"paper_read_only": True, "real_execution": True},
    ):
        _ecrire_suivi_collecteurs(tmp_path, {
            "ts_ms": now_ms,
            "status": "ACTIVE",
            "requested": ["worker"],
            "active": ["worker"],
            "missing": [],
            "lease_renewal": "OK",
            "causal_protocol_status": "OK",
            **flags,
        })

        suivi = ETA.lire_suivi_collecteurs(tmp_path, maintenant_ms=now_ms)

        assert suivi["code"] == "INCONNU"
        assert "READ-ONLY" in suivi["motif"]


def test_dashboard_court_affiche_separement_processus_et_croissance_fichiers():
    lignes = ETA.lignes_dashboard_simple(
        tours=1,
        mesure={
            "motif": None,
            "active_sources": 5,
            "source_count": 95,
            "active_source_paths": [
                "runtime/data/copy_vault_l2_lane.jsonl",
                "runtime/data/copy_vault_bbo_lane.jsonl",
            ],
        },
        etat={"code": "ACTIF"},
        denses_acquis=0,
        requis=6,
        age_sonde_h=None,
        eta={"statut": "INCONNU", "heures": None},
        besoins=[],
        sources=None,
        intervalle_s=2.0,
        suivi_collecteurs={"code": "ACTIF", "actifs": 20, "demandes": 20,
                            "age_s": 4.0, "gaps_causaux": 1184, "nouveaux_gaps": 3},
    )

    texte = "\n".join(lignes)
    ligne_etat = next(ligne for ligne in lignes if "| ÉTAT" in ligne)
    assert "5/95 fichiers de flux ont grandi en 2.0 s" in ligne_etat
    ligne_ecritures = next(ligne for ligne in lignes if "FICHIERS ÉCRIVANTS" in ligne)
    assert "copy_vault_l2_lane.jsonl" in ligne_ecritures
    assert "copy_vault_bbo_lane.jsonl" in ligne_ecritures
    assert "+3 autres" in ligne_ecritures
    assert len(ligne_etat) <= 100
    assert "COLLECTEURS" in texte and "20/20 actifs" in texte
    assert "écarts signalés: 1 184" in texte
    assert "+3 depuis lancement du suivi" in texte


def test_premier_cycle_ne_fait_pas_passer_les_fichiers_en_actifs_ou_en_zero_sur_95():
    lignes = ETA.lignes_dashboard_simple(
        tours=1,
        mesure={"motif": "PREMIERE_MESURE", "active_sources": 0, "source_count": 95},
        etat={"code": "EN_ATTENTE"},
        denses_acquis=2,
        requis=6,
        age_sonde_h=7.6,
        eta={"statut": "INCONNU", "heures": None},
        besoins=[],
        sources=None,
        intervalle_s=2.0,
    )

    texte = "\n".join(lignes)
    ligne_etat = next(ligne for ligne in lignes if "| ÉTAT" in ligne)
    assert "PREMIÈRE MESURE — 95 fichiers repérés" in ligne_etat
    assert "premier débit après 2.0 s" in ligne_etat
    assert "0/95" not in texte
    assert "5/95" not in texte
    assert "calcul au prochain relevé" in texte
    assert "noms au prochain relevé" in texte
    assert "33.3 % (2/6 jours denses), âge 7.6 h" in texte


def test_dashboard_affiche_le_rapport_sonde_reel_et_non_le_nombre_de_fichiers():
    lignes = ETA.lignes_dashboard_simple(
        tours=2,
        mesure={
            "motif": "PREMIERE_MESURE",
            "active_sources": 0,
            "source_count": 94,
            "recent_sources": 54,
        },
        etat={"code": "EN_ATTENTE"},
        denses_acquis=2,
        requis=6,
        age_sonde_h=7.6,
        eta={"statut": "INCONNU", "heures": None},
        besoins=[],
        sources=None,
        intervalle_s=2.0,
        source_denses="runtime/reports/sonde_horloges_20261124.json",
    )

    ligne_sonde = next(ligne for ligne in lignes if "SONDE DENSITÉ" in ligne)
    assert "sonde_horloges_20261124.json" in ligne_sonde
    assert "94 fichiers" not in ligne_sonde
    assert "mise à jour 2.0 s" in "\n".join(lignes)


def test_resume_detaille_explique_la_composition_des_ecarts_de_preuve():
    lignes = ETA._lignes_detail_suivi_collecteurs({
        "detail": {
            "coverage_receipt_status": "UNMEASURABLE",
            "checkpoint_expirations": 1159,
            "invalid_rejected": 479,
            "input_rotations": 7,
            "writer_outages": 11,
            "checkpoint_queue_rejections": 0,
        }
    })

    assert lignes == [
        "| DÉTAIL PREUVE     : UNMEASURABLE | expirés 1159; rejets invalides 479; "
        "rotations 7; interruptions écrivain 11"
    ]


def test_dashboard_indique_l_age_reel_du_recensement_coffre(monkeypatch):
    monkeypatch.setattr(ETA.time, "time", lambda: 10_000.0)
    lignes = ETA.lignes_dashboard_simple(
        tours=1,
        mesure={"motif": "PREMIERE_MESURE", "active_sources": 0, "source_count": 8},
        etat={"code": "EN_ATTENTE"},
        denses_acquis=2,
        requis=6,
        age_sonde_h=0.1,
        eta={"statut": "INCONNU", "heures": None},
        besoins=[],
        sources={
            "coffre_couverture_pct": 90.75,
            "coffre_status": "PARTIEL / À COMPLÉTER",
            "coffre_fichiers": 31_601,
            "coffre_genere_ms": 4_600_000,
        },
        intervalle_s=2.0,
    )

    coffre = next(ligne for ligne in lignes if "COFFRE" in ligne)

    assert "MAJ 1 h 30 min" in coffre


def test_le_dashboard_par_defaut_est_court_et_garde_les_sources_reelles(tmp_path):
    lignes = ETA.lignes_dashboard_simple(
        tours=2,
        mesure={
            "lignes_par_minute": 12.5,
            "motif": None,
            "active_sources": 2,
            "source_count": 7,
        },
        etat={"code": "ACTIF"},
        denses_acquis=3,
        requis=6,
        age_sonde_h=30.0,
        eta={"statut": "INCONNU", "heures": None},
        besoins=[{
            "statut": "MORE_DATA",
            "mesures": 8,
            "requis": 20,
            "restants": 12,
            "hypothese": "copy_vault_demo",
        }],
        sources={
            "restore_verified": True,
            "safe_shards": 12,
            "safe_bytes": 1024,
            "unpack_verified": True,
            "unpacked_shards": 2,
            "github_release_bound": True,
            "release_assets": 3,
            "coffre_couverture_pct": 92.5,
            "coffre_status": "PARTIEL / À COMPLÉTER",
        },
        intervalle_s=2.0,
    )
    texte = "\n".join(lignes)
    assert len(lignes) <= 17  # ligne séparée : noms des fichiers qui écrivent
    assert "SUIVI ACTUALISÉ" in texte
    ligne_etat = next(ligne for ligne in lignes if "| ÉTAT" in ligne)
    assert "2/7 fichiers de flux ont grandi en 2.0 s" in ligne_etat
    assert len(ligne_etat) <= 100
    assert "PÉRIMÉE — dernière mesure 3/6 jours, âge 30.0 h" in texte
    assert "ETA MOTEUR        : INCONNU — sonde périmée depuis 30.0 h" in texte
    assert "12.5 lignes/min" in texte
    assert "collecter encore 12 j 00 h 00 min 00 s" in texte
    assert "2 JSONL physiques selon le reçu" in texte
    assert "GITHUB" in texte and "3 fichiers dans le reçu" in texte
    assert "BESOINS LIVE" not in texte


def test_un_flux_absent_reste_inconnu_et_ne_devient_pas_arrete():
    etat = ETA.etat_flux(None, {"lignes_par_minute": None, "motif": "RUBAN_ILLISIBLE"})
    assert etat["code"] == "INCONNU"
    assert "absent" in etat["detail"]


def test_barre_progression_est_ascii_et_bornee():
    assert ETA.barre_progression(50, largeur=10) == "#####....."
    assert ETA.barre_progression(None, largeur=4) == "????"


def test_sonde_de_densite_future_ou_non_finie_ne_produit_pas_de_progression():
    for age in (-0.1, float("nan"), float("inf")):
        pct, detail = ETA._progression_densite_affiche(2, 6, age)
        assert pct is None
        assert "horodatage de sonde invalide" in detail
        assert ETA._eta_moteur_affiche(
            {"statut": "EN_COURS", "heures": 12.0}, age
        ) == "INCONNU — horodatage de sonde invalide"


# ------------------------------------------------------- le debit refuse sans mentir
def test_un_ruban_ABSENT_rend_un_debit_INCONNU_et_le_nomme(tmp_path):
    mesure = ETA.MesureDeDebit(tmp_path / "jamais_ecrit.jsonl")
    lu = mesure.lire()
    assert lu["debit_par_heure"] is None
    assert lu["motif"] == "RUBAN_ILLISIBLE"


def test_la_PREMIERE_mesure_ne_pretend_pas_connaitre_le_debit(tmp_path, monkeypatch):
    """Une croissance se mesure entre DEUX instants : la premiere lecture ne sait rien."""
    ruban = tmp_path / "fills.jsonl"
    ruban.write_text("\n".join('{"ts_ms":1,"coin":"BTC"}' for _ in range(50)) + "\n",
                     encoding="utf-8")
    horloge = iter((0.0, 1.0))
    monkeypatch.setattr(ETA.time, "monotonic", lambda: next(horloge))
    mesure = ETA.MesureDeDebit(ruban)
    assert mesure.lire()["motif"] == "PREMIERE_MESURE"
    ruban.write_text(ruban.read_text(encoding="utf-8") + '{"ts_ms":2,"coin":"BTC"}\n', encoding="utf-8")
    assert mesure.lire()["debit_par_heure"] is not None   # la deuxieme, oui


def test_un_ruban_qui_GRANDIT_donne_un_debit_positif(tmp_path, monkeypatch):
    ruban = tmp_path / "fills.jsonl"
    ligne = '{"ts_ms":1700000000000,"coin":"BTC","px":1.0}\n'
    ruban.write_text(ligne * 100, encoding="utf-8")
    horloge = iter((0.0, 1.0))
    monkeypatch.setattr(ETA.time, "monotonic", lambda: next(horloge))
    mesure = ETA.MesureDeDebit(ruban)
    mesure.lire()                                  # amorce
    with ruban.open("a", encoding="utf-8") as fh:
        fh.write(ligne * 500)
    lu = mesure.lire()
    assert lu["debit_par_heure"] is not None
    assert lu["debit_par_heure"] > 0
    assert lu["lignes_par_minute"] > 0


def test_eta_agrege_tous_les_flux_et_signale_le_flux_actif(tmp_path, monkeypatch):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    ligne = '{"ts_ms":1700000000000,"coin":"BTC","px":1.0}\n'
    actif = data / "copy_vault_trades_lane.jsonl"
    immobile = data / "copy_vault_l2_lane.jsonl"
    actif.write_text(ligne * 100, encoding="utf-8")
    immobile.write_text(ligne * 100, encoding="utf-8")
    horloge = iter((0.0, 0.0, 60.0, 60.0))
    monkeypatch.setattr(ETA.time, "monotonic", lambda: next(horloge))
    mesure = ETA.MesureMultiFlux(tmp_path)
    mesure.lire()
    actif.write_text(actif.read_text(encoding="utf-8") + ligne * 100, encoding="utf-8")
    lu = mesure.lire()
    assert lu["source_count"] == 2
    assert lu["active_sources"] == 1
    assert lu["lignes_par_minute"] > 0
    assert ETA.etat_flux_global(lu)["code"] == "ACTIF"


def test_le_ruban_est_CHERCHE_a_plusieurs_endroits_et_on_dit_lesquels(tmp_path):
    """Un << ruban illisible >> doit nommer ce qu'il a cherche : sinon on croit a une
    collecte morte alors qu'on regardait au mauvais endroit (mesure du 22/11/2026)."""
    trouve, cherches = ETA.trouver_ruban(tmp_path)
    assert trouve is None
    assert len(cherches) >= 2
    cible = tmp_path / ETA.RUBANS_FILLS[1]
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text("{}\n", encoding="utf-8")
    trouve, _ = ETA.trouver_ruban(tmp_path)
    assert trouve == cible


def test_la_sonde_par_defaut_choisit_le_rapport_le_plus_recent(tmp_path):
    rapports = tmp_path / "runtime" / "reports"
    rapports.mkdir(parents=True)
    ancien = rapports / "sonde_horloges_20261122.json"
    recent = rapports / "sonde_horloges_20261123.json"
    ancien.write_text("{}", encoding="utf-8")
    recent.write_text("{}", encoding="utf-8")
    ancien.touch()
    recent.touch()
    os.utime(ancien, (1_000, 1_000))
    os.utime(recent, (2_000, 2_000))

    assert ETA.trouver_sonde(tmp_path) == recent


def test_l_eta_recharge_la_sonde_a_chaque_rafraichissement(tmp_path, monkeypatch, capsys):
    rapport = tmp_path / "runtime" / "reports" / "sonde_horloges_20261123.json"
    rapport.parent.mkdir(parents=True)

    def ecrire(jours: int) -> None:
        rapport.write_text(
            json.dumps({"appariement": {"jours_DENSES": jours}}), encoding="utf-8"
        )

    ecrire(0)

    def avancer_la_sonde(_secondes: float) -> None:
        ecrire(6)

    monkeypatch.setattr(ETA.time, "sleep", avancer_la_sonde)
    monkeypatch.setattr(ETA.os, "system", lambda _commande: 0)

    assert ETA.main(["--racine", str(tmp_path), "--tours", "2", "--detail"]) == 0
    assert capsys.readouterr().out.count("[ATTEINT]") == 1


def _etude(racine, nom, verdicts):
    d = racine / ETA.ETUDES / nom
    d.mkdir(parents=True, exist_ok=True)
    (d / "resultat.json").write_text(json.dumps({"report": {"verdicts": verdicts}}), encoding="utf-8")


def test_les_besoins_viennent_des_etudes_du_labo_et_le_passage_le_plus_recent_fait_foi(tmp_path):
    """24/11/2026 : l'ETA affichait ATTEINT (7/6 journees) pendant que le labo repondait MORE_DATA (8 jours sur 20)."""
    _etude(tmp_path, "20261117T120000000000Z", [                               # même étude, plus ancienne
        {"hypothesis": "copy_vault_slow_inventory_replication", "status": "MORE_DATA",
         "reason": "3 jour(s) hors echantillon < 20 requis", "required_independent_days": 20}])
    _etude(tmp_path, "20261124T113912441906Z-retro", [                         # AUTRE étude, même hypothèse
        {"hypothesis": "copy_vault_slow_inventory_replication", "status": "MORE_DATA",
         "reason": "marche avant sur jours independants", "required_independent_days": 20}])
    _etude(tmp_path, "20261124T111022604526Z", [
        {"hypothesis": "copy_vault_slow_inventory_replication", "status": "MORE_DATA",
         "reason": "8 jour(s) hors echantillon < 20 requis", "required_independent_days": 20},
        {"hypothesis": "copy_vault_fast_follow_taker_fills", "status": "REJECTED", "reason": "derive sous les frais"},
        {"hypothesis": "copy_vault_naive_mirror_taker", "status": "MORE_DATA", "reason": "l'IC 95 % contient zero"}])
    _etude(tmp_path, "20261123T013157066783Z-ouvertures", [
        {"hypothesis": "copy_vault_aggressive_open_drift", "status": "MORE_DATA",
         "reason": "16 jour(s), 25643 decision(s), 163 leader(s) ; il en faut au moins 30, 200 et 10"}])
    tous = ETA.besoins_du_labo(tmp_path)
    retro = [x for x in tous if x["etude"] == "retro"]
    assert len(retro) == 1 and retro[0]["restants"] is None                 # gardée à part, elle n'efface pas la base
    b = {x["hypothese"]: x for x in tous if x["etude"] != "retro"}
    assert (b["copy_vault_slow_inventory_replication"]["mesures"], b["copy_vault_slow_inventory_replication"]["requis"],
            b["copy_vault_slow_inventory_replication"]["restants"]) == (8, 20, 12)          # le 24/11, pas le 17/11
    assert b["copy_vault_slow_inventory_replication"]["date_estimee"].strftime("%d/%m") == "06/12"
    assert (b["copy_vault_aggressive_open_drift"]["mesures"], b["copy_vault_aggressive_open_drift"]["requis"]) == (16, 30)
    assert b["copy_vault_naive_mirror_taker"]["restants"] is None                          # jamais suppose
    texte = "\n".join(ETA.lignes_besoins(list(b.values())))
    assert "tranchee : REJECTED" in texte and "besoin non chiffre en jours" in texte


def test_une_echeance_deja_passee_demande_de_relancer_l_etude_et_n_est_pas_la_prochaine_date(tmp_path):
    """24/11/2026 : « prochaine hypothese tranchable vers le 17/11 » d'apres une etude du 12/11 jamais relancee."""
    from datetime import datetime, timezone

    _etude(tmp_path, "20261112T164759533677Z-ordres", [
        {"hypothesis": "copy_vault_leader_order_intent", "status": "MORE_DATA",
         "reason": "0 jour(s), 0 fill(s) ; il en faut au moins 5, 200 et 5"}])
    maintenant = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
    b = ETA.besoins_du_labo(tmp_path)
    assert ETA.echeance_passee(b[0], maintenant)
    assert "PASSEE : relancer l'etude" in "\n".join(ETA.lignes_besoins(b, maintenant))


def test_l_ecran_ne_dit_plus_ATTEINT_quand_les_etudes_attendent_des_jours(tmp_path, monkeypatch, capsys):
    rapport = tmp_path / "runtime" / "reports" / "sonde_horloges_20261123.json"
    rapport.parent.mkdir(parents=True)
    rapport.write_text(json.dumps({"appariement": {"jours_DENSES": 7}}), encoding="utf-8")
    from datetime import datetime, timedelta, timezone

    maintenant = datetime.now(timezone.utc).replace(microsecond=0)          # indépendant du jour où tourne le test
    _etude(tmp_path, maintenant.strftime("%Y%m%dT%H%M%S") + "000000Z", [
        {"hypothesis": "copy_vault_slow_inventory_replication", "status": "MORE_DATA",
         "reason": "8 jour(s) hors echantillon < 20 requis", "required_independent_days": 20}])
    monkeypatch.setattr(ETA.os, "system", lambda _commande: 0)
    assert ETA.main(["--racine", str(tmp_path), "--une-fois"]) == 0
    sortie = capsys.readouterr().out
    attendu = (maintenant + timedelta(days=12)).strftime("%d/%m")
    assert f"ETA LABO (etudes)            : prochaine hypothese tranchable vers le {attendu}" in sortie
    assert "8 / 20  jours -> encore  12 j" in sortie
    assert "plancher du moteur" in sortie                     # le seuil de 6 journees reste dit, mais a sa place


def test_le_debit_se_mesure_d_abord_sur_le_ruban_du_poll():
    """24/11/2026 : le ruban WS ne bougeait presque pas (0,0 ligne/min) ; la collecte passe par le poll REST."""
    assert ETA.RUBANS_FILLS[0] == "runtime/data/vault_fills_poll.jsonl"


def test_main_ne_projette_pas_un_eta_dense_depuis_le_debit_global_des_fichiers(
    tmp_path, monkeypatch, capsys
):
    sonde = tmp_path / "runtime" / "reports" / "sonde_horloges_live.json"
    sonde.parent.mkdir(parents=True)
    sonde.write_text(json.dumps({"appariement": {"jours_DENSES": 2}}), encoding="utf-8")

    class MesureGlobale:
        def __init__(self, _racine):
            pass

        def lire(self):
            return {
                "debit_par_heure": 60_000.0,
                "lignes_par_minute": 1_000.0,
                "octets_par_minute": 50_000.0,
                "taille_octets": 1_000_000,
                "age_s": 2.0,
                "motif": None,
                "source_count": 94,
                "active_sources": 7,
                "recent_sources": 12,
            }

    monkeypatch.setattr(ETA, "MesureMultiFlux", MesureGlobale)
    monkeypatch.setattr(ETA.os, "system", lambda _commande: 0)

    assert ETA.main(["--racine", str(tmp_path), "--une-fois"]) == 0

    sortie = capsys.readouterr().out
    ligne_eta = next(ligne for ligne in sortie.splitlines() if "ETA moteur" in ligne)
    assert "INCONNU" in ligne_eta
    assert "DÉBIT FLUX LOCAUX" in sortie
    assert "pas de débit de signaux évaluables" in sortie
