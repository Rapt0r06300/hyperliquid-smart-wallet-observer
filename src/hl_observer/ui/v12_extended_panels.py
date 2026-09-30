"""Extended read-only V12 dashboard panels (V10.9): copy fidelity, execution quality,
cluster detector, proxy health, rate budget.

Pure payload builders fed by data the runtime already has. Every panel has an HONEST
empty state — when a subsystem is inactive or has no samples, the panel says so and
invents nothing. Read-only: no order, no money, no fabrication.
"""

from __future__ import annotations

from hl_observer.copy_fidelity.tracking_error import CopyTrade, tracking_error


def build_copy_fidelity_panel(copy_trades: list[dict] | None) -> dict:
    """Copy fidelity / tracking error from REAL leader-vs-copy fills. Empty if none."""
    trades: list[CopyTrade] = []
    for t in copy_trades or []:
        try:
            trades.append(CopyTrade(
                side=str(t["side"]),
                leader_price=float(t["leader_price"]),
                copy_price=float(t["copy_price"]),
                leader_ts_ms=t.get("leader_ts_ms"),
                copy_ts_ms=t.get("copy_ts_ms"),
                leader_size=t.get("leader_size"),
                copy_size=t.get("copy_size"),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    te = tracking_error(trades)
    return {
        "samples": te.samples,
        "rms_gap_bps": None if te.rms_gap_bps is None else round(te.rms_gap_bps, 4),
        "mean_gap_bps": None if te.mean_gap_bps is None else round(te.mean_gap_bps, 4),
        "mean_lag_ms": None if te.mean_lag_ms is None else round(te.mean_lag_ms, 1),
        "empty": te.samples == 0,
    }


def build_cluster_panel(clusters: list[dict] | None) -> dict:
    """Consensus-cluster summary. Empty when no multi-wallet cluster was detected."""
    rows = [c for c in (clusters or []) if int(c.get("wallets", 0)) >= 2]
    return {
        "clusters": [
            {"cluster_id": str(c.get("cluster_id", "?")),
             "wallets": int(c.get("wallets", 0)),
             "notional_usdc": round(float(c.get("notional_usdc", 0.0)), 2)}
            for c in rows
        ],
        "count": len(rows),
        "empty": not rows,
    }


def build_proxy_health_panel(proxy_rows: list[dict] | None) -> dict:
    """Proxy-pool health. Empty when the proxy pool is disabled / has no members."""
    rows = proxy_rows or []
    healthy = sum(1 for p in rows if p.get("ok"))
    return {
        "proxies": [
            {"proxy": str(p.get("proxy", "?")), "ok": bool(p.get("ok")),
             "latency_ms": p.get("latency_ms")}
            for p in rows
        ],
        "total": len(rows),
        "healthy": healthy,
        "empty": not rows,
    }


def build_rate_budget_panel(*, used: float | None, limit: float | None, window_s: int | None) -> dict:
    """Rate-limit budget. Empty when no limit is configured (honest 'unknown')."""
    if limit is None or limit <= 0:
        return {"used": used, "limit": limit, "remaining": None, "pct_used": None,
                "window_s": window_s, "empty": True}
    used_v = float(used or 0.0)
    remaining = max(0.0, float(limit) - used_v)
    return {
        "used": round(used_v, 3),
        "limit": round(float(limit), 3),
        "remaining": round(remaining, 3),
        "pct_used": round(used_v / float(limit) * 100.0, 2),
        "window_s": window_s,
        "empty": False,
    }


def build_extended_panels(
    *,
    copy_trades: list[dict] | None = None,
    clusters: list[dict] | None = None,
    proxy_rows: list[dict] | None = None,
    rate_used: float | None = None,
    rate_limit: float | None = None,
    rate_window_s: int | None = None,
) -> dict:
    return {
        "copy_fidelity": build_copy_fidelity_panel(copy_trades),
        "cluster_detector": build_cluster_panel(clusters),
        "proxy_health": build_proxy_health_panel(proxy_rows),
        "rate_budget": build_rate_budget_panel(used=rate_used, limit=rate_limit, window_s=rate_window_s),
    }


__all__ = [
    "build_copy_fidelity_panel", "build_cluster_panel", "build_proxy_health_panel",
    "build_rate_budget_panel", "build_extended_panels",
]
