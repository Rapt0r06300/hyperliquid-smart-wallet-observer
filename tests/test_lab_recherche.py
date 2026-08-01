"""[LAB α] lab_recherche : évaluation IS/OOS/FORWARD + stress + placebo, recherche large→fine, cache/reprise."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops.lab_recherche import evaluer_config, rechercher   # noqa: E402

T = 1_700_000_000_000


def _synth(n):
    evs = []
    for i in range(n):
        px = 60000.0 + i * 10.0
        evs.append({"coin": "BTC", "px": px, "mid": px, "sz": 0.3, "signe": 1 if i % 2 == 0 else -1,
                    "ts_ms": T + i * 1000, "vault": "A",
                    "book": {"asks": [[px + 10.0, 5.0]], "bids": [[px - 10.0, 5.0]]}})
    return evs


CFG = {"notional_max": 300.0, "fee_bps": 4.5, "min_fill_ratio": 0.85, "seuil_edge_cross_venue_bps": 1.0}


def test_evaluer_config_segments_stress_placebo():
    r = evaluer_config(_synth(40), CFG, leader_equity_defaut=100000.0, min_episodes=5)
    assert {"IS", "OOS", "FORWARD", "ADVERSE_P95", "ADVERSE_P99"} <= set(r["segments"])
    assert r["verdict"] in ("PROMU", "KILL", "MORE_DATA", "UNMEASURABLE")
    assert "placebo_net" in r and isinstance(r["metriques"]["reconcilie"], bool)


def test_rechercher_synthetique_est_non_economique():
    r = rechercher(_synth(40), leader_equity_defaut=100000.0, budget=8, source="SYNTHETIQUE")
    assert r["evalues"] <= 8 and r["n_candidats"] > 0
    assert r["verdict_global"] == "NON_ECONOMIQUE_SYNTHETIQUE"


def test_cache_et_reprise(tmp_path):
    espace = {"notional_max": [100.0, 300.0], "fee_bps": [4.5], "min_fill_ratio": [0.85],
              "seuil_edge_cross_venue_bps": [1.0]}
    cp = tmp_path / "ckpt.jsonl"
    r1 = rechercher(_synth(30), espace=espace, leader_equity_defaut=100000.0, budget=64,
                    checkpoint_path=cp, source="SYNTHETIQUE")
    r2 = rechercher(_synth(30), espace=espace, leader_equity_defaut=100000.0, budget=64,
                    checkpoint_path=cp, source="SYNTHETIQUE")
    assert r1["evalues"] >= 2 and r2["evalues"] == 0 and r2["caches"] >= 2   # reprise : tout en cache
