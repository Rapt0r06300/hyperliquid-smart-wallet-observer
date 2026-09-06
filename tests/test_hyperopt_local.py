from hl_observer.backtesting.hyperopt_local import hyperopt_local_only


def test_hyperopt_local_only_builds_and_ranks_candidates():
    candidates = [{"name": "slow"}, {"name": "fast"}]

    def objective(params):
        score = 2 if params["name"] == "fast" else 1
        return score, {"net_bps": score * 10}

    rows = hyperopt_local_only(candidates, objective, limit=1)

    assert len(rows) == 1
    assert rows[0].params == {"name": "fast"}
    assert rows[0].score == 2.0
    assert rows[0].metrics == {"net_bps": 20}
