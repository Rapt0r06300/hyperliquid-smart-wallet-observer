"""Tests du collecteur WS userFills de lane (cœur pur, sans réseau)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import collecter_userfills_ws_lane as L  # noqa: E402

NOW = 1_800_000_000_000


def _brut(**kw):
    base = {"coin": "ETH", "px": "2000.5", "sz": "1.5", "side": "B", "time": NOW - 1000,
            "dir": "Open Long", "tid": 42, "oid": 7, "hash": "0xabc", "startPosition": "0.0"}
    base.update(kw)
    return base


def _parse(fills, user="0xuser"):
    return L._normaliser({"user": user, "isSnapshot": False, "fills": fills},
                         user=user, received_at_ms=NOW, recv_mono_ns=None, connection_id="t")


def test_forward_emet_les_nouveaux():
    parsed = _parse([_brut(time=NOW - 1000, tid=1)])
    nouveaux, hw = L.filtrer_forward(parsed, None)
    assert len(nouveaux) == 1 and hw == parsed[0]["ts_ms"]


def test_forward_ignore_sous_high_water():
    parsed = _parse([_brut(time=NOW - 1000, tid=1)])
    nouveaux, hw = L.filtrer_forward(parsed, parsed[0]["ts_ms"])
    assert nouveaux == [] and hw == parsed[0]["ts_ms"]


def test_forward_high_water_est_le_max():
    parsed = _parse([_brut(time=NOW - 3000, tid=1), _brut(time=NOW - 1000, tid=2)])
    nouveaux, hw = L.filtrer_forward(parsed, NOW - 2000)
    assert len(nouveaux) == 1 and hw == NOW - 1000  # seul le plus récent, hw=max


def test_high_water_snapshot():
    parsed = _parse([_brut(time=NOW - 5000, tid=1), _brut(time=NOW - 2000, tid=2)])
    assert L.high_water_snapshot(parsed, NOW) == NOW - 2000
    assert L.high_water_snapshot([], NOW) == NOW  # snapshot vide -> maintenant


def test_charger_leaders_et_shard(tmp_path):
    cfg = tmp_path / "config" / "copy_vault_leaders.json"
    cfg.parent.mkdir(parents=True)
    vaults = [f"0x{i:040x}" for i in range(20)] + ["pas_une_adresse", "0x"]
    cfg.write_text(json.dumps({"vaults": vaults}), encoding="utf-8")
    lus = L._charger_leaders(tmp_path, "config/copy_vault_leaders.json")
    assert len(lus) == 20 and all(v.startswith("0x") for v in lus)


def test_normaliser_rest_et_ws_identiques():
    # un fill passé par _normaliser (REST ou WS) donne la même identité de dédup
    from hl_observer.collection.userfills_resilience import cle_dedup_fill
    a = _parse([_brut(tid=9)])[0]
    b = _parse([_brut(tid=9)])[0]
    assert cle_dedup_fill(a) == cle_dedup_fill(b)
