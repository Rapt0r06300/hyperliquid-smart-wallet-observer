from hl_observer.backtesting.experiment_harness import assess_parameter_neighbor_plateau


def test_plateau_compare_les_voisins_sur_le_meme_split_avec_ic():
    center = [
        {"episode_id": "e1", "net_usd": 10.0},
        {"episode_id": "e2", "net_usd": 11.0},
        {"episode_id": "e3", "net_usd": 9.0},
        {"episode_id": "e4", "net_usd": 10.0},
    ]
    neighbors = {
        "minus": [{"episode_id": f"e{i}", "net_usd": v} for i, v in enumerate((9.0, 10.0, 8.0, 10.0), 1)],
        "plus": [{"episode_id": f"e{i}", "net_usd": v} for i, v in enumerate((11.0, 12.0, 10.0, 11.0), 1)],
    }
    result = assess_parameter_neighbor_plateau(center, neighbors, n_bootstrap=200, seed=4)
    assert result["status"] == "PROVEN"
    assert result["same_split"] is True
    assert result["n_episodes"] == 4
    assert result["plateau"] is True
    assert all("delta_ci_low" in value for value in result["neighbors"].values())


def test_plateau_refuse_un_split_different_sans_faire_un_resultat():
    result = assess_parameter_neighbor_plateau(
        [{"episode_id": "e1", "net_usd": 3.0}, {"episode_id": "e2", "net_usd": 4.0}],
        {"near": [{"episode_id": "e1", "net_usd": 3.0}, {"episode_id": "other", "net_usd": 4.0}]},
        n_bootstrap=20,
    )
    assert result["status"] == "UNMEASURABLE"
    assert result["same_split"] is False
    assert result["plateau"] is False
