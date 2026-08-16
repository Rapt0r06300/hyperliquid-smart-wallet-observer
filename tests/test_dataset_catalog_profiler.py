from __future__ import annotations

import gzip
import json
from pathlib import Path

from hl_observer.datasets.catalog_profiler import profile_manifest, render_markdown


def _write_manifest(path: Path, rows: list[dict[str, object]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_profile_manifest_compte_les_familles_et_les_octets(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl.gz"
    _write_manifest(
        manifest,
        [
            {
                "relative_path": "runtime/data/copy_vault_l2_tape.jsonl",
                "size": 100,
                "mtime_ns": 1_700_000_000_000_000_000,
            },
            {
                "relative_path": "runtime/data/carnet_venues.jsonl",
                "size": 200,
                "mtime_ns": 1_700_000_001_000_000_000,
            },
            {
                "relative_path": "runtime/research_lab/continuous/history.sqlite3",
                "size": 300,
                "mtime_ns": 1_700_000_002_000_000_000,
            },
        ],
    )
    profile = profile_manifest(manifest)
    assert profile["total_files"] == 3
    assert profile["total_bytes"] == 600
    assert profile["families"]["copy_vault"]["files"] >= 1
    assert profile["families"]["cross_venue"]["files"] >= 1
    assert profile["families"]["research_lab"]["files"] >= 1


def test_render_markdown_reste_lisible(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl.gz"
    _write_manifest(
        manifest,
        [{"relative_path": "runtime/data/bbo.jsonl", "size": 10, "mtime_ns": 0}],
    )
    text = render_markdown(profile_manifest(manifest))
    assert "# Carte des données HyperSmart" in text
    assert "Familles" in text
    assert "Extensions" in text
    assert "ne supprime et ne trie rien" in text
