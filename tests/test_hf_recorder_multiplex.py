"""CHANTIER #1 — recorder HF multiplexé : normalisation canonique, dédup, gaps, reconnect, écriture durable."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import hf_recorder_multiplex as HR   # noqa: E402


def _msgs():
    return [
        {"raw": {"coin": "BTC", "venue": "HL", "type": "bbo", "seq": 1, "exchange_ts": 1000}, "receive_wall_ts": 1001},
        {"raw": {"coin": "BTC", "venue": "HL", "type": "bbo", "seq": 2, "exchange_ts": 1010}, "receive_wall_ts": 1011},
        {"raw": {"coin": "BTC", "venue": "HL", "type": "bbo", "seq": 2, "exchange_ts": 1010}, "receive_wall_ts": 1011},  # DUP
        {"raw": {"coin": "BTC", "venue": "HL", "type": "bbo", "seq": 5, "exchange_ts": 1050}, "receive_wall_ts": 1051},  # gap 3,4
        {"raw": {"coin": "BTC", "venue": "HL", "type": "bbo", "seq": 1, "exchange_ts": 1060}, "receive_wall_ts": 1061},  # RECONNECT
        {"raw": {"coin": "BTC", "venue": "BINANCE", "type": "bbo", "seq": 1, "exchange_ts": 1000}, "receive_wall_ts": 1002},
        {"raw": {"coin": "ETH", "venue": "HL", "type": "trade", "seq": 1}},                                            # ts manquants
    ]


def test_chantier1_recorder_dedup_gaps_reconnect_et_ecriture(tmp_path):
    out = tmp_path / "hf.jsonl"
    r = HR.enregistrer(_msgs(), str(out))
    assert r["n_ecrits"] == 6 and r["doublons"] == 1          # le doublon exact n'est jamais réécrit
    assert r["gaps_seq"] == 2 and r["reconnects"] == 1        # trou 3,4 détecté ; reset de séquence = reconnexion
    assert r["ts_manquants_total"] > 0 and r["quality_ok"] is False and r["real_execution"] is False
    # relecture durable + manifeste de qualité recalculé (research.hf_recorder.qualite)
    man = HR.manifeste_depuis_fichier(str(out))
    assert man["n"] == 6


def test_chantier1_capture_live_est_blocked_external():
    assert HR.capturer_live()["statut"] == "BLOCKED_EXTERNAL"   # capture WS tourne cote machine Flo
