from hl_observer.simulation.counterfactual_trade_replay import replay_contrefactuel_trade


def test_regret_positif_si_meilleure_sortie_ratee():
    r = replay_contrefactuel_trade(side=1, prix_entree=100.0, prix_sortie=105.0, notional_usd=100.0,
                                   chemin_prix=[100, 110, 105])
    assert r["pnl_reel"] == 5.0
    assert r["contrefactuels"]["meilleure_sortie"] == 10.0
    assert r["contrefactuels"]["ne_pas_entrer"] == 0.0
    assert r["regret"] == 5.0 and r["real_execution"] is False


def test_trade_parfait_regret_nul():
    r = replay_contrefactuel_trade(side=1, prix_entree=100.0, prix_sortie=110.0, notional_usd=100.0,
                                   chemin_prix=[100, 110])
    assert r["regret"] == 0.0


def test_short_direction():
    r = replay_contrefactuel_trade(side=-1, prix_entree=100.0, prix_sortie=95.0, notional_usd=100.0,
                                   chemin_prix=[100, 90, 95])
    assert r["pnl_reel"] == 5.0 and r["contrefactuels"]["meilleure_sortie"] == 10.0
