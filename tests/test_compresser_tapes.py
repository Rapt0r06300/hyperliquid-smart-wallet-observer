"""Tests de la compression des tapes (#67-70)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import compresser_tapes as K  # noqa: E402


def test_compresser_reduit_le_volume(tmp_path):
    tape = tmp_path / "fills.jsonl"
    rows = [{"vault": "0xaaaaaaaaaa", "coin": "ETH", "px": 2000 + i, "sz": 1, "signe": 1,
             "ts_ms": 1_800_000_000_000 + i * 1000, "source": "LIVE_WS"} for i in range(500)]
    tape.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    rap = K.compresser(tape)
    assert rap["lignes"] == 500
    assert rap["octets_sortie"] > 0
    assert rap["octets_sortie"] < rap["octets_source"]   # compressé
    assert Path(rap["out"]).exists()
    assert tape.exists()   # non destructif par défaut


def test_supprimer_source(tmp_path):
    tape = tmp_path / "t.jsonl"
    tape.write_text(json.dumps({"coin": "BTC", "vault": "0xa", "ts_ms": 1}), encoding="utf-8")
    rap = K.compresser(tape, supprimer_source=True)
    assert Path(rap["out"]).exists() and not tape.exists()


def test_records_heterogenes_ok(tmp_path):
    tape = tmp_path / "h.jsonl"
    rows = [
        {"coin": "ETH", "contexte": {"mid": 2000, "spread_bps": 2.0}},
        {"coin": "BTC", "autre": [1, 2, 3], "vault": "0xb"},
    ]
    tape.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    rap = K.compresser(tape)
    assert rap["lignes"] == 2 and Path(rap["out"]).exists()
