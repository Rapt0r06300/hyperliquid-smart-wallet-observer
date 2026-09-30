from pathlib import Path
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


def test_short_string_key_negative_size_closes_like_live_simulation():
    position = _pos(size=-2.0, avg=100.0)
    position["source_delta_key"] = "fusion-runtime-order:copy-sol-short"
    positions = {"w|SOL|SHORT": position}
    ledger = []
    closed = apply_sltp_exits(positions, ledger, {"SOL": 99.5}, cost_bps=0.0, config=CFG)
    assert len(closed) == 1
    assert "w|SOL|SHORT" not in positions
    assert ledger[0]["matched_position_key"] == "w|SOL|SHORT"
    assert ledger[0]["source_delta_key"] == "fusion-runtime-order:copy-sol-short"
    assert closed[0]["source_delta_key"] == "fusion-runtime-order:copy-sol-short"
    assert ledger[0]["estimated_net_pnl_usdc"] == 1.0


def test_duplicate_sltp_close_is_removed_without_second_pnl():
    first_position = _pos(size=1.0, avg=100.0)
    first_position["source_delta_key"] = "open-eth-long-1"
    first_position["opened_at_ms"] = 123000
    positions = {"w|ETH|LONG": first_position}
    ledger = []

    closed = apply_sltp_exits(positions, ledger, {"ETH": 100.5}, cost_bps=0.0, config=CFG, now_ms=124000)
    assert len(closed) == 1
    assert len(ledger) == 1
    assert ledger[0]["paper_position_instance_id"] == "w|ETH|LONG|src:open-eth-long-1"
    assert ledger[0]["estimated_net_pnl_usdc"] == 0.5

    stale_reloaded_position = _pos(size=1.0, avg=100.0)
    stale_reloaded_position["source_delta_key"] = "open-eth-long-1"
    stale_reloaded_position["opened_at_ms"] = 123000
    positions["w|ETH|LONG"] = stale_reloaded_position
    duplicate = apply_sltp_exits(positions, ledger, {"ETH": 100.5}, cost_bps=0.0, config=CFG, now_ms=125000)

    assert len(ledger) == 1
    assert positions == {}
    assert duplicate == [
        {
            "coin": "ETH",
            "side": "LONG",
            "reason": "DUPLICATE_SLTP_CLOSE_ALREADY_RECORDED",
            "net_pnl_usdc": 0.0,
            "matched_position_key": "w|ETH|LONG",
            "source_delta_key": "open-eth-long-1",
            "paper_position_instance_id": "w|ETH|LONG|src:open-eth-long-1",
            "duplicate_close_ignored": True,
        }
    ]


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
    """Aucune surface d'EXECUTION dans le runtime SL/TP.

    FAUX POSITIF CORRIGE (2026-07-11) : le motif "sign" attrapait `signed_pnl_bps` -- une simple
    fonction de calcul de PnL signe, importee pour le stop catastrophique. Un garde-fou qui crie
    au loup sur un nom de variable finit par etre desactive : on cible donc les vrais verbes
    d'action, et la SIGNATURE cryptographique explicitement.
    """
    import hl_observer.paper_trading.sltp_runtime as m

    pub = {n.lower() for n in dir(m) if not n.startswith("_")}
    interdits = (
        "submit", "place_order", "send_order", "cancel_order", "execute",
        "sign_typed", "sign_l1", "signature", "private_key", "wallet_sign",
    )
    for bad in interdits:
        coupables = [n for n in pub if bad in n]
        assert not coupables, f"surface d'execution interdite dans le runtime SL/TP : {coupables}"

    # et le module ne doit exposer AUCUN appel reseau
    src = Path("src/hl_observer/paper_trading/sltp_runtime.py").read_text(encoding="utf-8")
    assert "import requests" not in src and "import httpx" not in src
    assert "/exchange" not in src
