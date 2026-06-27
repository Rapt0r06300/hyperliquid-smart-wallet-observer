from hl_observer.copying.v9_paper_pipeline import (
    V9PipelineConfig,
    run_v9_paper_session,
)

NOW = 1_000_000_000


def _fill(**kw):
    base = dict(
        wallet="0xLEADER", coin="BTC", side="LONG", action_type="OPEN_LONG",
        price=100.0, size=1.0, notional_usdc=5000.0, fill_ts_ms=NOW - 2_000,
        leader_edge_bps=40.0, liquidity_score=0.8, leader_score=85, consensus_wallets=2,
        mark_price=100.0,
    )
    base.update(kw)
    return base


def test_clean_long_opens_then_closes_with_positive_pnl():
    fills = [
        _fill(action_type="OPEN_LONG", mark_price=100.0, fill_ts_ms=NOW - 5_000),
        _fill(action_type="CLOSE_LONG", mark_price=110.0, fill_ts_ms=NOW - 1_000),  # +10%
    ]
    r = run_v9_paper_session(fills, now_ms=NOW)
    assert r.entries_opened == 1 and r.exits_closed == 1
    assert r.realized_pnl_usdt > 4.0            # 50 notional * 10% = ~5 (moins frais)
    assert r.equity_usdt > r.starting_equity_usdt
    assert r.supply_report.bottleneck == "OK"
    assert all(d["execution"] == "forbidden" for d in r.decisions)


def test_clean_short_profits_when_price_drops():
    fills = [
        _fill(side="SHORT", action_type="OPEN_SHORT", mark_price=100.0, fill_ts_ms=NOW - 5_000),
        _fill(side="SHORT", action_type="CLOSE_SHORT", mark_price=90.0, fill_ts_ms=NOW - 1_000),  # -10% => short gagne
    ]
    r = run_v9_paper_session(fills, now_ms=NOW)
    assert r.entries_opened == 1 and r.exits_closed == 1 and r.realized_pnl_usdt > 4.0


def test_add_increases_position_without_resetting_entry():
    fills = [
        _fill(action_type="OPEN_LONG", mark_price=100.0, fill_ts_ms=NOW - 5_000),
        _fill(action_type="ADD", price=110.0, mark_price=110.0, fill_ts_ms=NOW - 1_000),
    ]
    r = run_v9_paper_session(fills, now_ms=NOW)
    assert r.entries_opened == 2
    pos = next(iter(r.open_positions.values()))
    assert pos.notional_usdt == 100.0
    assert pos.entry_price == 105.0
    assert any(d["status"] == "PAPER_INCREASE" for d in r.decisions)


def test_reduce_partially_closes_and_keeps_remaining_position():
    fills = [
        _fill(action_type="OPEN_LONG", mark_price=100.0, fill_ts_ms=NOW - 5_000),
        _fill(action_type="REDUCE", mark_price=110.0, fill_ts_ms=NOW - 1_000, reduce_fraction=0.4),
    ]
    r = run_v9_paper_session(fills, now_ms=NOW)
    assert r.entries_opened == 1
    assert r.exits_closed == 0
    assert r.reduces_applied == 1
    assert r.realized_pnl_usdt > 1.0
    pos = next(iter(r.open_positions.values()))
    assert pos.notional_usdt == 30.0
    reduce_decision = [d for d in r.decisions if d["status"] == "PAPER_REDUCE"][0]
    assert reduce_decision["remaining_notional_usdt"] == 30.0


def test_decisions_are_readonly_evidence_chained():
    r = run_v9_paper_session([_fill(action_type="OPEN_LONG", mark_price=100.0)], now_ms=NOW)
    assert r.decisions
    row = r.decisions[0]
    assert row["simulation_only"] is True
    assert row["read_only"] is True
    assert row["external_action"] is False
    assert row["execution"] == "forbidden"
    assert row["venue_endpoint"] is None
    assert row["secret_material_used"] is False
    assert row["paper_ref"].startswith("paper_entry:")
    assert row["evidence_hash"].startswith("ev:")


def test_noise_is_skipped_no_entry():
    fills = [
        _fill(coin="XYZ:TSLA"),                                   # exotique
        _fill(action_type="OPEN_LONG", fill_ts_ms=NOW - 5 * 3_600_000),  # backfill 5h
        _fill(action_type="REDUCE", side="LONG"),                 # sortie sans position
        _fill(),                                                   # ok
        _fill(),                                                   # doublon exact -> skip
    ]
    r = run_v9_paper_session(fills, now_ms=NOW)
    assert r.entries_opened == 1                                   # seul le fill propre unique ouvre
    # le bruit n'a pas créé de décisions loggées
    assert r.supply_report.skipped >= 3


def test_price_missing_is_no_trade():
    fills = [_fill(mark_price=None)]
    r = run_v9_paper_session(fills, now_ms=NOW, mark_price={})  # aucun prix
    assert r.entries_opened == 0
    assert any(d["reason"] == "PRICE_MISSING" for d in r.decisions)


def test_low_edge_is_refused():
    fills = [_fill(leader_edge_bps=1.0)]  # edge net négatif après coûts
    r = run_v9_paper_session(fills, now_ms=NOW)
    assert r.entries_opened == 0
    assert any(d["reason"] == "EDGE_REMAINING_TOO_LOW" for d in r.decisions)


def test_exposure_cap_blocks_after_max():
    # 6 entrées propres sur coins distincts, cap total 200 / 50 par position -> max 4 ouvertes
    fills = [
        _fill(coin=c, action_type="OPEN_LONG", fill_ts_ms=NOW - 3_000)
        for c in ["BTC", "ETH", "SOL", "HYPE", "AVAX", "ARB"]
    ]
    r = run_v9_paper_session(fills, now_ms=NOW)
    assert r.entries_opened == 4
    assert any(d.get("reason") == "MAX_EXPOSURE_REACHED" for d in r.decisions)


def test_empty_session_is_no_data():
    r = run_v9_paper_session([], now_ms=NOW)
    assert r.entries_opened == 0 and r.equity_usdt == 1000.0
    assert r.supply_report.bottleneck == "NO_DATA"
