"""Tests de l'enrichissement des fills avec contexte (pur, hors-ligne)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import enrichir_fills as E  # noqa: E402

NOW = 1_800_000_000_000


def test_plus_proche_causal_pas_de_futur():
    idx = E.construire_index([
        {"coin": "ETH", "received_at_ms": NOW - 2000, "bid": "1990", "ask": "2010"},
        {"coin": "ETH", "received_at_ms": NOW + 5000, "bid": "2100", "ask": "2110"},  # futur
    ])
    r, lag = E.plus_proche(idx, "ETH", NOW, 60_000, causal=True)
    assert r is not None and r["received_at_ms"] == NOW - 2000 and lag == 2000  # pas le futur


def test_plus_proche_hors_lag():
    idx = E.construire_index([{"coin": "ETH", "received_at_ms": NOW - 120_000, "bid": "1", "ask": "2"}])
    r, _ = E.plus_proche(idx, "ETH", NOW, 60_000)
    assert r is None


def test_enrichir_fill_contexte():
    idx_bbo = E.construire_index([{"coin": "ETH", "received_at_ms": NOW - 1000, "bid": "1998", "ask": "2002"}])
    idx_fund = E.construire_index([{"coin": "ETH", "time": NOW - 10_000, "funding": "0.0001"}])
    idx_candle = E.construire_index([{"coin": "ETH", "open_ts_ms": NOW - 30_000, "open": "2000",
                                      "high": "2020", "low": "1990", "close": "2000"}])
    fill = {"coin": "ETH", "px": "2004", "sz": "1", "signe": 1, "ts_ms": NOW}
    e = E.enrichir_fill(fill, idx_bbo=idx_bbo, idx_funding=idx_fund, idx_candle=idx_candle)
    c = e["contexte"]
    assert c["apparie_carnet"] is True and c["mid_at_fill"] == 2000.0
    assert round(c["spread_bps"], 1) == 20.0
    assert round(c["slippage_bps"], 1) == 20.0        # acheté 2004 vs mid 2000 => +20 bps
    assert c["funding_rate"] == 0.0001
    assert round(c["realized_vol_bps"], 0) == 150.0   # (2020-1990)/2000


def test_enrichir_bout_en_bout(tmp_path):
    fills = tmp_path / "fills.jsonl"
    fills.write_text("\n".join(json.dumps(f) for f in [
        {"coin": "ETH", "px": "2004", "sz": "1", "signe": 1, "ts_ms": NOW},
        {"coin": "BTC", "px": "50000", "sz": "0.1", "signe": -1, "ts_ms": NOW},  # pas de carnet BTC
    ]), encoding="utf-8")
    bbo = tmp_path / "bbo.jsonl"
    bbo.write_text(json.dumps({"coin": "ETH", "received_at_ms": NOW - 500, "bid": "1999", "ask": "2001"}),
                   encoding="utf-8")
    out = tmp_path / "out.jsonl"
    rap = E.enrichir(fills, out, bbo_path=bbo)
    assert rap["fills"] == 2 and rap["apparies_carnet"] == 1 and rap["taux_appariement"] == 0.5
    lignes = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert lignes[0]["contexte"]["apparie_carnet"] is True
    assert lignes[1]["contexte"]["apparie_carnet"] is False
