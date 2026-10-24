"""[LAB α] lab_recherche : évaluation IS/OOS/FORWARD + stress + placebo, recherche large→fine, cache/reprise."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import lab_recherche as L  # noqa: E402
from hl_observer.ops.lab_recherche import evaluer_config, rechercher  # noqa: E402

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


def test_espace_officiel_ne_contient_aucun_parametre_de_famille_en_pause():
    assert "seuil_edge_cross_venue_bps" not in L.ESPACE_DEFAUT


def test_cache_copyvault_ignore_un_ancien_parametre_crossvenue():
    base = {"notional_max": 300.0, "fee_bps": 4.5, "min_fill_ratio": 0.85}
    assert L._cle_cache({**base, "seuil_edge_cross_venue_bps": 1.0}, "data") == (
        L._cle_cache({**base, "seuil_edge_cross_venue_bps": 999.0}, "data")
    )


def test_replay_canonique_desactive_crossvenue_a_la_construction(monkeypatch):
    captured = {}

    class FakeExecutor:
        @staticmethod
        def pnl():
            return {"equity": 1_000.0, "reconcilie": True, "fees": 0.0}

    class FakePipe:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.trace = []
            self.executeur = FakeExecutor()

        @staticmethod
        def resume():
            return {"cross_venue_executes": 0}

    monkeypatch.setattr(L, "MegaCablage", FakePipe)

    result = L._rejouer_riche(
        [],
        config={"notional_max": 300.0, "fee_bps": 4.5, "min_fill_ratio": 0.85},
        leader_equity_defaut=None,
    )

    assert captured["cross_venue_paper"] is False
    assert "seuil_edge_cross_venue_bps" not in captured
    assert result["cross_venue"] == 0


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
