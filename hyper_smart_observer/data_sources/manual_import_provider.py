from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hyper_smart_observer.wallet_universe.wallet_universe import WalletUniverseImportResult, import_wallet_universe_file


@dataclass(slots=True)
class ManualImportProvider:
    name: str = "ManualImportProvider"
    enabled_by_default: bool = True
    requires_network: bool = False
    requires_api_key: bool = False

    def import_wallets(self, path: Path) -> WalletUniverseImportResult:
        return import_wallet_universe_file(path, source="manual_import")
