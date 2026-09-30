from __future__ import annotations

from typing import Any


def build_funding_panel(signals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = list(signals or [])
    return {
        "title": "Funding paper signals",
        "rows": rows,
        "count": len(rows),
        "paper_only": True,
        "real_execution": False,
    }


__all__ = ["build_funding_panel"]
