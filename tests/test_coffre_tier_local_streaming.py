"""Regression: context families remain streamed after the replay materialisation cap."""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting.copy_vault_tier_local import _charger_tier_local  # noqa: E402


def _write_shard(root: Path, family: str, name: str, rows: list[dict]) -> dict:
    relative = Path("runtime") / "coffre_certifie" / "local" / "shards" / family / f"{name}.jsonl.gz"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return {
        "famille": family,
        "shard": relative.as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "deposes": len(rows),
        "ts_min_ms": 1_000,
        "ts_max_ms": 2_000,
    }


def test_context_family_is_read_after_replay_cap(tmp_path: Path) -> None:
    fill = {
        "ts_ms": 1_000,
        "vault": "0x0000000000000000000000000000000000000001",
        "coin": "BTC",
        "px": 100.0,
        "sz": 1.0,
        "isSnapshot": False,
        "source": "LIVE_POLL",
    }
    funding = {"ts_ms": 2_000, "coin": "BTC", "funding_rate": 0.001}
    shards = [
        _write_shard(tmp_path, "fills_forward", "fills", [fill]),
        _write_shard(tmp_path, "funding_history", "funding", [funding]),
    ]
    index = tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({"shards": shards}), encoding="utf-8")

    result = _charger_tier_local(
        tmp_path,
        garder_signaux=False,
        garder_replay=False,
        max_lignes=1,
    )

    assert result["chargement_arrete"] == "PLAFOND_LIGNES"
    assert result["signaux_par_famille"]["funding_history"] == 1
    assert result["shards_non_lus"] == 0
