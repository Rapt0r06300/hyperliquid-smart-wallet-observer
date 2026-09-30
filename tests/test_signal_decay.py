from hl_observer.edge.signal_decay import decay_edge, is_late_signal


def test_signal_decay_reduces_edge():
    assert decay_edge(20, signal_age_ms=1000, half_life_ms=1000) < 20


def test_late_signal_rejected_custom_max():
    """Signal âgé de 4000 ms est rejeté quand max = 3500 ms."""
    assert is_late_signal(signal_age_ms=4000, max_signal_age_ms=3500)


def test_polling_signal_not_late():
    """Un signal de 5 minutes (300 000 ms) ne doit pas être tardif avec la limite polling de 10 min."""
    assert not is_late_signal(signal_age_ms=300_000, max_signal_age_ms=600_000)


def test_polling_signal_too_old():
    """Un signal de 15 minutes (900 000 ms) est bien tardif avec la limite polling de 10 min."""
    assert is_late_signal(signal_age_ms=900_000, max_signal_age_ms=600_000)

