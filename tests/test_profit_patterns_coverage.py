from hl_observer.analysis.profit_patterns import rank_profit_patterns


def test_rank_profit_patterns_empty_input_is_empty():
    assert rank_profit_patterns({}) == []
