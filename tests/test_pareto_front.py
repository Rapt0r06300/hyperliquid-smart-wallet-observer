from hl_observer.backtesting.pareto_front import front_pareto


def test_front_non_domine():
    pts = [
        {"n": "A", "pnl": 10.0, "sharpe": 1.0},
        {"n": "B", "pnl": 8.0, "sharpe": 2.0},
        {"n": "C", "pnl": 5.0, "sharpe": 0.5},   # domine par A et B
    ]
    front = {p["n"] for p in front_pareto(pts, objectifs=["pnl", "sharpe"])}
    assert front == {"A", "B"}


def test_point_unique_est_son_propre_front():
    assert len(front_pareto([{"pnl": 1.0, "sharpe": 1.0}], objectifs=["pnl", "sharpe"])) == 1
