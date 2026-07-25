"""MESURE liquidations confirmées — dédup en épisodes + sens du fade, prouvé sur fixtures.

Prouve : dédup coin+hash (une liquidation multi-fills = 1 épisode), sens (forced sell signe<0 → fade long
SELL_OVERSHOOT ; forced buy → BUY_OVERSHOOT), et le filtre liquidatedUser==vault (forced-flow du user suivi).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("liquidations_confirmees_mesure",
                                               _ROOT / "tools" / "liquidations_confirmees_mesure.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def _rec(coin, h, signe, ts, vault="0xV", liq="0xV"):
    return {"coin": coin, "hash": h, "signe": signe, "ts_ms": ts, "vault": vault, "liquidatedUser": liq}


def test_dedup_et_sens_vault_liquide(tmp_path):
    p = tmp_path / "liq.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        _rec("BTC", "0xA", -1, 1700000000000),         # vault liquidé, force-vend -> fade long (SELL_OVERSHOOT)
        _rec("BTC", "0xA", -1, 1700000000000),         # MEME hash -> meme episode (dedup)
        _rec("ETH", "0xB", 1, 1700000001000),          # vault liquidé, force-achat -> fade short (BUY_OVERSHOOT)
    ]), encoding="utf-8")
    ev, stats = M.charger_episodes(p)
    assert stats["n_fills"] == 3 and stats["n_episodes"] == 2, "coin+hash dedup -> 2 episodes"
    sens = {e["coin"]: e["sens"] for e in ev}
    assert sens["BTC"] == "SELL_OVERSHOOT" and sens["ETH"] == "BUY_OVERSHOOT"


def test_role_liquidateur_INVERSE_le_sens_forced(tmp_path):
    """Si notre vault est le LIQUIDATEUR (liquidatedUser!=vault), il prend l'AUTRE côté : un fill ACHAT
    (signe +1) du liquidateur = le liquidé a été force-VENDU → forced-flow SELL → SELL_OVERSHOOT (fade long)."""
    p = tmp_path / "liq.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        _rec("BTC", "0xA", +1, 1700000000000, vault="0xV", liq="0xAUTRE"),  # liquidateur achète -> liquidé force-vend
        _rec("ETH", "0xB", -1, 1700000001000, vault="0xV", liq="0xAUTRE"),  # liquidateur vend -> liquidé force-achète
    ]), encoding="utf-8")
    ev, stats = M.charger_episodes(p)
    assert stats["n_liquidateur"] == 2 and stats["n_vault_liquide"] == 0
    sens = {e["coin"]: e["sens"] for e in ev}
    assert sens["BTC"] == "SELL_OVERSHOOT" and sens["ETH"] == "BUY_OVERSHOOT"
    assert all(e["role"] == "liquidateur" for e in ev)


def test_aucune_confirmee_donne_zero(tmp_path):
    p = tmp_path / "vide.jsonl"
    p.write_text("", encoding="utf-8")
    ev, stats = M.charger_episodes(p)
    assert ev == [] and stats["n_episodes"] == 0
