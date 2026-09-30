"""P5.1 v2 — anticipation Wallet×Binance : direction f(action,side), dédup, tolérance, N clusterisé, freeze/OOS."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.following import binance_anticipation as A  # noqa: E402

H = (1000,)


# --- LE BUG CORRIGÉ : direction économique = f(action, position_side) --------
def test_close_short_est_un_achat():
    assert A.direction_economique("CLOSE_SHORT") == 1
    assert A.direction_economique("CLOSE_LONG") == -1


def test_reduce_short_est_un_achat_reduce_long_une_vente():
    assert A.direction_economique("REDUCE", position_side="SHORT") == 1     # le bug : c'était −1
    assert A.direction_economique("REDUCE", position_side="LONG") == -1


def test_open_add_suivent_le_side():
    assert A.direction_economique("OPEN_LONG") == 1 and A.direction_economique("OPEN_SHORT") == -1
    assert A.direction_economique("ADD", position_side="SHORT") == -1
    assert A.direction_economique("INCREASE", position_side="LONG") == 1


def test_flip_et_close_ambigu_sont_none():
    assert A.direction_economique("FLIP") is None
    assert A.direction_economique("CLOSE") is None            # sans side → ambigu
    assert A.direction_economique("REDUCE") is None


# --- scoring orienté par la vraie direction ---------------------------------
def test_close_short_avant_hausse_est_une_anticipation_positive():
    # Fermer un short = ACHAT ; prix plat avant, MONTE après → favorable → anticipation positive.
    path = [(8000, 100.0), (9000, 100.0), (10000, 100.0), (11000, 100.5), (12000, 101.0)]
    s = A.score_anticipation(t_event_ms=10000, action="CLOSE_SHORT", path=path, horizons_ms=H)
    assert s["sens"] == 1 and s["par_horizon"][1000]["anticipation_bps"] == 50.0


def test_reduce_long_avant_hausse_est_negative():
    # Réduire un long = VENTE ; prix monte après → défavorable pour une vente → anticipation négative.
    path = [(9000, 100.0), (10000, 100.0), (11000, 100.5)]
    s = A.score_anticipation(t_event_ms=10000, action="REDUCE", position_side="LONG", path=path, horizons_ms=H)
    assert s["sens"] == -1 and s["par_horizon"][1000]["anticipation_bps"] == -50.0


def test_action_ambigue_tout_unmeasurable():
    path = [(9000, 100.0), (10000, 100.0), (11000, 100.5)]
    s = A.score_anticipation(t_event_ms=10000, action="FLIP", path=path, horizons_ms=H)
    assert s["sens"] is None and s["par_horizon"][1000]["statut"] == "UNMEASURABLE"


# --- tolérance temporelle PAR horizon ---------------------------------------
def test_feed_trop_grossier_rend_les_courts_horizons_unmeasurable():
    # Feed clairsemé : point à T, puis rien avant T+5000. Horizon 100 ms → prix à T+100 trop vieux.
    path = [(5000, 100.0), (10000, 100.0), (15000, 101.0)]
    s = A.score_anticipation(t_event_ms=10000, action="OPEN_LONG", path=path,
                             horizons_ms=(100, 5000))
    assert s["par_horizon"][100]["statut"] == "UNMEASURABLE"      # 100 ms non mesurable sur ce feed
    assert s["par_horizon"][5000]["statut"] == "MEASURED"         # 5 s oui


# --- déduplication -----------------------------------------------------------
def test_dedup_par_event_id():
    evs = [{"event_id": "e1", "wallet": "w"}, {"event_id": "e1", "wallet": "w"}, {"tid": 7, "wallet": "w"}]
    assert len(A.dedup_evenements(evs)) == 2


def test_un_doublon_ne_compte_pas_pour_deux_observations():
    path = {"BTC": [(9000, 100.0), (10000, 100.0), (11000, 100.5), (12000, 101.0)]}
    evs = [
        {"event_id": "e1", "wallet": "wA", "coin": "BTC", "action": "OPEN_LONG", "ts_ms": 10000, "metaorder_id": "m1"},
        {"event_id": "e1", "wallet": "wA", "coin": "BTC", "action": "OPEN_LONG", "ts_ms": 10000, "metaorder_id": "m1"},
    ]
    r = A.anticipation_par_wallet(evs, path, horizon_ms=1000)
    assert r["wallets"]["wA"]["n_raw"] == 1          # le doublon est écarté


def test_n_raw_vs_n_clustered():
    path = {"BTC": [(9000, 100.0), (10000, 100.0), (11000, 100.5), (12000, 101.0)]}
    evs = [
        {"event_id": f"e{i}", "wallet": "wA", "coin": "BTC", "action": "OPEN_LONG",
         "ts_ms": 10000, "metaorder_id": "M1"} for i in range(3)          # même métaordre
    ]
    r = A.anticipation_par_wallet(evs, path, horizon_ms=1000)
    assert r["wallets"]["wA"]["n_raw"] == 3 and r["wallets"]["wA"]["n_clustered"] == 1


# --- DISCOVERY → FREEZE → OOS ------------------------------------------------
def test_selection_freeze_oos_gele_puis_mesure_sur_validation_intacte():
    path = {"BTC": [(t, 100.0 + t / 100000.0) for t in range(0, 70001, 250)]}
    evs = [
        {"event_id": "a1", "wallet": "wA", "coin": "BTC", "action": "OPEN_LONG", "ts_ms": 10000, "metaorder_id": "mA1"},
        {"event_id": "a2", "wallet": "wA", "coin": "BTC", "action": "OPEN_LONG", "ts_ms": 20000, "metaorder_id": "mA2"},
        {"event_id": "a3", "wallet": "wA", "coin": "BTC", "action": "OPEN_LONG", "ts_ms": 30000, "metaorder_id": "mA3"},
        {"event_id": "a4", "wallet": "wA", "coin": "BTC", "action": "OPEN_LONG", "ts_ms": 50000, "metaorder_id": "mA4"},
        {"event_id": "a5", "wallet": "wA", "coin": "BTC", "action": "OPEN_LONG", "ts_ms": 60000, "metaorder_id": "mA5"},
    ]
    r = A.selection_freeze_oos(evs, path, horizon_ms=1000, fraction_decouverte=0.6, top_k=1, min_clusters=2)
    assert r["fenetres_disjointes"] is True
    assert r["n_decouverte"] == 3 and r["n_validation"] == 2
    assert "wA" in r["wallets_geles"]
    assert r["oos_wallets_geles"]["wA"] is not None       # le wallet gelé est mesuré sur la validation intacte
