from hl_observer.features.midpoint_jump_filter import MidpointJumpFilter, is_midpoint_jump
from hl_observer.features.mid_stability import requires_stable_confirmation
from hl_observer.features.ema_median_smoother import EmaMedianSmoother
from hl_observer.copy_mode.cooldown import FillCooldown
from hl_observer.paper_trading.max_chase_guard import max_chase_exceeded
from hl_observer.config.local_rule_store import LocalRuleStore
from hl_observer.ui.local_commands import parse_command


def test_midpoint_jump_blocks():
    assert is_midpoint_jump(100.0, 100.6, max_jump_bps=50) is True      # 60 bps jump
    assert is_midpoint_jump(100.0, 100.2, max_jump_bps=50) is False
    f = MidpointJumpFilter(max_jump_bps=50)
    assert f.accept(100.0) is True
    assert f.accept(100.6) is False                                     # jump blocked


def test_stable_confirmation_requires_multiple_ticks():
    assert requires_stable_confirmation([100.0], window=3, tol_bps=5) is False
    assert requires_stable_confirmation([100.0, 100.01, 100.02], window=3, tol_bps=5) is True
    assert requires_stable_confirmation([100.0, 101.0, 100.0], window=3, tol_bps=5) is False


def test_ema_median_smoothing_no_fake_price():
    s = EmaMedianSmoother(alpha=0.5, median_window=3)
    assert s.push(None) is None                 # no input -> no fabricated value
    s.push(100.0); s.push(102.0)
    out = s.push(101.0)
    assert out is not None and 99.0 <= out <= 103.0   # bounded by real inputs


def test_fill_cooldown_blocks_duplicate():
    cd = FillCooldown(window_ms=5000)
    assert cd.allow("BTC:LONG", now_ms=1000) is True
    assert cd.allow("BTC:LONG", now_ms=3000) is False    # within window
    assert cd.allow("BTC:LONG", now_ms=7000) is True     # window passed


def test_max_chase_blocks_degraded_copy():
    assert max_chase_exceeded(100.0, 100.30, "LONG", max_chase_bps=18) is True   # +30 bps
    assert max_chase_exceeded(100.0, 100.10, "LONG", max_chase_bps=18) is False
    assert max_chase_exceeded(100.0, 99.70, "SHORT", max_chase_bps=18) is True   # short, price dropped 30 bps


def test_local_rule_store_roundtrip(tmp_path):
    s = LocalRuleStore(str(tmp_path / "rules.json"))
    s.set("min_edge_bps", 12)
    assert LocalRuleStore(str(tmp_path / "rules.json")).get("min_edge_bps") == 12


def test_local_commands_parse():
    assert parse_command("/status")["mode"] == "read"
    sr = parse_command("/set_rule min_edge 15")
    assert sr["ok"] and sr["key"] == "min_edge" and sr["value"] == "15" and sr["external_action"] is False
    assert parse_command("/launch_real")["ok"] is False
