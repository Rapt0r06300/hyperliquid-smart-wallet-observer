from __future__ import annotations


def reconciliation_ok(open_order_seen: bool, fill_seen: bool) -> bool:
    return open_order_seen or fill_seen
