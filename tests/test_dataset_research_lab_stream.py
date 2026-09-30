from __future__ import annotations

import json
from pathlib import Path

from hl_observer.datasets.research_lab_stream import (
    discover_research_jsonl,
    profile_research_jsonl,
    write_research_stream_profile,
)


def _research_file(root: Path, name: str = "episodes.jsonl", *, rows: int = 10) -> Path:
    path = root / "runtime" / "research_lab" / "continuous" / "run-a" / "historique" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for index in range(rows):
        lines.append(
            json.dumps(
                {
                    "ts_ms": 1_780_000_000_000 + index,
                    "family": "copy_vault" if index % 2 == 0 else "lead_lag",
                    "event_type": "TRADE",
                    "coin": "BTC",
                    "net_pnl_usd": 1.0 if index % 3 else -0.5,
                    "metrics": {"edge_remaining_bps": 4.0 + index},
                    "secret_payload": "VALEUR_QUI_NE_DOIT_PAS_SORTIR",
                },
                sort_keys=True,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_research_stream_reprend_un_jsonl_depuis_le_checkpoint(tmp_path: Path) -> None:
    path = _research_file(tmp_path, rows=10)

    partial = profile_research_jsonl(
        tmp_path,
        path,
        max_lines=4,
        sample_every=2,
        heartbeat_seconds=999,
        checkpoint_seconds=999,
    )
    assert partial["complete"] is False
    assert partial["stop_reason"] == "MAX_LINES"
    assert partial["lines"] == 4
    assert Path(partial["checkpoint"]).is_file()

    finished = profile_research_jsonl(
        tmp_path,
        path,
        resume=True,
        sample_every=2,
        heartbeat_seconds=999,
        checkpoint_seconds=999,
    )
    assert finished["resumed"] is True
    assert finished["complete"] is True
    assert finished["lines"] == 10
    assert finished["valid_json"] == 10
    assert finished["invalid_json"] == 0
    assert finished["family_counts"]["copy_vault"] == 5
    assert finished["family_counts"]["lead_lag"] == 5
    assert finished["metrics"]["net_pnl_usd"]["count"] == 10
    assert finished["metrics"]["edge_remaining_bps"]["count"] == 10


def test_research_stream_n_exporte_pas_les_valeurs_brutes(tmp_path: Path) -> None:
    _research_file(tmp_path, rows=3)

    json_path, md_path, profile = write_research_stream_profile(
        tmp_path,
        sample_every=1,
        heartbeat_seconds=999,
    )

    assert profile["file_count"] == 1
    assert profile["lines"] == 3
    combined = json_path.read_text(encoding="utf-8") + md_path.read_text(encoding="utf-8")
    assert "VALEUR_QUI_NE_DOIT_PAS_SORTIR" not in combined
    assert "secret_payload" in combined  # le nom de champ est permis; sa valeur ne l'est pas.


def test_research_stream_compte_les_json_invalides_sans_planter(tmp_path: Path) -> None:
    path = _research_file(tmp_path, rows=2)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{pas json}\n")

    profile = profile_research_jsonl(
        tmp_path,
        path,
        heartbeat_seconds=999,
    )

    assert profile["lines"] == 3
    assert profile["valid_json"] == 2
    assert profile["invalid_json"] == 1


def test_research_discovery_priorise_les_gros_jsonl(tmp_path: Path) -> None:
    small = _research_file(tmp_path, "small.jsonl", rows=1)
    large = _research_file(tmp_path, "large.jsonl", rows=20)

    found = discover_research_jsonl(tmp_path)

    assert large in found
    assert small in found
    assert found.index(large) < found.index(small)
