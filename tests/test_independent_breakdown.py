"""P2.2 — ventilation du N indépendant : un métaordre = 1 obs, pas N fills."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.simulation import independent_breakdown as B  # noqa: E402


def test_un_metaorder_de_200_fills_compte_pour_une_observation():
    fills = [{"metaorder_id": "M1", "net_bps": 2.0, "wallet": "w", "coin": "BTC", "ts_ms": 0}
             for _ in range(200)]
    v = B.ventilation_independance(fills)
    assert v["n_raw_fills"] == 200
    assert v["n_metaorders"] == 1
    assert v["n_independent"] == 1          # PAS 200
    assert v["facteur_replication"] == 200.0


def test_ventilation_metaorder_burst_wallet_coin_jour():
    eps = [
        {"metaorder_id": "M1", "net_bps": 1.0}, {"metaorder_id": "M1", "net_bps": 3.0},   # 1 metaorder
        {"burst_id": "B1", "net_bps": 2.0},                                               # 1 burst
        {"wallet": "wa", "coin": "BTC", "ts_ms": 0, "net_bps": 5.0},                       # wcj #1
        {"wallet": "wa", "coin": "BTC", "ts_ms": 100, "net_bps": 6.0},                     # même jour → même wcj
        {"wallet": "wb", "coin": "ETH", "ts_ms": 90_000_000, "net_bps": 4.0},              # wcj #2
    ]
    v = B.ventilation_independance(eps)
    assert v["n_raw_fills"] == 6
    assert v["n_metaorders"] == 1 and v["n_bursts"] == 1 and v["n_wallet_coin_days"] == 2
    assert v["n_independent"] == 4          # 1 + 1 + 2


def test_meme_wallet_coin_deux_jours_sont_deux_observations():
    eps = [
        {"wallet": "w", "coin": "BTC", "ts_ms": 0, "net_bps": 1.0},
        {"wallet": "w", "coin": "BTC", "ts_ms": 86_400_001, "net_bps": 2.0},   # jour suivant
    ]
    v = B.ventilation_independance(eps)
    assert v["n_wallet_coin_days"] == 2 and v["n_independent"] == 2


def test_n_episodes_none_si_aucune_identite():
    eps = [{"wallet": "w", "coin": "BTC", "ts_ms": 0, "net_bps": 1.0}]
    assert B.ventilation_independance(eps)["n_episodes"] is None


def test_n_episodes_compte_les_identites_reelles():
    eps = [
        {"episode_id": "E:a", "wallet": "w", "coin": "BTC", "ts_ms": 0, "net_bps": 1.0},
        {"position_id": "p2", "wallet": "w", "coin": "ETH", "ts_ms": 0, "net_bps": 2.0},
    ]
    assert B.ventilation_independance(eps)["n_episodes"] == 2


def test_lcb_none_si_trop_peu_de_votes():
    eps = [{"metaorder_id": f"M{i}", "net_bps": 1.0} for i in range(3)]
    v = B.ventilation_independance(eps)
    assert v["n_independent"] == 3 and v["lower_confidence_bound_bps"] is None   # < 8 votes


def test_lcb_calculee_avec_assez_de_votes():
    eps = [{"metaorder_id": f"M{i}", "net_bps": 5.0} for i in range(20)]
    v = B.ventilation_independance(eps)
    assert v["n_independent"] == 20 and v["lower_confidence_bound_bps"] is not None


def test_vide():
    v = B.ventilation_independance([])
    assert v["n_raw_fills"] == 0 and v["n_independent"] == 0 and v["real_execution"] is False
