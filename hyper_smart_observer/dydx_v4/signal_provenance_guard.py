from __future__ import annotations


def cluster_has_wallets(cluster) -> bool:
    wallets = getattr(cluster, "participating_wallets", None) or []
    if not isinstance(wallets, list):
        return False
    wallets = [w for w in wallets if isinstance(w, str) and w.strip()]
    if not wallets:
        return False
    cluster_id = str(getattr(cluster, "cluster_id", "") or "")
    if cluster_id.startswith("flow:"):
        return False
    return True


def install_signal_provenance_guard() -> None:
    try:
        from hyper_smart_observer.dydx_v4.live_observer import DydxLiveObserver
    except Exception:
        return
    if getattr(DydxLiveObserver, "_signal_provenance_guard_installed", False):
        return
    original = DydxLiveObserver._evaluate_cluster

    def wrapped(self, cluster):
        if not cluster_has_wallets(cluster):
            self._refuse("NO_REAL_WALLET_PROVENANCE")
            return None
        return original(self, cluster)

    DydxLiveObserver._evaluate_cluster = wrapped
    DydxLiveObserver._signal_provenance_guard_installed = True


install_signal_provenance_guard()


__all__ = ["cluster_has_wallets", "install_signal_provenance_guard"]
