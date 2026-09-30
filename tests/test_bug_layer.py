"""[BUG-001..080] Preuve que la couche 'bugs data' est ADOSSEE a du code REEL et TESTE. Chaque BUG-NNN
est le miroir exact de son jumeau AUD-3NN ; ce test IMPORTE et EXERCE les modules qui les implementent
-> BUG-001..080 ne sont pas des cases cochees a vide : ils pointent vers des fonctions qui tournent.
Trace complete BUG -> module:fonction -> test dans docs/audit/BUG_001_080_DISPOSITION.md."""
from __future__ import annotations


def test_bug001_registre_blocked_external():
    from hl_observer.research.source_governance import RegistreBlockedExternal
    r = RegistreBlockedExternal(); r.bloquer("bybit", raison="reseau", condition_levee="reseau")
    assert r.est_bloque("bybit")


def test_bug002_modules_sans_appelant():
    from hl_observer.research.data_integrity import detecter_modules_sans_appelant
    assert detecter_modules_sans_appelant({"a": ["b"], "b": [], "orphelin": []}, points_entree=["a"])["modules_morts"] == ["orphelin"]


def test_bug003_074_success_zero_data():
    from hl_observer.research.data_honesty import interdire_success_si_zero_donnee
    assert interdire_success_si_zero_donnee("SUCCESS", 0)["honnete"] is False


def test_bug004_except_larges():
    from hl_observer.research.data_integrity import scanner_except_larges
    assert scanner_except_larges(["    except Exception:"])["n"] == 1


def test_bug006_derive_tasklist():
    from hl_observer.research.data_integrity import detecter_derive_tasklist
    assert detecter_derive_tasklist(["A"], ["B"])["coherent"] is False


def test_bug008_liveness_vs_progression():
    from hl_observer.research.stream_reliability import liveness_vs_progression
    assert liveness_vs_progression(socket_connecte=True, dernier_event_ts=0.0, maintenant=1000.0)["vivant_utile"] is False


def test_bug009_last_useful_ts():
    from hl_observer.research.stream_reliability import last_useful_event_ts
    assert last_useful_event_ts([{"ts": 2, "utile": True}, {"ts": 3, "utile": False}]) == 2


def test_bug010_ready_multi_venue():
    from hl_observer.research.venue_capabilities import registre_par_defaut
    assert registre_par_defaut().ready()["ready"] is True


def test_bug011_statuts_source():
    from hl_observer.research.data_mesh import DataMesh, REQUIRED
    m = DataMesh(); m.enregistrer("hl", statut=REQUIRED)
    assert m.sources_par_statut(REQUIRED) == ["hl"]


def test_bug012_stale_par_stream():
    from hl_observer.research.stream_reliability import seuils_stale_par_stream
    assert seuils_stale_par_stream({"ob": 0.0}, {"ob": 1.0}, maintenant=1000.0)["perimes"] == ["ob"]


def test_bug013_dlq():
    from hl_observer.research.stream_reliability import DeadLetterQueue
    q = DeadLetterQueue(); q.deposer({"x": 1}, "ERR"); assert q.compter() == 1


def test_bug014_migrations_schema():
    from hl_observer.research.stream_reliability import RegistreMigrationsSchema
    r = RegistreMigrationsSchema(); r.enregistrer(1, "init"); assert r.version_courante() == 1


def test_bug031_symbol_master_pit():
    from hl_observer.research.normalization_units import symbol_master_pit
    h = [{"venue": "x", "symbole": "B", "canonique": "OLD", "depuis": 0}]
    assert symbol_master_pit(h, "x", "B", 5)["canonique"] == "OLD"


def test_bug035_oi_normalise():
    from hl_observer.research.normalization_units import normaliser_open_interest
    assert normaliser_open_interest(2.0, unite="base", prix=50000.0)["oi_usd"] == 100000.0


def test_bug036_liquidation_side():
    from hl_observer.research.normalization_units import normaliser_sens_liquidation
    assert normaliser_sens_liquidation("long")["ordre_force"] == "SELL"


def test_bug039_mark_index_versionne():
    from hl_observer.research.normalization_units import MethodologieMarkIndex
    m = MethodologieMarkIndex(); m.enregistrer("v1", description="d", formule="f"); assert m.obtenir("v1")


def test_bug040_reject_revised_non_pit():
    from hl_observer.research.data_honesty import rejeter_donnees_revisees_non_pit
    assert rejeter_donnees_revisees_non_pit([{"revised": True, "asof": None}])["ok"] is False


def test_bug041_cache_paye_ttl():
    from hl_observer.research.source_governance import cache_paye_expire
    assert cache_paye_expire(0.0, 10.0, 100.0)["expire"] is True


def test_bug042_low_latency_policy():
    from hl_observer.research.source_governance import politique_basse_latence
    assert politique_basse_latence("nansen")["basse_latence_autorisee"] is False


def test_bug043_seuil_merge():
    from hl_observer.research.wallet_integrity import seuil_confiance_merge
    assert seuil_confiance_merge([{"a": "x", "b": "y", "confiance": 0.9}])["merges_retenus"] == [("x", "y")]


def test_bug044_sybils():
    from hl_observer.research.wallet_integrity import detecter_sybils
    assert detecter_sybils({("a", "b"): 0.99})["n"] == 1


def test_bug045_transferts_hors_pnl():
    from hl_observer.research.wallet_integrity import transferts_hors_pnl
    assert transferts_hors_pnl([{"type": "deposit", "montant": 100.0}])["transferts_exclus"] == 100.0


def test_bug046_survivorship():
    from hl_observer.research.wallet_integrity import correction_survivorship
    assert correction_survivorship(["a", "b"], ["a"])["biais_present"] is True


def test_bug047_wallets_liquides():
    from hl_observer.research.wallet_integrity import inclure_wallets_liquides
    assert inclure_wallets_liquides([{"id": "a", "liquide": False}])["cohorte_suspecte"] is True


def test_bug050_manipulation():
    from hl_observer.research.market_quality import filtrer_manipulation
    assert filtrer_manipulation([{"annule_apres_ms": 5}])["n_suspects"] == 1


def test_bug051_pannes_correlees():
    from hl_observer.research.market_quality import pannes_correlees
    assert pannes_correlees({"a": "DOWN", "b": "DOWN"})["panne_correlee"] is True


def test_bug052_consensus_independance():
    from hl_observer.research.wallet_integrity import consensus_pondere_independance
    assert consensus_pondere_independance({"w1": 1.0, "w2": 1.0}, {"w1": "G", "w2": "G"})["n_voix_independantes"] == 1


def test_bug053_054_ablation_sources():
    from hl_observer.research.data_mesh import ablation_sources
    assert ablation_sources(["A"], lambda r: 1.0 - (0.5 if "A" in r else 0.0))[0]["valeur_marginale"] == 0.5


def test_bug055_lineage_ligne():
    from hl_observer.research.storage_partition import lineage_ligne
    assert lineage_ligne(1, ["hl"])["tracable"] is True


def test_bug056_057_bronze_hash():
    from hl_observer.research.storage_partition import hash_partition
    from hl_observer.research.medallion import bronze_immuable
    assert bronze_immuable([{"x": 1}])["immutable"] is True
    assert hash_partition([{"x": 1}]) != hash_partition([{"x": 2}])


def test_bug059_adaptateur_unique():
    from hl_observer.research.data_integrity import adaptateur_unique_live_replay
    assert adaptateur_unique_live_replay({"hl": ["a", "b"]})["unifie"] is False


def test_bug062_changement_api():
    from hl_observer.research.market_quality import detecter_changement_api
    assert detecter_changement_api({"a": "int"}, {"a": "str"})["a_change"] is True


def test_bug063_pin_endpoints():
    from hl_observer.research.source_governance import pin_versions_endpoints
    assert pin_versions_endpoints({"x": {"version": "latest", "endpoint": "e"}})["toutes_pinnees"] is False


def test_bug064_licences():
    from hl_observer.research.source_governance import RegistreLicences
    r = RegistreLicences(); r.enregistrer("n", licence="pro", quota_req_jour=1, cout_usd_mois=1.0)
    assert r.cout_total_mois() == 1.0


def test_bug065_read_only_key():
    from hl_observer.research.source_governance import politique_cle_read_only
    assert politique_cle_read_only(["withdraw"])["read_only"] is False


def test_bug066_conformite():
    from hl_observer.research.source_governance import RegistreConformite
    c = RegistreConformite(); c.revue("x", "OK"); assert c.utilisable("x") is True


def test_bug067_dashboard_sante():
    from hl_observer.research.source_governance import dashboard_sante_mesh
    assert dashboard_sante_mesh({"a": "DOWN"})["global_ok"] is False


def test_bug068_sla():
    from hl_observer.research.source_governance import sla_source
    assert sla_source({"disponibilite": 0.5, "latence_ms": 10})["respecte_sla"] is False


def test_bug069_onboarding():
    from hl_observer.research.source_governance import checklist_onboarding
    assert checklist_onboarding({})["complet"] is False


def test_bug070_retrait():
    from hl_observer.research.source_governance import politique_retrait
    assert politique_retrait({})["retirable"] is False


def test_bug071_collecteurs_doublons():
    from hl_observer.research.data_integrity import detecter_collecteurs_doublons
    cols = [{"nom": "a", "venue": "h", "stream": "b"}, {"nom": "c", "venue": "h", "stream": "b"}]
    assert detecter_collecteurs_doublons(cols)["doublons"] == ["c"]


def test_bug072_correspondance():
    from hl_observer.research.data_integrity import correspondance_registre_lanceur_superviseur
    assert correspondance_registre_lanceur_superviseur(["a"], [], ["a"])["coherent"] is False


def test_bug075_compteur_events_utiles():
    from hl_observer.research.stream_reliability import compteur_evenements_utiles
    assert compteur_evenements_utiles({"A": [{"utile": False}]})["consommateurs_morts"] == ["A"]


def test_bug076_quarantaine_champs():
    from hl_observer.research.data_honesty import quarantaine_champs_inconnus
    assert quarantaine_champs_inconnus({"x": 1, "y": 2}, ["x"])["quarantaine"] == ["y"]


def test_bug077_zeros_inventes():
    from hl_observer.research.data_honesty import distinguer_zero
    assert distinguer_zero(0, mesuree=False)["valeur"] is None


def test_bug078_carry_forward():
    from hl_observer.research.data_honesty import detecter_carry_forward_silencieux
    serie = [{"valeur": 1, "source_ts": 1}, {"valeur": 1, "source_ts": 1}]
    assert detecter_carry_forward_silencieux(serie)["carry_forward"] is True


def test_bug080_ressources_par_source():
    from hl_observer.research.data_integrity import attribuer_ressources_par_source
    assert attribuer_ressources_par_source({"hl": {"cpu": 1.0}})["total"]["cpu"] == 1.0
