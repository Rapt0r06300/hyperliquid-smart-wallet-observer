"""Edge de copie MESURÉ (rectif Flo 23/07) : on prouve que l'edge est mesuré sur l'historique forward
+ placebo, JAMAIS fixé. Détection d'événements, rendement forward signé, statut NEED_MORE_DATA honnête,
et gel de config. Aucune exécution."""
from __future__ import annotations

import json

from hl_observer.experimental import copy_edge_forward as CE


def _ecrire_snaps(root, snaps):
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "data" / "vault_snapshots.jsonl").write_text(
        "\n".join(json.dumps(s) for s in snaps), encoding="utf-8")


def _ecrire_tape(root, points):
    """points = [(ts_ms, {coin: px})]."""
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "data" / "hl_allmids_tape.jsonl").write_text(
        "\n".join(json.dumps({"ts_ms": t, "mids": m}) for t, m in points), encoding="utf-8")


def test_charger_evenements_detecte_le_changement_par_coin(tmp_path):
    T = 1_000_000_000_000
    _ecrire_snaps(tmp_path, [
        {"vault": "0xA", "ts_ms": T - 300_000, "nav_usd": 100_000, "positions": [{"coin": "SOL", "szi": 0.0, "entryPx": 150.0}]},
        {"vault": "0xA", "ts_ms": T, "nav_usd": 100_000, "positions": [{"coin": "SOL", "szi": 100.0, "entryPx": 150.0}]},
    ])
    ev = CE.charger_evenements(tmp_path)
    assert len(ev) == 1 and ev[0]["coin"] == "SOL" and ev[0]["direction"] == 1
    assert ev[0]["ts_ms"] == T and ev[0]["move_frac"] >= 0.05          # 100×150 = 15 000 $ = 15 % du NAV


def test_rendement_forward_signe(tmp_path):
    serie = [(1000, 100.0), (2000, 101.0)]                             # +100 bps entre les deux
    assert CE.rendement_forward({"ts_ms": 1000, "direction": 1}, serie, 1000) == 100.0
    assert CE.rendement_forward({"ts_ms": 1000, "direction": -1}, serie, 1000) == -100.0   # short -> inverse
    assert CE.rendement_forward({"ts_ms": 1000, "direction": 1}, serie, 999_999) is None   # trou -> None


def test_mesurer_need_more_data_sur_peu_devenements(tmp_path):
    T = 1_000_000_000_000
    _ecrire_snaps(tmp_path, [
        {"vault": "0xA", "ts_ms": T - 300_000, "nav_usd": 100_000, "positions": [{"coin": "SOL", "szi": 0.0, "entryPx": 150.0}]},
        {"vault": "0xA", "ts_ms": T, "nav_usd": 100_000, "positions": [{"coin": "SOL", "szi": 100.0, "entryPx": 150.0}]},
    ])
    _ecrire_tape(tmp_path, [(T, {"SOL": 150.0}), (T + 300_000, {"SOL": 151.0})])
    m = CE.mesurer(tmp_path)                                           # min_events=30 par défaut
    assert m["statut"] == "NEED_MORE_DATA" and m["n_evenements"] == 1


def test_mesurer_produit_un_edge_et_un_placebo(tmp_path):
    """4 événements long appariables + tape en hausse -> statut MESURE (min_events abaissé), edge et
    placebo calculés. Tape MONOTONE => pas d'edge vs placebo (honnête : un simple drift n'est pas un edge)."""
    T = 1_000_000_000_000
    coins = ["C0", "C1", "C2", "C3"]
    snaps = []
    for i, c in enumerate(coins):
        snaps += [
            {"vault": "0x%d" % i, "ts_ms": T - 300_000, "nav_usd": 100_000, "positions": [{"coin": c, "szi": 0.0, "entryPx": 100.0}]},
            {"vault": "0x%d" % i, "ts_ms": T, "nav_usd": 100_000, "positions": [{"coin": c, "szi": 100.0, "entryPx": 100.0}]},
        ]
    _ecrire_snaps(tmp_path, snaps)
    pts = []
    for t in (T - 120_000, T - 60_000, T, T + 300_000, T + 360_000):
        pts.append((t, {c: (100.0 if t <= T else 101.0) for c in coins}))   # saut +100 bps après T
    _ecrire_tape(tmp_path, pts)
    m = CE.mesurer(tmp_path, horizons_ms=(300_000.0,), min_events=3, frais_bps=6.0)
    assert m["statut"] == "MESURE" and m["n_appariables_max"] >= 4
    h = m["par_horizon"]["300000"]
    assert h["n"] >= 4 and h["brut_bps"] == 100.0                      # rendement forward mesuré, pas fixé
    assert "placebo_bps" in h and "edge_vs_placebo_bps" in h


def test_geler_et_relire(tmp_path):
    assert CE.config_gelee(tmp_path) is None
    CE.geler(tmp_path, horizon_ms=900_000.0, edge_brut_bps=45.0, edge_net_mesure_bps=33.0)
    cfg = CE.config_gelee(tmp_path)
    assert cfg["gele"] is True and cfg["edge_brut_bps"] == 45.0 and cfg["horizon_ms"] == 900_000.0
