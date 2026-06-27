from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from hyper_smart_observer.scale.incremental_aggregator import IncrementalAggregator


@dataclass(slots=True)
class ScaleBenchmarkResult:
    wallets_requested: int
    events_requested: int
    wallets_aggregated: int
    events_processed: int
    elapsed_seconds: float
    events_per_second: float
    network_used: bool
    stopped_reason: str


def run_scale_benchmark(wallets: int = 14_000, events: int = 1_000_000) -> ScaleBenchmarkResult:
    wallet_count = max(1, int(wallets))
    event_count = max(0, int(events))
    aggregator = IncrementalAggregator()
    start = perf_counter()
    chunk: list[dict] = []
    for index in range(event_count):
        wallet_id = (index % wallet_count) + 1
        chunk.append(
            {
                "wallet": f"0x{wallet_id:040x}",
                "coin": ("BTC", "ETH", "SOL", "HYPE")[index % 4],
                "closed_pnl": float((index % 17) - 8),
                "notional": float((index % 50) + 1),
            }
        )
        if len(chunk) >= 10_000:
            aggregator.add_chunk(chunk)
            chunk = []
    if chunk:
        aggregator.add_chunk(chunk)
    elapsed = max(0.000001, perf_counter() - start)
    return ScaleBenchmarkResult(
        wallets_requested=wallet_count,
        events_requested=event_count,
        wallets_aggregated=len(aggregator.wallets),
        events_processed=sum(row.events for row in aggregator.wallets.values()),
        elapsed_seconds=round(elapsed, 6),
        events_per_second=round(event_count / elapsed, 3),
        network_used=False,
        stopped_reason="SCALE_BENCHMARK_COMPLETE",
    )


def format_scale_benchmark_report(result: ScaleBenchmarkResult) -> str:
    return "\n".join(
        [
            "scale_benchmark=local_synthetic_no_network",
            f"wallets_requested={result.wallets_requested}",
            f"events_requested={result.events_requested}",
            f"wallets_aggregated={result.wallets_aggregated}",
            f"events_processed={result.events_processed}",
            f"elapsed_seconds={result.elapsed_seconds}",
            f"events_per_second={result.events_per_second}",
            f"network_used={str(result.network_used).lower()}",
            f"stopped_reason={result.stopped_reason}",
        ]
    )
