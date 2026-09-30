"""X1 — pipeline de filtres composable : chaque garde s'applique si son entrée est là, sinon
abstention ; les sorties ne sont jamais bloquées ; un garde applicable qui échoue -> refus."""
from __future__ import annotations

from hl_observer.gating.filter_pipeline import ContexteDecision, appliquer_filtres


def test_sortie_jamais_filtree():
    r = appliquer_filtres(ContexteDecision(coin="DOGE", est_sortie=True, univers=("BTC", "ETH")))
    assert r.accepte is True
    assert "SORTIE_NON_FILTREE" in r.abstentions


def test_coin_hors_univers_refuse():
    r = appliquer_filtres(ContexteDecision(coin="DOGE", est_sortie=False, univers=("BTC", "ETH")))
    assert r.accepte is False
    assert "COIN_HORS_UNIVERS" in r.refus


def test_coin_dans_univers_accepte():
    r = appliquer_filtres(ContexteDecision(coin="BTC", est_sortie=False, univers=("BTC", "ETH")))
    assert r.accepte is True


def test_univers_insuffisant_abstention_pas_refus():
    # univers < 2 : trop pauvre pour gater -> abstention, JAMAIS un refus fabriqué (anti-affamé)
    r = appliquer_filtres(ContexteDecision(coin="BTC", est_sortie=False, univers=("BTC",)))
    assert r.accepte is True
    assert "UNIVERS_INSUFFISANT" in r.abstentions


def test_entree_absente_donne_abstention_pas_refus():
    r = appliquer_filtres(ContexteDecision(coin="BTC", est_sortie=False, univers=("BTC", "ETH")))
    # ni wallet_stats, ni référence tick, ni marge, ni crowding -> abstentions, accepte quand même
    assert r.accepte is True
    for code in ("WALLET_STATS_ABSENTES", "TICK_REFERENCE_ABSENTE", "MARGE_CAPITAL_ABSENTS",
                 "CROWDING_HISTORIQUE_ABSENT", "FRAICHEUR_AGE_ABSENT"):
        assert code in r.abstentions


def test_signal_trop_vieux_refuse():
    r = appliquer_filtres(ContexteDecision(coin="BTC", est_sortie=False, univers=("BTC", "ETH"),
                                           age_signal_s=600.0))  # > 120 s
    assert r.accepte is False and "SIGNAL_TROP_VIEUX" in r.refus


def test_wallet_structurel_refuse():
    stats = {"adresse": "0xvault", "winrate": 1.0, "pnl_total_usd": 0.0, "n_trades": 5000}
    r = appliquer_filtres(ContexteDecision(coin="BTC", est_sortie=False, univers=("BTC", "ETH"),
                                           wallet_stats=stats))
    assert r.accepte is False and "WALLET_STRUCTUREL" in r.refus


def test_wallet_reel_non_structurel_accepte():
    stats = {"adresse": "0xtrader", "winrate": 0.58, "pnl_total_usd": 90000.0, "n_trades": 300}
    r = appliquer_filtres(ContexteDecision(coin="BTC", est_sortie=False, univers=("BTC", "ETH"),
                                           wallet_stats=stats))
    assert r.accepte is True


def test_tick_stale_refuse():
    r = appliquer_filtres(ContexteDecision(coin="BTC", est_sortie=False, univers=("BTC", "ETH"),
                                           mid=130.0, prix_reference=100.0))  # +30% > 15%
    assert r.accepte is False and "TICK_STALE" in r.refus


def test_reserve_marge_violee_refuse():
    r = appliquer_filtres(ContexteDecision(coin="BTC", est_sortie=False, univers=("BTC", "ETH"),
                                           marge_utilisee=990.0, capital=1000.0))  # ~99% utilisé
    assert r.accepte is False and "RESERVE_MARGE_VIOLEE" in r.refus


def test_crowding_sature_refuse_mais_non_sature_passe():
    sature = appliquer_filtres(ContexteDecision(coin="BTC", est_sortie=False, univers=("BTC", "ETH"),
                                                edge_hist_bps=40.0, edge_recent_bps=5.0))  # 12% -> saturé
    assert sature.accepte is False and "EDGE_SATURE" in sature.refus
    ok = appliquer_filtres(ContexteDecision(coin="BTC", est_sortie=False, univers=("BTC", "ETH"),
                                            edge_hist_bps=40.0, edge_recent_bps=38.0))  # 95% -> sain
    assert ok.accepte is True and "EDGE_SATURE" not in ok.refus
