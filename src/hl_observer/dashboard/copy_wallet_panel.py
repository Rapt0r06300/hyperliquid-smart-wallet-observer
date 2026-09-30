from __future__ import annotations

from typing import Any

from hl_observer.copy_wallet.wallet_mirror_runtime import MirrorPipelineResult


def build_copy_wallet_panel(results: list[MirrorPipelineResult]) -> dict[str, Any]:
    rows = [item.as_dict() for item in results]
    return {
        "title": "Wallet mirror paper decisions",
        "accepted": sum(1 for item in results if item.accepted),
        "no_trade": sum(1 for item in results if not item.accepted),
        "rows": rows,
        "paper_only": True,
        "real_execution": False,
    }


__all__ = ["build_copy_wallet_panel"]
