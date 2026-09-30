from __future__ import annotations

import gzip
import json
from pathlib import Path

from hl_observer.datasets.research_lab_stream_safe import (
    profile_research_jsonl_safe,
    write_research_stream_profile_safe,
)


def _gzip_research_file(root: Path, *, rows: int = 100) -> Path:
    path = (
        root
        / "runtime"
        / "research_lab"
        / "continuous"
        / "run-gzip"
        / "historique"
        / "episodes.jsonl.gz"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        for index in range(rows):
            handle.write(
                json.dumps(
                    {
                        "ts_ms": 1_780_000_000_000 + index,
                        "family": "copy_vault",
                        "event_type": "TRADE",
                        "coin": "BTC",
                        "net_pnl_usd": 1.0,
                        "repetitive_payload": "X" * 4_000,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    return path


def test_progression_gzip_separe_octets_physiques_et_logiques(tmp_path: Path) -> None:
    path = _gzip_research_file(tmp_path, rows=100)
    source_size = path.stat().st_size

    profile = profile_research_jsonl_safe(
        tmp_path,
        path,
        max_lines=10,
        sample_every=0,
        heartbeat_seconds=999,
    )

    assert profile["compressed"] is True
    assert profile["resume_supported"] is False
    assert profile["progress_basis"] == "compressed_physical_bytes"
    assert 0 <= profile["scanned_physical_bytes"] <= source_size
    assert profile["scanned_bytes"] == profile["scanned_physical_bytes"]
    assert profile["logical_scanned_bytes"] > source_size
    assert profile["progress_percent"] is None or 0 <= profile["progress_percent"] <= 100
    assert profile["stop_reason"] == "MAX_LINES"


def test_progression_gzip_terminee_vaut_exactement_100_pour_cent(tmp_path: Path) -> None:
    path = _gzip_research_file(tmp_path, rows=12)
    source_size = path.stat().st_size

    profile = profile_research_jsonl_safe(
        tmp_path,
        path,
        sample_every=0,
        heartbeat_seconds=999,
    )

    assert profile["complete"] is True
    assert profile["lines"] == 12
    assert profile["progress_percent"] == 100.0
    assert profile["scanned_physical_bytes"] == source_size
    assert profile["logical_scanned_bytes"] > source_size


def test_rapport_workspace_gzip_explique_les_deux_volumes(tmp_path: Path) -> None:
    _gzip_research_file(tmp_path, rows=5)

    json_path, md_path, profile = write_research_stream_profile_safe(
        tmp_path,
        sample_every=0,
        heartbeat_seconds=999,
    )

    assert profile["schema"] == "hypersmart.research_lab_stream_profile.v2"
    assert profile["progress_basis"] == "physical_source_bytes"
    assert profile["scanned_bytes"] <= profile["source_bytes"]
    assert profile["logical_scanned_bytes"] >= profile["scanned_bytes"]
    markdown = md_path.read_text(encoding="utf-8")
    assert "octets compressés réellement lus" in markdown
    assert "logical_scanned_gib" in markdown
    assert json_path.is_file()
