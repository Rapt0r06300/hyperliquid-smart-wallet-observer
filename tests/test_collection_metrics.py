from __future__ import annotations

import json

from tools import build_collection_metrics as metrics


def test_instant_collection_metrics_counts_durable_copy_vault_fills(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog"
    campaigns = catalog / "campaigns"
    campaigns.mkdir(parents=True)

    summary = {
        "schema": "alina.copy_vault_cloud_window.v1",
        "accepted_frames": 1406,
        "persisted_frames": 1406,
        "l2_frames": 1338,
        "bbo_frames": 0,
        "queue_drops": 0,
        "manifest_inventory_complete": True,
        "frame_metrics_complete": True,
        "live_fill_counts": {"0xabc": 50},
        "reconciliation": {
            "0xabc": {
                "status": "MATCHED",
                "reference_count": 50,
                "matched_count": 50,
            }
        },
        "bundle": {
            "shard_count": 60,
            "safe_count": 40,
            "partial_count": 20,
            "reject_count": 0,
        },
    }
    campaign = {
        "kind": "copy_vault_collection",
        "status": "COMPLETE",
        "updated_at": "2026-10-01T15:10:03Z",
        "completed_units": {
            "1": {
                "result": {
                    "durable_persisted": True,
                    "release_tag": "data-v2-test",
                    "stdout": json.dumps(summary),
                }
            }
        },
    }
    (campaigns / "copy-vault.json").write_text(
        json.dumps(campaign), encoding="utf-8"
    )
    data_metrics = catalog / "DATA_METRICS.json"
    data_metrics.write_text(
        json.dumps(
            {
                "totals": {
                    "TOTAL_TRADES_COLLECTED": 0,
                    "TOTAL_TRADES_REPLAYABLE": 0,
                    "TOTAL_TRADES_SAFE": 0,
                    "TOTAL_UNIQUE_TRADES_GLOBAL": None,
                    "GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE": False,
                    "TOTAL_SHARDS": 0,
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(metrics, "CAMPAIGNS", campaigns)
    monkeypatch.setattr(metrics, "DATA_METRICS", data_metrics)
    monkeypatch.setattr(metrics, "OUTPUT", catalog / "COLLECTION_METRICS.json")

    out = metrics.build()

    assert out["instant"]["trades_collected_observed"] == 50
    assert out["instant"]["persisted_frames"] == 1406
    assert out["instant"]["shards_published"] == 60
    assert out["instant"]["coverage_complete"] is True
    assert out["by_kind"]["copy_vault_collection"]["trades_observed"] == 50
    assert out["indexed_dataset"]["trades_indexed_exact"] == 0
    assert out["indexed_dataset"]["global_unique_trades"] is None


def test_compact_checkpoint_metrics_do_not_depend_on_stdout(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog"
    campaigns = catalog / "campaigns"
    campaigns.mkdir(parents=True)
    (campaigns / "market.json").write_text(
        json.dumps(
            {
                "kind": "market_collection",
                "status": "COMPLETE",
                "updated_at": "2026-10-01T15:20:00Z",
                "completed_units": {
                    "0": {
                        "result": {
                            "durable_persisted": True,
                            "release_tag": "data-v2-market",
                            "stdout": "truncated and not valid json",
                            "collection_metrics": {
                                "trade_count_observed": 1234,
                                "record_count_observed": 2000,
                                "accepted_frames": 1800,
                                "persisted_frames": 1800,
                                "l2_frames": 700,
                                "queue_drops": 0,
                                "shard_count": 12,
                                "safe_count": 8,
                                "partial_count": 4,
                                "reject_count": 0,
                                "compressed_bytes": 500000,
                            },
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    data_metrics = catalog / "DATA_METRICS.json"
    data_metrics.write_text(json.dumps({"totals": {}}), encoding="utf-8")

    monkeypatch.setattr(metrics, "CAMPAIGNS", campaigns)
    monkeypatch.setattr(metrics, "DATA_METRICS", data_metrics)
    monkeypatch.setattr(metrics, "OUTPUT", catalog / "COLLECTION_METRICS.json")

    out = metrics.build()
    assert out["instant"]["trades_collected_observed"] == 1234
    assert out["instant"]["compressed_bytes_known"] == 500000
    assert out["instant"]["coverage_complete"] is True
    assert out["instant"]["persisted_frames"] is None


def test_incomplete_frame_metrics_are_not_reported_as_exact_zero(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog"
    campaigns = catalog / "campaigns"
    campaigns.mkdir(parents=True)
    (campaigns / "market.json").write_text(
        json.dumps(
            {
                "kind": "market_collection",
                "status": "COMPLETE",
                "updated_at": "2026-10-01T15:20:00Z",
                "completed_units": {
                    "0": {
                        "result": {
                            "durable_persisted": True,
                            "release_tag": "data-v2-market",
                            "collection_metrics": {
                                "trade_count_observed": 4,
                                "trade_count_coverage_complete": True,
                                "record_count_observed": 10,
                                "accepted_frames": 0,
                                "persisted_frames": 0,
                                "l2_frames": 0,
                                "queue_drops": 0,
                                "manifest_inventory_complete": True,
                                "frame_metrics_complete": False,
                                "shard_count": 1,
                                "safe_count": 1,
                                "partial_count": 0,
                                "reject_count": 0,
                                "compressed_bytes": 128,
                            },
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    data_metrics = catalog / "DATA_METRICS.json"
    data_metrics.write_text(json.dumps({"totals": {}}), encoding="utf-8")
    monkeypatch.setattr(metrics, "CAMPAIGNS", campaigns)
    monkeypatch.setattr(metrics, "DATA_METRICS", data_metrics)
    monkeypatch.setattr(metrics, "OUTPUT", catalog / "COLLECTION_METRICS.json")

    out = metrics.build()

    assert out["instant"]["all_collection_metrics_complete"] is False
    assert out["instant"]["units_frame_metrics_incomplete"] == 1
    assert out["instant"]["persisted_frames"] is None
    assert out["instant"]["l2_frames"] is None


def test_exact_zero_frame_metrics_remain_zero_when_explicitly_complete(
    tmp_path, monkeypatch
):
    catalog = tmp_path / "catalog"
    campaigns = catalog / "campaigns"
    campaigns.mkdir(parents=True)
    (campaigns / "zero.json").write_text(
        json.dumps(
            {
                "kind": "market_collection",
                "status": "COMPLETE",
                "completed_units": {
                    "0": {
                        "result": {
                            "durable_persisted": True,
                            "release_tag": "data-v2-zero",
                            "collection_metrics": {
                                "trade_count_observed": 0,
                                "trade_count_coverage_complete": True,
                                "record_count_observed": 0,
                                "accepted_frames": 0,
                                "persisted_frames": 0,
                                "l2_frames": 0,
                                "bbo_frames": 0,
                                "queue_drops": 0,
                                "manifest_inventory_complete": True,
                                "frame_metrics_complete": True,
                                "shard_count": 0,
                                "safe_count": 0,
                                "partial_count": 0,
                                "reject_count": 0,
                                "compressed_bytes": 0,
                                "uncompressed_bytes": 0,
                                "uncompressed_size_coverage_complete": True,
                            },
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    data_metrics = catalog / "DATA_METRICS.json"
    data_metrics.write_text(json.dumps({"totals": {}}), encoding="utf-8")
    monkeypatch.setattr(metrics, "CAMPAIGNS", campaigns)
    monkeypatch.setattr(metrics, "DATA_METRICS", data_metrics)
    monkeypatch.setattr(metrics, "OUTPUT", catalog / "COLLECTION_METRICS.json")

    out = metrics.build()

    assert out["instant"]["all_collection_metrics_complete"] is True
    assert out["instant"]["persisted_frames"] == 0
    assert out["instant"]["l2_frames"] == 0


def test_safe_build_preserves_last_good_snapshot_on_failure(tmp_path, monkeypatch):
    output = tmp_path / "COLLECTION_METRICS.json"
    output.write_text(
        json.dumps(
            {
                "schema": "alina.collection_metrics.v1",
                "status": "OK",
                "stale": False,
                "instant": {
                    "trades_collected_observed": 1234,
                    "coverage_complete": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(metrics, "OUTPUT", output)

    def boom():
        raise RuntimeError("simulated metrics failure")

    monkeypatch.setattr(metrics, "build", boom)
    out = metrics.safe_build()

    assert out["status"] == "DEGRADED"
    assert out["stale"] is True
    assert out["instant"]["trades_collected_observed"] == 1234
    assert out["source"] == "last_known_good_snapshot"
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "DEGRADED"
    assert persisted["instant"]["trades_collected_observed"] == 1234


def test_safe_build_without_previous_uses_unknown_not_zero(tmp_path, monkeypatch):
    output = tmp_path / "COLLECTION_METRICS.json"
    monkeypatch.setattr(metrics, "OUTPUT", output)

    def boom():
        raise RuntimeError("simulated first-run failure")

    monkeypatch.setattr(metrics, "build", boom)
    out = metrics.safe_build()

    assert out["status"] == "DEGRADED"
    assert out["stale"] is True
    assert out["instant"]["trades_collected_observed"] is None
    assert out["instant"]["coverage_complete"] is False


def test_source_admission_counts_no_viable_checkpoint_without_inventing_shards(
    tmp_path, monkeypatch,
):
    catalog = tmp_path / "catalog"
    campaigns = catalog / "campaigns"
    campaigns.mkdir(parents=True)
    (campaigns / "market.json").write_text(json.dumps({
        "kind": "market_collection",
        "status": "PARTIAL",
        "completed_units": {
            "0": {"result": {
                "reason": "NO_REPLAY_ADMISSIBLE_SHARDS",
                "durable_persisted": False,
                "release_tag": None,
                "source_admission": {
                    "mode": "replay_only", "excluded_shards": 2,
                    "excluded_compressed_bytes": 8192,
                    "blocking_reasons": {"SEQUENCE_OR_QUEUE_GAP": 2},
                    "no_rejected_payload_published": True,
                },
            }},
        },
    }))
    (catalog / "DATA_METRICS.json").write_text(json.dumps({"totals": {}}))
    monkeypatch.setattr(metrics, "CAMPAIGNS", campaigns)
    monkeypatch.setattr(metrics, "DATA_METRICS", catalog / "DATA_METRICS.json")
    monkeypatch.setattr(metrics, "OUTPUT", catalog / "COLLECTION_METRICS.json")
    out = metrics.build()
    assert out["totals"]["durable_units"] == 0
    assert out["totals"]["shards"] == 0
    assert out["source_admission"]["status"] == "COMPLETE"
    assert out["source_admission"]["excluded_data_published"] is False
    assert out["source_admission"]["known_excluded_shards"] == 2
    assert out["source_admission"]["known_excluded_compressed_bytes"] == 8192
    assert out["source_admission"]["zero_viable_units"] == 1
    assert out["source_admission"]["blocking_reason_occurrences"] == {
        "SEQUENCE_OR_QUEUE_GAP": 2,
    }
    assert out["paper_only"] is True
