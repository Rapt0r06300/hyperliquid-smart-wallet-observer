import math

from hl_observer.simulation.diagnostic_reports import build_profitability_diagnostics, format_diagnostic_report


def classify_profitability_measurement(net_pnl_usd: object) -> dict[str, object]:
    """Distinguish missing, measured zero and measured negative PnL."""
    if (
        isinstance(net_pnl_usd, bool)
        or not isinstance(net_pnl_usd, (int, float))
        or not math.isfinite(float(net_pnl_usd))
    ):
        return {"status": "MISSING", "reason": "NET_PNL_NOT_MEASURED", "paper_read_only": True}
    value = float(net_pnl_usd)
    status = "ZERO_MEASURED" if value == 0.0 else "NEGATIVE" if value < 0.0 else "POSITIVE"
    return {"status": status, "net_pnl_usd": value, "paper_read_only": True, "real_execution": False}

__all__ = ["build_profitability_diagnostics", "classify_profitability_measurement", "format_diagnostic_report"]
