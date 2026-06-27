from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LocalIndexConfig:
    target_wallets_per_second: int = 2_000
    backend: str = "memory"
    allow_network: bool = False
    starting_equity_usdt: float = 1000.0
    max_position_notional_usdt: float = 50.0
    max_total_exposure_usdt: float = 200.0

