"""COLLECTEUR DE CARNET (Levier 3, la donnee manquante de l'arbitrage). On VERROUILLE : priorite
aux coins REELLEMENT disloques, parseurs tolerants des deux venues, demi-spread reel, ecart
EXECUTABLE (ask d'une venue vs bid de l'autre), et une passe propre (dedup + qualite). Fetchers
injectes -> aucun reseau."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / ("%s.py" % nom))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


K = _mod("collecter_carnet")


def test_coins_prioritaires_classe_par_ecart_et_ignore_l_aberrant():
    lignes = [{"coin": "BTC", "ecart_prix_bps": 25.0}, {"coin": "ETH", "ecart_prix_bps": 40.0},
              {"coin": "SOL", "ecart_prix_bps": 5.0}, {"coin": "MKR", "ecart_prix_bps": 1_670_000.0}]
    top = K.coins_prioritaires(lignes, n=2)
    assert top == ["ETH", "BTC"]                 # ETH (40) > BTC (25) ; MKR aberrant ecarte


def test_coins_premium_funding_classe_par_premium_et_ignore_l_artefact():
    """🟠 23/07 — le carnet ratait les cibles du CARRY (premium de funding fort mais prix peu
    disloqué : DASH/NEO/INJ). On les sélectionne par |hl−bin| ; un premium aberrant est écarté."""
    lignes = [{"coin": "DASH", "hl_bps_h": 0.20, "bin_bps_h": 0.0},    # premium 0.20
              {"coin": "INJ", "hl_bps_h": 0.30, "bin_bps_h": 0.05},    # premium 0.25 (le plus fort)
              {"coin": "BTC", "hl_bps_h": 0.125, "bin_bps_h": 0.10},   # premium 0.025
              {"coin": "ARTE", "hl_bps_h": 9.0, "bin_bps_h": 0.0}]     # 9 > 5 bps/h -> artefact, ignoré
    top = K.coins_premium_funding(lignes, n=2)
    assert top == ["INJ", "DASH"]                # INJ (0.25) > DASH (0.20) ; ARTE aberrant écarté


def test_parser_book_hl_lit_le_haut_de_carnet_ou_None():
    rep = {"levels": [[{"px": "100.0", "sz": "3"}], [{"px": "100.2", "sz": "4"}]]}
    assert K.parser_book_hl(rep) == (100.0, 100.2, 3.0, 4.0)
    assert K.parser_book_hl({"levels": [[], []]}) is None
    assert K.parser_book_hl("nawak") is None


def test_parser_depth_binance_lit_le_haut_de_carnet():
    rep = {"bids": [["100.05", "2"]], "asks": [["100.15", "6"]]}
    assert K.parser_depth_binance(rep) == (100.05, 100.15, 2.0, 6.0)
    assert K.parser_depth_binance({"bids": [], "asks": []}) is None


def test_demi_spread_bps_est_le_cout_de_franchissement():
    # bid 100, ask 100.2 -> spread 0.2, demi 0.1, mid 100.1 -> ~9.99 bps
    assert abs(K.demi_spread_bps(100.0, 100.2) - 9.99) < 0.05


def test_ligne_carnet_calcule_l_ecart_EXECUTABLE_pas_le_mid():
    # HL cher (bid/ask ~101), Binance moins cher (~100) : vendre HL, acheter Binance
    hl = (100.9, 101.1, 5.0, 5.0)
    binance = (99.9, 100.1, 5.0, 5.0)
    l = K.ligne_carnet("BTC", hl, binance)
    # acheter BIN a 100.1, vendre HL a 100.9 -> ecart executable ~ +80 bps
    assert l["ecart_executable_max_bps"] > 0
    assert l["hl_demi_spread_bps"] > 0 and l["taille_min_usd"] > 0


def test_une_passe_ecrit_propre_et_dedoublonne(tmp_path):
    hl = {"levels": [[{"px": "100.0", "sz": "5"}], [{"px": "100.2", "sz": "5"}]]}
    bn = {"bids": [["99.5", "5"]], "asks": [["99.7", "5"]]}
    cache = K.CF.CacheDedup()
    n1 = K.une_passe(tmp_path, ["BTC"], cache=cache,
                     post_hl=lambda c, **k: hl, get_binance=lambda c, **k: bn)
    assert n1 == 1
    ligne = json.loads((tmp_path / K.SORTIE).read_text(encoding="utf-8").strip().splitlines()[0])
    assert ligne["coin"] == "BTC" and ligne["source"] == "carnet_hl_bin"
    assert ligne["real_execution"] is False and "ecart_executable_max_bps" in ligne
    # 2e passe identique (meme cache) -> dedup -> rien de neuf
    n2 = K.une_passe(tmp_path, ["BTC"], cache=cache,
                     post_hl=lambda c, **k: hl, get_binance=lambda c, **k: bn)
    assert n2 == 0


def test_un_coin_illisible_ne_casse_pas_la_passe(tmp_path):
    def hl_ok(c, **k): return {"levels": [[{"px": "1", "sz": "1"}], [{"px": "1.01", "sz": "1"}]]}
    def bin_casse(c, **k): raise OSError("reseau")
    assert K.une_passe(tmp_path, ["BTC"], post_hl=hl_ok, get_binance=bin_casse) == 0
