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
    assert "foo" in patterns and len(patterns) > 1
    with pytest.raises(DatasetBridgeError, match="max-download"):
        bridge._validate_args(_args("find", "--max-download-gib", "-1"))
    with pytest.raises(DatasetBridgeError, match="disk-reserve"):
        bridge._validate_args(_args("find", "--disk-reserve-gib", "-1"))
    suite = bridge.suite_names()[0]
    with pytest.raises(DatasetBridgeError, match="sélection reproductible"):
        bridge._validate_args(_args("find", "--suite", suite, "--contains", "x"))
    with pytest.raises(DatasetBridgeError, match="locate exige"):
        bridge._validate_args(_args("locate"))
    with pytest.raises(DatasetBridgeError, match="aucun filtre"):
        bridge._validate_args(_args("plan-all", "--family", "lead-lag"))


def test_snapshot_fingerprint_and_disk_guard(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "manifest.gz"
    manifest.write_bytes(b"manifest-bytes")
    release = {"name": "R", "tag_name": "v1", "published_at": "now"}
    assets = {
        "b": SimpleNamespace(size=2, sha256="22", asset_id=2),
        "a": SimpleNamespace(size=1, sha256="11", asset_id=1),
    }
    one = bridge.snapshot_fingerprint(manifest, release, assets, repository="o/r", release_id=7)
    two = bridge.snapshot_fingerprint(
        manifest,
        release,
        dict(reversed(list(assets.items()))),
        repository="o/r",
        release_id=7,
    )
    assert one == two and len(one) == 64
    with pytest.raises(DatasetBridgeError, match="Manifeste FULL/COLD absent"):
        bridge.snapshot_fingerprint(tmp_path / "missing", release, assets, repository="o/r", release_id=7)

    monkeypatch.setattr(bridge.shutil, "disk_usage", lambda root: SimpleNamespace(free=1000))
    assert bridge._disk_guard(
        tmp_path,
        network_remaining_bytes=-1,
        raw_materialized_bytes=-2,
        reserve_gib=0,
    )["ok"] is True
    assert bridge._disk_guard(
        tmp_path,
        network_remaining_bytes=800,
        raw_materialized_bytes=300,
        reserve_gib=0,
    )["ok"] is False


def test_library_and_provenance_reports(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        bridge,
        "render_library_markdown",
        lambda plans, release_id: f"release={release_id} plans={len(plans)}",
    )
    release = {"name": "R", "tag_name": "v1", "published_at": "now"}
    json_path, md_path = bridge._write_library_reports(
        tmp_path,
        release,
        {"s": {"x": 1}},
        release_id=9,
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["paper_read_only"] is True and payload["real_execution"] is False
    assert "release=9" in md_path.read_text(encoding="utf-8")
    provenance = bridge._write_preparation_provenance(
        tmp_path,
        release=release,
        release_id=9,
        preview={"suite": "x"},
    )
    row = json.loads(provenance.read_text(encoding="utf-8"))
    assert row["schema"] == "hypersmart.dataset_selection_provenance.v2"
    assert row["paper_read_only"] is True and row["real_execution"] is False


def test_main_status_locate_and_invalid(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        bridge,
        "build_release_status",
        lambda root, repository, release_id: {"ok": True, "release_id": release_id},
    )
    assert bridge.main(["status", "--root", str(tmp_path), "--release-id", "7"]) == 0
    assert '"release_id": 7' in capsys.readouterr().out
    suite = bridge.suite_names()[0]
    monkeypatch.setattr(
        bridge,
        "resolve_current_workspace",
        lambda root, selected_suite: tmp_path / "workspace",
    )
    assert bridge.main(["locate", "--root", str(tmp_path), "--suite", suite]) == 0
    assert "workspace" in capsys.readouterr().out
    assert bridge.main(["find", "--root", str(tmp_path), "--max-download-gib", "-1"]) == 2
    assert "DATASET_BRIDGE_NO_GO" in capsys.readouterr().out
