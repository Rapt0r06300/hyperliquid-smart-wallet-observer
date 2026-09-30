"""Tests du garde anti-lookahead : passe pour une fonction honnête, lève pour une tricheuse."""
from __future__ import annotations

import pytest

from hl_observer.backtesting.lookahead_guard import LookaheadError, assert_no_lookahead


def honest_rolling_mean(series):
    out = []
    for i in range(len(series)):
        if i < 2:
            out.append(None)
        else:
            out.append((series[i] + series[i - 1] + series[i - 2]) / 3.0)
    return out


def cheating_uses_future_max(series):
    m = max(series)                      # utilise le MAXIMUM GLOBAL = le futur
    return [1 if v == m else 0 for v in series]


def test_honest_function_passes():
    series = [float(i) for i in range(60)]
    assert assert_no_lookahead(honest_rolling_mean, series) is True


def test_cheating_function_is_detected():
    series = [float(i) for i in range(60)]   # croissant -> le max global tombe à la fin
    with pytest.raises(LookaheadError):
        assert_no_lookahead(cheating_uses_future_max, series)
