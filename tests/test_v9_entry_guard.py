from hl_observer.risk.entry_guard import (
    EntryGuardConfig,
    evaluate_entry,
    evaluate_entry_from_components,
)
from hl_observer.risk.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, TradeOutcome


def test_all_clear_allows():
    d = evaluate_entry(now_sec=0, leader_qualified=True, edge_remaining_bps=20.0)
    assert d.allow
    assert d.reasons == ()
    assert not d.blocked


def test_circuit_breaker_blocks():
    d = evaluate_entry(now_sec=0, circuit_tripped=True, leader_qualified=True, edge_remaining_bps=20.0)
    assert d.blocked
    assert "CIRCUIT_BREAKER_TRIPPED" in d.reasons


def test_leader_not_smart_money_blocks_when_required():
    d = evaluate_entry(now_sec=0, leader_qualified=False, edge_remaining_bps=20.0)
    assert d.blocked
    assert "LEADER_NOT_SMART_MONEY" in d.reasons


def test_leader_quality_optional():
    cfg = EntryGuardConfig(require_leader_quality=False)
    d = evaluate_entry(now_sec=0, leader_qualified=False, edge_remaining_bps=20.0, config=cfg)
    assert d.allow


def test_unknown_leader_quality_does_not_block():
    # None = unknown (warmup) -> not a hard block
    d = evaluate_entry(now_sec=0, leader_qualified=None, edge_remaining_bps=20.0)
    assert d.allow


def test_low_edge_blocks():
    d = evaluate_entry(now_sec=0, leader_qualified=True, edge_remaining_bps=4.0)
    assert d.blocked
    assert "EDGE_REMAINING_TOO_LOW" in d.reasons


def test_exec_reasons_propagated():
    d = evaluate_entry(now_sec=0, leader_qualified=True, edge_remaining_bps=20.0,
                       exec_blocked=True, exec_reasons=("DEPTH_TOO_LOW", "SPREAD_TOO_WIDE"))
    assert d.blocked
    assert "DEPTH_TOO_LOW" in d.reasons and "SPREAD_TOO_WIDE" in d.reasons


def test_reasons_deduped_and_ordered():
    d = evaluate_entry(now_sec=0, circuit_tripped=True, leader_qualified=False,
                       edge_remaining_bps=1.0, exec_blocked=True,
                       exec_reasons=("CIRCUIT_BREAKER_TRIPPED",))  # duplicate on purpose
    assert d.reasons[0] == "CIRCUIT_BREAKER_TRIPPED"
    assert len(d.reasons) == len(set(d.reasons))


def test_from_components_with_live_circuit_breaker():
    cb = CircuitBreaker(CircuitBreakerConfig(max_consecutive_losses=2, cooldown_sec=600))
    cb.record(TradeOutcome(0, -1.0))
    cb.record(TradeOutcome(1, -1.0))  # trips
    d = evaluate_entry_from_components(now_sec=2, circuit_breaker=cb, edge_remaining_bps=50.0)
    assert d.blocked
    assert "CIRCUIT_BREAKER_TRIPPED" in d.reasons


def test_from_components_clear():
    cb = CircuitBreaker()

    class _LQ:
        qualified = True

    class _EG:
        blocked = False
        reasons = ()

    d = evaluate_entry_from_components(
        now_sec=10, circuit_breaker=cb, leader_quality=_LQ(), exec_gate_result=_EG(),
        edge_remaining_bps=15.0,
    )
    assert d.allow


def test_guard_has_no_execution_surface():
    import hl_observer.risk.entry_guard as m
    public = {n for n in dir(m) if not n.startswith("_")}
    for forbidden in ("submit", "place_order", "sign", "send_order", "execute"):
        assert not any(forbidden in name.lower() for name in public)
