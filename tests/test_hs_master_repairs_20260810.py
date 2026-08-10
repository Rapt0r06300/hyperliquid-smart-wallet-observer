"""Regression barriers for the 2026-08-10 master wiring/accounting repair.

Offline only. No network, key, signature or real execution.
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.experimental.execution_paper import pnl_deux_jambes
from hl_observer.ops import registre_pids as RP
from hl_observer.ops import session_harvest as SH


def test_pid_registry_scopes_signature_to_exact_checkout(tmp_path):
    root_a = (tmp_path / "checkout-a").resolve()
    root_b = (tmp_path / "checkout-b").resolve()
    root_a.mkdir()
    root_b.mkdir()
    procs = [
        {
            "pid": 101,
            "ppid": 1,
            "cmd": f'"{root_b / "tools/python/python.exe"}" -m hl_observer ui --root "{root_b}"',
        },
        {
            "pid": 202,
            "ppid": 1,
            "cmd": f'"{root_a / "tools/python/python.exe"}" -m hl_observer ui --root "{root_a}"',
        },
    ]
    reg = RP.construire_registre(procs, root=root_a)
    assert reg["composants"]["ui"]["pid"] == 202
    assert 101 not in RP.pids_enregistres(reg)


def test_orphan_detection_never_claims_other_checkout(tmp_path):
    root_a = (tmp_path / "checkout-a").resolve()
    root_b = (tmp_path / "checkout-b").resolve()
    root_a.mkdir()
    root_b.mkdir()
    procs = [
        {
            "pid": 301,
            "ppid": 1,
            "cmd": f'cmd /c "{root_b / "tools/boucle_collecteur.cmd"}" bbo-collector',
        },
        {
            "pid": 302,
            "ppid": 1,
            "cmd": f'cmd /c "{root_a / "tools/boucle_collecteur.cmd"}" bbo-collector',
        },
    ]
    orphans = RP.detecter_orphelins(procs, set(), root=root_a)
    assert [row["pid"] for row in orphans] == [302]


def test_writer_stop_proof_reads_canonical_nested_component_schema(tmp_path):
    path = tmp_path / RP.REGISTRE_RELPATH
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "composants": {
                    "ui": {"pid": 111, "role": "moteur-ui"},
                    "poller": {"pid": 222, "role": "poller"},
                },
                "collecteurs": {"bbo-collector": 333},
            }
        ),
        encoding="utf-8",
    )
    stopped, living = SH.preuve_writers_arretes(tmp_path, pid_vivant=lambda pid: pid in {222})
    assert stopped is False
    assert living == ["poller"]
    stopped2, living2 = SH.preuve_writers_arretes(tmp_path, pid_vivant=lambda pid: False)
    assert stopped2 is True and living2 == []


def test_two_leg_realized_charges_entry_and_exit_fee_once_each():
    legs = [
        {
            "venue": "HL",
            "side": 1,
            "entry_px": 100.0,
            "exit_px": 101.0,
            "size_usd": 100.0,
            "fee_bps": 4.5,
            "slippage_bps": 0.0,
        },
        {
            "venue": "BINANCE",
            "side": -1,
            "entry_px": 100.0,
            "exit_px": 99.0,
            "size_usd": 100.0,
            "fee_bps": 4.5,
            "slippage_bps": 0.0,
        },
    ]
    result = pnl_deux_jambes(legs)
    # Gross = $2.00. Fees = 4 executions * 4.5 bps * $100 = $0.18.
    assert result["round_trip_cost_usd"] == 0.18
    assert result["realized_usd"] == 1.82
    assert all(row["round_trip_cost_bps"] == 9.0 for row in result["jambes"])


def test_hyperliquid_fee_fallback_is_conservative_tier_zero():
    config = json.loads(Path("config/frais_venues.json").read_text(encoding="utf-8"))
    assert float(config["hl_taker_bps"]) >= 4.5
    assert "tier 0" in config["source"].lower()
