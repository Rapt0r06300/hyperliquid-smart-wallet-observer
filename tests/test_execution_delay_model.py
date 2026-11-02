from hl_observer.backtesting.execution_delay_model import apply_execution_delay
import pytest


def test_execution_delay_model_adds_delay_ms():
    delayed = apply_execution_delay("e1", 1000, delay_seconds=10)
    assert delayed.effective_ts_ms == 11000
    assert delayed.delay_ms == 10000


@pytest.mark.parametrize(
    ("event_id", "ts_ms", "delay_seconds"),
    [
        ("", 1000, 0),
        ("e1", 0, 0),
        ("e1", True, 0),
        ("e1", 1000, -1),
        ("e1", 1000, float("nan")),
        ("e1", 1000, float("inf")),
    ],
)
def test_execution_delay_rejects_non_causal_inputs(event_id, ts_ms, delay_seconds):
    with pytest.raises(ValueError):
        apply_execution_delay(event_id, ts_ms, delay_seconds=delay_seconds)
