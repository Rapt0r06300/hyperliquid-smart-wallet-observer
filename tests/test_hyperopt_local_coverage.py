from hl_observer.backtesting.hyperopt_local import hyperopt_local_only


def test_hyperopt_local_only_scores_and_ranks_nonempty_candidates() -> None:
    candidates = [{"name": "slow", "edge": 1}, {"name": "fast", "edge": 2}]

    def objective(params: dict[str, object]) -> tuple[float, dict[str, float]]:
        edge = float(params["edge"])
        return edge, {"net_edge": edge - 0.25}

    ranked = hyperopt_local_only(candidates, objective, limit=1)

    assert len(ranked) == 1
    assert ranked[0].params == {"name": "fast", "edge": 2}
    assert ranked[0].score == 2.0
    assert ranked[0].metrics == {"net_edge": 1.75}
