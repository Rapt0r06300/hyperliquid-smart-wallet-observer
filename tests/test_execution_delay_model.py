from hl_observer.backtesting.execution_delay_model import apply_execution_delay


def test_execution_delay_model_adds_delay_ms():
    delayed = apply_execution_delay("e1", 1000, delay_seconds=10)
    assert delayed.effective_ts_ms == 11000
    assert delayed.delay_ms == 10000
