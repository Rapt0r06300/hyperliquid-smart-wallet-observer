from hl_observer.risk.partial_fill_pair_guard import guard_partial_fill_pair


def test_partial_fill_pair_guard_blocks_one_weak_leg():
    result = guard_partial_fill_pair(leg_a_ratio=1.0, leg_b_ratio=0.4)
    assert result.blocked is True
    assert result.reason == "PARTIAL_PAIR_FILL"
