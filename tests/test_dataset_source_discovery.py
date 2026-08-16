from __future__ import annotations

import json
from pathlib import Path

from hl_observer.datasets.source_discovery import (
    discover_family_sources,
    is_dataset_workspace,
    load_family_source_paths,
    write_family_source_manifest,
)


def _mark_workspace(root: Path) -> None:
    marker = root / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"source_release_id": 371149058}), encoding="utf-8")


def test_decouvre_les_copies_archivees_sans_les_melanger(tmp_path: Path) -> None:
    _mark_workspace(tmp_path)
    files = [
        tmp_path / "runtime" / "data" / "vault_fills.jsonl",
        tmp_path / "archive" / "run1" / "runtime" / "data" / "vault_fills.jsonl",
        tmp_path / "runtime" / "data" / "bbo_tape.jsonl",
        tmp_path / "archive" / "run2" / "runtime" / "data" / "bbo_shards" / "a.jsonl.gz",
        tmp_path / "runtime" / "data" / "carnet_venues.jsonl",
        tmp_path / "runtime" / "replay" / "candidates.jsonl",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"{}\n")

    groups = discover_family_sources(tmp_path)
    assert len(groups["copy_vault"]) == 2
    assert len(groups["lead_lag"]) == 2
    assert len(groups["cross_venue"]) == 1
    assert len(groups["replay"]) == 1
    assert is_dataset_workspace(tmp_path) is True

    manifest = write_family_source_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["dataset_workspace"] is True
    assert payload["groups"]["lead_lag"]["file_count"] == 2
    assert len(load_family_source_paths(tmp_path, "copy_vault")) == 2


def test_un_dossier_normal_n_est_pas_un_workspace_dataset(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "data" / "bbo_tape.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("{}\n", encoding="utf-8")
    assert is_dataset_workspace(tmp_path) is False
