from hl_observer.backtesting.hyperopt_local import HyperoptCandidate, hyperopt_local_only


def test_hyperopt_local_only_materializes_and_ranks_candidate():
    rows = hyperopt_local_only(
        [{"lookback": 3}],
        lambda params: (1.25, {"net_bps": float(params["lookback"])}),
        limit=1,
    )

    assert rows == [
        HyperoptCandidate(
            params={"lookback": 3},
            score=1.25,
            metrics={"net_bps": 3.0},
        )
    ]
