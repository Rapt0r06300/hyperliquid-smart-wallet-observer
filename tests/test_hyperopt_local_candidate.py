from hl_observer.backtesting.hyperopt_local import HyperoptCandidate, hyperopt_local_only


def test_hyperopt_local_builds_ranked_candidate_with_metrics() -> None:
    rows = hyperopt_local_only(
        [{"window": 7}],
        lambda params: (2.5, {"net_bps": float(params["window"])}),
        limit=1,
    )

    assert rows == [
        HyperoptCandidate(
            params={"window": 7},
            score=2.5,
            metrics={"net_bps": 7.0},
        )
    ]
