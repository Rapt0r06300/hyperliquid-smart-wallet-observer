"""Contract tests for byte-certified AlinaSync SAFE -> Copy-Vault replay input."""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import tools.copy_vault_safe_bridge as bridge_module
import tools.unpack_verified_safe as unpack_module
from tools.copy_vault_safe_bridge import SafeBridgeError, build_safe_copy_workspace
from tools.restore_alina import _windows_io_path as canonical_windows_io_path


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
                    "time": 100_000, "dir": "Open Long", "closedPnl": "0.5",
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


def _broad_state_envelope() -> dict:
    address = "0x" + "1" * 40
    raw = json.dumps({
        "vault": address,
        "phase": "START",
        "clearinghouseState": {
            "marginSummary": {"accountValue": "1000"},
            "assetPositions": [],
            "time": 99_990,
        },
    }, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "hypersmart.tick.v1",
        "source_id": "hyperliquid_public_info",
        "channel": "copy_vault_broad_state",
        "instrument": "*",
        "event_kind": "SNAPSHOT",
        "exchange_ts_ms": None,
        "received_ts_ms": 100_050,
        "local_monotonic_ns": 12345678,
        "connection_id": None,
        "read_only": True,
        "real_execution": False,
        "raw_payload": raw,
        "raw_sha256": _sha(raw.encode("utf-8")),
        "parsed_summary": {"vault": address, "phase": "START", "nav_usd": 1000.0},
        "provenance": {
            "url": "https://api.hyperliquid.xyz/info",
            "network": "mainnet",
            "access": "read_only",
            "transport": "https",
            "authenticated": False,
            "request_type": "clearinghouseState",
            "broad_sweep": True,
            "timestamp_semantics": "receive_observation_time_only",
            "request_send_wall_ms": 100_000,
            "request_receive_wall_ms": 100_050,
        },
    }


def _corpus(
    tmp_path: Path, envelopes: list[dict], *, release_tag: str = "test-release",
    long_dataset_names: bool = False,
) -> Path:
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
        "CREATE TABLE current_safe_shards (dataset_id TEXT, release_tag TEXT, "
        "relative_path TEXT, bytes INTEGER, "
        "sha256 TEXT, stat_dev INTEGER, stat_ino INTEGER, "
        "stat_mtime_ns INTEGER, stat_ctime_ns INTEGER)"
    )
    for n, record in enumerate(envelopes):
        tag = release_tag
        name = f"{'d' * 180}-{n}.jsonl" if long_dataset_names else f"safe-{n}.jsonl"
        plain = recovery / "usable" / "unpacked" / tag / name
        canonical_windows_io_path(plain).parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
        canonical_windows_io_path(plain).write_bytes(data)
        gz = recovery / "usable" / "shards" / tag / (name + ".gz")
        canonical_windows_io_path(gz).parent.mkdir(parents=True, exist_ok=True)
        # Stable gzip metadata makes the physical SAFE fixture identical across
        # the archive-read and extracted-JSONL paths below.
        canonical_windows_io_path(gz).write_bytes(gzip.compress(data, mtime=0))
        compressed = canonical_windows_io_path(gz).read_bytes()
        canonical_windows_io_path(plain.parent / (name + ".alina.json")).write_text(
            json.dumps({
                "schema": "alina.safe_jsonl_proof.v1",
                "compressed_sha256": _sha(compressed),
                "jsonl_sha256": _sha(data),
                "jsonl_bytes": len(data),
            }), encoding="utf-8",
        )
        stat = canonical_windows_io_path(gz).stat()
        db.execute(
            "INSERT INTO current_safe_shards VALUES (?,?,?,?,?,?,?,?,?)",
            (
                name.removesuffix(".jsonl"), tag,
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
        "mode": "FULL_JSONL",
        "physical_jsonl_available": True,
        "streamable_gzip_available": True,
        "replay_read_mode": "JSONL",
        "certified_shards": len(envelopes),
        "unpacked_shards": len(envelopes),
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
    assert fill["isSnapshot"] is False
    assert fill["is_snapshot"] is False
    assert fill["closed_pnl"] == "0.5"
    assert fill["source_quality_status"] == "SAFE"
    assert fill["source_manifest_verified"] is True
    assert fill["source_replay_compatible"] is True
    assert fill["source_catalog_sha256"] == report["catalog_sha256"]
    assert fill["source_shard_sha256"] == _sha(
        (tmp_path / "runtime/recovery/full/usable/shards/test-release/safe-0.jsonl.gz").read_bytes()
    )
    assert fill["source_dataset_id"] == "safe-0"
    assert fill["source_frame_number"] == 1
    assert len(fill["source_frame_sha256"]) == 64
    assert len(fill["source_raw_sha256"]) == 64
    assert book["causal_observation"] is True
    assert book["received_at_ms"] == 100_050
    assert book["source_quality_status"] == "SAFE"
    assert book["source_manifest_verified"] is True
    assert book["source_replay_compatible"] is True
    assert len(book["bids5"]) == len(book["asks5"]) == 5
    # Prove downstream canonical source discovery and causal book loader consume
    # the generated payload, not just that its files exist.
    from hl_observer.backtesting.copy_vault_book_loader import load_observed_books
    from hl_observer.datasets.source_discovery import discover_family_sources

    sources = discover_family_sources(workspace)
    assert {p.name for p in sources["copy_vault"]} == {
        "vault_fills.jsonl", "vault_fills_live.jsonl", "vault_snapshots.jsonl",
        "copy_vault_l2_tape.jsonl",
    }
    books, book_audit = load_observed_books(workspace, coins={"BTC"})
    assert len(books.get("BTC", [])) == 1
    assert book_audit["valid_rows"] == 1
    assert books["BTC"][0]["causal_observation"] is True
    assert books["BTC"][0]["connection_id"] == "live-test-1"
    assert books["BTC"][0]["l2_gap_epoch"] == 3
    assert books["BTC"][0]["source_evidence_status"] == "STRUCTURALLY_COMPLETE"
    from hl_observer.backtesting.copy_vault_chargeurs_safe import charger_leader_fills_safe

    assert charger_leader_fills_safe(workspace) == [
        {"vault": "0xabc", "ts_ms": 100_050, "closed_pnl": 0.5}
    ]
    proof = json.loads((
        workspace / "runtime/reports/datasets/SELECTION_PROVENANCE.json"
    ).read_text())
    assert proof["economic_proof"] is False
    assert proof["selected_files"] == 2
    assert proof["source_read_mode"] == "JSONL"
    assert proof["verified_unpacked_bytes"] == sum(
        row["jsonl_bytes"] for row in proof["safe_input_shards"]
    )
    assert proof["verified_streamed_bytes"] == 0
    assert proof["source_read_mode_shards"] == {"JSONL": 2}
    assert build_safe_copy_workspace(tmp_path)["workspace"] == str(workspace)


def test_bridge_streams_seal_only_archives_without_claiming_physical_unpack(
    tmp_path: Path,
) -> None:
    recovery = _corpus(tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")])
    report_path = recovery / "UNPACK_REPORT.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.update({
        "status": "SAFE_SEAL_CERTIFICATION_COMPLETE",
        "mode": "SEAL_ONLY",
        "physical_jsonl_available": False,
        "streamable_gzip_available": True,
        "replay_read_mode": "GZIP_STREAM",
    })
    report_path.write_text(json.dumps(report), encoding="utf-8")
    for plain in (recovery / "usable" / "unpacked" / "test-release").glob("*.jsonl"):
        plain.unlink()

    result = build_safe_copy_workspace(tmp_path)

    assert result["status"] == "SAFE_COPY_WORKSPACE_READY"
    assert result["source_read_mode"] == "GZIP_STREAM"
    proof = json.loads((
        Path(result["workspace"])
        / "runtime/reports/datasets/SELECTION_PROVENANCE.json"
    ).read_text())
    assert proof["verified_unpacked_bytes"] == 0
    assert proof["verified_streamed_bytes"] == sum(
        row["jsonl_bytes"] for row in proof["safe_input_shards"]
    )
    assert proof["source_read_mode_shards"] == {"GZIP_STREAM": 2}


@pytest.mark.parametrize(
    "missing_or_invalid",
    [
        {"mode": None},
        {"physical_jsonl_available": None},
        {"physical_jsonl_available": False},
        {"streamable_gzip_available": None},
        {"replay_read_mode": "GZIP_STREAM"},
    ],
)
def test_bridge_rejects_full_jsonl_receipt_without_physical_proof(
    tmp_path: Path, missing_or_invalid: dict[str, object],
) -> None:
    recovery = _corpus(
        tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")]
    )
    unpack_path = recovery / "UNPACK_REPORT.json"
    unpack = json.loads(unpack_path.read_text(encoding="utf-8"))
    for key, value in missing_or_invalid.items():
        if value is None:
            unpack.pop(key, None)
        else:
            unpack[key] = value
    unpack_path.write_text(json.dumps(unpack), encoding="utf-8")

    with pytest.raises(SafeBridgeError, match="restoration and extraction are not certified"):
        build_safe_copy_workspace(tmp_path)


def test_copy_vault_scope_keeps_only_active_registry_rows_in_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery = _corpus(
        tmp_path,
        [
            _envelope("copy_vault_fills"),
            _envelope("copy_vault_l2"),
            _envelope("bbo"),
        ],
    )
    unpack_path = recovery / "UNPACK_REPORT.json"
    unpack = json.loads(unpack_path.read_text(encoding="utf-8"))
    unpack.update({
        "unpack_scope": "COPY_VAULT_ONLY",
        "unpacked_shards": 2,
    })
    unpack_path.write_text(json.dumps(unpack), encoding="utf-8")

    shard_paths = sorted((recovery / "usable" / "shards" / "test-release").glob("*.gz"))
    active = {
        path: (
            path.stat().st_size, _sha(path.read_bytes()), f"safe-{index}",
            "copy_vault_fills" if index == 0 else "copy_vault_l2", "test-release",
        )
        for index, path in enumerate(shard_paths[:2])
    }
    monkeypatch.setattr(
        unpack_module,
        "_catalog_safe_bytes",
        lambda *_args, **_kwargs: (active, ["copy_vault_fills", "copy_vault_l2"]),
    )

    report = build_safe_copy_workspace(tmp_path)

    assert report["status"] == "SAFE_COPY_WORKSPACE_READY"
    assert report["selected_shards"] == 2
    assert report["counts"]["copy_vault_fills"] == 1
    assert report["counts"]["copy_vault_l2"] == 1
    assert report["counts"]["copy_vault_snapshot"] == 0


def test_bridge_reports_mixed_physical_and_stream_reads_accurately(tmp_path: Path) -> None:
    recovery = _corpus(
        tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")]
    )
    plain = recovery / "usable" / "unpacked" / "test-release" / "safe-1.jsonl"
    plain.unlink()

    result = build_safe_copy_workspace(tmp_path)

    assert result["status"] == "SAFE_COPY_WORKSPACE_READY"
    assert result["source_read_mode"] == "MIXED"
    assert result["reported_read_mode"] == "JSONL"
    proof = json.loads((
        Path(result["workspace"])
        / "runtime/reports/datasets/SELECTION_PROVENANCE.json"
    ).read_text())
    sizes_by_mode = {
        row["relative_path"].rsplit("/", 1)[-1]: row["jsonl_bytes"]
        for row in proof["safe_input_shards"]
    }
    assert proof["verified_unpacked_bytes"] == sizes_by_mode["safe-0.jsonl.gz"]
    assert proof["verified_streamed_bytes"] == sizes_by_mode["safe-1.jsonl.gz"]
    assert proof["source_read_mode_shards"] == {"GZIP_STREAM": 1, "JSONL": 1}


def test_bridge_can_bind_an_explicit_current_recovery_and_catalog(
    tmp_path: Path,
) -> None:
    recovery = _corpus(tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")])
    report = build_safe_copy_workspace(
        tmp_path,
        recovery_dir=recovery,
        catalog_path=tmp_path / "catalog" / "DATA_INDEX.json",
    )
    assert report["status"] == "SAFE_COPY_WORKSPACE_READY"
    assert report["selected_shards"] == 2


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
    with pytest.raises(SafeBridgeError, match="no causal live fills"):
        build_safe_copy_workspace(tmp_path)


def test_bridge_propagates_collector_proof_when_live_snapshot_flag_is_omitted(
    tmp_path: Path,
) -> None:
    from hl_observer.backtesting.copy_vault_chargeurs_safe import charger_leader_fills_safe

    live = _envelope("copy_vault_fills")
    message = json.loads(live["raw_payload"])
    del message["data"]["isSnapshot"]
    live["raw_payload"] = json.dumps(message, sort_keys=True, separators=(",", ":"))
    live["raw_sha256"] = _sha(live["raw_payload"].encode("utf-8"))
    live["parsed_summary"] = {"is_snapshot": False}
    _corpus(tmp_path, [live, _envelope("copy_vault_l2")])

    report = build_safe_copy_workspace(tmp_path)

    workspace = Path(report["workspace"])
    fill = json.loads((workspace / "runtime/data/vault_fills_live.jsonl").read_text())
    assert fill["isSnapshot"] is False
    assert fill["source_quality_status"] == "SAFE"
    assert fill["source_frame_number"] == 1
    assert charger_leader_fills_safe(workspace) == [
        {"vault": "0xabc", "ts_ms": 100_050, "closed_pnl": 0.5}
    ]


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


def test_bridge_materializes_only_proven_safe_broad_state_asof_nav(tmp_path: Path) -> None:
    _corpus(tmp_path, [
        _envelope("copy_vault_fills"),
        _broad_state_envelope(),
        _envelope("copy_vault_l2"),
    ])

    report = build_safe_copy_workspace(tmp_path)
    workspace = Path(report["workspace"])
    nav_path = workspace / "runtime/data/vault_snapshots.jsonl"
    nav = json.loads(nav_path.read_text(encoding="utf-8"))
    provenance = json.loads(
        (workspace / "runtime/reports/datasets/SELECTION_PROVENANCE.json").read_text(
            encoding="utf-8"
        )
    )

    assert report["counts"]["copy_vault_broad_state"] == 1
    assert report["counts"]["snapshot_nav_observations"] == 1
    assert nav["vault"] == "0x" + "1" * 40
    assert nav["nav_usd"] == 1000.0
    assert nav["ts_ms"] == 100_050  # availability is the observed receive time
    assert nav["source_family"] == "copy_vault_broad_state"
    assert nav["source_quality_status"] == "SAFE"
    assert nav["source_manifest_verified"] is True
    assert nav["source_replay_compatible"] is True
    assert nav["source_frame_sha256"] == _sha(
        (json.dumps(_broad_state_envelope(), sort_keys=True) + "\n").encode("utf-8")
    )
    assert provenance["economic_proof"] is False


def test_safe_bridge_nav_is_consumable_by_copy_vault_asof_pipeline(tmp_path: Path) -> None:
    """The bridge's verified output must pass the real downstream SAFE NAV reader."""
    import tools.pipeline_copie_reel as pipeline

    _corpus(tmp_path, [
        _envelope("copy_vault_fills"),
        _broad_state_envelope(),
        _envelope("copy_vault_l2"),
    ])
    report = build_safe_copy_workspace(tmp_path)

    assert pipeline._nav_history(Path(report["workspace"])) == {
        "0x" + "1" * 40: [(100_050, 1_000.0)],
    }


@pytest.mark.parametrize(
    "mutation",
    ("receive_time", "raw_hash", "summary_nav", "exchange_time", "source_url"),
)
def test_broad_state_nav_rejects_incomplete_or_inconsistent_evidence(mutation: str) -> None:
    record = _broad_state_envelope()
    if mutation == "receive_time":
        record["provenance"]["request_receive_wall_ms"] += 1
    elif mutation == "raw_hash":
        record["raw_sha256"] = "0" * 64
    elif mutation == "summary_nav":
        record["parsed_summary"]["nav_usd"] = 2_000.0
    elif mutation == "exchange_time":
        record["exchange_ts_ms"] = 99_990
    else:
        record["provenance"]["url"] = "https://example.invalid/info"

    with pytest.raises(SafeBridgeError):
        bridge_module._broad_state_snapshot(record)


def test_bridge_rejects_corrupted_extracted_data(tmp_path: Path) -> None:
    recovery = _corpus(tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")])
    plain = recovery / "usable" / "unpacked" / "test-release" / "safe-0.jsonl"
    plain.write_bytes(plain.read_bytes() + b"{}\n")
    with pytest.raises(SafeBridgeError, match="byte proof mismatch"):
        build_safe_copy_workspace(tmp_path)


def _sans_extraction(recovery: Path) -> int:
    """Efface les JSONL extraits : il ne reste que les archives et leurs sceaux."""
    efface = 0
    for chemin in (recovery / "usable" / "unpacked").rglob("*.jsonl"):
        chemin.unlink()
        efface += 1
    return efface


def test_le_pont_travaille_depuis_les_ARCHIVES_quand_l_extraction_manque(tmp_path: Path) -> None:
    """LE cas qui bloquait tout (20/11/2026).

    Extraire le corpus SAFE reclame **2,31 To** quand la machine en offre 705 Go :
    `unpack_verified_safe` refuse proprement et conserve le corpus compresse. Sans ce chemin,
    le pont ne pouvait JAMAIS convertir, et 1 792 577 shards restaient invisibles au labo.
    Le sceau portant les deux empreintes, on decompresse en flux et on verifie les memes
    preuves -- sans ecrire un octet.
    """
    recovery = _corpus(tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")])
    assert _sans_extraction(recovery) == 2

    report = build_safe_copy_workspace(tmp_path)

    assert report["status"] == "SAFE_COPY_WORKSPACE_READY"
    assert report["selected_shards"] == 2
    assert report["counts"]["copy_vault_fills"] == 1
    assert report["counts"]["copy_vault_l2"] == 1
    workspace = Path(report["workspace"])
    fill = json.loads((workspace / "runtime/data/vault_fills_live.jsonl").read_text())
    assert fill["vault"] == "0xabc"
    # Rien n a ete extrait sur disque au passage : c est tout l interet.
    assert not list((recovery / "usable" / "unpacked").rglob("*.jsonl"))


def test_les_deux_chemins_donnent_le_MEME_resultat(tmp_path: Path, tmp_path_factory) -> None:
    """Lire l archive ou l extraction doit etre indiscernable : sinon la preuve differe."""
    avec = tmp_path_factory.mktemp("avec")
    _corpus(avec, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")])
    r_avec = build_safe_copy_workspace(avec)

    sans = tmp_path_factory.mktemp("sans")
    recovery = _corpus(sans, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")])
    _sans_extraction(recovery)
    r_sans = build_safe_copy_workspace(sans)

    assert r_avec["counts"] == r_sans["counts"]
    assert r_avec["selected_shards"] == r_sans["selected_shards"]
    # Plus fort qu un digest de selection : les fichiers PRODUITS doivent etre identiques
    # octet pour octet. Si lire l archive donnait autre chose que lire l extraction, la
    # preuve livree au labo differerait selon le disque disponible.
    assert ({n: o["sha256"] for n, o in r_avec["outputs"].items()}
            == {n: o["sha256"] for n, o in r_sans["outputs"].items()})
    assert r_avec["catalog_sha256"] == r_sans["catalog_sha256"]


def test_une_archive_corrompue_est_refusee_meme_sans_extraction(tmp_path: Path) -> None:
    """La certification ne doit pas s affaiblir quand on lit en flux."""
    recovery = _corpus(tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")])
    _sans_extraction(recovery)
    archive = recovery / "usable" / "shards" / "test-release" / "safe-0.jsonl.gz"
    archive.write_bytes(archive.read_bytes()[:-5] + b"XXXXX")
    with pytest.raises(SafeBridgeError):
        build_safe_copy_workspace(tmp_path)


def test_bridge_preserves_available_shallow_l2_depth(tmp_path: Path) -> None:
    _corpus(tmp_path, [
        _envelope("copy_vault_fills"), _envelope("copy_vault_l2", shallow=True),
    ])

    report = build_safe_copy_workspace(tmp_path)

    assert report["counts"]["copy_vault_l2"] == 1
    workspace = Path(report["workspace"])
    book = json.loads(
        (workspace / "runtime/data/copy_vault_l2_tape.jsonl").read_text()
    )
    assert book["source_bid_levels"] == 4
    assert book["source_ask_levels"] == 4
    assert len(book["bids5"]) == len(book["asks5"]) == 4


def test_book_loader_rejects_boolean_checkpoint_counters(tmp_path: Path) -> None:
    _corpus(tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")])
    report = build_safe_copy_workspace(tmp_path)
    workspace = Path(report["workspace"])
    state_path = workspace / "runtime/data/copy_vault_checkpoint_tail_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"counters": {"input_rotations": True}}),
        encoding="utf-8",
    )

    from hl_observer.backtesting.copy_vault_book_loader import load_observed_books

    _, audit = load_observed_books(workspace, coins={"BTC"})

    assert audit["clean_epoch_receipt"]["collector_gap_count"] == 1
    assert audit["clean_epoch_receipt"]["receipt_valid"] is False


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



def test_bridge_reads_long_safe_release_paths(tmp_path: Path, monkeypatch) -> None:
    release_tag = "r" * 180
    _corpus(
        tmp_path,
        [_envelope("copy_vault_fills"), _envelope("copy_vault_l2")],
        release_tag=release_tag,
        long_dataset_names=True,
    )
    seen = []
    original = bridge_module._windows_io_path

    def recording_normalizer(path):
        if len(str(path)) > 260:
            seen.append(str(path))
        return original(path)

    monkeypatch.setattr(bridge_module, "_windows_io_path", recording_normalizer)
    report = build_safe_copy_workspace(tmp_path)

    assert report["status"] == "SAFE_COPY_WORKSPACE_READY"
    assert report["selected_shards"] == 2
    assert len(seen) >= 6



def test_bridge_l2_freshness_and_depth_match_canonical_replay_contract() -> None:
    record = _envelope("copy_vault_l2", shallow=True)
    record["received_ts_ms"] = record["exchange_ts_ms"] + 1_501

    book = bridge_module._book(record)

    assert book["causal_observation"] is True
    assert book["received_at_ms"] - book["exchange_ts_ms"] == 1_501
    assert book["source_bid_levels"] == 4
    assert book["source_ask_levels"] == 4
    assert len(book["bids5"]) == len(book["asks5"]) == 4

    record["received_ts_ms"] = record["exchange_ts_ms"] + 30_000
    assert bridge_module._book(record)["received_at_ms"] - record["exchange_ts_ms"] == 30_000

    record["received_ts_ms"] += 1
    with pytest.raises(SafeBridgeError, match="freshness"):
        bridge_module._book(record)


def test_bridge_preserves_top_level_l2_gap_epoch() -> None:
    record = _envelope("copy_vault_l2")
    record["parsed_summary"] = {}
    record["l2_gap_epoch"] = 7

    assert bridge_module._book(record)["l2_gap_epoch"] == 7


def test_bridge_rejects_conflicting_l2_gap_epochs() -> None:
    record = _envelope("copy_vault_l2")
    record["l2_gap_epoch"] = 4

    with pytest.raises(SafeBridgeError, match="conflicting L2 gap epoch"):
        bridge_module._book(record)



def test_bridge_records_bad_l2_as_quarantined_without_dropping_the_frame(tmp_path: Path) -> None:
    bad = _envelope("copy_vault_l2")
    message = json.loads(bad["raw_payload"])
    message["data"]["levels"][0] = []
    bad["raw_payload"] = json.dumps(message, sort_keys=True, separators=(",", ":"))
    bad["raw_sha256"] = _sha(bad["raw_payload"].encode("utf-8"))
    _corpus(tmp_path, [
        _envelope("copy_vault_fills"), bad, _envelope("copy_vault_l2"),
    ])

    report = build_safe_copy_workspace(tmp_path)

    assert report["status"] == "SAFE_COPY_WORKSPACE_READY"
    assert report["counts"]["copy_vault_l2"] == 1
    assert report["input_decisions"]["quarantined"] == 1
    workspace = Path(report["workspace"])
    provenance = json.loads((
        workspace / "runtime/reports/datasets/SELECTION_PROVENANCE.json"
    ).read_text(encoding="utf-8"))
    decisions = (workspace / provenance["input_decisions"]["path"]).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(decisions) == 1
    decision = json.loads(decisions[0])
    assert decision["decision"] == "QUARANTINE"
    assert decision["reason_code"] == "L2_REPLAY_CONTRACT_REJECTED"
    assert decision["frame_sha256"] == _sha(
        (json.dumps(bad, sort_keys=True) + "\n").encode("utf-8")
    )



def test_bridge_quarantines_fill_with_unknown_snapshot_semantics(tmp_path: Path) -> None:
    unknown = _envelope("copy_vault_fills")
    message = json.loads(unknown["raw_payload"])
    del message["data"]["isSnapshot"]
    unknown["raw_payload"] = json.dumps(message, sort_keys=True, separators=(",", ":"))
    unknown["raw_sha256"] = _sha(unknown["raw_payload"].encode("utf-8"))
    _corpus(tmp_path, [
        _envelope("copy_vault_fills"), unknown, _envelope("copy_vault_l2"),
    ])

    report = build_safe_copy_workspace(tmp_path)

    assert report["counts"]["copy_vault_fills"] == 1
    assert report["input_decisions"]["quarantined"] == 1
    workspace = Path(report["workspace"])
    provenance = json.loads((
        workspace / "runtime/reports/datasets/SELECTION_PROVENANCE.json"
    ).read_text(encoding="utf-8"))
    decision = json.loads((workspace / provenance["input_decisions"]["path"]).read_text(
        encoding="utf-8"
    ).splitlines()[0])
    assert decision["reason_code"] == "FILL_REPLAY_CONTRACT_REJECTED"
    assert decision["frame_sha256"] == _sha(
        (json.dumps(unknown, sort_keys=True) + "\n").encode("utf-8")
    )



def test_bridge_persists_auditable_no_go_when_live_fills_are_absent(tmp_path: Path) -> None:
    _corpus(tmp_path, [
        _envelope("copy_vault_fills", snapshot=True), _envelope("copy_vault_l2"),
    ])

    with pytest.raises(SafeBridgeError, match="no causal live fills"):
        build_safe_copy_workspace(tmp_path)

    diagnostic_files = list((
        tmp_path / "runtime/research_lab/copy_vault_safe/diagnostics"
    ).glob("no-go-*/NO_GO.json"))
    assert len(diagnostic_files) == 1
    diagnostic = json.loads(diagnostic_files[0].read_text(encoding="utf-8"))
    assert diagnostic["status"] == "SAFE_COPY_NO_GO"
    assert diagnostic["counts"]["copy_vault_fills"] == 0
    assert diagnostic["counts"]["copy_vault_l2"] == 1
    assert diagnostic["economic_proof"] is False
    decisions = diagnostic_files[0].parent / "SAFE_INPUT_DECISIONS.jsonl"
    assert decisions.is_file()
    assert _sha(decisions.read_bytes()) == diagnostic["input_decisions"]["sha256"]


def _perimetre_copy_vault(tmp_path: Path, monkeypatch, unpacked_shards: int) -> Path:
    """Registre complet de 3 shards ; les deux premiers seulement sont dans le périmètre actif déballé."""
    import tools.unpack_verified_safe as U

    recovery = _corpus(tmp_path, [_envelope("copy_vault_fills"), _envelope("copy_vault_l2"), _envelope("copy_vault_fills")])
    rapport = json.loads((recovery / "UNPACK_REPORT.json").read_text())
    rapport.update({"unpack_scope": "COPY_VAULT_ONLY", "unpacked_shards": unpacked_shards})
    (recovery / "UNPACK_REPORT.json").write_text(json.dumps(rapport), encoding="utf-8")
    actifs = {}
    for n, family in ((0, "copy_vault_fills"), (1, "copy_vault_l2")):
        archive = recovery / "usable" / "shards" / "test-release" / f"safe-{n}.jsonl.gz"
        compressed = canonical_windows_io_path(archive).read_bytes()
        actifs[archive] = (
            len(compressed), _sha(compressed), f"safe-{n}", family, "test-release",
        )
    monkeypatch.setattr(U, "_catalog_safe_bytes", lambda *a, **k: (actifs, ["copy_vault_fills", "copy_vault_l2"]))
    return recovery


def test_le_pont_ne_lit_que_le_perimetre_deballe(tmp_path: Path, monkeypatch) -> None:
    """23/11/2026 : le pont parcourait les 1,79 M de shards du registre pour en écarter 99 %."""
    _perimetre_copy_vault(tmp_path, monkeypatch, unpacked_shards=2)
    report = build_safe_copy_workspace(tmp_path)
    assert report["status"] == "SAFE_COPY_WORKSPACE_READY" and report["selected_shards"] == 2   # le 3e est ignoré


def test_le_pont_refuse_un_perimetre_et_un_deballage_qui_divergent(tmp_path: Path, monkeypatch) -> None:
    import pytest

    from tools.copy_vault_safe_bridge import SafeBridgeError

    _perimetre_copy_vault(tmp_path, monkeypatch, unpacked_shards=3)
    with pytest.raises(SafeBridgeError, match="disagree"):
        build_safe_copy_workspace(tmp_path)


def test_bridge_rejects_safe_registry_identity_that_disagrees_with_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3

    recovery = _perimetre_copy_vault(tmp_path, monkeypatch, unpacked_shards=2)
    registry = sqlite3.connect(recovery / "SAFE_SHARDS.sqlite3")
    registry.execute(
        "UPDATE current_safe_shards SET sha256=? WHERE relative_path=?",
        ("f" * 64, "usable/shards/test-release/safe-0.jsonl.gz"),
    )
    registry.commit()
    registry.close()

    with pytest.raises(SafeBridgeError, match="registry identity differs from catalog"):
        build_safe_copy_workspace(tmp_path)


def _sans_drapeau(classement_collecteur):
    """Fill en direct dont le message brut n'a PAS `isSnapshot` (cas reel des 29 messages SAFE)."""
    env = _envelope("copy_vault_fills")
    message = json.loads(env["raw_payload"])
    del message["data"]["isSnapshot"]
    env["raw_payload"] = json.dumps(message, sort_keys=True, separators=(",", ":"))
    env["raw_sha256"] = _sha(env["raw_payload"].encode("utf-8"))
    if classement_collecteur is not None:
        env["parsed_summary"] = {"is_snapshot": classement_collecteur}
    return env


def test_drapeau_absent_mais_collecteur_d_accord_est_un_fill_en_direct(tmp_path: Path) -> None:
    _corpus(tmp_path, [_sans_drapeau(False), _envelope("copy_vault_l2")])
    report = build_safe_copy_workspace(tmp_path)
    assert report["counts"]["copy_vault_fills"] == 1 and report["input_decisions"]["quarantined"] == 0


def test_drapeau_absent_et_collecteur_contradictoire_reste_en_quarantaine(tmp_path: Path) -> None:
    _corpus(tmp_path, [_envelope("copy_vault_fills"), _sans_drapeau(True), _envelope("copy_vault_l2")])
    report = build_safe_copy_workspace(tmp_path)
    assert report["counts"]["copy_vault_fills"] == 1 and report["input_decisions"]["quarantined"] == 1
