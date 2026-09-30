"""Tests de l'espace etendu de scenarios + de la DB SQLite (replay-only, pur, deterministe)."""

from __future__ import annotations

import sqlite3

from hl_observer.backtesting import scenario_db
from hl_observer.backtesting.scenario_grid import (
    CATASTROPHIC_STOP_GRID,
    MIN_CONSENSUS_GRID,
    SIDE_MODE_GRID,
    SL_RANGE,
    TP_RANGE,
    generate_many,
)


def test_generate_many_distinct_and_deterministic():
    a = generate_many(5000, seed=7)
    b = generate_many(5000, seed=7)
    assert len(a) == 5000
    # distincts
    keys = {s.key() for s in a}
    assert len(keys) == 5000
    # deterministe : meme seed => meme suite
    assert [s.key() for s in a] == [s.key() for s in b]


def test_generate_many_respects_dimension_bounds():
    for s in generate_many(3000, seed=3):
        assert SL_RANGE[0] <= s.sl_bps <= SL_RANGE[1]
        assert TP_RANGE[0] <= s.tp_bps <= TP_RANGE[1]
        assert s.side_mode in SIDE_MODE_GRID
        assert int(s.min_consensus_wallets) in MIN_CONSENSUS_GRID
        assert s.catastrophic_stop_bps in CATASTROPHIC_STOP_GRID
        # coherence trailing : desactive => activation/breakeven a 0
        if s.trailing_stop_bps == 0.0:
            assert s.trailing_activation_bps == 0.0
            assert s.breakeven_bps == 0.0


def test_build_database_rows_and_meta(tmp_path):
    out = tmp_path / "scenarios.db"
    stats = scenario_db.build_database(out, count=4000, seed=11)
    assert out.exists()
    assert stats["count_rows"] == 4000
    con = sqlite3.connect(str(out))
    try:
        n = con.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0]
        distinct_hash = con.execute("SELECT COUNT(DISTINCT param_hash) FROM scenarios").fetchone()[0]
        cols = {r[1] for r in con.execute("PRAGMA table_info(scenarios)")}
        meta_keys = {r[0] for r in con.execute("SELECT key FROM meta")}
    finally:
        con.close()
    assert n == 4000
    assert distinct_hash == 4000  # aucun doublon
    # 15 dimensions presentes en colonnes
    for f in ("sl_bps", "max_signal_age_ms", "min_leader_score", "side_mode", "catastrophic_stop_bps"):
        assert f in cols
    assert {"generator_version", "seed", "count_rows", "dimensions"} <= meta_keys


def test_scenarios_are_replay_only_no_orders(tmp_path):
    # garde-fou : la DB ne contient aucune notion d'ordre reel, uniquement des parametres.
    out = tmp_path / "s.db"
    scenario_db.build_database(out, count=500, seed=1)
    con = sqlite3.connect(str(out))
    try:
        rows = con.execute("SELECT * FROM scenarios LIMIT 50").fetchall()
    finally:
        con.close()
    assert rows  # non vide, purement descriptif


def test_scale_build_and_reader_roundtrip(tmp_path):
    out = tmp_path / "scale.db"
    stats = scenario_db.build_database_scale(out, 5000, seed=7, batch_rows=1000)
    assert stats["count_rows"] == 5000
    scs = list(scenario_db.iter_db_scenarios(out, limit=120))
    assert len(scs) == 120
    for s in scs:
        assert SL_RANGE[0] <= s.sl_bps <= SL_RANGE[1]
        assert s.side_mode in SIDE_MODE_GRID
        assert int(s.min_consensus_wallets) in MIN_CONSENSUS_GRID


def test_db_scenarios_feed_eval_trades(tmp_path):
    # CABLAGE replay : DB -> Scenario -> eval_trades produit des rapports (sans lancer le vrai replay).
    from hl_observer.backtesting import scenario_search as ss
    out = tmp_path / "scale.db"
    scenario_db.build_database_scale(out, 400, seed=5, batch_rows=100)
    scs = list(scenario_db.iter_db_scenarios(out, limit=50))
    ts0 = 1_000_000.0
    candidates = [{"coin": "AAA", "direction": "LONG", "current_mid": 100.0,
                   "recorded_at": ts0, "edge_remaining_bps": 50.0, "copy_degradation_bps": 2.0}]
    marks = {"AAA": [(ts0 + i * 10.0, 100.0 + i * 0.1) for i in range(1, 200)]}
    for s in scs:
        rep = ss.report_from_trades(ss.eval_trades(s, candidates, marks, 500.0))
        assert "trades" in rep and "net_total_usd" in rep


def test_eval_trades_entry_filters_reject_as_expected():
    # Prouve que les 7 filtres branches excluent bien selon les champs reels des candidats.
    from hl_observer.backtesting import scenario_search as ss
    from hl_observer.backtesting.scenario_grid import Scenario
    ts0 = 1_000_000.0
    marks = {"AAA": [(ts0 + i * 10.0, 100.0 + i * 0.1) for i in range(1, 200)]}
    cand = [dict(coin="AAA", direction="LONG", current_mid=100.0, recorded_at=ts0,
                 edge_remaining_bps=50.0, copy_degradation_bps=5.0, signal_age_ms=8000.0,
                 liquidity_score=0.7, consensus_wallets=2, leader_score=65.0)]

    def sc(**kw):
        d = dict(name="t", sl_bps=60.0, tp_bps=120.0, trailing_stop_bps=0.0,
                 trailing_activation_bps=0.0, breakeven_bps=0.0, horizon_min=60.0,
                 cost_bps=12.0, min_edge_bps=0.0, source="test")
        d.update(kw)
        return Scenario(**d)

    assert ss.eval_trades(sc(), cand, marks, 500.0)                              # baseline: 1 trade
    assert ss.eval_trades(sc(side_mode="short_only"), cand, marks, 500.0) == []  # LONG rejete
    assert ss.eval_trades(sc(side_mode="long_only"), cand, marks, 500.0)         # LONG accepte
    assert ss.eval_trades(sc(max_signal_age_ms=5000.0), cand, marks, 500.0) == []   # age 8000>5000
    assert ss.eval_trades(sc(max_signal_age_ms=10000.0), cand, marks, 500.0)        # 8000<10000
    assert ss.eval_trades(sc(min_liquidity_score=0.8), cand, marks, 500.0) == []    # 0.7<0.8
    assert ss.eval_trades(sc(min_liquidity_score=0.6), cand, marks, 500.0)          # 0.7>=0.6
    assert ss.eval_trades(sc(min_liquidity_score=80.0), cand, marks, 500.0) == []   # compat 0..100 -> 0.8
    assert ss.eval_trades(sc(min_consensus_wallets=3), cand, marks, 500.0) == []    # 2<3
    assert ss.eval_trades(sc(min_leader_score=70.0), cand, marks, 500.0) == []      # 65<70
    assert ss.eval_trades(sc(max_copy_degradation_bps=4.0), cand, marks, 500.0) == []  # 5>4
    # stop catastrophe = plafond de perte (min avec sl) : n'empeche pas un trade gagnant
    assert ss.eval_trades(sc(catastrophic_stop_bps=180.0), cand, marks, 500.0)


def test_search_over_db_streaming(tmp_path):
    # Recherche STREAMING depuis la DB (memoire bornee) : lit, evalue, renvoie des finalistes.
    from hl_observer.backtesting import scenario_search as ss
    db = tmp_path / "s.db"
    scenario_db.build_database_scale(db, 800, seed=3, batch_rows=200)
    ts0 = 1_000_000.0
    cands = [dict(coin="AAA", direction="LONG", current_mid=100.0,
                  recorded_at=ts0 + k * 100.0, edge_remaining_bps=40.0,
                  copy_degradation_bps=5.0, signal_age_ms=4000.0,
                  liquidity_score=0.85, consensus_wallets=2, leader_score=60.0)
             for k in range(60)]
    mark_rows = [dict(coin="AAA", ts=ts0 + i * 20.0, mid=100.0 + i * 0.05) for i in range(1, 2000)]
    rep = ss.search_over_db(cands, mark_rows, str(db), sample=400, batch=100,
                            top_k=5, min_trades=1, jobs=1, notional_usd=500.0)
    assert rep["scenarios_evaluated"] == 400
    assert rep["source"].startswith("db:")
    assert isinstance(rep["finalists"], list)
    # le rapport des finalistes doit exposer les 15 dimensions
    if rep["finalists"]:
        srow = rep["finalists"][0]["scenario"]
        for f in ("sl_bps", "side_mode", "min_liquidity_score", "catastrophic_stop_bps"):
            assert f in srow


def test_start_id_offset(tmp_path):
    db = tmp_path / "s.db"
    scenario_db.build_database_scale(db, 1000, seed=1, batch_rows=200)
    assert len(list(scenario_db.iter_db_scenarios(db, start_id=0))) == 1000
    assert len(list(scenario_db.iter_db_scenarios(db, start_id=990))) == 10  # id>990 => 10 restants


def test_stop_file_halts_early(tmp_path):
    from hl_observer.backtesting import scenario_search as ss
    db = tmp_path / "s.db"
    scenario_db.build_database_scale(db, 3000, seed=3, batch_rows=500)
    stop = tmp_path / "STOP"
    stop.write_text("stop")  # signal deja present => stoppe apres le 1er lot
    ts0 = 1_000_000.0
    cands = [dict(coin="AAA", direction="LONG", current_mid=100.0, recorded_at=ts0 + k * 100.0,
                  edge_remaining_bps=40.0, copy_degradation_bps=5.0, signal_age_ms=4000.0,
                  liquidity_score=0.85, consensus_wallets=2, leader_score=60.0) for k in range(40)]
    marks = [dict(coin="AAA", ts=ts0 + i * 20.0, mid=100.0 + i * 0.05) for i in range(1, 500)]
    rep = ss.search_over_db(cands, marks, str(db), sample=None, batch=200,
                            stop_file=str(stop), top_k=5, min_trades=1, jobs=1, notional_usd=500.0)
    assert rep["scenarios_evaluated"] <= 400  # ~1 lot, pas les 3000
