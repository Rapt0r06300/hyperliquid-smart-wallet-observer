"""[Bloc 5-7/37/56] Orchestrateur hyperlab_master : pipeline REEL bout-en-bout + resume + enveloppe."""
import os

from hl_observer.hyperlab import data_mesh_catalog as dm
from hl_observer.hyperlab import master


def _fixtures():
    return {
        "venue": "bybit", "symbole": "BTCUSDT", "ts": 1000.0,
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
        "equity_series": [1000.0, 1001.0, 999.5, 1002.0],
    }


def _conn(tmp_path):
    conn = dm.ouvrir(os.path.join(str(tmp_path), "mesh.db"))
    dm.bootstrap(conn, ts=1000.0)
    return conn


def test_run_full_pipeline(tmp_path):
    conn = _conn(tmp_path)
    out = master.run("full", root=str(tmp_path / "lake"), conn=conn, fixtures=_fixtures(),
                     blocages=["collecte live: REQUIRES_NETWORK"])
    # copy(1) + leadlag(1) + cross(2) = 4 intents, tous sous l'enveloppe
    assert out["intents"] == 4 and out["fills"] == 4 and out["refus"] == 0
    assert out["rapport"]["expo_brute_usd"] <= 1000.0
    assert out["rapport"]["blocages"] == ["collecte live: REQUIRES_NETWORK"]
    assert out["validation"] is None  # full n'inclut pas la validation


def test_run_maximum_inclut_validation(tmp_path):
    conn = _conn(tmp_path)
    out = master.run("maximum", root=str(tmp_path / "lake"), conn=conn, fixtures=_fixtures())
    assert out["validation"] is not None and "pbo" in out["validation"] and "dsr" in out["validation"]


def test_resume_reprend_etat(tmp_path):
    conn = _conn(tmp_path)
    out1 = master.run("full", root=str(tmp_path / "lake"), conn=conn, fixtures=_fixtures())
    etat = out1["etat"]
    assert "ingest" in etat["faites"]
    out2 = master.run("resume", root=str(tmp_path / "lake"), conn=conn, fixtures=_fixtures(), etat=etat)
    assert out2["mode"] == "full" and "report" in out2["etat"]["faites"]


def test_mode_inconnu_rejete(tmp_path):
    conn = _conn(tmp_path)
    import pytest
    with pytest.raises(AssertionError):
        master.run("turbo", root=str(tmp_path / "lake"), conn=conn, fixtures=_fixtures())
