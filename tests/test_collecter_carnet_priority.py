"""Famille A #3 : collecte L2 priorisée copy-vault.

Les coins bougés par les leaders (vaults suivis) sont collectés D'ABORD, car
leur carnet L2 est celui qui transforme un fill en jour actif scoreable. Ordre
déterministe, déduplication conservant la première place.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from tools.collecter_carnet import coins_a_suivre


def _write_leader_coins(root: Path, coins_ts: dict[str, float]) -> None:
    data = root / "runtime" / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "coins_bouges_par_vaults.json").write_text(
        json.dumps({"coins": coins_ts}), encoding="utf-8"
    )


def test_leader_active_coins_are_collected_first(tmp_path: Path) -> None:
    _write_leader_coins(tmp_path, {"LEADERCOIN": time.time() * 1000})
    lines = [{"coin": "OTHER", "ecart_prix_bps": 3.0}]

    coins = coins_a_suivre(tmp_path, lines, n_coins=5, n_premium=2)

    assert coins[0] == "LEADERCOIN"
    assert "OTHER" in coins
    assert coins.index("LEADERCOIN") < coins.index("OTHER")


def test_stale_leader_coins_are_not_followed(tmp_path: Path) -> None:
    # Bougé il y a 24 h (> fenêtre 6 h) -> écarté.
    _write_leader_coins(tmp_path, {"STALECOIN": time.time() * 1000 - 24 * 3600 * 1000})

    coins = coins_a_suivre(
        tmp_path, [{"coin": "OTHER", "ecart_prix_bps": 3.0}], n_coins=5, n_premium=2
    )

    assert "STALECOIN" not in coins
    assert coins[0] == "OTHER"


def test_dedup_keeps_leader_priority(tmp_path: Path) -> None:
    # Un coin leader AUSSI prioritaire ne doit apparaître qu'une fois, en tête.
    _write_leader_coins(tmp_path, {"DUAL": time.time() * 1000})
    lines = [{"coin": "DUAL", "ecart_prix_bps": 4.0}]

    coins = coins_a_suivre(tmp_path, lines, n_coins=5, n_premium=2)

    assert coins[0] == "DUAL"
    assert coins.count("DUAL") == 1
