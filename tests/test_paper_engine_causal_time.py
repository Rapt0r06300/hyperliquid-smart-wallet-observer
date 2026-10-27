from __future__ import annotations

import pytest

from hl_observer.paper_trading.paper_engine import PaperEngine


def test_mark_to_market_requires_an_explicit_observation_timestamp() -> None:
    engine = PaperEngine()

    with pytest.raises(TypeError):
        engine.mark_to_market({})


def test_mark_to_market_rejects_nonpositive_or_boolean_timestamps() -> None:
    engine = PaperEngine()

    for timestamp in (0, -1, True):
        with pytest.raises(ValueError, match="explicit positive causal timestamp"):
            engine.mark_to_market({}, timestamp_ms=timestamp)
