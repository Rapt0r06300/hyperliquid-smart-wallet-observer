"""Tests des modèles de régime."""
from __future__ import annotations

from hl_observer.backtesting.regime_models import fit_two_regimes, gaussian_hmm_viterbi


def test_viterbi_recovers_two_regimes():
    obs = [0.0] * 20 + [10.0] * 20                       # régime 0 puis régime 1
    means, stds = [0.0, 10.0], [1.0, 1.0]
    trans = [[0.95, 0.05], [0.05, 0.95]]
    init = [0.5, 0.5]
    path = gaussian_hmm_viterbi(obs, means, stds, trans, init)
    assert path[0] == 0 and path[-1] == 1
    assert sum(path[:20]) <= 2 and sum(path[20:]) >= 18   # majoritairement bon régime


def test_fit_two_regimes_splits_calm_and_volatile():
    returns = [0.001] * 30 + [0.05] * 30
    labels, (m0, m1) = fit_two_regimes(returns)
    assert m0 < m1                                        # 0 = calme, 1 = volatil
    assert sum(labels[:30]) <= 3 and sum(labels[30:]) >= 27
