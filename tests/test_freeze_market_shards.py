from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_freeze_market_shards_exact_disjoint_cover(tmp_path: Path) -> None:
    selected = [
        {
            "coin": coin,
            "venue_count": 2,
            "symbols": {"hyperliquid": coin, "binance": f"{coin}USDT"},
        }
        for coin in ("BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE", "LINK", "SUI", "ADA", "AVAX", "ARB", "OP")
    ]
    plan = {
        "schema": "alina.cloud_collection_plan.v1",
        "min_venues": 2,
        "venue_market_counts": {"hyperliquid": 12, "binance": 12},
        "selected_coin_count": len(selected),
        "selected": selected,
        "errors": {},
        "read_only": True,
        "real_execution": False,
    }
    source = tmp_path / "full.json"
    source.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")
    out_dir = tmp_path / "shards"
    index = out_dir / "index.json"

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "freeze_market_shards.py"),
            "--plan",
            str(source),
            "--output-dir",
            str(out_dir),
            "--shard-count",
            "8",
            "--index-output",
            str(index),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    meta = json.loads(index.read_text(encoding="utf-8"))
    assert meta["schema"] == "alina.market_shard_index.v1"
    assert meta["universe_digest"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert meta["market_shard_count"] == 8
    assert meta["full_selected_coin_count"] == len(selected)
    assert meta["read_only"] is True
    assert meta["real_execution"] is False

    seen: list[str] = []
    for shard in meta["shards"]:
        path = Path(shard["plan_file"])
        row = json.loads(path.read_text(encoding="utf-8"))
        assert row["universe_digest"] == meta["universe_digest"]
        assert row["market_shard_index"] == shard["market_shard_index"]
        assert row["market_shard_count"] == 8
        assert row["read_only"] is True
        assert row["real_execution"] is False
        assert hashlib.sha256(path.read_bytes()).hexdigest() == shard["plan_sha256"]
        coins = [str(item["coin"]).upper() for item in row["selected"]]
        assert coins
        seen.extend(coins)

    expected = sorted(str(row["coin"]).upper() for row in selected)
    assert sorted(seen) == expected
    assert len(seen) == len(set(seen))
