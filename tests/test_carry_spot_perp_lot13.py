"""LOT13 Part3 — HL_SPOT_PERP_CARRY_V1 prouvé sans réseau (Flo 26/07)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("carry", _ROOT / "tools" / "hl_spot_perp_carry_v1.py")
CA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CA)


def test_decouverte_spot_perp_intersection():
    meta = {"universe": [{"name": "BTC"}, {"name": "SOL"}, {"name": "PERPONLY"}]}
    spot_meta = {"universe": [{"name": "BTC/USDC"}], "tokens": [{"name": "SOL"}, {"name": "SPOTONLY"}]}
    assert CA.decouvrir_spot_perp(meta, spot_meta) == ["BTC", "SOL"]     # perp ∩ spot


def test_carry_net_funding_moins_couts():
    # funding +1 bps/h sur 24h = +24 bps ; coûts 20 -> net +4 (basis conservateur 0)
    assert abs(CA.carry_net_bps(1.0, 24, cout_ar_bps=20.0) - 4.0) < 1e-9
    # funding négatif capté par un long-perp ? ici la fonction ne suppose pas le sens : funding brut − coûts
    assert CA.carry_net_bps(0.1, 24, cout_ar_bps=20.0) < 0                # funding faible -> négatif


def test_gate_refuse_si_funding_insuffisant():
    # funding minuscule, constant : ne couvre jamais marge×coûts -> aucune entrée -> INSUFFISANT
    ctx = [{"coin": "BTC", "ts_wall_ms": i * 3600_000, "funding": 0.000001} for i in range(20)]
    r = CA.backtest_carry(ctx, horizon_h=24)
    assert r["decision"] == "SHADOW" and r["motif"] == "INSUFFISANT"


def test_backtest_carry_positif_si_funding_fort_persistant():
    # funding +5 bps/h persistant sur 24h = +120 bps >> coûts 20 -> entrées + net positif
    ctx = [{"coin": c, "ts_wall_ms": i * 3600_000, "funding": 0.0005}
           for c in ("BTC", "ETH", "SOL") for i in range(30)]
    r = CA.backtest_carry(ctx, horizon_h=24)
    assert r["n_episodes"] >= 8 and r["net_median_bps"] > 0 and r["pf"] > 1.0
