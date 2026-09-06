from hl_observer.modeling.ridge_regression import MIN_POINTS, ajuster_ridge


def test_ajuster_ridge_accepts_one_dimensional_feature_series() -> None:
    X = [float(i) for i in range(MIN_POINTS)]
    y = [2.0 * value + 3.0 for value in X]

    result = ajuster_ridge(X, y, alpha=1.0)

    assert result is not None
    coefs, intercept = result
    assert coefs.shape == (1,)
    assert isinstance(intercept, float)
