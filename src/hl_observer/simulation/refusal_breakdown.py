from collections.abc import Mapping, Sequence
import math

from hl_observer.simulation.diagnostic_reports import build_refusal_breakdown, format_diagnostic_report


def compare_refusal_scenarios(
    scenarios: Sequence[Mapping[str, object]],
    *,
    certified_pnl: object | None = None,
) -> dict[str, object]:
    """Compare NO_TRADE reasons while keeping certified PnL separate."""
    rows: list[dict[str, object]] = []
    for scenario in scenarios:
        name = str(scenario.get("name") or "").strip()
        counts = scenario.get("no_trade_counts")
        if not name or not isinstance(counts, Mapping):
            return {"status": "UNMEASURABLE", "reason": "INVALID_SCENARIO", "paper_read_only": True}
        normalized: dict[str, int] = {}
        for key, value in counts.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return {"status": "UNMEASURABLE", "reason": "INVALID_REFUSAL_COUNT", "paper_read_only": True}
            normalized[str(key)] = value
        rows.append({"name": name, "no_trade_counts": normalized, "total_refusals": sum(normalized.values())})
    pnl_is_separate = certified_pnl is None or (
        isinstance(certified_pnl, (int, float))
        and not isinstance(certified_pnl, bool)
        and math.isfinite(float(certified_pnl))
    )
    return {
        "status": "PROVEN" if rows and pnl_is_separate else "UNMEASURABLE",
        "scenarios": rows,
        "certified_pnl_separate": True,
        "certified_pnl": certified_pnl if pnl_is_separate else None,
        "paper_read_only": True,
        "real_execution": False,
    }

__all__ = ["build_refusal_breakdown", "compare_refusal_scenarios", "format_diagnostic_report"]
