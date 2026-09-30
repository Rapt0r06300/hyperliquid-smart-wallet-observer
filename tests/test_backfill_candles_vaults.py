"""Backfill candles 5m sur les coins de vaults (rectif Flo 23/07) : lit les coins tradés + la fenêtre
depuis les fills, tire les candles par coin, détecte la troncature au cap 5000. Poster injecté (aucun
réseau)."""
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


BC = _mod("backfill_candles_vaults")


def test_coins_et_fenetre(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vault_fills.jsonl").write_text("\n".join([
        json.dumps({"coin": "BTC", "ts_ms": 1000}),
        json.dumps({"coin": "hype", "ts_ms": 5000}),
        json.dumps({"coin": "BTC", "ts_ms": 9000}),
    ]))
    coins, t0, t1 = BC.coins_et_fenetre(tmp_path)
    assert set(coins) == {"BTC", "HYPE"} and t0 == 1000 and t1 == 9000


def test_backfill_un_coin_parse_et_detecte_troncature(tmp_path):
    from hl_observer.collection import collecte_fiable as CF
    # réponse candleSnapshot HL : liste de bougies {t,T,s,i,o,c,h,l,v}
    def poster(coin, interval, a, b):
        return [{"t": 1000 * i, "T": 1000 * i + 999, "s": coin, "i": interval,
                 "o": "100", "c": "101", "h": "102", "l": "99", "v": "10"} for i in range(3)]
    bougies, tronque = BC.backfill_un_coin("BTC", 0, 10000, limiteur=CF.Limiteur(0.0), poster=poster)
    assert len(bougies) == 3 and bougies[0]["coin"] == "BTC" and bougies[0]["c"] == 101.0 and tronque is False

    def poster_plein(coin, interval, a, b):                          # réponse au cap 5000 -> tronquée
        return [{"t": i, "T": i, "s": coin, "i": interval, "o": "1", "c": "1", "h": "1", "l": "1", "v": "1"}
                for i in range(BC.CAP_CANDLES)]
    _, tronque2 = BC.backfill_un_coin("BTC", 0, 10 ** 9, limiteur=CF.Limiteur(0.0), poster=poster_plein)
    assert tronque2 is True
