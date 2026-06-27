from __future__ import annotations

from pathlib import Path

from hyper_smart_observer.hyperliquid_client.models import Wallet
from hyper_smart_observer.wallet_discovery.collector import collect_manual_wallets


def import_wallets_from_text(path: str | Path, *, source: str = "manual_file") -> list[Wallet]:
    file_path = Path(path)
    lines = [line.strip() for line in file_path.read_text(encoding="utf-8").splitlines()]
    return collect_manual_wallets(lines, source=source)
