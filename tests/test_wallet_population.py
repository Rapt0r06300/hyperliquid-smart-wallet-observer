"""ALPHA — population wallets à l'échelle : archétype, indépendance d'entité, classement streaming."""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import wallet_population as P  # noqa: E402

JOUR = 86_400_000


def test_archetype_scalper_et_momentum():
    scalper = [{"coin": "BTC", "ts_ms": i * 1000} for i in range(100)]     # 100 fills en ~100s
    assert P.archetype(scalper) == "scalper"
    mono = [{"coin": "PUMP", "ts_ms": d * JOUR} for d in range(10)]        # 1 coin, lent
    assert P.archetype(mono) == "momentum_mono_coin"


def test_independance_entite_detecte_cotrade():
    par_wallet = {
        "0xA": [{"coin": "BTC", "ts_ms": 1000}],
        "0xB": [{"coin": "BTC", "ts_ms": 1500}],    # même coin, +500ms de 0xA -> même entité
        "0xC": [{"coin": "ETH", "ts_ms": 9_000_000}],
    }
    clusters = P.independance_entite(par_wallet, fenetre_ms=2000)
    lie = {w for grp in clusters.values() for w in grp}
    assert "0xA" in lie and "0xB" in lie and "0xC" not in lie


def test_classer_population_streaming(tmp_path):
    recs = []
    for d in range(4):
        for coin in ("BTC", "ETH", "SOL"):
            recs.append({"adresse": "0xWIN", "coin": coin, "side": "LONG",
                         "ts_ms": (10 + d) * JOUR, "mid_at_fill": 100.0, "mid_forward": 100.3})
            recs.append({"adresse": "0xLOSE", "coin": coin, "side": "LONG",
                         "ts_ms": (10 + d) * JOUR, "mid_at_fill": 100.0, "mid_forward": 99.9})
    p = tmp_path / "pop.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in recs), encoding="utf-8")
    out = P.classer_population(str(p), min_fills=5)
    assert out["n_wallets"] == 2 and out["n_evalues"] == 2
    assert out["classement"][0]["wallet"] == "0xWIN"
    assert "archetype" in out["classement"][0] and "entite_potentiellement_liee" in out["classement"][0]
