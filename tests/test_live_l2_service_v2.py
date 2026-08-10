from __future__ import annotations

import json

from hl_observer.market_data.live_l2_service import LiveL2Service, write_dynamic_snapshot


def test_live_l2_service_reads_dynamic_snapshot(tmp_path):
    snapshot = {
        "SOL": {
            "coin": "SOL",
            "bids": [[149.0, 2.0]],
            "asks": [[150.0, 2.0]],
            "source": "hyperliquid:ws:l2Book:dynamic",
            "ts_ms": 10_000,
        }
    }
    write_dynamic_snapshot(tmp_path, snapshot)
    service = LiveL2Service(tmp_path)
    reader = service.as_legacy_reader()
    book = reader("SOL")
    assert book is not None


def test_dynamic_snapshot_persists_normalized_rows(tmp_path):
    snapshot = {
        "SOL": {
            "coin": "SOL",
            "bids": [[149.0, 2.0]],
            "asks": [[150.0, 2.0]],
            "source": "hyperliquid:ws:l2Book:dynamic",
            "ts_ms": 10_000,
        }
    }
    write_dynamic_snapshot(tmp_path, snapshot)
    raw = json.loads(
        (tmp_path / "runtime" / "data" / "raw_l2_live.json").read_text(encoding="utf-8")
    )
    assert raw["SOL"]["bids"] == [[149.0, 2.0]]
    assert raw["SOL"]["asks"] == [[150.0, 2.0]]
    assert raw["SOL"]["source"] == "hyperliquid:ws:l2Book:dynamic"


def test_experimental_runner_injects_canonical_reader(tmp_path, monkeypatch):
    from hl_observer.experimental import runner

    captured = {}

    def copy_adapter(root, now_ms=None, lecteur_l2=None, **kwargs):
        captured["reader"] = lecteur_l2
        return [], []

    monkeypatch.setattr(runner, "COLLECTEURS", {"copy_vault": copy_adapter})
    runner.tick(tmp_path, now_ms=50_000, moteurs=("copy_vault",))
    assert callable(captured["reader"])
