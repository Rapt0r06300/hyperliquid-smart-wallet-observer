"""[Bloc 36/53/54/41/42] Parite live/replay, coherence fast/exact, reconciliation 5 vues, cross-venue exec."""
from hl_observer.hyperlab import cross_venue_exec as cx
from hl_observer.hyperlab import replay_parite as rp


def _lignes():
    return [{"symbole": "BTCUSDT", "prix": 60000.0, "taille": 0.5},
            {"symbole": "ETHUSDT", "prix": 3000.0, "taille": 2.0}]


def test_parite_live_replay():
    lignes = _lignes()
    replayed = rp.rejouer(lambda x: dict(x), lignes)
    assert rp.parite_live_replay(lignes, replayed)["parite"] is True
    # une divergence -> detectee
    bad = rp.rejouer(lambda x: dict(x), lignes)
    bad[1]["prix"] = 9999.0
    assert rp.parite_live_replay(lignes, bad)["parite"] is False


def test_fast_exact_coherents():
    lignes = _lignes()
    coh = rp.coherence_fast_exact(rp.fast_screen(lignes), rp.exact_replay(lignes))
    assert coh["coherent"] is True and abs(coh["delta_notionnel"]) < 1e-9


def test_reconciliation_5_vues():
    assert rp.reconcilier_5_vues(1000, 1000, 1000, 1000, 1000)["coherent"] is True
    r = rp.reconcilier_5_vues(1000, 1000, 999.9, 1000, 1000)
    assert r["coherent"] is False and "store" in r["ecarts"]


def test_cross_venue_jambe_manquee_unwind():
    # jambe A remplie, jambe B timeout -> unwind A, residuel expose
    e = cx.executer_paire({"venue": "a", "symbole": "S", "side": "buy", "notionnel": 100.0},
                          {"venue": "b", "symbole": "S", "side": "sell", "notionnel": 100.0},
                          fill_a=100.0, fill_b=0.0, timeout_b=True)
    assert e["raison"] == "jambe_unique_unwind" and e["residual_risk_usd"] == 100.0
    assert e["expose_une_jambe"] is True


def test_cross_venue_paire_ok_et_partielle():
    ok = cx.executer_paire({"notionnel": 100.0, "venue": "a", "symbole": "S", "side": "buy"},
                           {"notionnel": 100.0, "venue": "b", "symbole": "S", "side": "sell"},
                           fill_a=100.0, fill_b=100.0)
    assert ok["raison"] == "apparie" and ok["residual_risk_usd"] == 0.0
    part = cx.executer_paire({"notionnel": 100.0, "venue": "a", "symbole": "S", "side": "buy"},
                             {"notionnel": 100.0, "venue": "b", "symbole": "S", "side": "sell"},
                             fill_a=100.0, fill_b=60.0)
    assert part["raison"] == "jambe_partielle" and part["residual_risk_usd"] == 40.0
