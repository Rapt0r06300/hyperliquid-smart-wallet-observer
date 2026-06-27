import os

from hl_observer.paper_trading.sl_tp import SLTPConfig
from hl_observer.paper_trading.sltp_runtime import apply_sltp_exits, sltp_config_from_env


def _pos(size=1.0, avg=100.0, hi=None, lo=None):
    return {
        "size": size, "avg_price": avg,
        "highest_price": hi if hi is not None else avg,
        "lowest_price": lo if lo is not None else avg,
        "entry_costs": 0.0,
    }


CFG = SLTPConfig(take_profit_bps=30.0, stop_loss_bps=40.0, trailing_stop_bps=None)


def test_long_take_profit_closes_and_realizes():
    positions = {("w", "ETH", "LONG"): _pos(size=1.0, avg=100.0)}
    ledger = []
    # +0.5% mark -> above +0.30% TP
    closed = apply_sltp_exits(positions, ledger, {"ETH": 100.5}, cost_bps=0.0, config=CFG)
    assert len(closed) == 1
    assert ("w", "ETH", "LONG") not in positions      # position closed
    ev = ledger[0]
    assert ev["status"] == "LOCAL_REPLAY"
    assert ev["bot_replay_action"] == "PAPER_CLOSE_REPLAYED"
    assert ev["estimated_net_pnl_usdc"] == 0.5        # 1 * (100.5-100)
    assert "TAKE_PROFIT" in ev["exit_method"]
    assert ev["sltp_take_profit_bps"] == 30.0
    assert ev["sltp_stop_loss_bps"] == 40.0
    assert ev["sltp_pnl_bps"] == 50.0


def test_long_stop_loss_closes_negative():
    positions = {("w", "ETH", "LONG"): _pos(size=2.0, avg=100.0)}
    ledger = []
    closed = apply_sltp_exits(positions, ledger, {"ETH": 99.5}, cost_bps=0.0, config=CFG)  # -0.5% < -0.40% SL
    assert len(closed) == 1
    assert ledger[0]["estimated_net_pnl_usdc"] == -1.0  # 2*(99.5-100)
    assert "STOP_LOSS" in ledger[0]["exit_method"]


def test_short_take_profit_on_drop():
    positions = {("w", "SOL", "SHORT"): _pos(size=1.0, avg=100.0)}
    ledger = []
    closed = apply_sltp_exits(positions, ledger, {"SOL": 99.5}, cost_bps=0.0, config=CFG)  # short profits on drop
    assert len(closed) == 1
    assert ledger[0]["estimated_net_pnl_usdc"] == 0.5


def test_hold_in_band_keeps_position():
    positions = {("w", "ETH", "LONG"): _pos(size=1.0, avg=100.0)}
    ledger = []
    closed = apply_sltp_exits(positions, ledger, {"ETH": 100.1}, cost_bps=0.0, config=CFG)  # +0.1% < TP
    assert closed == []
    assert ("w", "ETH", "LONG") in positions
    assert ledger == []


def test_trailing_stop_tracks_live_peak_then_exits_on_giveback():
    cfg = SLTPConfig(take_profit_bps=99999.0, stop_loss_bps=999.0, trailing_stop_bps=30.0)
    positions = {("w", "ETH", "LONG"): _pos(size=1.0, avg=100.0)}
    ledger = []

    first = apply_sltp_exits(positions, ledger, {"ETH": 101.0}, cost_bps=0.0, config=cfg)
    assert first == []
    assert positions[("w", "ETH", "LONG")]["highest_price"] == 101.0

    closed = apply_sltp_exits(positions, ledger, {"ETH": 100.6}, cost_bps=0.0, config=cfg)
    assert len(closed) == 1
    assert ("w", "ETH", "LONG") not in positions
    assert ledger[0]["exit_method"] == "SLTP_TRAILING_STOP"
    assert ledger[0]["matched_position_key"] == "w|ETH|LONG"


def test_costs_reduce_realized_pnl():
    positions = {("w", "ETH", "LONG"): _pos(size=1.0, avg=100.0)}
    ledger = []
    apply_sltp_exits(positions, ledger, {"ETH": 100.5}, cost_bps=12.0, config=CFG)
    # gross 0.5 - exit_cost (100.5 * 12/10000 = 0.1206) = 0.3794
    assert abs(ledger[0]["estimated_net_pnl_usdc"] - 0.3794) < 1e-6


def test_no_mark_skips():
    positions = {("w", "XYZ", "LONG"): _pos()}
    ledger = []
    closed = apply_sltp_exits(positions, ledger, {}, config=CFG)
    assert closed == [] and ("w", "XYZ", "LONG") in positions


def test_disabled_config_noop():
    positions = {("w", "ETH", "LONG"): _pos()}
    ledger = []
    closed = apply_sltp_exits(positions, ledger, {"ETH": 200.0}, config=None)
    assert closed == [] and ledger == [] and positions


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("HYPERSMART_SLTP_ENABLED", "1")
    monkeypatch.setenv("HYPERSMART_SLTP_TAKE_PROFIT_BPS", "25")
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_LOSS_BPS", "35")
    monkeypatch.setenv("HYPERSMART_SLTP_TRAILING_BPS", "20")
    monkeypatch.setenv("HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS", "45")
    monkeypatch.setenv("HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS", "7")
    cfg = sltp_config_from_env()
    assert cfg is not None and cfg.take_profit_bps == 25.0 and cfg.stop_loss_bps == 35.0
    assert cfg.trailing_stop_bps == 20.0
    assert cfg.trailing_activation_bps == 45.0
    assert cfg.breakeven_buffer_bps == 7.0
    monkeypatch.setenv("HYPERSMART_SLTP_ENABLED", "0")
    assert sltp_config_from_env() is None


def test_runtime_has_no_execution_surface():
    import hl_observer.paper_trading.sltp_runtime as m
    pub = {n for n in dir(m) if not n.startswith("_")}
    for bad in ("submit", "place_order", "sign", "send_order", "execute"):
        assert not any(bad in n.lower() for n in pub)
