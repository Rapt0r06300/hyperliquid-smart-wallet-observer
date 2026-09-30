"""
Tests de la politique de risque (anti-churn, exits ATR, coupe-circuit, anti-scalper).

100% pur, déterministe, sans réseau. READ-ONLY / PAPER-ONLY.
"""

from __future__ import annotations

from hyper_smart_observer.dydx_v4.risk_policy import (
    CircuitBreaker,
    atr_exit_decision,
    held_long_enough,
    is_scalper,
    reopen_allowed,
    rolling_atr,
)

_DAY_MS = 86_400_000


# --------------------------------------------------------------------------- #
# 1. Anti-churn
# --------------------------------------------------------------------------- #
def test_held_long_enough():
    assert held_long_enough(0, 10_000, 20) is False   # 10s < 20s
    assert held_long_enough(0, 25_000, 20) is True     # 25s ≥ 20s
    assert held_long_enough(0, 1, 0) is True           # désactivé


def test_reopen_allowed():
    assert reopen_allowed(None, 10_000, 30) is True     # jamais fermé
    assert reopen_allowed(0, 10_000, 30) is False       # 10s < cooldown 30s
    assert reopen_allowed(0, 40_000, 30) is True        # 40s ≥ 30s
    assert reopen_allowed(0, 1, 0) is True              # désactivé


# --------------------------------------------------------------------------- #
# 4. Anti-scalper
# --------------------------------------------------------------------------- #
def test_is_scalper():
    assert is_scalper(None, 60) is False     # inconnu → ne filtre pas
    assert is_scalper(30, 60) is True        # détention 30s < 60s → scalper
    assert is_scalper(120, 60) is False      # détention 120s ≥ 60s → OK


# --------------------------------------------------------------------------- #
# 2. ATR
# --------------------------------------------------------------------------- #
def test_rolling_atr():
    assert rolling_atr([]) == 0.0
    assert rolling_atr([100]) == 0.0
    assert rolling_atr([100, 101, 103, 102]) == (1 + 2 + 1) / 3


def test_atr_exit_long_stop_and_tp():
    stop = atr_exit_decision("LONG", 100, 96, 2, stop_mult=1.5, tp_mult=3)
    assert stop.exit is True and stop.reason == "ATR_STOP"       # 96 ≤ 100-3
    tp = atr_exit_decision("LONG", 100, 107, 2, stop_mult=1.5, tp_mult=3)
    assert tp.exit is True and tp.reason == "ATR_TAKE_PROFIT"     # 107 ≥ 100+6


def test_atr_exit_short_stop():
    s = atr_exit_decision("SHORT", 100, 104, 2, stop_mult=1.5, tp_mult=3)
    assert s.exit is True and s.reason == "ATR_STOP"             # 104 ≥ 100+3


def test_atr_exit_no_atr():
    s = atr_exit_decision("LONG", 100, 96, 0)
    assert s.exit is False and s.reason == "NO_ATR"


def test_atr_trailing_arms_then_exits():
    s1 = atr_exit_decision("LONG", 100, 104, 2, tp_mult=10, trail_mult=1)
    assert s1.exit is False and s1.armed is True and s1.peak == 104
    s2 = atr_exit_decision("LONG", 100, 101, 2, tp_mult=10, trail_mult=1,
                           peak=s1.peak, armed=s1.armed)
    assert s2.exit is True and s2.reason == "ATR_TRAILING"       # 101 ≤ peak(104)-2


# --------------------------------------------------------------------------- #
# 3. Coupe-circuit
# --------------------------------------------------------------------------- #
def test_circuit_consecutive_losses():
    cb = CircuitBreaker(max_consecutive_losses=3)
    cb.record(-1.0, now_ms=0)
    cb.record(-1.0, now_ms=0)
    assert cb.is_tripped(0) is False
    cb.record(-1.0, now_ms=0)
    tripped, reason = cb.status(0)
    assert tripped is True and reason == "CIRCUIT_MAX_CONSECUTIVE_LOSSES"


def test_circuit_win_resets_streak():
    cb = CircuitBreaker(max_consecutive_losses=2)
    cb.record(-1.0, now_ms=0)
    cb.record(+0.5, now_ms=0)   # un gain remet le compteur à zéro
    cb.record(-1.0, now_ms=0)
    assert cb.is_tripped(0) is False


def test_circuit_daily_loss_limit():
    cb = CircuitBreaker(max_consecutive_losses=99, starting_equity=1000.0,
                        max_daily_drawdown_pct=0.05)  # limite = 50 USDC
    cb.record(-60.0, now_ms=0)
    tripped, reason = cb.status(0)
    assert tripped is True and reason == "CIRCUIT_DAILY_LOSS_LIMIT"


def test_circuit_resets_next_day():
    cb = CircuitBreaker(max_consecutive_losses=2)
    cb.record(-1.0, now_ms=0)
    cb.record(-1.0, now_ms=0)
    assert cb.is_tripped(0) is True
    # Jour suivant → réarmement automatique
    assert cb.is_tripped(_DAY_MS) is False
