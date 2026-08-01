"""[CABLAGE replay] replay_driver : découpe IS/OOS/FORWARD + rejeu massif (synthétique + logs jsonl)."""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.replay_driver import (   # noqa: E402
    separer_temporel, rejouer_is_oos_forward, driver_depuis_logs)

T = 1_700_000_000_000


def _synth(n):
    evs = []
    for i in range(n):
        px = 60000.0 + i * 10.0
        evs.append({"coin": "BTC", "px": px, "mid": px, "sz": 0.3, "signe": 1 if i % 2 == 0 else -1,
                    "ts_ms": T + i * 1000, "vault": "A",
                    "book": {"asks": [[px + 10.0, 5.0]], "bids": [[px - 10.0, 5.0]]}})
    return evs


def test_separation_temporelle():
    segs = separer_temporel(_synth(10))
    assert len(segs["IS"]) == 6 and len(segs["OOS"]) == 2 and len(segs["FORWARD"]) == 2


def test_driver_depuis_logs_reconcilie(tmp_path):
    f = tmp_path / "replay.jsonl"
    f.write_text("\n".join(json.dumps(e) for e in _synth(20)), encoding="utf-8")
    rap = driver_depuis_logs(f, leader_equity_defaut=100000.0)
    assert rap["reconcilie_partout"] is True and set(rap["segments"]) == {"IS", "OOS", "FORWARD"}
    assert rap["verdict"]["note"] == "REEL"


def test_synthetique_est_labellise():
    rap = rejouer_is_oos_forward(_synth(12), source="SYNTHETIQUE", leader_equity_defaut=100000.0)
    assert rap["verdict"]["note"] == "SYNTHETIQUE_DEMO" and rap["reconcilie_partout"] is True
