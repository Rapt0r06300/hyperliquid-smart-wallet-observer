"""Contract tests for byte-certified AlinaSync SAFE -> Copy-Vault replay input."""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tools.copy_vault_safe_bridge import SafeBridgeError, build_safe_copy_workspace


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _envelope(
    channel: str, *, snapshot: bool = False, shallow: bool = False,
    coin: str = "BTC",
) -> dict:
    if channel in {"copy_vault_fills", "copy_vault_snapshot"}:
        is_snapshot = snapshot or channel == "copy_vault_snapshot"
        message = {
            "channel": "userFills",
            "data": {
                "user": "0xabc",
                "isSnapshot": is_snapshot,
                "fills": [{
                    "coin": "BTC", "px": "100", "sz": "1", "side": "B",
                    "time": 100_000, "dir": "Open Long",
                    "tid": 321, "oid": 123, "hash": "0x123", "fee": "0.01",
                }],
            },
        }
        instrument = "0xabc"
        source = (
            "hyperliquid_public_userfills_backfill"
            if channel == "copy_vault_snapshot"
            else "hyperliquid_public_userfills"
        )
    else:
        size = 4 if shallow else 5
        message = {
            "channel": "l2Book",
            "data": {
                "coin": coin, "time": 100_000,
                "levels": [
                    [{"px": str(100 - n), "sz": "1", "n": 1} for n in range(size)],
                    [{"px": str(101 + n), "sz": "1", "n": 1} for n in range(size)],
                ],
            },
        }
        instrument = coin
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
        "parsed_summary": {"l2_gap_epoch": 3} if channel == "copy_vault_l2" else {},
        "read_only": True,
        "real_execution": False,
        "raw_payload": raw,
        "raw_sha256": _sha(raw.encode("utf-8")),
        "provenance": {
            "access": "read_only", "authenticated": False,
            "transport": "https" if channel == "copy_vault_snapshot" else "websocket",
            **({
                "historical_only": True,
                "forward_evidence_allowed": False,
                "timestamp_semantics": "causal_event_availability",
            } if channel == "copy_vault_snapshot" else {}),
        },
    }


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
    from hl_observer.backtesting.copy_vault_book_loader import load_observed_books
    from hl_observer.datasets.source_discovery import discover_family_sources

    sources = discover_family_sources(workspace)
    assert {p.name for p in sources["copy_vault"]} == {
        "vault_fills.jsonl", "vault_fills_live.jsonl", "copy_vault_l2_tape.jsonl",
    }
    books, book_audit = load_observed_books(workspace, coins={"BTC"})
    assert len(books.get("BTC", [])) == 1
    assert book_audit["valid_rows"] == 1
    assert books["BTC"][0]["causal_observation"] is True
    assert books["BTC"][0]["connection_id"] == "live-test-1"
    assert books["BTC"][0]["l2_gap_epoch"] == 3
    proof = json.loads((
        workspace / "runtime/reports/datasets/SELECTION_PROVENANCE.json"
    ).read_text())
    assert proof["economic_proof"] is False
    assert proof["selected_files"] == 2
    assert build_safe_copy_workspace(tmp_path)["workspace"] == str(workspace)


def test_bridge_preserves_native_market_case_and_l2_gap_identity(tmp_path: Path) -> None:
    from hl_observer.backtesting.copy_vault_book_loader import load_observed_books

    _corpus(tmp_path, [
        _envelope("copy_vault_fills"),
        _envelope("copy_vault_l2", coin="kPEPE"),
    ])

    report = build_safe_copy_workspace(tmp_path)
    workspace = Path(report["workspace"])
    book = json.loads(
        (workspace / "runtime/data/copy_vault_l2_tape.jsonl").read_text()
    )
    books, audit = load_observed_books(workspace, coins={"kPEPE"})

    assert book["coin"] == "kPEPE"
    assert book["connection_id"] == "live-test-1"
    assert book["l2_gap_epoch"] == 3
    assert len(books["kPEPE"]) == 1
    assert audit["valid_rows"] == 1


def test_bridge_excludes_snapshot_fills(tmp_path: Path) -> None:
    _corpus(tmp_path, [
        _envelope("copy_vault_fills", snapshot=True), _envelope("copy_vault_l2"),
    ])
    with pytest.raises(SafeBridgeError, match="lacks both causal fills"):
        build_safe_copy_workspace(tmp_path)


def test_bridge_keeps_historical_snapshot_fills_separate_from_forward(tmp_path: Path) -> None:
    _corpus(tmp_path, [
        _envelope("copy_vault_fills"),
        _envelope("copy_vault_snapshot"),
        _envelope("copy_vault_l2"),
    ])
    report = build_safe_copy_workspace(tmp_path)
    workspace = Path(report["workspace"])

    historical = json.loads(
        (workspace / "runtime/data/vault_fills.jsonl").read_text(encoding="utf-8")
    )
    incremental = json.loads(
        (workspace / "runtime/data/vault_fills_live.jsonl").read_text(encoding="utf-8")
    )
    provenance = json.loads(
        (workspace / "runtime/reports/datasets/SELECTION_PROVENANCE.json").read_text(
            encoding="utf-8"
        )
    )
    assert historical["source"] == "REST_BACKFILL"
    assert historical["isSnapshot"] is True
    assert historical["causal_forward_eligible"] is False
    assert incremental["source"] == "LIVE_WS"
    assert incremental["isSnapshot"] is False
    assert report["counts"]["historical_fill_observations"] == 1
    assert provenance["snapshot_fills_train_only"] is True
    assert provenance["snapshot_fills_excluded_from_forward"] is True


def test_bridge_rejects_corrupted_extracted_data(tmp_path: Path) -> None:
    recovery = _corpus(tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")])
    plain = recovery / "usable" / "unpacked" / "test-release" / "safe-0.jsonl"
    plain.write_bytes(plain.read_bytes() + b"{}\n")
    with pytest.raises(SafeBridgeError, match="byte proof mismatch"):
        build_safe_copy_workspace(tmp_path)


def test_bridge_rejects_shallow_l2(tmp_path: Path) -> None:
    _corpus(tmp_path, [
        _envelope("copy_vault_fills"), _envelope("copy_vault_l2", shallow=True),
    ])
    with pytest.raises(SafeBridgeError, match="fewer than five levels"):
        build_safe_copy_workspace(tmp_path)


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
