"""Chart series builders (V12, repo 14 — TradingView lightweight-charts feed).

Transforms REAL observed/paper data into the {time, value} arrays consumed by
lightweight-charts on the frontend. Hard rule: **no fake points** — empty input
yields an empty series, never an invented one. Pure / deterministic / read-only.
"""

from __future__ import annotations


def _sorted_unique_by_time(points: list[dict]) -> list[dict]:
    """Sort by time and dedupe (last write wins) — lightweight-charts requires strictly increasing time."""
    by_time: dict[int, dict] = {}
    for p in points:
        if p.get("time") is None:
            continue
        by_time[int(p["time"])] = p
    return [by_time[t] for t in sorted(by_time)]


def build_equity_series(points: list[dict]) -> list[dict]:
    """[{time, equity}] -> [{time, value}]. Empty in -> empty out."""
    return [{"time": int(p["time"]), "value": float(p["equity"])}
            for p in _sorted_unique_by_time(points) if "equity" in p]


def build_drawdown_series(equity_points: list[dict]) -> list[dict]:
    """Running drawdown (<=0) from an equity series. No fabricated baseline."""
    out: list[dict] = []
    peak: float | None = None
    for p in _sorted_unique_by_time(equity_points):
        if "equity" not in p:
            continue
        eq = float(p["equity"])
        peak = eq if peak is None else max(peak, eq)
        dd = 0.0 if peak <= 0 else (eq - peak) / peak * 100.0
        out.append({"time": int(p["time"]), "value": round(dd, 6)})
    return out


def build_candle_series(ohlc: list[dict]) -> list[dict]:
    """[{time,open,high,low,close}] passthrough with sort/dedupe + type coercion."""
    out: list[dict] = []
    for p in _sorted_unique_by_time(ohlc):
        if not all(k in p for k in ("open", "high", "low", "close")):
            continue
        out.append({"time": int(p["time"]), "open": float(p["open"]), "high": float(p["high"]),
                    "low": float(p["low"]), "close": float(p["close"])})
    return out


def build_line_series(points: list[dict], value_key: str) -> list[dict]:
    """Generic line series for edge / liquidity / source-latency panels."""
    return [{"time": int(p["time"]), "value": float(p[value_key])}
            for p in _sorted_unique_by_time(points) if value_key in p]


def build_edge_series(points: list[dict]) -> list[dict]:
    return build_line_series(points, "edge_bps")


def build_liquidity_series(points: list[dict]) -> list[dict]:
    return build_line_series(points, "liquidity_score")


def build_source_latency_series(points: list[dict]) -> list[dict]:
    return build_line_series(points, "latency_ms")


def build_position_markers(positions: list[dict]) -> list[dict]:
    """Entry/exit markers from REAL paper positions (lightweight-charts marker shape)."""
    markers: list[dict] = []
    for p in positions:
        if p.get("time") is None:
            continue
        is_long = str(p.get("side", "")).upper() == "LONG"
        is_open = str(p.get("action", "")).upper() in {"OPEN", "ADD"}
        markers.append({
            "time": int(p["time"]),
            "position": "belowBar" if is_long else "aboveBar",
            "color": "#26a69a" if is_open else "#ef5350",
            "shape": "arrowUp" if is_long else "arrowDown",
            "text": f"{p.get('action', '')} {p.get('coin', '')}".strip(),
        })
    return sorted(markers, key=lambda m: m["time"])


def build_no_trade_markers(no_trades: list[dict]) -> list[dict]:
    """NO_TRADE reason markers — only for events that actually occurred."""
    markers: list[dict] = []
    for n in no_trades:
        if n.get("time") is None:
            continue
        markers.append({"time": int(n["time"]), "position": "inBar", "color": "#b0b0b0",
                        "shape": "circle", "text": str(n.get("code", "NO_TRADE"))})
    return sorted(markers, key=lambda m: m["time"])


def incremental_update(series: list[dict], new_point: dict) -> list[dict]:
    """Append-only update with time-dedupe (lightweight-charts `series.update()` semantics)."""
    if new_point.get("time") is None:
        return series
    t = int(new_point["time"])
    out = [p for p in series if int(p["time"]) != t]
    out.append({**new_point, "time": t})
    return sorted(out, key=lambda p: int(p["time"]))


__all__ = [
    "build_equity_series", "build_drawdown_series", "build_candle_series", "build_line_series",
    "build_edge_series", "build_liquidity_series", "build_source_latency_series",
    "build_position_markers", "build_no_trade_markers", "incremental_update",
]
