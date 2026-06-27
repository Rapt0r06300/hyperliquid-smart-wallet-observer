from __future__ import annotations

WIDE_TRACK_TARGET = 15000
HOT_WALLET_TARGET = 2500
SUBACCOUNT_DEPTH = 4
DECISION_WALLET_TARGET = 3000
REST_POLL_TARGET = 250


def install_leaderboard_import_patch() -> None:
    try:
        from hyper_smart_observer.dydx_v4.fast_scan_integration import FastScanIntegration
        from hyper_smart_observer.dydx_v4.leaderboard_import import leaderboard_file_source
        from hyper_smart_observer.dydx_v4.live_observer import DydxLiveObserver
        from hyper_smart_observer.dydx_v4.wallet_discovery import WalletScore
    except Exception:
        return
    if getattr(FastScanIntegration, "_leaderboard_import_patch_installed", False):
        return
    original_init = FastScanIntegration.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        try:
            self.harvester.max_track = max(int(getattr(self.harvester, "max_track", 0) or 0), WIDE_TRACK_TARGET)
            self.scanner.hot.capacity = max(int(getattr(self.scanner.hot, "capacity", 0) or 0), HOT_WALLET_TARGET)
            old_sub = self.scanner._subscribe
            old_unsub = self.scanner._unsubscribe

            def many_sub(address: str, subaccount_number: int = 0) -> None:
                if self.scanner.ws is None:
                    return old_sub(address, subaccount_number)
                for sub in range(SUBACCOUNT_DEPTH):
                    try:
                        self.scanner.ws.subscribe_subaccount(address, sub)
                    except Exception:
                        continue

            def many_unsub(address: str) -> None:
                if self.scanner.ws is None:
                    return old_unsub(address)
                for sub in range(SUBACCOUNT_DEPTH):
                    try:
                        if hasattr(self.scanner.ws, "unsubscribe_subaccount"):
                            self.scanner.ws.unsubscribe_subaccount(address, sub)
                    except Exception:
                        continue

            self.scanner._subscribe = many_sub
            self.scanner._unsubscribe = many_unsub
            names = {getattr(src, "name", "") for src in getattr(self.harvester, "_sources", [])}
            if "local_leaderboard_import" not in names:
                self.harvester.add_source(leaderboard_file_source())
        except Exception:
            pass

    def fast_scan_exact_subaccounts(self) -> None:
        if self.fast_scan is None:
            return
        try:
            fills = self.fast_scan.scanner.drain_fresh(limit=2000)
        except Exception:
            return
        seen = set()
        for fill in fills:
            addr = getattr(fill, "address", None)
            if not isinstance(addr, str) or not addr:
                continue
            sub = int(getattr(fill, "subaccount_number", 0) or 0)
            key = (addr, sub)
            if key in seen:
                continue
            seen.add(key)
            self._poll_one_wallet(WalletScore(address=addr, subaccount_number=sub, source="fast_scan_subaccount"))

    old_merge = getattr(DydxLiveObserver, "_merge_harvester_into_shortlist", None)

    def merge_more_wallets(self) -> None:
        if self.fast_scan is None:
            if callable(old_merge):
                return old_merge(self)
            return None
        try:
            self.config.rest_poll_cap = max(int(getattr(self.config, "rest_poll_cap", 0) or 0), REST_POLL_TARGET)
        except Exception:
            pass
        if callable(old_merge):
            return old_merge(self)
        return None

    FastScanIntegration.__init__ = patched_init
    FastScanIntegration._leaderboard_import_patch_installed = True
    if not getattr(DydxLiveObserver, "_exact_subaccount_scan_installed", False):
        DydxLiveObserver._poll_priority_wallets = fast_scan_exact_subaccounts
        DydxLiveObserver._exact_subaccount_scan_installed = True
    if not getattr(DydxLiveObserver, "_wide_decision_merge_installed", False):
        DydxLiveObserver._merge_harvester_into_shortlist = merge_more_wallets
        DydxLiveObserver._wide_decision_merge_installed = True


install_leaderboard_import_patch()


__all__ = [
    "DECISION_WALLET_TARGET",
    "HOT_WALLET_TARGET",
    "REST_POLL_TARGET",
    "SUBACCOUNT_DEPTH",
    "WIDE_TRACK_TARGET",
    "install_leaderboard_import_patch",
]
