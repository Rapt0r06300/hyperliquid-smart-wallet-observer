"""Contract tests for byte-certified AlinaSync SAFE -> Copy-Vault replay input."""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tools.copy_vault_safe_bridge import SafeBridgeError, _fills, build_safe_copy_workspace


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _envelope(channel: str, *, snapshot: bool = False, shallow: bool = False) -> dict:
    if channel == "copy_vault_fills":
        message = {
            "channel": "userFills",
            "data": {
                "user": "0xabc",
                "isSnapshot": snapshot,
                "fills": [{
                    "coin": "BTC", "px": "100", "sz": "1", "side": "B",
                    "time": 100_000, "dir": "Open Long",
                    "tid": 321, "oid": 123, "hash": "0x123",
                }],
            },
        }
        instrument = "0xabc"
        source = "hyperliquid_public_userfills"
    else:
        size = 4 if shallow else 5
        message = {
            "channel": "l2Book",
            "data": {
                "coin": "BTC", "time": 100_000,
                "levels": [
                    [{"px": str(100 - n), "sz": "1", "n": 1} for n in range(size)],
                    [{"px": str(101 + n), "sz": "1", "n": 1} for n in range(size)],
                ],
            },
        }
        instrument = "BTC"
        source = "hyperliquid_public_copy_l2"
    raw = json.dumps(message, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "hypersmart.tick.v1",
        "source_id": source,
        "channel": channel,
        "instrument": instrument,
        "exchange_ts_ms": 100_000,
        "received_ts_ms": 100_050,
        "local_monotonic_ns": 12345678,
        "connection_id": "live-test-1",
        "read_only": True,
        "real_execution": False,
        "raw_payload": raw,
        "raw_sha256": _sha(raw.encode("utf-8")),
        "provenance": {"access": "read_only", "authenticated": False},
    }


def _history_envelope() -> dict:
    raw = json.dumps({
        "request": {
            "type": "userFillsByTime", "user": "0xabc",
            "startTime": 1, "endTime": 100_000, "aggregateByTime": False,
        },
        "fills": [{
            "vault": "0xabc", "coin": "BTC", "px": 100.0, "sz": 1.0,
            "signe": 1, "dir": "Open Long", "ts_ms": 100_000,
            "tid": 321, "oid": 123, "hash": "0xhistory",
        }],
    }, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "hypersmart.tick.v1",
        "source_id": "hyperliquid_info_user_fills_by_time_history",
        "channel": "copy_vault_snapshot", "instrument": "0xabc",
        "exchange_ts_ms": 100_000, "received_ts_ms": 100_050,
        "local_monotonic_ns": 12345678, "connection_id": "history-1",
        "read_only": True, "real_execution": False,
        "raw_payload": raw, "raw_sha256": _sha(raw.encode("utf-8")),
        "provenance": {
            "access": "read_only", "authenticated": False,
            "transport": "https", "request_type": "userFillsByTime",
            "window_reconciliation_complete": True, "history_bootstrap": True,
        },
    }


def test_exact_rest_backfill_is_normalized_only_with_complete_window_provenance():
    row = {
        "schema_version": "hypersmart.tick.v1",
        "source_id": "hyperliquid_info_user_fills_by_time",
        "channel": "copy_vault_fills",
        "instrument": "0xabc",
        "exchange_ts_ms": 100_000,
        "received_ts_ms": 100_050,
        "local_monotonic_ns": 12345678,
        "connection_id": "copy-vault-rest-1",
        "read_only": True,
        "real_execution": False,
        "raw_payload": json.dumps({
            "request": {
                "type": "userFillsByTime", "user": "0xabc",
                "startTime": 99_000, "endTime": 101_000,
                "aggregateByTime": False,
            },
            "fills": [{
                "vault": "0xabc", "coin": "BTC", "px": 100.0, "sz": 1.0,
                "signe": 1, "dir": "Open Long", "ts_ms": 100_000,
                "tid": 321, "oid": 123, "hash": "0x123",
            }],
        }, sort_keys=True, separators=(",", ":")),
        "provenance": {
            "access": "read_only", "authenticated": False,
            "transport": "https", "request_type": "userFillsByTime",
            "window_reconciliation_complete": True, "history_bootstrap": False,
        },
    }
    row["raw_sha256"] = _sha(row["raw_payload"].encode("utf-8"))

    fills, excluded = _fills(row)

    assert excluded == 0
    assert len(fills) == 1
    assert fills[0]["ts_ms"] == 100_000
    assert fills[0]["received_at_ms"] == 100_050
    assert fills[0]["source"] == "REST_BACKFILL"


def test_rest_backfill_without_complete_window_proof_is_rejected():
    row = {
        "schema_version": "hypersmart.tick.v1",
        "source_id": "hyperliquid_info_user_fills_by_time",
        "channel": "copy_vault_fills",
        "instrument": "0xabc",
        "exchange_ts_ms": 100_000,
        "received_ts_ms": 100_050,
        "local_monotonic_ns": 12345678,
        "connection_id": "copy-vault-rest-1",
        "read_only": True,
        "real_execution": False,
        "raw_payload": json.dumps({
            "request": {"type": "userFillsByTime", "user": "0xabc", "startTime": 99_000, "endTime": 101_000},
            "fills": [{"vault": "0xabc", "coin": "BTC", "px": 100.0, "sz": 1.0, "signe": 1, "dir": "Open Long", "ts_ms": 100_000}],
        }, sort_keys=True, separators=(",", ":")),
        "provenance": {"access": "read_only", "authenticated": False, "transport": "https", "request_type": "userFillsByTime"},
    }
    row["raw_sha256"] = _sha(row["raw_payload"].encode("utf-8"))
    with pytest.raises(SafeBridgeError, match="complete window"):
        _fills(row)


def test_historical_rest_bootstrap_is_marked_and_not_mislabeled_forward():
    row = {
        "schema_version": "hypersmart.tick.v1",
        "source_id": "hyperliquid_info_user_fills_by_time_history",
        "channel": "copy_vault_fills",
        "instrument": "0xabc",
        "exchange_ts_ms": 100_000,
        "received_ts_ms": 100_050,
        "local_monotonic_ns": 12345678,
        "connection_id": "copy-vault-history-1",
        "read_only": True,
        "real_execution": False,
        "raw_payload": json.dumps({
            "request": {
                "type": "userFillsByTime", "user": "0xabc",
                "startTime": 1, "endTime": 101_000,
                "aggregateByTime": False,
            },
            "fills": [{
                "vault": "0xabc", "coin": "BTC", "px": 100.0, "sz": 1.0,
                "signe": 1, "dir": "Open Long", "ts_ms": 100_000,
                "tid": 321, "oid": 123, "hash": "0x123",
            }],
        }, sort_keys=True, separators=(",", ":")),
        "provenance": {
            "access": "read_only", "authenticated": False,
            "transport": "https", "request_type": "userFillsByTime",
            "window_reconciliation_complete": True, "history_bootstrap": True,
        },
    }
    row["raw_sha256"] = _sha(row["raw_payload"].encode("utf-8"))

    fills, excluded = _fills(row)

    assert excluded == 0
    assert fills[0]["source"] == "REST_BACKFILL"
    assert fills[0]["historical_bootstrap"] is True


def test_bridge_routes_historical_rest_to_train_file_separately(tmp_path: Path) -> None:
    _corpus(tmp_path, [
        _history_envelope(), _envelope("copy_vault_fills"), _envelope("copy_vault_l2"),
    ])

    report = build_safe_copy_workspace(tmp_path)

    assert report["counts"]["copy_vault_snapshot"] == 1
    assert report["counts"]["copy_vault_fills"] == 1
    workspace = Path(report["workspace"])
    historical = json.loads((workspace / "runtime/data/vault_fills.jsonl").read_text())
    forward = json.loads((workspace / "runtime/data/vault_fills_live.jsonl").read_text())
    assert historical["historical_bootstrap"] is True
    assert forward["source"] == "LIVE_WS"
    binding = json.loads((workspace / "SAFE_INPUT_MANIFEST.json").read_text())
    assert binding["selection_digest"] == report["selection_digest"]


def _corpus(tmp_path: Path, envelopes: list[dict]) -> Path:
    recovery = tmp_path / "runtime" / "recovery" / "full"
    recovery.mkdir(parents=True)
    index = tmp_path / "catalog" / "DATA_INDEX.json"
    index.parent.mkdir(parents=True)
    index.write_text('{"schema": "test_catalog"}\\n', encoding="utf-8")
    catalog = _sha(index.read_bytes())
    db = sqlite3.connect(recovery / "SAFE_SHARDS.sqlite3")
    db.execute("CREATE TABLE safe_shard_registry_meta (key TEXT, value TEXT)")
    db.executemany(
        "INSERT INTO safe_shard_registry_meta VALUES (?,?)",
        [("run_status", "COMPLETE"), ("active_catalog_sha256", catalog)],
    )
    db.execute(
        "CREATE TABLE current_safe_shards (relative_path TEXT, bytes INTEGER, "
        "sha256 TEXT, stat_dev INTEGER, stat_ino INTEGER, "
        "stat_mtime_ns INTEGER, stat_ctime_ns INTEGER)"
    )
    for n, record in enumerate(envelopes):
        tag = "test-release"
        name = f"safe-{n}.jsonl"
        plain = recovery / "usable" / "unpacked" / tag / name
        plain.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
        plain.write_bytes(data)
        gz = recovery / "usable" / "shards" / tag / (name + ".gz")
        gz.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(gz, "wb") as stream:
            stream.write(data)
        compressed = gz.read_bytes()
        (plain.parent / (name + ".alina.json")).write_text(
            json.dumps({
                "schema": "alina.safe_jsonl_proof.v1",
                "compressed_sha256": _sha(compressed),
                "jsonl_sha256": _sha(data),
                "jsonl_bytes": len(data),
            }), encoding="utf-8",
        )
        stat = gz.stat()
        db.execute(
            "INSERT INTO current_safe_shards VALUES (?,?,?,?,?,?,?)",
            (
                f"usable/shards/{tag}/{name}.gz", len(compressed), _sha(compressed),
                stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns,
            ),
        )
    db.commit()
    db.close()
    (recovery / "RESTORE_REPORT.json").write_text(json.dumps({
        "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "status": "REPLAY_READY_COMPLETE",
        "selection_families": ["copy_vault_fills", "copy_vault_l2", "copy_vault_snapshot"],
        "catalog_verification": {"source_index_sha256": catalog},
        "classification": {
            "materialization_complete": True, "usable_shards": len(envelopes),
            "failures": [],
        },
    }), encoding="utf-8")
    (recovery / "UNPACK_REPORT.json").write_text(json.dumps({
        "status": "SAFE_UNPACK_COMPLETE",
        "certified_shards": len(envelopes),
        "catalog_index_sha256": catalog,
    }), encoding="utf-8")
    return recovery


def test_bridge_consumes_certified_gzip_without_global_unpack(tmp_path: Path) -> None:
    recovery = _corpus(
        tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")]
    )
    import shutil

    shutil.rmtree(recovery / "usable" / "unpacked")
    (recovery / "UNPACK_REPORT.json").unlink()

    report = build_safe_copy_workspace(tmp_path)

    assert report["status"] == "SAFE_COPY_WORKSPACE_READY"
    assert report["selected_shards"] == 2
    proof = json.loads((
        Path(report["workspace"])
        / "runtime/reports/datasets/SELECTION_PROVENANCE.json"
    ).read_text())
    assert proof["source_kind"] == "alina-sync-safe-compressed"


def test_bridge_uses_real_safe_envelopes_and_reports_provenance(tmp_path: Path) -> None:
    _corpus(tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")])
    report = build_safe_copy_workspace(tmp_path)
    assert report["status"] == "SAFE_COPY_WORKSPACE_READY"
    assert report["selected_shards"] == 2
    assert report["counts"]["copy_vault_fills"] == 1
    assert report["counts"]["copy_vault_l2"] == 1
    workspace = Path(report["workspace"])
    fill = json.loads((workspace / "runtime/data/vault_fills_live.jsonl").read_text())
    book = json.loads((workspace / "runtime/data/copy_vault_l2_tape.jsonl").read_text())
    assert fill["vault"] == "0xabc"
    assert fill["source"] == "LIVE_WS"
    assert fill["received_at_ms"] == 100_050
    assert book["causal_observation"] is True
    assert book["received_at_ms"] == 100_050
    assert len(book["bids5"]) == len(book["asks5"]) == 5
    # Prove downstream canonical source discovery and causal book loader consume
    # the generated payload, not just that its files exist.
    from hl_observer.datasets.source_discovery import discover_family_sources
    from hl_observer.backtesting.copy_vault_book_loader import load_observed_books

    sources = discover_family_sources(workspace)
    assert {p.name for p in sources["copy_vault"]} == {
        "vault_fills.jsonl", "vault_fills_live.jsonl", "copy_vault_l2_tape.jsonl",
    }
    books, book_audit = load_observed_books(workspace, coins={"BTC"})
    assert len(books.get("BTC", [])) == 1
    assert book_audit["valid_rows"] == 1
    assert books["BTC"][0]["causal_observation"] is True
    proof = json.loads((
        workspace / "runtime/reports/datasets/SELECTION_PROVENANCE.json"
    ).read_text())
    assert proof["economic_proof"] is False
    assert proof["selected_files"] == 2
    assert build_safe_copy_workspace(tmp_path)["workspace"] == str(workspace)


def test_bridge_excludes_snapshot_fills(tmp_path: Path) -> None:
    _corpus(tmp_path, [
        _envelope("copy_vault_fills", snapshot=True), _envelope("copy_vault_l2"),
    ])
    with pytest.raises(SafeBridgeError, match="lacks both causal fills"):
        build_safe_copy_workspace(tmp_path)


def test_bridge_accepts_outer_classified_live_fill_without_raw_snapshot_flag(
    tmp_path: Path,
) -> None:
    fill = _envelope("copy_vault_fills")
    raw = json.loads(fill["raw_payload"])
    raw["data"].pop("isSnapshot")
    fill["raw_payload"] = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    fill["raw_sha256"] = _sha(fill["raw_payload"].encode("utf-8"))
    _corpus(tmp_path, [fill, _envelope("copy_vault_l2")])

    report = build_safe_copy_workspace(tmp_path)

    assert report["counts"]["copy_vault_fills"] == 1


def test_bridge_rejects_corrupted_registered_compressed_data(tmp_path: Path) -> None:
    recovery = _corpus(tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")])
    archive = recovery / "usable" / "shards" / "test-release" / "safe-0.jsonl.gz"
    archive.write_bytes(archive.read_bytes() + b"corrupt")
    with pytest.raises(SafeBridgeError, match="registered SAFE shard was modified"):
        build_safe_copy_workspace(tmp_path)


def test_bridge_rejects_shallow_l2(tmp_path: Path) -> None:
    _corpus(tmp_path, [
        _envelope("copy_vault_fills"), _envelope("copy_vault_l2", shallow=True),
    ])
    with pytest.raises(SafeBridgeError, match="lacks both causal fills and subsecond L2"):
        build_safe_copy_workspace(tmp_path)


def test_bridge_excludes_shallow_l2_when_executable_book_exists(tmp_path: Path) -> None:
    _corpus(tmp_path, [
        _envelope("copy_vault_fills"),
        _envelope("copy_vault_l2", shallow=True),
        _envelope("copy_vault_l2"),
    ])

    report = build_safe_copy_workspace(tmp_path)

    assert report["counts"]["copy_vault_l2"] == 1
    assert report["counts"]["shallow_l2_excluded"] == 1


def test_bridge_excludes_stale_l2_but_keeps_causal_books(tmp_path: Path) -> None:
    stale = _envelope("copy_vault_l2")
    stale["received_ts_ms"] = stale["exchange_ts_ms"] + 1_501
    _corpus(tmp_path, [
        _envelope("copy_vault_fills"), stale, _envelope("copy_vault_l2"),
    ])

    report = build_safe_copy_workspace(tmp_path)

    assert report["counts"]["copy_vault_l2"] == 1
    assert report["counts"]["stale_l2_excluded"] == 1


def test_bridge_rejects_stale_safe_registry(tmp_path: Path) -> None:
    recovery = _corpus(tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")])
    db = sqlite3.connect(recovery / "SAFE_SHARDS.sqlite3")
    db.execute("UPDATE safe_shard_registry_meta SET value='IN_PROGRESS' WHERE key='run_status'")
    db.commit()
    db.close()
    with pytest.raises(SafeBridgeError, match="does not match final catalog"):
        build_safe_copy_workspace(tmp_path)


def test_bridge_refuses_stale_catalog_after_alinasync(tmp_path: Path) -> None:
    _corpus(tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")])
    (tmp_path / "catalog" / "DATA_INDEX.json").write_text(
        '{"schema": "changed_catalog"}\\n', encoding="utf-8",
    )
    with pytest.raises(SafeBridgeError, match="active DATA_INDEX changed"):
        build_safe_copy_workspace(tmp_path)
