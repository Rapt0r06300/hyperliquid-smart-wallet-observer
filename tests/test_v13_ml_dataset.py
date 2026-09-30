from hl_observer.ml.dataset import FeatureRow, Outcome, build_training_set, to_matrix


def _row(i, ts, ctx="LIVE", **feats):
    return FeatureRow(decision_id=str(i), ts_ms=ts, features=feats, context=ctx, side="LONG")


def test_join_labels_and_no_lookahead():
    rows = [
        _row(1, 1000, edge=20, liq=0.5),     # closes later, win
        _row(2, 2000, edge=8, liq=0.3),      # closes later, loss
        _row(3, 3000, edge=15, liq=0.4),     # NO outcome -> skipped
        _row(4, 4000, edge=30, liq=0.6),     # outcome BEFORE decision -> lookahead drop
    ]
    outcomes = [
        Outcome("1", 5000, 12.0),
        Outcome("2", 6000, -4.0),
        Outcome("4", 3500, 9.0),             # close_ts < decision ts -> invalid
    ]
    ds = build_training_set(rows, outcomes)
    assert ds["n"] == 2 and ds["n_win"] == 1 and ds["n_loss"] == 1
    assert ds["skipped_no_outcome"] == 1 and ds["skipped_lookahead"] == 1
    assert ds["feature_names"] == ["edge", "liq"]


def test_context_isolation():
    rows = [_row(1, 100, "LIVE", edge=20), _row(2, 100, "BACKTEST", edge=20)]
    outcomes = [Outcome("1", 200, 5.0), Outcome("2", 200, 5.0)]
    live = build_training_set(rows, outcomes, context="LIVE")
    assert live["n"] == 1 and live["skipped_context"] == 1


def test_to_matrix_ordering():
    rows = [_row(1, 100, edge=20, liq=0.5)]
    outcomes = [Outcome("1", 200, 3.0)]
    ds = build_training_set(rows, outcomes)
    X, y = to_matrix(ds["samples"], ds["feature_names"])
    assert X == [[20.0, 0.5]] and y == [1]


def test_empty_is_honest():
    ds = build_training_set([], [])
    assert ds["empty"] is True and ds["n"] == 0
