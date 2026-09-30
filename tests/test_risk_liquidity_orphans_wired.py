"""Câblage vague 1: contrats des orphelins risque + liquidité (AUDIT-B).

Fige le comportement de graded_halt (arrêt progressif GREEN→AMBER→RED avec
escalade immédiate et désescalade cooldownée), kill_switch, et le walk-the-book
L2 (coûts réels vs profondeur inventée). Prouve qu'ils sont prêts à câbler.
"""

from __future__ import annotations

from hl_observer.collection.l2_snapshot_cache import compute_book_costs
from hl_observer.risk.graded_halt import GradedHaltStateMachine
from hl_observer.risk.kill_switch import KillSwitch


def _loss_event(pnl: float, ts_ms: int) -> dict:
    return {"paper_action_type": "CLOSE", "estimated_net_pnl_usdc": pnl, "observed_at_ms": ts_ms}


def test_graded_halt_escalates_immediately_then_de_escalates_after_cooldown():
    env = {
        "HYPERSMART_V26_HALT_AMBER_LOSS_USD": "12",
        "HYPERSMART_V26_HALT_RED_LOSS_USD": "25",
        "HYPERSMART_V26_HALT_WINDOW_MIN": "240",
        "HYPERSMART_V26_HALT_COOLDOWN_MIN": "45",
        "HYPERSMART_V26_HALT_AMBER_SIZE_MULT": "0.5",
    }
    sm = GradedHaltStateMachine()
    t0 = 1_000_000_000
    # perte de 30 USD sur la fenêtre -> RED immédiat
    assert sm.update([_loss_event(-30.0, t0)], t0, env) == "RED"
    eff = sm.effects(env)
    assert eff.state == "RED" and eff.entries_blocked_globally is True and eff.force_exit_all is True
    sm.mark_forced_exit_done()
    # plus de perte, mais avant cooldown -> reste RED
    assert sm.update([], t0 + 10 * 60_000, env) == "RED"
    # après cooldown -> descend d'UN palier (RED -> AMBER), pas directement GREEN
    assert sm.update([], t0 + 50 * 60_000, env) == "AMBER"
    assert sm.effects(env).size_multiplier == 0.5
    # encore un cooldown -> GREEN
    assert sm.update([], t0 + 100 * 60_000, env) == "GREEN"
    assert sm.effects(env).entries_blocked_globally is False


def test_kill_switch_blocks_when_active():
    ks = KillSwitch()
    assert ks.allows_trading() is True
    ks.active = True
    ks.reason = "MANUAL"
    assert ks.allows_trading() is False


def test_l2_book_costs_from_real_levels():
    bids = [(99.9, 100.0), (99.8, 200.0)]
    asks = [(100.1, 5.0), (100.3, 50.0), (100.6, 200.0)]
    out = compute_book_costs(bids, asks, notional_usd=2_000.0)
    assert out is not None
    spread_bps, slip_bps = out
    assert spread_bps > 0  # spread réel mesuré
    assert slip_bps > 0    # walk-the-book: le notionnel dépasse le meilleur niveau


def test_l2_book_costs_empty_returns_none_never_invents():
    assert compute_book_costs([], [], 1_000.0) is None
    assert compute_book_costs([(100.0, 1.0)], [], 1_000.0) is None
    # ask < bid incohérent -> None
    assert compute_book_costs([(101.0, 1.0)], [(100.0, 1.0)], 1_000.0) is None
