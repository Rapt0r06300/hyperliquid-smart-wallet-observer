from __future__ import annotations


def build_paper_report(order_count: int, rejected_count: int) -> dict[str, int]:
    return {"paper_orders": order_count, "rejected": rejected_count}
