from __future__ import annotations


def install_fast_scan_whale_patch() -> None:
    try:
        from hyper_smart_observer.dydx_v4.fast_scan_integration import FastScanIntegration
        from hyper_smart_observer.dydx_v4.whale_ranker import blended_whale_top, whale_stats
    except Exception:
        return
    if getattr(FastScanIntegration, "_whale_patch_installed", False):
        return

    def track_harvester_top(self, n=None):
        limit = n if n is not None else self.harvester.max_track
        pairs = blended_whale_top(self.harvester.index, limit=limit, whale_share=0.65)
        if not pairs:
            pairs = self.harvester.top_for_scanner(n=n)
        if pairs:
            self.scanner.track_wallets(pairs)
        return len(pairs)

    old_stats = FastScanIntegration.stats

    def stats(self):
        s = old_stats(self)
        try:
            s["whales"] = whale_stats(self.harvester.index)
            s["whale_priority_enabled"] = True
        except Exception:
            s["whale_priority_enabled"] = False
        return s

    FastScanIntegration.track_harvester_top = track_harvester_top
    FastScanIntegration.stats = stats
    FastScanIntegration._whale_patch_installed = True


install_fast_scan_whale_patch()


__all__ = ["install_fast_scan_whale_patch"]
