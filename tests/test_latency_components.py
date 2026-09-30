from hl_observer.simulation.latency_components import COMPOSANTES, decomposer_latence


def test_trois_composantes_sommees():
    r = decomposer_latence(feed_ms=10.0, order_ms=25.0, inter_leg_ms=5.0)
    assert r["total_ms"] == 40.0 and r["mesurable"] is True
    assert set(r["composantes"]) == set(COMPOSANTES)


def test_composante_manquante_unmeasurable_pas_zero():
    r = decomposer_latence(feed_ms=10.0, order_ms=None, inter_leg_ms=5.0)
    assert r["total_ms"] is None and "order_ms" in r["manquantes"] and r["mesurable"] is False
