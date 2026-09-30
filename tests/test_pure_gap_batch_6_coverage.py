from __future__ import annotations

import json

from hl_observer.backtest.monte_carlo import bootstrap_mean
from hl_observer.research.jsonl_stream import stream_jsonl
from hl_observer.simulation.funding_payment_tracker import compute_funding_payment_usdc


def test_bootstrap_mean_non_empty_path() -> None:
    assert bootstrap_mean([2.0, 4.0, 6.0]) == 4.0


def test_long_funding_pays_negative_normalized_payment() -> None:
    assert compute_funding_payment_usdc(
        side="long", notional_usdc=1_000.0, funding_rate=0.0001, intervals=2
    ) == -0.2


def test_stream_jsonl_stops_at_max_lignes(tmp_path) -> None:
    path = tmp_path / "sample.jsonl"
    path.write_text(
        "\n".join(json.dumps({"i": i}) for i in range(3)) + "\n",
        encoding="utf-8",
    )
    assert list(stream_jsonl(str(path), max_lignes=1)) == [{"i": 0}]
