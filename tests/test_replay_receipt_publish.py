from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import backfill_replay_compatibility as replay  # noqa: E402
import replay_receipt_publish as publisher  # noqa: E402


def _fixture(tmp_path: Path, monkeypatch):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    dataset_id = "immutable-trades"
    sha = "a" * 64
    manifest_path = tmp_path / "datasets" / "quarantine" / "immutable-trades.manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({
        "dataset_id": dataset_id,
        "sha256": sha,
        "family": "trades",
        "source": "binance_usdm_official_archive",
        "venue": "binance",
        "symbol": "BTCUSDT",
        "release": {"repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
                    "tag": "archive-v2-verified", "asset_name": "trades.jsonl.gz"},
    }), encoding="utf-8")
    row = {
        "dataset_id": dataset_id, "sha256": sha, "bytes": 99,
        "family": "trades", "source": "binance_usdm_official_archive",
        "venue": "binance", "symbol": "BTCUSDT",
        "manifest_path": manifest_path.relative_to(tmp_path).as_posix(),
        "quality_status": "PARTIAL", "replay_compatible": False,
    }
    proof = {
        "asset_sha256": sha, "asset_size": 99, "verified_from_release": True,
        "verifier_version": replay.VERIFIER_VERSION, "replay_compatible": True,
        "record_count": 2, "replay_reason": "STRICT_PARSE_CHRONOLOGY_OK",
    }
    index_path = catalog / "DATA_INDEX.json"
    patch_path = catalog / "REPLAY_COMPAT_PATCH.json"
    index_path.write_text(json.dumps({"shards": [row]}), encoding="utf-8")
    patch_path.write_text(json.dumps({"results": {dataset_id: proof}}), encoding="utf-8")
    monkeypatch.setattr(replay, "ROOT", tmp_path)
    monkeypatch.setattr(replay, "INDEX_PATH", index_path)
    monkeypatch.setattr(replay, "PATCH_PATH", patch_path)
    monkeypatch.setattr(publisher, "_previous_results", lambda: {})
    return row, proof, index_path, patch_path


def test_cached_verified_receipt_reapplies_without_redownloading(tmp_path, monkeypatch):
    row, proof, index, patch = _fixture(tmp_path, monkeypatch)
    cache = tmp_path / "receipts.json"
    assert publisher.capture(cache) == 1
    assert json.loads(cache.read_text())["receipts"][row["dataset_id"]]["sha256"] == row["sha256"]
    patch.write_text(json.dumps({"results": {}}), encoding="utf-8")
    invoked = []
    monkeypatch.setattr(replay, "_apply_result",
                        lambda current_row, result, **kw: (
                            invoked.append(result),
                            current_row.update(replay_compatible=result["replay_compatible"])))
    monkeypatch.setattr(replay, "_refresh_catalog",
                        lambda document, root: index.write_text(json.dumps(document), encoding="utf-8"))
    assert publisher.apply(cache) == 1
    assert invoked == [proof]
    assert json.loads(patch.read_text())["results"][row["dataset_id"]] == proof
    assert json.loads(index.read_text())["shards"][0]["replay_compatible"] is True
    assert publisher.apply(cache) == 0


def test_cached_receipt_rejects_changed_immutable_sha_before_writes(tmp_path, monkeypatch):
    row, proof, index, patch = _fixture(tmp_path, monkeypatch)
    cache = tmp_path / "receipts.json"
    publisher.capture(cache)
    patch.write_text(json.dumps({"results": {}}), encoding="utf-8")
    before_patch = patch.read_bytes()
    before_index = json.loads(index.read_text())
    before_index["shards"][0]["sha256"] = "b" * 64
    index.write_text(json.dumps(before_index), encoding="utf-8")
    monkeypatch.setattr(replay, "_apply_result",
                        lambda *_args, **_kw: pytest.fail("unsafe application"))
    with pytest.raises(replay.BackfillError, match="unverified replay receipt"):
        publisher.apply(cache)
    assert patch.read_bytes() == before_patch


def test_cached_receipt_rejects_forged_or_outdated_verification(tmp_path, monkeypatch):
    row, proof, index, patch = _fixture(tmp_path, monkeypatch)
    proof["verified_from_release"] = False
    patch.write_text(json.dumps({"results": {row["dataset_id"]: proof}}), encoding="utf-8")
    with pytest.raises(replay.BackfillError, match="lacks immutable SHA proof"):
        publisher.capture(tmp_path / "receipts.json")


def test_cached_receipts_prevalidate_all_before_mutation(tmp_path, monkeypatch):
    row, _, index, patch = _fixture(tmp_path, monkeypatch)
    cache = tmp_path / "receipts.json"
    publisher.capture(cache)
    payload = json.loads(cache.read_text())
    payload["receipts"]["different-id"] = payload["receipts"][row["dataset_id"]]
    cache.write_text(json.dumps(payload), encoding="utf-8")
    patch.write_text(json.dumps({"results": {}}), encoding="utf-8")
    monkeypatch.setattr(replay, "_apply_result",
                        lambda *_args, **_kw: pytest.fail("partial manifest modification"))
    with pytest.raises(replay.BackfillError, match="target absent"):
        publisher.apply(cache)
