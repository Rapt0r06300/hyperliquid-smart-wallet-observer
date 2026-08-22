"""Tests du collecteur de carnet Cross-Venue, sans réseau."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import threading

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / f"{nom}.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

K = _mod("collecter_carnet")


def test_coins_prioritaires_classe_par_ecart_et_ignore_l_aberrant():
    lignes = [{"coin": "BTC", "ecart_prix_bps": 25.0}, {"coin": "ETH", "ecart_prix_bps": 40.0}, {"coin": "SOL", "ecart_prix_bps": 5.0}, {"coin": "MKR", "ecart_prix_bps": 1_670_000.0}]
    assert K.coins_prioritaires(lignes, n=2) == ["ETH", "BTC"]


def test_coins_bouges_par_vaults_abonnement_dynamique(tmp_path):
    import time
    now_ms = time.time() * 1000; (tmp_path / "runtime/data").mkdir(parents=True)
    (tmp_path / "runtime/data/coins_bouges_par_vaults.json").write_text(json.dumps({"coins": {"HYPE": now_ms - 1000, "FARTCOIN": now_ms - 60_000, "VIEUX": now_ms - 9 * 3600 * 1000}}), encoding="utf-8")
    coins = K.coins_bouges_par_vaults(tmp_path)
    assert "HYPE" in coins and "FARTCOIN" in coins and "VIEUX" not in coins
    assert K.coins_bouges_par_vaults(tmp_path / "vide") == []


def test_coins_premium_funding_classe_par_premium_et_ignore_l_artefact():
    lignes = [{"coin": "DASH", "hl_bps_h": 0.20, "bin_bps_h": 0.0}, {"coin": "INJ", "hl_bps_h": 0.30, "bin_bps_h": 0.05}, {"coin": "BTC", "hl_bps_h": 0.125, "bin_bps_h": 0.10}, {"coin": "ARTE", "hl_bps_h": 9.0, "bin_bps_h": 0.0}]
    assert K.coins_premium_funding(lignes, n=2) == ["INJ", "DASH"]


def test_parser_book_hl_lit_le_haut_de_carnet_ou_none():
    rep = {"levels": [[{"px": "100.0", "sz": "3"}], [{"px": "100.2", "sz": "4"}]]}
    assert K.parser_book_hl(rep) == (100.0, 100.2, 3.0, 4.0)
    assert K.parser_book_hl({"levels": [[], []]}) is None
    assert K.parser_book_hl("nawak") is None


def test_parser_depth_binance_lit_le_haut_de_carnet():
    rep = {"bids": [["100.05", "2"]], "asks": [["100.15", "6"]]}
    assert K.parser_depth_binance(rep) == (100.05, 100.15, 2.0, 6.0)
    assert K.parser_depth_binance({"bids": [], "asks": []}) is None


def test_demi_spread_bps_est_le_cout_de_franchissement():
    assert abs(K.demi_spread_bps(100.0, 100.2) - 9.99) < 0.05


def test_ligne_carnet_calcule_l_ecart_executable_pas_le_mid():
    row = K.ligne_carnet("BTC", (100.9, 101.1, 5.0, 5.0), (99.9, 100.1, 5.0, 5.0))
    assert row["ecart_executable_max_bps"] > 0 and row["hl_demi_spread_bps"] > 0 and row["taille_min_usd"] > 0
    assert row["atomic_snapshot_certified"] is False


def test_mapping_binance_canonique_refuse_les_faux_instruments():
    assert K.binance_perp_symbol("PEPE") == "1000PEPEUSDT"
    assert K.binance_perp_symbol("kBONK") == "1000BONKUSDT"
    assert K.binance_perp_symbol("HYPE") is None


def test_une_passe_ecrit_provenance_mapping_top5_et_skew(tmp_path):
    hl = {"levels": [[{"px": str(100.0 - i * 0.01), "sz": "5"} for i in range(5)], [{"px": str(100.2 + i * 0.01), "sz": "5"} for i in range(5)]]}
    bn = {"bids": [[str(99.5 - i * 0.01), "5"] for i in range(5)], "asks": [[str(99.7 + i * 0.01), "5"] for i in range(5)]}
    symbols = []
    n = K.une_passe(tmp_path, ["BTC"], post_hl=lambda coin, **kwargs: hl, get_binance=lambda symbol, **kwargs: symbols.append(symbol) or bn)
    assert n == 1
    row = json.loads((tmp_path / K.SORTIE).read_text(encoding="utf-8").strip())
    assert symbols == ["BTCUSDT"] and row["coin"] == "BTC" and row["binance_symbol"] == "BTCUSDT"
    assert row["instrument_mapping_exact"] is True and row["read_only"] is True and row["real_execution"] is False
    assert len(row["hl_bids5"]) == len(row["bin_asks5"]) == 5
    assert row["hl_received_at_ms"] > 0 and row["bin_received_at_ms"] > 0
    assert row["venue_skew_ms"] >= 0 and row["observation_id"]
    assert row["atomic_snapshot_certified"] is True


def test_une_passe_lit_les_deux_venues_en_parallele(tmp_path):
    barrier = threading.Barrier(2, timeout=1.0)
    hl = {"levels": [[{"px": "100.0", "sz": "5"}], [{"px": "100.2", "sz": "5"}]]}
    bn = {"bids": [["99.5", "5"]], "asks": [["99.7", "5"]]}

    def post_hl(coin, **kwargs):
        barrier.wait()
        return hl

    def get_binance(symbol, **kwargs):
        barrier.wait()
        return bn

    assert K.une_passe(tmp_path, ["BTC"], post_hl=post_hl, get_binance=get_binance) == 1
    row = json.loads((tmp_path / K.SORTIE).read_text(encoding="utf-8").strip())
    assert row["source_mode"] == K.CERTIFIED_SOURCE_MODE
    assert row["venue_skew_ms"] <= K.MAX_VENUE_SKEW_MS


def test_deux_observations_memes_prix_ne_sont_plus_ecrasees(tmp_path):
    hl = {"levels": [[{"px": "100.0", "sz": "5"}], [{"px": "100.2", "sz": "5"}]]}; bn = {"bids": [["99.5", "5"]], "asks": [["99.7", "5"]]}; cache = K.CF.CacheDedup()
    assert K.une_passe(tmp_path, ["BTC"], cache=cache, post_hl=lambda c, **k: hl, get_binance=lambda c, **k: bn) == 1
    assert K.une_passe(tmp_path, ["BTC"], cache=cache, post_hl=lambda c, **k: hl, get_binance=lambda c, **k: bn) == 1
    lines = (tmp_path / K.SORTIE).read_text(encoding="utf-8").splitlines(); assert len(lines) == 2
    first, second = map(json.loads, lines); assert first["observation_id"] != second["observation_id"]


def test_un_coin_non_mappable_ou_illisible_ne_casse_pas_la_passe(tmp_path):
    def hl_ok(c, **k): return {"levels": [[{"px": "1", "sz": "1"}], [{"px": "1.01", "sz": "1"}]]}
    def bin_casse(c, **k): raise OSError("reseau")
    assert K.une_passe(tmp_path, ["HYPE"], post_hl=hl_ok, get_binance=bin_casse) == 0
    assert K.une_passe(tmp_path, ["BTC"], post_hl=hl_ok, get_binance=bin_casse) == 0
