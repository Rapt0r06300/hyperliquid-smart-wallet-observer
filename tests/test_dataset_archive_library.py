from __future__ import annotations

from pathlib import Path

from hl_observer.datasets.archive_library import (
    SUITES,
    build_all_suite_plans,
    record_matches_suite,
    resolve_current_workspace,
    select_suite_records,
    suite_workspace_for_digest,
    write_current_workspace,
)
from hl_observer.datasets.github_release_bridge import DatasetRecord, ReleaseAsset


def _record(path: str, size: int, asset: str) -> DatasetRecord:
    return DatasetRecord(
        relative_path=path,
        size=size,
        sha256=("a" * 64),
        storage="zip_entry",
        asset=asset,
    )


def _asset(name: str, size: int) -> ReleaseAsset:
    return ReleaseAsset(
        asset_id=1,
        name=name,
        size=size,
        digest="sha256:" + ("b" * 64),
    )


def test_suites_couvrent_archive_et_recherche() -> None:
    assert "economic-core" in SUITES
    assert "economic-full" in SUITES
    assert "copy-vault-full" in SUITES
    assert "lead-lag-full" in SUITES
    assert "cross-venue-full" in SUITES
    assert "microstructure-full" in SUITES
    assert "research-lab-full" in SUITES
    assert "full-archive" in SUITES


def test_economic_full_reunit_les_trois_familles() -> None:
    rows = [
        _record("runtime/data/vault_fills.jsonl", 10, "a.zip"),
        _record("runtime/data/bbo_tape.jsonl", 20, "b.zip"),
        _record("runtime/data/carnet_venues.jsonl", 30, "c.zip"),
        _record("docs/README.md", 40, "d.zip"),
    ]
    selected = select_suite_records(rows, "economic-full")
    assert [row.relative_path for row in selected] == [
        "runtime/data/vault_fills.jsonl",
        "runtime/data/bbo_tape.jsonl",
        "runtime/data/carnet_venues.jsonl",
    ]


def test_full_archive_prend_tout() -> None:
    rows = [
        _record("runtime/data/a.jsonl", 10, "a.zip"),
        _record("docs/a.md", 20, "b.zip"),
    ]
    suite = SUITES["full-archive"]
    assert all(record_matches_suite(row, suite) for row in rows)
    assert select_suite_records(rows, "full-archive") == rows


def test_plan_all_compte_cache_et_volume_restant(tmp_path: Path) -> None:
    rows = [
        _record("runtime/data/vault_fills.jsonl", 10, "a.zip"),
        _record("runtime/data/bbo_tape.jsonl", 20, "b.zip"),
        _record("runtime/research_lab/continuous/episodes.jsonl", 30, "c.bin"),
    ]
    assets = {
        "a.zip": _asset("a.zip", 100),
        "b.zip": _asset("b.zip", 200),
        "c.bin": _asset("c.bin", 300),
    }
    cache = tmp_path / "data" / "hypersmart_datasets" / "assets"
    cache.mkdir(parents=True)
    (cache / "a.zip").write_bytes(b"x" * 100)

    plans = build_all_suite_plans(rows, assets, project_root=tmp_path)
    economic = plans["economic-full"]
    assert economic["matched_files"] == 2
    assert economic["download_bytes"] == 300
    assert economic["cache_hits_size_only"] == 1
    assert economic["remaining_download_bytes"] == 200
    research = plans["research-lab-full"]
    assert research["matched_files"] == 1
    assert research["download_bytes"] == 300


def test_workspace_est_versionne_par_digest_et_pointe_sans_melange(tmp_path: Path) -> None:
    digest = "1" * 64
    workspace = suite_workspace_for_digest(tmp_path, "economic-full", digest)
    workspace.mkdir(parents=True)
    pointer = write_current_workspace(
        tmp_path,
        "economic-full",
        digest=digest,
        workspace=workspace,
        release_id=371149058,
    )
    assert pointer.is_file()
    assert resolve_current_workspace(tmp_path, "economic-full") == workspace.resolve()
