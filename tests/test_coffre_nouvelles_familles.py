"""Coffre : exclusion des données inférées + certification trades/candle/positions."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.datasets import coffre_certifie as C  # noqa: E402

NOW = 1_800_000_000_000


# ---- INTÉGRITÉ : l'inféré ne doit JAMAIS être certifié SAFE --------------------

def test_inference_jamais_reconnue_par_sniffer():
    # un fill ESTIMÉ (explorer) a la forme d'un fill mais source EXPLORER_INFERRED
    inf = {"vault": "0xabc1234567", "coin": "ETH", "px": 2000, "sz": 1, "ts_ms": NOW - 1,
           "observed_at_ms": NOW, "source": "EXPLORER_INFERRED", "certifie": False}
    assert C.sniffer_famille(inf) is None            # ignoré, pas classé fill


def test_inference_quarantaine_si_routee():
    inf = {"vault": "0xabc1234567", "coin": "ETH", "px": 2000, "sz": 1, "ts_ms": NOW - 1,
           "observed_at_ms": NOW, "source": "EXPLORER_INFERRED"}
    _, dec, raison = C.certifier_record(inf, famille=C.FAMILLE_FILLS_FORWARD, source="x", now_ms=NOW)
    assert dec == C.QUARANTAINE and "inference" in raison


def test_fill_reel_toujours_certifie():
    reel = {"vault": "0xabc1234567", "coin": "ETH", "px": 2000, "sz": 1, "ts_ms": NOW - 1,
            "observed_at_ms": NOW, "signe": 1, "source": "LIVE_POLL"}
    norm, dec, _ = C.certifier_record(reel, famille=C.FAMILLE_FILLS_FORWARD, source="LIVE_POLL", now_ms=NOW)
    assert dec in (C.PASS, C.REPARE) and norm["causal_forward_eligible"] is True


# ---- Nouvelles familles ---------------------------------------------------------

def test_detecter_nouveaux_fichiers():
    assert C.detecter_famille("copy_vault_trades_lane.jsonl")[0] == C.FAMILLE_TRADES
    assert C.detecter_famille("copy_vault_candle_lane.jsonl")[0] == C.FAMILLE_CANDLE
    assert C.detecter_famille("copy_vault_positions_lane.jsonl")[0] == C.FAMILLE_POSITION
    assert C.detecter_famille("node_fills_tape.jsonl")[0] == C.FAMILLE_FILLS_BACKFILL
    assert C.detecter_famille("copy_vault_twap_lane.jsonl")[0] == C.FAMILLE_FILLS_FORWARD


def test_certifier_trade():
    tr = {"schema_version": "hypersmart.copy_vault_trades.v1", "coin": "ETH", "price": 2000.5,
          "size": 1.5, "exchange_ts_ms": NOW - 10, "aggressor_side": "BUY", "tid": 7}
    norm, dec, _ = C.certifier_record(tr, famille=C.FAMILLE_TRADES, source="x", now_ms=NOW)
    assert dec == C.PASS and norm["price"] == 2000.5 and norm["size"] == 1.5
    bad = dict(tr, price=0)
    assert C.certifier_record(bad, famille=C.FAMILLE_TRADES, source="x", now_ms=NOW)[1] == C.QUARANTAINE


def test_certifier_candle():
    ca = {"coin": "ETH", "open": 2000, "high": 2020, "low": 1990, "close": 2010, "open_ts_ms": NOW - 60000}
    norm, dec, _ = C.certifier_record(ca, famille=C.FAMILLE_CANDLE, source="x", now_ms=NOW)
    assert dec == C.PASS and norm["high"] == 2020
    incoherent = dict(ca, high=1980)   # high < low/open
    assert C.certifier_record(incoherent, famille=C.FAMILLE_CANDLE, source="x", now_ms=NOW)[1] == C.QUARANTAINE


def test_certifier_position():
    po = {"vault": "0xabc1234567", "coin": "ETH", "szi": 2.5, "received_at_ms": NOW - 5}
    norm, dec, _ = C.certifier_record(po, famille=C.FAMILLE_POSITION, source="x", now_ms=NOW)
    assert dec == C.PASS and norm["szi"] == 2.5
    assert C.certifier_record(dict(po, szi=None), famille=C.FAMILLE_POSITION, source="x", now_ms=NOW)[1] == C.QUARANTAINE


def test_sniffer_reconnait_schemas():
    assert C.sniffer_famille({"schema_version": "hypersmart.copy_vault_trades.v1", "coin": "ETH"})[0] == C.FAMILLE_TRADES
    assert C.sniffer_famille({"schema_version": "hypersmart.copy_vault_candle.v1", "coin": "ETH"})[0] == C.FAMILLE_CANDLE
    assert C.sniffer_famille({"schema_version": "hypersmart.copy_vault_positions.v1",
                              "vault": "0xa", "coin": "ETH", "szi": 1})[0] == C.FAMILLE_POSITION
