"""[Bloc 47-49] Validation statistique anti-overfit."""
from hl_observer.hyperlab import validation as v


def test_cpcv_splits_purge():
    splits = v.cpcv_splits(5, 2, embargo=1)
    assert len(splits) == 10  # C(5,2)
    train, test = next(s for s in splits if s[1] == [1, 2])
    assert set(test).isdisjoint(train)
    assert 0 not in train and 3 not in train  # groupes adjacents purges


def test_pbo_bornes_et_sens():
    # IS-best est aussi le meilleur OOS -> surclasse mediane, pbo bas
    r = v.pbo([1, 2, 3], [1, 2, 3])
    assert r["config_is_best"] == 2 and r["surclasse_mediane"] and r["pbo"] == 0.0
    # IS-best est le pire OOS -> pbo eleve
    r2 = v.pbo([3, 2, 1], [1, 2, 3])
    assert r2["pbo"] > 0.5 and r2["surclasse_mediane"] is False


def test_deflated_sharpe_monotone():
    haut = v.deflated_sharpe(1.5, n_trials=5, T=250)["dsr"]
    bas = v.deflated_sharpe(0.0, n_trials=5, T=250)["dsr"]
    assert 0.0 <= bas <= 1.0 and 0.0 <= haut <= 1.0 and haut > bas


def test_spa_pvalue_edge_vs_bruit():
    edge = v.spa_pvalue([0.02, 0.015, 0.025, 0.02, 0.018, 0.022, 0.02, 0.019], n_boot=400, seed=0)
    nul = v.spa_pvalue([0.02, -0.02, 0.01, -0.015, 0.005, -0.01, 0.02, -0.02], n_boot=400, seed=0)
    assert edge["p_value"] < 0.1 and nul["p_value"] > edge["p_value"]


def test_placebo_detecte_signal_reel():
    sig = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    ret = [1.1, 1.9, 3.2, 3.8, 5.1, 6.2, 6.9, 8.1]  # tres correle
    r = v.placebo_pvalue(sig, ret, n_perm=300, seed=0)
    assert r["p_value"] < 0.05 and r["corr_obs"] > 0.9


def test_leave_one_group_out_et_ablation():
    loo = v.leave_one_group_out(["s1", "s1", "s2", "s3"])
    assert (("s1", ["s2", "s3"]) in loo) and len(loo) == 3
    assert v.ablation_marginale(1.2, 1.0)["garder"] is True
    assert v.ablation_marginale(1.0, 1.05)["garder"] is False
