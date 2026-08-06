"""[Bloc 13-14] Gate LIVE_READY : OFFLINE_READY ne vaut jamais LIVE_READY ; les 6 criteres runtime."""
from hl_observer.hyperlab.live_ready import (
    PreuveLive, evaluer_live_ready, offline_ready_implique_live_ready, venues_live_ready, CRITERES)


def test_offline_ne_vaut_pas_live():
    assert offline_ready_implique_live_ready() is False


def test_sans_preuve_tous_criteres_manquants():
    r = evaluer_live_ready(PreuveLive("bybit"), maintenant=1000.0, seuil_fraicheur_s=60)
    assert r["live_ready"] is False
    assert set(r["manquants"]) == set(CRITERES)


def test_preuve_complete_est_live_ready():
    p = PreuveLive("bybit", connexion=True, n_messages=42, last_useful_event_ts=990.0,
                   sequences_ok=True, bronze_lignes_ecrites=42, replay_parite=True)
    r = evaluer_live_ready(p, maintenant=1000.0, seuil_fraicheur_s=60)
    assert r["live_ready"] is True and r["manquants"] == []


def test_fraicheur_perimee_bloque():
    p = PreuveLive("okx", connexion=True, n_messages=10, last_useful_event_ts=100.0,
                   sequences_ok=True, bronze_lignes_ecrites=10, replay_parite=True)
    r = evaluer_live_ready(p, maintenant=1000.0, seuil_fraicheur_s=60)
    assert r["live_ready"] is False and r["manquants"] == ["fraicheur"]


def test_agregat_requises():
    ok = PreuveLive("bybit", connexion=True, n_messages=5, last_useful_event_ts=999.0,
                    sequences_ok=True, bronze_lignes_ecrites=5, replay_parite=True)
    ko = PreuveLive("okx")
    agg = venues_live_ready([ok, ko], maintenant=1000.0, seuil_fraicheur_s=60, requises=["bybit", "okx"])
    assert agg["ready_global"] is False
    assert agg["requises_non_pretes"] == ["okx"] and agg["live_ready"] == ["bybit"]
