from __future__ import annotations

import json
from pathlib import Path

from hl_observer.realtime.feed_quality_reader import read_coin_feed_quality


def _feed(channel: str, *, ready: bool = True, score: float = 92.0) -> dict:
    return {
        "source_id": "hyperliquid",
        "channel": channel,
        "instrument": "BTC",
        "ready": ready,
        "feed_quality_score": score,
        "reasons": [],
    }


def _write(path: Path, *, generated_at_ms: int = 10_000) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "hypersmart.feed_quality.v1",
                "generated_at_ms": generated_at_ms,
                "feeds": {
                    "hyperliquid:bbo:BTC": _feed("bbo", score=94.0),
                    "hyperliquid:l2Book:BTC": _feed("l2Book", score=87.0),
                    "hyperliquid:trades:BTC": _feed("trades", ready=False, score=10.0),
                },
            }
        ),
        encoding="utf-8",
    )


def test_reader_exige_bbo_et_l2_et_prend_le_score_minimum(tmp_path: Path):
    path = tmp_path / "feed_quality.json"
    _write(path)

    quality = read_coin_feed_quality(path, coin="btc", now_ms=11_000)

    assert quality.ready is True
    assert quality.feed_quality_score == 87.0
    assert quality.ready_channels == ("bbo", "l2Book")
    assert "trades" not in quality.required_channels


def test_reader_refuse_un_snapshot_global_perime(tmp_path: Path):
    path = tmp_path / "feed_quality.json"
    _write(path)

    quality = read_coin_feed_quality(path, coin="BTC", now_ms=20_001)

    assert quality.ready is False
    assert "FEED_QUALITY_FILE_STALE" in quality.reasons
    assert quality.file_age_ms == 10_001.0


def test_reader_refuse_un_canal_obligatoire_absent(tmp_path: Path):
    path = tmp_path / "feed_quality.json"
    payload = {
        "schema_version": "hypersmart.feed_quality.v1",
        "generated_at_ms": 10_000,
        "feeds": {"hyperliquid:bbo:BTC": _feed("bbo")},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    quality = read_coin_feed_quality(path, coin="BTC", now_ms=10_100)

    assert quality.ready is False
    assert quality.feed_quality_score is None
    assert "REQUIRED_FEED_MISSING:l2Book" in quality.reasons


def test_reader_ne_transforme_pas_un_fichier_invalide_en_etat_sain(tmp_path: Path):
    path = tmp_path / "feed_quality.json"
    path.write_text("{not-json", encoding="utf-8")

    quality = read_coin_feed_quality(path, coin="BTC", now_ms=10_100)

    assert quality.ready is False
    assert quality.feed_quality_score is None
    assert quality.reasons == ("FEED_QUALITY_FILE_INVALID",)


def test_raisons_diagnostiques_d_un_feed_ready_ne_bloquent_pas(tmp_path: Path):
    path = tmp_path / "feed_quality.json"
    _write(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["feeds"]["hyperliquid:bbo:BTC"]["reasons"] = ["RECENT_RECONNECT_RECOVERED"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    quality = read_coin_feed_quality(path, coin="BTC", now_ms=10_100)

    assert quality.ready is True
    assert "bbo:RECENT_RECONNECT_RECOVERED" in quality.reasons
