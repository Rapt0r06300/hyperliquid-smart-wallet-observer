from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from hyper_smart_observer.local_index.index_config import LocalIndexConfig
from hyper_smart_observer.local_index.query_engine import scan_wallet_index
from hyper_smart_observer.local_index.wallet_index import WalletLocalIndex, fake_wallet


@dataclass(slots=True)
class LocalIndexBenchmarkResult:
    wallets_requested: int
    wallets_indexed: int
    wallets_scanned: int
    elapsed_seconds: float
    wallets_per_second: float
    target_wallets_per_second: int
    target_met: bool
    network_used: bool
    stopped_reason: str


def run_local_scan_benchmark(wallets: int = 2_000, *, config: LocalIndexConfig | None = None) -> LocalIndexBenchmarkResult:
    cfg = config or LocalIndexConfig()
    count = max(0, int(wallets))
    index = WalletLocalIndex()
    start = perf_counter()
    for i in range(count):
        index.upsert(fake_wallet(i + 1))
    summary = scan_wallet_index(index, limit=count)
    elapsed = max(0.000001, perf_counter() - start)
    rate = summary.wallets_scanned / elapsed
    return LocalIndexBenchmarkResult(
        wallets_requested=count,
        wallets_indexed=len(index),
        wallets_scanned=summary.wallets_scanned,
        elapsed_seconds=round(elapsed, 6),
        wallets_per_second=round(rate, 3),
        target_wallets_per_second=cfg.target_wallets_per_second,
        target_met=rate >= cfg.target_wallets_per_second,
        network_used=False,
        stopped_reason="BENCHMARK_COMPLETE" if count else "NO_WALLETS_REQUESTED",
    )


def format_benchmark_report(result: LocalIndexBenchmarkResult) -> str:
    status = "PASS" if result.target_met else "WARN_TARGET_NOT_MET"
    return "\n".join(
        [
            "local_scan_benchmark=research_only_no_network",
            f"status={status}",
            f"wallets_requested={result.wallets_requested}",
            f"wallets_indexed={result.wallets_indexed}",
            f"wallets_scanned={result.wallets_scanned}",
            f"elapsed_seconds={result.elapsed_seconds}",
            f"wallets_per_second={result.wallets_per_second}",
            f"target_wallets_per_second={result.target_wallets_per_second}",
            f"network_used={str(result.network_used).lower()}",
            f"stopped_reason={result.stopped_reason}",
        ]
    )
