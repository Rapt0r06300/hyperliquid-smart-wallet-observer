"""P3.2b — orchestration Binance : buffer avant snapshot, replay, resync auto, publication canonique."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import binance_depth_orchestrator as O  # noqa: E402
from hl_observer.collection import binance_depth_book as D          # noqa: E402


def test_diffs_avant_snapshot_sont_bufferises_puis_rejoues():
    orch = O.BinanceDepthOrchestrator()
    assert orch.sur_diff(U=101, u=105, bids=[[10.0, 5.0]]) == O.BUFFERISE
    assert orch.sur_diff(U=106, u=108, asks=[[11.0, 2.0]]) == O.BUFFERISE
    r = orch.sur_snapshot(last_update_id=100, bids=[[10.0, 1.0]], asks=[[11.0, 1.0]])
    assert r["applied_from_buffer"] == 2 and r["needs_snapshot"] is False
    assert orch.book.best_bid() == 10.0 and orch.book.bids[10.0] == 5.0


def test_diff_en_direct_applique_apres_snapshot():
    orch = O.BinanceDepthOrchestrator()
    orch.sur_snapshot(last_update_id=100, bids=[[10.0, 1.0]], asks=[[11.0, 1.0]])
    assert orch.sur_diff(U=101, u=103, bids=[[9.5, 2.0]]) == D.APPLIQUE
    assert orch.book.best_bid() == 10.0


def test_gap_declenche_resync_automatique():
    orch = O.BinanceDepthOrchestrator()
    orch.sur_snapshot(last_update_id=100, bids=[[10.0, 1.0]], asks=[[11.0, 1.0]])
    orch.sur_diff(U=101, u=105)
    st = orch.sur_diff(U=107, u=110)                 # gap → DESYNC
    assert st.startswith("DESYNC") and orch.needs_snapshot is True
    assert orch.besoin_resnapshot() is True
    # les diffs suivants sont rebufferisés en attendant le nouveau snapshot
    assert orch.sur_diff(U=111, u=112) == O.BUFFERISE


def test_resync_recupere_par_nouveau_snapshot():
    orch = O.BinanceDepthOrchestrator()
    orch.sur_snapshot(last_update_id=100, bids=[[10.0, 1.0]], asks=[[11.0, 1.0]])
    orch.sur_diff(U=101, u=105)
    orch.sur_diff(U=200, u=205)                      # DESYNC
    assert orch.besoin_resnapshot() is True
    r = orch.sur_snapshot(last_update_id=300, bids=[[10.0, 1.0]], asks=[[11.0, 1.0]])
    assert orch.besoin_resnapshot() is False
    assert orch.sur_diff(U=301, u=302, bids=[[10.0, 9.0]]) == D.APPLIQUE


def test_publication_canonique_timestamps_sequence_quality():
    orch = O.BinanceDepthOrchestrator()
    orch.sur_snapshot(last_update_id=100, bids=[[10.0, 1.0]], asks=[[11.0, 1.0]],
                      exchange_ts_ms=1000, receive_ts_ms=1005)
    orch.sur_diff(U=101, u=103, bids=[[10.0, 4.0]], exchange_ts_ms=1100, receive_ts_ms=1106)
    pub = orch.publier()
    assert pub["quality"] == "EXPLOITABLE" and pub["needs_resnapshot"] is False
    assert pub["sequence"] == 103 and pub["exchange_ts_ms"] == 1100 and pub["receive_ts_ms"] == 1106
    assert pub["best_bid"] == 10.0


def test_carnet_desync_publie_non_exploitable():
    orch = O.BinanceDepthOrchestrator()
    orch.sur_snapshot(last_update_id=100, bids=[[10.0, 1.0]], asks=[[11.0, 1.0]])
    orch.sur_diff(U=101, u=105)
    orch.sur_diff(U=999, u=1000)                     # DESYNC
    pub = orch.publier()
    assert pub["quality"] == "DESYNC" and pub["needs_resnapshot"] is True
    assert pub["exploitable"] is False


def test_buffer_est_borne():
    orch = O.BinanceDepthOrchestrator(max_buffer=3)
    for i in range(10):
        orch.sur_diff(U=100 + i, u=100 + i)          # tous bufferisés (pas de snapshot)
    assert len(orch.buffer) == 3                      # borné, garde les plus récents
