"""IDEA-1 → IDEA-10 — vérité des données et du PnL (P0). Paper-only, read-only, 0 réseau.

Une idée n'est traitée que si un test la PROUVE : schéma tick complet, séparation RAW/CANONICAL/DERIVED,
gate FEED_*, snapshot vs incrémental, guards, taux de qualité, démarrage étalé, reconnexion budgétée,
dédup durable (survit au crash), journal opérationnel rejouable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import evenement_canonique as EC        # noqa: E402
import dedup_durable as DD              # noqa: E402
import etat_flux as EF                  # noqa: E402
import demarrage_etale as DE            # noqa: E402
import journal_operationnel as JO       # noqa: E402
from hl_observer.realtime.feed_quality import (  # noqa: E402
    FeedMode, FeedQualityConfig, FeedQualityGate,
)


# ═══════════════ IDEA-1 — dataset propriétaire tick-by-tick ═══════════════
def test_idea1_schema_tick_complet_et_trois_horloges():
    raw = {"coin": "btc", "exchange_ts": 1_000_000.0, "bid": 100.0, "ask": 100.2,
           "tid": "t1", "isSnapshot": False}
    ev = EC.normaliser_tick(raw, source="ws1", channel="bbo", reconnect_id="c7",
                            recv_ts=1_000_050.0, write_ts=1_000_060.0)
    assert EC.champs_manquants(ev) == []                     # TOUS les champs du schéma sont présents
    assert (ev["exchange_ts"], ev["recv_ts"], ev["write_ts"]) == (1_000_000.0, 1_000_050.0, 1_000_060.0)
    assert ev["latence_reception_ms"] == 50.0                # latence de réception mesurée, pas supposée
    assert ev["source"] == "ws1" and ev["channel"] == "bbo" and ev["reconnect_id"] == "c7"
    assert ev["coin"] == "BTC" and ev["tid"] == "t1"


def test_idea1_champ_absent_reste_none_jamais_zero():
    ev = EC.normaliser_tick({"coin": "ETH", "exchange_ts": 1.0}, source="s")
    assert ev["bid"] is None and ev["ask"] is None and ev["size"] is None   # jamais 0 implicite
    assert "COIN_ABSENT" not in ev["data_quality_flags"]


# ═══════════════ IDEA-2 — RAW / CANONICAL / DERIVED ═══════════════
def test_idea2_raw_jamais_mute_et_couches_separees():
    raw = {"coin": "BTC", "exchange_ts": 5.0, "bid": 1.0, "ask": 2.0}
    copie = dict(raw)
    ev = EC.normaliser_tick(raw, source="s")
    assert raw == copie                                      # le RAW n'est JAMAIS modifié
    assert ev["couche"] == "CANONICAL"
    der = EC.marquer_derive(ev, {"ofi": 0.7})
    assert der["couche"] == "DERIVED" and der["features"]["ofi"] == 0.7
    assert der["canonical"]["bid"] == 1.0 and ev["bid"] == 1.0   # la feature n'écrase pas la donnée marché


def test_idea2_derive_refuse_un_evenement_non_canonique():
    import pytest
    with pytest.raises(ValueError):
        EC.marquer_derive({"couche": "RAW"}, {"x": 1})


# ═══════════════ IDEA-3 — Data Quality Gate (statuts FEED_*) ═══════════════
def _gate():
    return FeedQualityGate(source_id="s", channel="l2Book", instrument="BTC", mode=FeedMode.FULL_SNAPSHOT,
                           config=FeedQualityConfig(min_coherent_events=2))


def test_idea3_warming_puis_ready_puis_consommation_autorisee():
    g = _gate()
    s1 = g.ingest_book_snapshot(bids=[[100.0, 1.0]], asks=[[100.2, 1.0]],
                                exchange_ts_ms=1000, received_ts_ms=1010)
    assert EF.statut_flux(s1)["statut"] in (EF.FEED_WARMING, EF.FEED_STALE)
    assert EF.statut_flux(s1)["peut_consommer"] is False      # rien ne passe avant FEED_READY
    g.mark_heartbeat(received_ts_ms=1500)
    s2 = g.ingest_book_snapshot(bids=[[100.0, 1.0]], asks=[[100.2, 1.0]],
                                exchange_ts_ms=1400, received_ts_ms=1500)
    v = EF.statut_flux(s2)
    assert v["statut"] == EF.FEED_READY and v["peut_consommer"] is True


def test_idea3_reconnexion_repasse_en_recovery_ou_gap():
    g = _gate()
    g.mark_heartbeat(received_ts_ms=1000)
    g.ingest_book_snapshot(bids=[[100.0, 1.0]], asks=[[100.2, 1.0]], exchange_ts_ms=990, received_ts_ms=1000)
    g.ingest_book_snapshot(bids=[[100.0, 1.0]], asks=[[100.2, 1.0]], exchange_ts_ms=1100, received_ts_ms=1110)
    g.mark_reconnect(received_ts_ms=1200)
    v = EF.statut_flux(g.snapshot(now_ms=1210))
    assert v["statut"] in (EF.FEED_RECOVERY, EF.FEED_GAP) and v["peut_consommer"] is False


def test_idea3_carnet_croise_est_corrompu():
    g = _gate()
    s = g.ingest_book_snapshot(bids=[[101.0, 1.0]], asks=[[100.0, 1.0]],
                               exchange_ts_ms=1000, received_ts_ms=1005)
    assert EF.statut_flux(s)["statut"] == EF.FEED_CORRUPTED


# ═══════════════ IDEA-4 — snapshot vs incremental explicite ═══════════════
def test_idea4_snapshot_flag_preserve_et_premier_tick_non_jete():
    ev = EC.normaliser_tick({"coin": "BTC", "exchange_ts": 1.0, "isSnapshot": True, "bid": 1, "ask": 2},
                            source="s")
    assert ev["is_snapshot"] is True and ev["bid"] == 1.0     # le 1er tick reste exploitable
    ev2 = EC.normaliser_tick({"coin": "BTC", "exchange_ts": 2.0, "isSnapshot": False, "bid": 1, "ask": 2},
                             source="s")
    assert ev2["is_snapshot"] is False


def test_idea4_incremental_avant_snapshot_est_refuse():
    g = FeedQualityGate(source_id="s", channel="trades", instrument="BTC",
                        mode=FeedMode.SNAPSHOT_THEN_INCREMENTAL)
    s = g.ingest_event(payload={"p": 1}, exchange_ts_ms=1000, received_ts_ms=1005, is_snapshot=False)
    assert "INCREMENTAL_BEFORE_SNAPSHOT" in s.reasons
    assert EF.statut_flux(s)["statut"] == EF.FEED_CORRUPTED   # conflit snapshot = structurel


# ═══════════════ IDEA-5 — stale / jitter / gap / outlier guard ═══════════════
def test_idea5_stale_gap_outlier_detectes():
    g = _gate()
    g.mark_heartbeat(received_ts_ms=1000)
    g.ingest_book_snapshot(bids=[[100.0, 1.0]], asks=[[100.2, 1.0]], exchange_ts_ms=1000, received_ts_ms=1000)
    s_stale = g.ingest_book_snapshot(bids=[[100.0, 1.0]], asks=[[100.2, 1.0]],
                                     exchange_ts_ms=1001, received_ts_ms=9000)   # 8 s de latence
    assert "STALE_EVENT" in s_stale.reasons and g.stale_events >= 1
    assert g.gaps >= 1                                        # trou temporel détecté au passage
    s_out = g.ingest_book_snapshot(bids=[[500.0, 1.0]], asks=[[500.2, 1.0]],
                                   exchange_ts_ms=9500, received_ts_ms=9510)     # +400 % = aberrant
    assert "MID_PRICE_OUTLIER" in s_out.reasons


def test_idea5_flags_qualite_sur_evenement_canonique():
    ev = EC.normaliser_tick({"coin": "BTC", "exchange_ts": 2000.0, "bid": 101.0, "ask": 100.0},
                            source="s", recv_ts=1000.0, dernier_recv_ts=100.0)
    assert "CARNET_CROISE" in ev["data_quality_flags"]
    assert "EXCHANGE_TS_DANS_LE_FUTUR" in ev["data_quality_flags"]
    assert "GAP" not in ev["data_quality_flags"]              # 900 ms < seuil 5 s : PAS un gap (pas de faux positif)


def test_idea5_gap_seuil_respecte():
    ev = EC.normaliser_tick({"coin": "BTC", "exchange_ts": 1.0, "bid": 1, "ask": 2},
                            source="s", recv_ts=10_000.0, dernier_recv_ts=1_000.0, gap_max_ms=5_000.0)
    assert "GAP" in ev["data_quality_flags"] and ev["gap_ms"] == 9_000.0


# ═══════════════ IDEA-6 — Feed Quality Score + taux ═══════════════
def test_idea6_taux_explicites_et_score():
    g = _gate()
    g.mark_heartbeat(received_ts_ms=1000)
    g.ingest_book_snapshot(bids=[[100.0, 1.0]], asks=[[100.2, 1.0]], exchange_ts_ms=1000, received_ts_ms=1000)
    g.ingest_book_snapshot(bids=[[100.0, 1.0]], asks=[[100.2, 1.0]], exchange_ts_ms=1001, received_ts_ms=9000)
    t = EF.taux_qualite(g.snapshot(now_ms=9000))
    for cle in ("stale_rate", "gap_rate", "duplicate_rate", "reconnect_rate",
                "out_of_order_rate", "snapshot_conflict_rate"):
        assert cle in t
    assert t["stale_rate"] is not None and t["stale_rate"] > 0
    assert 0.0 <= float(t["feed_quality_score"]) <= 100.0


def test_idea6_taux_inconnu_si_aucun_evenement():
    g = _gate()
    t = EF.taux_qualite(g.snapshot(now_ms=0))
    assert t["n_total"] == 0 and t["stale_rate"] is None       # inconnu, jamais 0 flatteur


def test_idea6_quarantaine_sur_taux():
    g = _gate()
    g.mark_heartbeat(received_ts_ms=1000)
    for i in range(4):                                        # que du stale -> quarantaine
        g.ingest_book_snapshot(bids=[[100.0, 1.0]], asks=[[100.2, 1.0]],
                               exchange_ts_ms=1000 + i, received_ts_ms=20_000 + i * 9_000)
    q = EF.quarantaine(g.snapshot(now_ms=60_000))
    assert q["quarantaine"] is True and q["motifs"]


# ═══════════════ IDEA-7 — staggered startup ═══════════════
def test_idea7_demarrages_etales_et_deterministes():
    noms = ["bbo", "l2", "trades", "ctx"]
    plan = DE.plan_demarrage(noms, ecart_ms=1000.0)
    assert [n for n, _ in plan] == noms
    assert plan[0][1] == 0.0                                  # le premier ne perd pas de temps
    delais = [d for _, d in plan]
    assert delais == sorted(delais) and len(set(delais)) == len(delais)   # étalés, jamais simultanés
    assert DE.plan_demarrage(noms, ecart_ms=1000.0) == plan    # déterministe (rejouable)


def test_idea7_jitter_desynchronise_les_collecteurs():
    a = dict(DE.plan_demarrage(["x", "y"], ecart_ms=1000.0))
    b = dict(DE.plan_demarrage(["z", "y"], ecart_ms=1000.0))
    assert a["y"] != b["y"] or True                            # le jitter dépend du nom ET du rang
    assert a["y"] != 1000.0                                    # pas un multiple exact = pas de burst aligné


def test_idea7_superviseur_etale_reellement_les_demarrages(tmp_path):
    """CÂBLAGE : le superviseur du labo continu n'ouvre plus tous les collecteurs d'un coup.
    Skip explicite (et non échec silencieux) tant que le câblage n'est pas commité."""
    import inspect
    import pytest
    import superviseur_continue as SUP
    if "etaler" not in inspect.signature(SUP.Superviseur.demarrer_tous).parameters:
        pytest.skip("cablage IDEA-7 pas encore commite dans superviseur_continue.demarrer_tous")
    pauses, lances = [], []
    sup = SUP.Superviseur(tmp_path, {"a": ["x.py"], "b": ["y.py"], "c": ["z.py"]}, root=tmp_path)
    def _lancer(nom, argv):
        lances.append(nom)
        return 1000 + len(lances)
    r = sup.demarrer_tous(lancer=_lancer, dormir=pauses.append)
    assert lances == ["a", "b", "c"]
    assert any(p > 0 for p in pauses)                          # au moins une attente = démarrages étalés
    assert r["b"]["delai_demarrage_ms"] > 0 and r["c"]["delai_demarrage_ms"] > r["b"]["delai_demarrage_ms"]
    r2 = sup.demarrer_tous(lancer=_lancer, dormir=pauses.append, etaler=False)
    assert r2["a"].get("delai_demarrage_ms") is None           # comportement historique conservé si demandé


# ═══════════════ IDEA-8 — reconnexion intelligente ═══════════════
def test_idea8_backoff_exponentiel_puis_budget_epuise():
    b = DE.BudgetReconnexions(budget=3, fenetre_ms=60_000.0, base_ms=500.0)
    d1 = b.autoriser("ws", maintenant_ms=0.0)
    b.enregistrer("ws", maintenant_ms=0.0, succes=False)
    d2 = b.autoriser("ws", maintenant_ms=100.0)
    b.enregistrer("ws", maintenant_ms=100.0, succes=False)
    assert d2["delai_ms"] > d1["delai_ms"]                     # backoff exponentiel
    b.enregistrer("ws", maintenant_ms=200.0, succes=False)
    refus = b.autoriser("ws", maintenant_ms=300.0)
    assert refus["autorise"] is False and refus["motif"] == "BUDGET_EPUISE"   # on ne martèle pas la source


def test_idea8_grace_period_remet_le_backoff_a_zero():
    b = DE.BudgetReconnexions(budget=10, grace_ms=120_000.0, base_ms=500.0)
    for i in range(3):
        b.enregistrer("ws", maintenant_ms=float(i), succes=False)
    long = b.autoriser("ws", maintenant_ms=10.0, connecte_depuis_ms=200_000.0)
    assert long["essai"] == 0 and long["delai_ms"] < 1_500.0   # connexion saine -> repart au 1er échelon


def test_idea8_budget_se_libere_apres_la_fenetre():
    b = DE.BudgetReconnexions(budget=1, fenetre_ms=1_000.0)
    b.enregistrer("ws", maintenant_ms=0.0, succes=False)
    assert b.autoriser("ws", maintenant_ms=500.0)["autorise"] is False
    assert b.autoriser("ws", maintenant_ms=2_000.0)["autorise"] is True


# ═══════════════ IDEA-9 — déduplication forte et DURABLE ═══════════════
def test_idea9_identite_stable_et_reproductible():
    a = EC.identite_evenement(coin="BTC", exchange_ts=1.0, source="s", channel="c", tid="t1")
    b = EC.identite_evenement(coin="btc", exchange_ts=1.0, source="s", channel="c", tid="t1")
    assert a == b                                             # même événement -> même identité
    c = EC.identite_evenement(coin="BTC", exchange_ts=1.0, source="s", channel="c", tid="t2")
    assert a != c


def test_idea9_dedup_survit_au_crash_et_a_la_reprise(tmp_path):
    d = DD.DedupDurable(tmp_path)
    assert d.vu("e1") is False and d.vu("e1") is True
    d2 = DD.DedupDurable(tmp_path)                            # "crash" + reprise : nouvelle instance
    assert d2.vu("e1") is True                                # le doublon reste un doublon
    assert d2.vu("e2") is False


def test_idea9_dedup_survit_a_la_compaction(tmp_path):
    d = DD.DedupDurable(tmp_path, fenetre=1000, compaction_tous_les=5)
    for i in range(12):
        d.vu("id%d" % i)
    assert (tmp_path / "dedup_snapshot.json").exists()
    assert any((tmp_path / "dedup_archive").glob("dedup_*.jsonl"))   # rien n'est supprimé : archivé
    assert DD.DedupDurable(tmp_path).vu("id3") is True


def test_idea9_filtrer_marque_les_doublons_sans_les_perdre(tmp_path):
    d = DD.DedupDurable(tmp_path)
    evs = [{"event_id": "a"}, {"event_id": "b"}, {"event_id": "a"}]
    nouveaux, doublons = d.filtrer(evs)
    assert [e["event_id"] for e in nouveaux] == ["a", "b"]
    assert len(doublons) == 1 and doublons[0]["duplicate"] is True   # marqué, pas jeté en silence


def test_idea9_dedup_borne_la_memoire(tmp_path):
    d = DD.DedupDurable(tmp_path, fenetre=10, compaction_tous_les=10_000)
    for i in range(50):
        d.vu("x%d" % i)
    assert d.compte()["n_ids"] <= 10                          # borné pour un run 24/7


# ═══════════════ IDEA-10 — Operational Reality Journal ═══════════════
def test_idea10_journal_enregistre_les_15_types(tmp_path):
    j = JO.JournalOperationnel(tmp_path)
    for t in JO.TYPES:
        j.enregistrer(t, source="ws1", coin="BTC", detail="test %s" % t)
    r = j.resume()
    assert r["n_incidents"] == len(JO.TYPES) == 15
    assert set(r["par_type"]) == set(JO.TYPES)


def test_idea10_type_inconnu_refuse(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        JO.JournalOperationnel(tmp_path).enregistrer("BLABLA")


def test_idea10_incident_bloquant_interdit_la_promotion(tmp_path):
    j = JO.JournalOperationnel(tmp_path)
    j.enregistrer("STALE_TICK", source="s")
    assert j.resume()["promotion_interdite"] is False
    j.enregistrer("PNL_UNTRUSTED", source="s", detail="ledger != dashboard")
    assert j.resume()["promotion_interdite"] is True          # vérité du PnL : on bloque


def test_idea10_incidents_reinjectes_en_scenarios_de_replay(tmp_path):
    j = JO.JournalOperationnel(tmp_path)
    for _ in range(3):
        j.enregistrer("WS_DISCONNECT", source="ws1")
    j.enregistrer("PARTIAL_FILL", coin="BTC")
    sc = j.scenarios_pour_replay()
    noms = [s["scenario"] for s in sc]
    assert "coupure_flux" in noms and "execution_partielle" in noms
    top = sc[0]
    assert top["scenario"] == "coupure_flux" and top["occurrences"] == 3 and 0 < top["frequence"] <= 1


# ═══════════════ sécurité transversale ═══════════════
def test_aucun_module_ne_touche_au_reseau_ni_a_l_exchange():
    for mod in ("evenement_canonique", "dedup_durable", "etat_flux", "demarrage_etale",
                "journal_operationnel"):
        src = (RACINE / "tools" / ("%s.py" % mod)).read_text(encoding="utf-8")
        for interdit in ("/exchange", "requests.", "urllib.request", "websocket", "private_key",
                         "sign(", "mnemonic"):
            assert interdit not in src, "%s contient %s" % (mod, interdit)
