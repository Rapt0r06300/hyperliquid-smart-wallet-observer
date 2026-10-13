"""Admission protects the durable dataset from unreplayable source shards."""
from __future__ import annotations

import hashlib
import json

from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.datasets.v2_pipeline import build_bundle, locally_replay_admissible
from tools.publish_dataset_v2_release import publish_bundle


def _event(ts: int, kind: str = "UPDATE") -> TickEnvelope:
    return TickEnvelope(
        source_id="bybit_public_ws", channel="l2Book", instrument="BTCUSDT",
        event_kind=kind, raw_payload={"ts": ts, "kind": kind},
        exchange_ts_ms=ts, received_ts_ms=ts + 5,
        local_monotonic_ns=ts * 1000, connection_id="ws-a",
        sequence=ts,
        provenance={
            "access": "read_only", "transport": "websocket", "authenticated": False,
        },
    )


def test_source_rejects_unreplayable_before_publication(tmp_path):
    root = tmp_path / "ticks"
    writer = PartitionedTickDatasetWriter(root)
    writer.append(_event(1000))
    writer.rotate_all()
    writer.append(_event(1010, "GAP"))
    writer.rotate_all()
    sources = list(root.glob("**/shards/*.jsonl.gz"))
    assert len(sources) == 2
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    bundle = tmp_path / "bundle"
    index = build_bundle(root, bundle, collector_version="a" * 40,
                         replay_admission_only=True)
    assert index["source_shard_count"] == 2
    assert index["shard_count"] == 1
    assert index["source_admission"]["excluded_shards"] == 1
    assert "GAP" in index["source_admission"]["blocking_reasons"]
    assert len(list((bundle / "assets").glob("*"))) == 1
    manifest = json.loads(next((bundle / "manifests").glob("*.json")).read_text())
    assert locally_replay_admissible(manifest)
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}


def test_all_rejected_bundle_does_not_contact_github(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "manifests").mkdir(parents=True)
    bad = {
        "dataset_id": "bad", "release_asset": "bad.jsonl.gz",
        "quality_status": "REJECT", "replay_compatible": False,
        "quality_reasons": ["GAP"], "validation_allowed": False,
    }
    (bundle / "manifests" / "bad.json").write_text(json.dumps(bad))
    (bundle / "BUNDLE_INDEX.json").write_text(json.dumps({
        "manifests": ["manifests/bad.json"], "source_admission": {"excluded_shards": 1},
    }))
    def refuse_network(*args, **kwargs):
        raise AssertionError("rejected bundle must not contact GitHub")
    monkeypatch.setattr("tools.publish_dataset_v2_release.ensure_release", refuse_network)
    result = publish_bundle(
        bundle, repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
        tag="data-v2-rejected-only", target="main", title="rejection",
    )
    assert result["status"] == "NO_REPLAY_ADMISSIBLE_SHARDS"
    assert result["excluded_payload_count"] == 1
    assert result["read_only"] is True
