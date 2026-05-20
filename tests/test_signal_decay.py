from hl_observer.edge.signal_decay import decay_edge, is_late_signal


def test_signal_decay_reduces_edge():
    assert decay_edge(20, signal_age_ms=1000, half_life_ms=1000) < 20


def test_late_signal_rejected():
    assert is_late_signal(signal_age_ms=4000, max_signal_age_ms=3500)
