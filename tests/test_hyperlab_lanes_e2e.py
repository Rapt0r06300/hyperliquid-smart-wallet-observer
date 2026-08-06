"""[Bloc 6-7/52-55] Integrateur lanes : chaine complete prouvee E2E + lanes de scope."""
import os

from hl_observer.hyperlab import data_mesh_catalog as dm
from hl_observer.hyperlab import lanes


def _fixtures():
    return {
        "session_id": "sess-e2e", "venue": "bybit", "symbole": "BTCUSDT", "ts": 1000.0,
        "records": [
            {"ts": 1720000000000, "venue": "bybit", "symbole": "BTCUSDT", "type": "trade",
             "prix": "60000", "taille": "0.5", "side": "buy"},
            {"ts": 1720000001000, "venue": "bybit", "symbole": "BTCUSDT", "type": "trade",
             "prix": "60010", "taille": "1", "side": "sell"},
        ],
        "copy_action": {"venue": "bybit", "symbole": "BTCUSDT", "side": "buy", "prix_ref": 60000.0},
        "leadlag": ({"bid": 100, "bid_sz": 5, "ask": 101, "ask_sz": 5},
                    {"bid": 100, "bid_sz": 9, "ask": 101, "ask_sz": 5}),
        "crossvenue": ({"mid": 60000.0, "venue": "bybit"}, {"mid": 60100.0, "venue": "okx"}),
        "perf_is": [1, 2, 3, 2.5], "perf_oos": [1.1, 1.8, 2.9, 2.4], "sr": 1.2, "n_trials": 20, "T": 250,
        "quotes": [{"bid": 59999.0, "ask": 60001.0}],
        "fills": [{"prix_exec": 60001.0, "mid_ref": 60000.0, "frais": 0.05, "notionnel": 100.0,
                   "mid_apres": 60000.5, "side": "buy"}],
        "latences": [10, 20, 30, 40, 50],
        "is_idx": [0, 1], "oos_idx": [2, 3], "forward_idx": [4, 5], "finalistes": ["cfg_a"],
        "blocages": ["collecte live: REQUIRES_NETWORK", "Windows E2E: pas de runner ici"],
    }


def test_run_session_validee_chaine_ok(tmp_path):
    conn = dm.ouvrir(os.path.join(str(tmp_path), "mesh.db"))
    dm.bootstrap(conn, ts=1000.0)
    out = lanes.run_session_validee(_fixtures(), root=str(tmp_path / "lake"), conn=conn, ts=1000.0)
    assert out["verdict_chaine_ok"] is True
    assert out["parite"]["parite"] and out["coherence_fast_exact"]["coherent"]
    assert out["reconciliation_5_vues"]["coherent"] and out["session"]["statut"] == "COMPLETE"
    assert out["fuite"]["fuite"] is False
    assert out["cross_venue"]["residual_risk_usd"] == 100.0  # jambe manquee -> unwind expose
    assert out["calibration"]["frais_bps"] == 5.0
    # les blocages honnetes remontent dans le rapport
    assert any("REQUIRES_NETWORK" in b for b in out["rapport"]["blocages"])


def test_lanes_scope():
    sessions = [{"records": [1, 2, 3]}, {"records": []}, {"records": [1]}]
    assert len(lanes.selection_session(sessions, min_events=1)) == 2  # la vide est ecartee
    agg = lanes.multi_session_aggrege([{"pnl_net_usd": 1.0, "couts_usd": 0.1, "positions": [1]},
                                       {"pnl_net_usd": -0.5, "couts_usd": 0.2, "positions": []}])
    assert agg["n_sessions"] == 2 and round(agg["pnl_net_usd"], 2) == 0.5
    rapports = lanes.suite_historique([{"records": [1]}, {"records": [2]}], runner=lambda s: {"n": len(s["records"])})
    assert rapports == [{"n": 1}, {"n": 1}]
