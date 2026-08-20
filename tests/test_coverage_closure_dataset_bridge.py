from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import hl_observer.ops.dataset_bridge as bridge
from hl_observer.datasets.github_release_bridge import DatasetBridgeError


def _args(*extra: str):
    return bridge._parser().parse_args(list(extra))


def test_parser_validation_and_patterns() -> None:
    args = _args("find", "--family", "copy-vault", "--contains", "foo", "--preset", "economic-core")
    patterns = bridge._patterns(args)
    assert "foo" in patterns
    assert len(patterns) > 1

    args = _args("find", "--max-download-gib", "-1")
    with pytest.raises(DatasetBridgeError, match="max-download"):
        bridge._validate_args(args)
    args = _args("find", "--disk-reserve-gib", "-1")
    with pytest.raises(DatasetBridgeError, match="disk-reserve"):
        bridge._validate_args(args)
    args = _args("find", "--suite", bridge.suite_names()[0], "--contains", "x")
    with pytest.raises(DatasetBridgeError, match="sélection reproductible"):
        bridge._validate_args(args)
    args = _args("locate")
    with pytest.raises(DatasetBridgeError, match="locate exige"):
        bridge._validate_args(args)
    args = _args("plan-all", "--family", "lead-lag")
    with pytest.raises(DatasetBridgeError, match="aucun filtre"):
        bridge._validate_args(args)
    bridge._validate_args(_args("status"))


def test_snapshot_fingerprint_is_deterministic_and_fail_closed(tmp_path) -> None:
    manifest = tmp_path / "manifest.gz"
    manifest.write_bytes(b"manifest-bytes")
    release = {"name": "R", "tag_name": "v1", "published_at": "now"}
    assets = {
        "b": SimpleNamespace(size=2, sha256="22", asset_id=2),
        "a": SimpleNamespace(size=1, sha256="11", asset_id=1),
    }
    one = bridge.snapshot_fingerprint(manifest, release, assets, repository="o/r", release_id=7)
    two = bridge.snapshot_fingerprint(manifest, release, dict(reversed(list(assets.items()))), repository="o/r", release_id=7)
    assert one == two and len(one) == 64
    assert bridge.snapshot_fingerprint(manifest, release, assets, repository="o/r", release_id=8) != one
    with pytest.raises(DatasetBridgeError, match="Manifeste FULL/COLD absent"):
        bridge.snapshot_fingerprint(tmp_path / "missing", release, assets, repository="o/r", release_id=7)


def test_legacy_preview_success_and_missing_asset(monkeypatch) -> None:
    records = [SimpleNamespace(size=100, relative_path="a.json"), SimpleNamespace(size=200, relative_path="b.json")]
    assets = {"asset": SimpleNamespace(size=500)}
    monkeypatch.setattr(bridge, "assets_for_records", lambda selected: ("asset",))
    row = bridge._legacy_preview(records, assets, family="copy-vault", preset=None)
    assert row["fichiers_selectionnes"] == 2
    assert row["octets_bruts_selectionnes"] == 300
    assert row["assets_necessaires"] == 1
    assert row["octets_a_telecharger"] == 500
    assert row["premiers_fichiers"] == ["a.json", "b.json"]
    monkeypatch.setattr(bridge, "assets_for_records", lambda selected: ("missing",))
    with pytest.raises(DatasetBridgeError, match="assets absents"):
        bridge._legacy_preview(records, assets, family=None, preset=None)


def test_library_and_provenance_reports(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bridge, "render_library_markdown", lambda plans, release_id: f"release={release_id} plans={len(plans)}")
    release = {"name": "R", "tag_name": "v1", "published_at": "now"}
    json_path, md_path = bridge._write_library_reports(tmp_path, release, {"s": {"x": 1}}, release_id=9)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "hypersmart.dataset_library.v1"
    assert payload["release_id"] == 9
    assert payload["paper_read_only"] is True and payload["real_execution"] is False
    assert "release=9" in md_path.read_text(encoding="utf-8")

    prov = bridge._write_preparation_provenance(tmp_path, release=release, release_id=9, preview={"suite": "x"})
    p = json.loads(prov.read_text(encoding="utf-8"))
    assert p["schema"] == "hypersmart.dataset_selection_provenance.v2"
    assert p["source_release_id"] == 9 and p["suite"] == "x"
    assert p["paper_read_only"] is True and p["real_execution"] is False


def test_disk_guard_clamps_negative_and_checks_reserve(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bridge.shutil, "disk_usage", lambda root: SimpleNamespace(free=1000))
    row = bridge._disk_guard(tmp_path, network_remaining_bytes=-1, raw_materialized_bytes=-2, reserve_gib=0)
    assert row["network_remaining_bytes"] == 0
    assert row["raw_materialized_bytes_worst_case"] == 0
    assert row["ok"] is True
    row = bridge._disk_guard(tmp_path, network_remaining_bytes=800, raw_materialized_bytes=300, reserve_gib=0)
    assert row["worst_case_required_bytes"] == 1100
    assert row["ok"] is False


def _context(tmp_path):
    metadata = tmp_path / "metadata"
    metadata.mkdir(exist_ok=True)
    manifest = metadata / "FULL_UPLOADED_FILE_MANIFEST.jsonl.gz"
    manifest.write_bytes(b"manifest")
    release = {"name": "R", "tag_name": "v1", "published_at": "now"}
    assets = {"asset": SimpleNamespace(size=10, sha256="aa", asset_id=1)}
    return tmp_path, release, assets, metadata, manifest


def test_main_status_and_locate(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(bridge, "build_release_status", lambda root, repository, release_id: {"ok": True, "release_id": release_id})
    assert bridge.main(["status", "--root", str(tmp_path), "--release-id", "7"]) == 0
    assert '"release_id": 7' in capsys.readouterr().out

    suite = bridge.suite_names()[0]
    monkeypatch.setattr(bridge, "resolve_current_workspace", lambda root, s: tmp_path / "workspace")
    assert bridge.main(["locate", "--root", str(tmp_path), "--suite", suite]) == 0
    assert "workspace" in capsys.readouterr().out


def test_main_catalog_and_plan_all(tmp_path, monkeypatch, capsys) -> None:
    context = _context(tmp_path)
    monkeypatch.setattr(bridge, "_load_context", lambda args: context)
    monkeypatch.setattr(bridge, "snapshot_fingerprint", lambda *a, **k: "f" * 64)
    summary = context[3] / "FULL_SNAPSHOT_SUMMARY.json"
    summary.write_text('{"files": 3}', encoding="utf-8")
    assert bridge.main(["catalog", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert '"snapshot_fingerprint_sha256"' in out and '"files": 3' in out

    monkeypatch.setattr(bridge, "iter_manifest_records", lambda manifest: ["r"])
    monkeypatch.setattr(bridge, "build_all_suite_plans", lambda records, assets, project_root: {"suite": {"ok": True}})
    monkeypatch.setattr(bridge, "_write_library_reports", lambda *a, **k: (tmp_path / "r.json", tmp_path / "r.md"))
    assert bridge.main(["plan-all", "--root", str(tmp_path)]) == 0
    assert '"plans"' in capsys.readouterr().out


def test_main_suite_find_preview_no_download_limits_disk_and_success(tmp_path, monkeypatch, capsys) -> None:
    context = _context(tmp_path)
    suite = bridge.suite_names()[0]
    record = SimpleNamespace(size=10, relative_path="x.json")
    monkeypatch.setattr(bridge, "_load_context", lambda args: context)
    monkeypatch.setattr(bridge, "snapshot_fingerprint", lambda *a, **k: "s" * 64)
    monkeypatch.setattr(bridge, "iter_manifest_records", lambda manifest: [record])
    monkeypatch.setattr(bridge, "select_suite_records", lambda records, s: [record])
    monkeypatch.setattr(bridge, "build_selection_plan", lambda selected, assets, s, project_root: {
        "needed_assets": ["asset"], "missing_assets": [], "selection_digest": "digest", "suite": s,
    })
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(bridge, "suite_workspace_for_digest", lambda root, s, digest: workspace)
    transfer = {"verified_cache_bytes": 1, "partial_cache_bytes": 2, "remaining_network_bytes": 3}
    monkeypatch.setattr(bridge, "cache_transfer_plan", lambda *a, **k: dict(transfer))

    assert bridge.main(["find", "--root", str(tmp_path), "--suite", suite]) == 0
    assert '"remaining_network_bytes": 3' in capsys.readouterr().out

    assert bridge.main(["prepare", "--root", str(tmp_path), "--suite", suite]) == 0
    assert "Mode aperçu seulement" in capsys.readouterr().out

    transfer["remaining_network_bytes"] = 2 * 1024**3
    assert bridge.main(["prepare", "--root", str(tmp_path), "--suite", suite, "--download", "--max-download-gib", "1"]) == 2
    assert "au-dessus du plafond" in capsys.readouterr().out

    transfer["remaining_network_bytes"] = 3
    monkeypatch.setattr(bridge, "_disk_guard", lambda *a, **k: {"ok": False, "free_bytes": 1, "worst_case_required_bytes": 2})
    assert bridge.main(["prepare", "--root", str(tmp_path), "--suite", suite, "--download"]) == 2
    assert "Espace disque insuffisant" in capsys.readouterr().out

    monkeypatch.setattr(bridge, "_disk_guard", lambda *a, **k: {"ok": True, "free_bytes": 100, "worst_case_required_bytes": 13})
    monkeypatch.setattr(bridge, "download_needed_assets_with_progress", lambda *a, **k: {"asset": tmp_path / "asset.bin"})
    monkeypatch.setattr(bridge, "materialize_records", lambda selected, downloaded, output_root: [output_root / "x.json"])
    monkeypatch.setattr(bridge, "write_current_workspace", lambda *a, **k: tmp_path / "CURRENT.json")
    assert bridge.main(["prepare", "--root", str(tmp_path), "--suite", suite, "--download", "--heartbeat-seconds", "0"]) == 0
    out = capsys.readouterr().out
    assert "RECONSTRUCTION" in out and '"etat": "OK"' in out
    assert (tmp_path / "runtime" / "reports" / "datasets" / f"DERNIERE_PREPARATION_{suite}.json").is_file()
    assert (tmp_path / "runtime" / "reports" / "datasets" / "DERNIERE_PREPARATION_DATASET.json").is_file()
    assert (workspace / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json").is_file()


def test_main_legacy_empty_selection_and_invalid_args(tmp_path, monkeypatch, capsys) -> None:
    context = _context(tmp_path)
    monkeypatch.setattr(bridge, "_load_context", lambda args: context)
    monkeypatch.setattr(bridge, "snapshot_fingerprint", lambda *a, **k: "s" * 64)
    monkeypatch.setattr(bridge, "iter_manifest_records", lambda manifest: [])
    monkeypatch.setattr(bridge, "select_records", lambda *a, **k: [])
    monkeypatch.setattr(bridge, "_legacy_preview", lambda *a, **k: {"x": 1})
    monkeypatch.setattr(bridge, "assets_for_records", lambda selected: ())
    monkeypatch.setattr(bridge, "cache_transfer_plan", lambda *a, **k: {"verified_cache_bytes": 0, "partial_cache_bytes": 0, "remaining_network_bytes": 0})
    assert bridge.main(["prepare", "--root", str(tmp_path), "--download"]) == 2
    assert "Aucun fichier" in capsys.readouterr().out
    assert bridge.main(["find", "--root", str(tmp_path), "--max-download-gib", "-1"]) == 2
    assert "DATASET_BRIDGE_NO_GO" in capsys.readouterr().out
