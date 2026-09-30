"""Edge de copie MESURÉ (rectif Flo 23/07) : on prouve que l'edge est mesuré sur l'historique forward
+ placebo, JAMAIS fixé. Détection d'événements, rendement forward signé, statut NEED_MORE_DATA honnête,
et gel de config. Aucune exécution."""
from __future__ import annotations

import gzip
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


def _ecrire_bbo(root, records):
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    path = root / "runtime" / "data" / "bbo_tape.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    return path


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


def test_charger_prix_tape_candles(tmp_path):
    from hl_observer.experimental.copy_edge_forward import charger_prix_tape_candles
    (tmp_path / "runtime" / "history").mkdir(parents=True)
    (tmp_path / "runtime" / "history" / "candles_1m.jsonl").write_text("\n".join([
        json.dumps({"coin": "BTC", "t_ms": 1000, "c": 60000.0}),
        json.dumps({"coin": "BTC", "t_ms": 2000, "c": 60100.0}),
        json.dumps({"coin": "eth", "t_ms": 1500, "c": 2000.0}),
        json.dumps({"coin": "BAD", "t_ms": 3000, "c": 0}),           # px<=0 ignoré
    ]))
    tape = charger_prix_tape_candles(tmp_path, intervalle="1m")
    assert tape["BTC"] == [(1000, 60000.0), (2000, 60100.0)] and tape["ETH"] == [(1500, 2000.0)]
    assert "BAD" not in tape


def test_charger_prix_tape_ciblee_ne_conserve_que_les_points_utiles(tmp_path):
    T = 1_000_000_000_000
    points = []
    for offset in range(-120_000, 3_840_001, 30_000):
        points.append((T + offset, {"BTC": 60_000.0 + offset / 100_000, "ETH": 2_000.0}))
    _ecrire_tape(tmp_path, points)

    tape, meta = CE.charger_prix_tape_ciblee(
        tmp_path,
        {"BTC": [T]},
        horizon_ms=3_600_000,
        tolerance_ms=45_000,
    )

    assert len(tape["BTC"]) == 2
    assert tape["BTC"][0][0] == T
    assert tape["BTC"][1][0] == T + 3_600_000
    assert "ETH" not in tape
    assert meta["mode"] == "EVENT_TARGETED_BOUNDED"
    assert meta["cibles_prix"] == meta["cibles_appariees"] == 2


def test_charger_prix_tape_ciblee_borne_les_evenements_les_plus_recents(tmp_path):
    T = 1_000_000_000_000
    _ecrire_tape(
        tmp_path,
        [(T + index * 1_000, {"BTC": 100.0 + index}) for index in range(20)],
    )

    _tape, meta = CE.charger_prix_tape_ciblee(
        tmp_path,
        {"BTC": [T + index * 1_000 for index in range(10)]},
        horizon_ms=1_000,
        tolerance_ms=100,
        max_evenements_total=3,
        max_evenements_par_coin=10,
    )

    assert meta["evenements_demandes"] == 10
    assert meta["evenements_retenus"] == 3
    assert meta["cibles_prix"] == 4


def test_charger_prix_tape_ciblee_supporte_les_coins_a_caracteres_speciaux(tmp_path):
    T = 1_000_000_000_000
    _ecrire_tape(
        tmp_path,
        [
            (T, {"XYZ:SNDK": 12.5, "@107": 0.25, "HORS_CIBLE": 999.0}),
            (T + 1_000, {"XYZ:SNDK": 12.75, "@107": 0.5, "HORS_CIBLE": 1.0}),
        ],
    )

    tape, meta = CE.charger_prix_tape_ciblee(
        tmp_path,
        {"XYZ:SNDK": [T], "@107": [T]},
        horizon_ms=1_000,
        tolerance_ms=10,
    )

    assert tape == {
        "@107": [(T, 0.25), (T + 1_000, 0.5)],
        "XYZ:SNDK": [(T, 12.5), (T + 1_000, 12.75)],
    }
    assert meta["cibles_appariees"] == 4


def test_charger_prix_tape_ciblee_complete_allmids_stale_avec_bbo_hl(tmp_path):
    T = 1_000_000_000_000
    _ecrire_tape(tmp_path, [(T - 100_000, {"BTC": 90.0})])
    bbo = _ecrire_bbo(tmp_path, [
        {"venue": "BIN", "coin": "BTC", "ts_wall_ms": T, "mid": 999.0},
        {"venue": "HL", "coin": "BTC", "ts_wall_ms": T + 5, "mid": 100.0},
        {"venue": "HL", "coin": "BTC", "ts_wall_ms": T + 1_005, "mid": 101.0},
    ])

    tape, meta = CE.charger_prix_tape_ciblee(
        tmp_path,
        {"BTC": [T]},
        horizon_ms=1_000,
        tolerance_ms=10,
        sources_bbo=[bbo],
    )

    assert tape["BTC"] == [(T + 5, 100.0), (T + 1_005, 101.0)]
    assert meta["cibles_appariees"] == 2
    assert meta["cibles_par_source"]["runtime/data/bbo_tape.jsonl"] == 2
    assert meta["source_mode"] == "ALLMIDS_THEN_HL_BBO_FALLBACK"


def test_charger_prix_tape_ciblee_garde_le_point_le_plus_proche_sans_extrapoler(tmp_path):
    T = 1_000_000_000_000
    _ecrire_tape(tmp_path, [(T + 9, {"BTC": 90.0}), (T + 1_009, {"BTC": 91.0})])
    bbo = _ecrire_bbo(tmp_path, [
        {"venue": "HL", "coin": "BTC", "ts_wall_ms": T + 2, "mid": 100.0},
        {"venue": "HL", "coin": "BTC", "ts_wall_ms": T + 1_050, "mid": 101.0},
    ])

    tape, meta = CE.charger_prix_tape_ciblee(
        tmp_path,
        {"BTC": [T]},
        horizon_ms=1_000,
        tolerance_ms=10,
        sources_bbo=[bbo],
    )

    assert tape["BTC"] == [(T + 2, 100.0), (T + 1_009, 91.0)]
    assert meta["cibles_appariees"] == 2
    assert all(ts != T + 1_050 for ts, _price in tape["BTC"])


def test_charger_prix_tape_ciblee_refuse_un_point_anterieur_meme_plus_proche(tmp_path):
    T = 1_000_000_000_000
    _ecrire_tape(tmp_path, [])
    bbo = _ecrire_bbo(tmp_path, [
        {"venue": "HL", "coin": "BTC", "ts_wall_ms": T - 1, "mid": 99.0},
        {"venue": "HL", "coin": "BTC", "ts_wall_ms": T + 3, "mid": 100.0},
        {"venue": "HL", "coin": "BTC", "ts_wall_ms": T + 999, "mid": 101.0},
        {"venue": "HL", "coin": "BTC", "ts_wall_ms": T + 1_004, "mid": 102.0},
    ])

    tape, meta = CE.charger_prix_tape_ciblee(
        tmp_path,
        {"BTC": [T]},
        horizon_ms=1_000,
        tolerance_ms=10,
        sources_bbo=[bbo],
    )

    assert tape["BTC"] == [(T + 3, 100.0), (T + 1_004, 102.0)]
    assert meta["cibles_appariees"] == 2


def test_charger_prix_tape_ciblee_charge_les_delais_prenregistres(tmp_path):
    T = 1_000_000_000_000
    _ecrire_tape(tmp_path, [
        (T, {"BTC": 100.0}),
        (T + 50, {"BTC": 100.1}),
        (T + 100, {"BTC": 100.2}),
        (T + 1_000, {"BTC": 101.0}),
    ])

    tape, meta = CE.charger_prix_tape_ciblee(
        tmp_path,
        {"BTC": [T]},
        horizon_ms=1_000,
        tolerance_ms=1,
        delays_ms=(50, 100),
    )

    assert tape["BTC"] == [
        (T, 100.0),
        (T + 50, 100.1),
        (T + 100, 100.2),
        (T + 1_000, 101.0),
    ]
    assert meta["delays_ms"] == [50, 100]
    assert meta["cibles_appariees"] == 4


def test_charger_prix_tape_ciblee_lit_un_shard_bbo_historique_compresse(tmp_path):
    T = 1_000_000_000_000
    shard_dir = tmp_path / "runtime" / "data" / "bbo_shards"
    shard_dir.mkdir(parents=True)
    shard = shard_dir / f"bbo_tape_{(T + 2_000) * 1_000_000}.jsonl.gz"
    records = [
        {"venue": "HL", "coin": "BTC", "ts_wall_ms": T + 3, "mid": 100.0},
        {"venue": "HL", "coin": "BTC", "ts_wall_ms": T + 1_003, "mid": 101.0},
    ]
    with gzip.open(shard, "wt", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    tape, meta = CE.charger_prix_tape_ciblee(
        tmp_path,
        {"BTC": [T]},
        horizon_ms=1_000,
        tolerance_ms=10,
        inclure_historique_bbo=True,
    )

    assert tape["BTC"] == [(T + 3, 100.0), (T + 1_003, 101.0)]
    assert meta["historique_bbo_active"] is True
    assert meta["cibles_appariees"] == 2
    assert meta["cibles_par_source"]["runtime/data/bbo_shards/" + shard.name] == 2


def test_geler_et_relire(tmp_path):
    assert CE.config_gelee(tmp_path) is None
    CE.geler(tmp_path, horizon_ms=900_000.0, edge_brut_bps=45.0, edge_net_mesure_bps=33.0)
    cfg = CE.config_gelee(tmp_path)
    assert cfg["gele"] is True and cfg["edge_brut_bps"] == 45.0 and cfg["horizon_ms"] == 900_000.0
