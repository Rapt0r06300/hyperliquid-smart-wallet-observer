"""Fusion des fills des lanes GitHub : dédup + préférence causale + fraîcheur."""
from __future__ import annotations

import json
from pathlib import Path

from tools.fusionner_fills_lanes import fusionner


def _w(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _fill(tid: int, t: int, obs: int, *, source="LIVE_POLL", snap=False) -> dict:
    return {"vault": "0xV", "coin": "BTC", "time": t, "tid": tid, "oid": 100 + tid,
            "px": "1.0", "sz": "1.0", "side": "B", "source": source,
            "isSnapshot": snap, "observed_at_ms": obs}


def test_fusion_dedupe_prefere_causal_et_rejette_pollue(tmp_path: Path) -> None:
    root = tmp_path
    cible = root / "runtime" / "data" / "vault_fills_poll.jsonl"
    # Local : un fill frais non-snapshot (tid 1).
    _w(cible, [_fill(1, 1_000, 1_100)])
    # Lane 0 : un nouveau (tid 2), un DOUBLON de tid 1 mais snapshot, un STALE, un NON-CAUSAL.
    _w(root / "dl" / "poll-fills-shard-0" / "vault_fills_poll.jsonl", [
        _fill(2, 2_000, 2_050),
        _fill(1, 1_000, 1_100, snap=True),                 # doublon (snapshot)
        _fill(3, 1_000, 1_000 + 700_000),                  # stale (lag 700 s > 600 s)
        _fill(4, 4_000, 4_050, source="REST_BACKFILL"),    # non causal
    ])
    # Lane 1 : un nouveau (tid 5).
    _w(root / "dl" / "poll-fills-shard-1" / "vault_fills_poll.jsonl", [_fill(5, 3_000, 3_050)])

    rap = fusionner(root, root / "dl", max_lag_ms=600_000)

    assert rap["doublons_retires"] == 1          # tid 1 vu 2 fois
    assert rap["rejets_qualite"] == 2            # stale + non causal
    assert rap["total_final"] == 3               # tids 1, 2, 5

    rows = [json.loads(l) for l in cible.read_text(encoding="utf-8").splitlines()]
    tids = sorted(r["tid"] for r in rows)
    assert tids == [1, 2, 5]
    tid1 = [r for r in rows if r["tid"] == 1][0]
    assert tid1["isSnapshot"] is False           # on a gardé la vue causale, pas le snapshot
    # Backup non destructif de l'ancien fichier local.
    assert (cible.with_suffix(".jsonl.avant-fusion.bak")).exists()
