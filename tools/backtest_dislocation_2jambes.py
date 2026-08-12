"""Causal two-leg paper replay for Hyperliquid/Binance dislocations.

The module is intentionally read-only.  It consumes locally recorded BBO
events, waits for the configured execution latency, crosses the executable
bid/ask on both venues at entry and exit, and reports every cost component it
can actually measure.  Depth/slippage cannot be inferred from BBO alone, so a
BBO-only result is never labelled ``LIQUIDATABLE_NET``.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

SEUIL_ENTREE_BPS = 15.0
SEUIL_SORTIE_BPS = 3.0
STOP_AGGRAVATION_BPS = 25.0
HORIZON_MAX_S = 4 * 3600.0
FRAICHEUR_MAX_MS = 3000.0
LATENCE_MS = 400.0
FEES_AR_BPS = 16.0
ECART_MAX_ENTREE_BPS = 100.0
NOTIONAL_USD = 15.0

COINS_COMMUNS = ("BTC", "ETH", "SOL", "AVAX", "INJ", "DASH", "NEO", "LINK", "AAVE", "ONDO")


def _basis_bps(hl, bn):
    """Return ``mid_HL - mid_BIN`` in basis points."""
    mh = 0.5 * (hl[1] + hl[2])
    mb = 0.5 * (bn[1] + bn[2])
    if mh <= 0 or mb <= 0:
        return None
    return (mh - mb) / (0.5 * (mh + mb)) * 1e4


def _net_trade_bps(hl_in, bn_in, hl_out, bn_out, *, sens: int, fees_ar_bps: float) -> float:
    """Executable two-leg/four-fill return, including configured fees."""
    hb_i, ha_i = hl_in[1], hl_in[2]
    bb_i, ba_i = bn_in[1], bn_in[2]
    hb_o, ha_o = hl_out[1], hl_out[2]
    bb_o, ba_o = bn_out[1], bn_out[2]
    if sens > 0:
        pnl_hl = (hb_i - ha_o) / hb_i
        pnl_bin = (bb_o - ba_i) / ba_i
    else:
        pnl_hl = (hb_o - ha_i) / ha_i
        pnl_bin = (bb_i - ba_o) / bb_i
    return (pnl_hl + pnl_bin) * 1e4 - fees_ar_bps


def _mid_trade_bps(hl_in, bn_in, hl_out, bn_out, *, sens: int) -> float:
    """Gross two-leg return at mids, used only for cost reconciliation."""
    hm_i = 0.5 * (hl_in[1] + hl_in[2])
    bm_i = 0.5 * (bn_in[1] + bn_in[2])
    hm_o = 0.5 * (hl_out[1] + hl_out[2])
    bm_o = 0.5 * (bn_out[1] + bn_out[2])
    if sens > 0:
        return ((hm_i - hm_o) / hm_i + (bm_o - bm_i) / bm_i) * 1e4
    return ((hm_o - hm_i) / hm_i + (bm_i - bm_o) / bm_i) * 1e4


def _trade_id(*, coin: str, ts_detect: float, ts_in: float, ts_out: float, sens: int) -> str:
    identity = f"{coin}|{ts_detect:.3f}|{ts_in:.3f}|{ts_out:.3f}|{sens}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def backtester(
    series: dict,
    *,
    seuil_entree=SEUIL_ENTREE_BPS,
    seuil_sortie=SEUIL_SORTIE_BPS,
    stop_bps=STOP_AGGRAVATION_BPS,
    horizon_s=HORIZON_MAX_S,
    fraicheur_ms=FRAICHEUR_MAX_MS,
    latence_ms=LATENCE_MS,
    fees_ar_bps=FEES_AR_BPS,
    ecart_max=ECART_MAX_ENTREE_BPS,
) -> list[dict]:
    """Replay causally: detect, wait, execute, then close on a later quote."""
    trades: list[dict] = []
    for coin, raw_events in series.items():
        if str(coin).startswith("_"):
            continue
        events = sorted(raw_events, key=lambda event: event[0])
        latest = {"HL": None, "BIN": None}
        pending = None
        position = None
        for ts, venue, bid, ask in events:
            if venue not in latest:
                continue
            latest[venue] = (ts, bid, ask)
            hl, bn = latest["HL"], latest["BIN"]
            if hl is None or bn is None:
                continue
            if ts - hl[0] > fraicheur_ms or ts - bn[0] > fraicheur_ms:
                continue
            basis = _basis_bps(hl, bn)
            if basis is None:
                continue

            if position is None:
                if pending is not None:
                    if ts < pending["execute_after_ms"]:
                        continue
                    same_direction = (1 if basis > 0 else -1) == pending["sens"]
                    still_executable = seuil_entree <= abs(basis) <= ecart_max
                    if not (same_direction and still_executable):
                        pending = None
                        continue
                    position = {
                        "ts_detect": pending["ts_detect"],
                        "basis_detect": pending["basis_detect"],
                        "hl_detect": pending["hl_detect"],
                        "bn_detect": pending["bn_detect"],
                        "ts_in": ts,
                        "basis_in": basis,
                        "sens": pending["sens"],
                        "hl_in": hl,
                        "bn_in": bn,
                    }
                    pending = None
                    continue
                if seuil_entree <= abs(basis) <= ecart_max:
                    pending = {
                        "ts_detect": ts,
                        "execute_after_ms": ts + max(0.0, float(latence_ms)),
                        "basis_detect": basis,
                        "sens": 1 if basis > 0 else -1,
                        "hl_detect": hl,
                        "bn_detect": bn,
                    }
                continue

            age_s = (ts - position["ts_in"]) / 1000.0
            converged = abs(basis) <= seuil_sortie
            expired = age_s >= horizon_s
            stopped = abs(basis) >= abs(position["basis_in"]) + stop_bps
            if not (converged or expired or stopped):
                continue

            executable_before_fees = _net_trade_bps(
                position["hl_in"], position["bn_in"], hl, bn,
                sens=position["sens"], fees_ar_bps=0.0,
            )
            gross_at_detection = _mid_trade_bps(
                position["hl_detect"], position["bn_detect"], hl, bn,
                sens=position["sens"],
            )
            gross_at_entry = _mid_trade_bps(
                position["hl_in"], position["bn_in"], hl, bn,
                sens=position["sens"],
            )
            latency_cost = gross_at_detection - gross_at_entry
            spread_cost = gross_at_entry - executable_before_fees
            net = executable_before_fees - float(fees_ar_bps)
            trade_id = _trade_id(
                coin=str(coin), ts_detect=position["ts_detect"],
                ts_in=position["ts_in"], ts_out=ts, sens=position["sens"],
            )
            trades.append({
                "trade_id": trade_id,
                "coin": coin,
                "ts_detect": position["ts_detect"],
                "ts_in": position["ts_in"],
                "ts_out": ts,
                "age_s": round(age_s, 1),
                "basis_detect_bps": round(position["basis_detect"], 4),
                "basis_in_bps": round(position["basis_in"], 4),
                "basis_out_bps": round(basis, 4),
                "gross_signal_bps": round(gross_at_detection, 4),
                "gross_entry_bps": round(gross_at_entry, 4),
                "fees_bps": round(float(fees_ar_bps), 4),
                "spread_cost_bps": round(spread_cost, 4),
                "slippage_bps": None,
                "latency_cost_bps": round(latency_cost, 4),
                "net_bps": round(net, 4),
                "net_usd": round(net / 1e4 * NOTIONAL_USD, 6),
                "two_leg": True,
                "LIQUIDATABLE_NET": False,
                "sortie": "CONVERGENCE" if converged else ("STOP" if stopped else "AGE"),
            })
            position = None
    return trades


def _pf(nets):
    positive = sum(value for value in nets if value > 0)
    negative = sum(-value for value in nets if value < 0)
    return round(positive / negative, 3) if negative > 0 else (float("inf") if positive > 0 else 0.0)


def _dd_usd(trades):
    cumulative = peak = 0.0
    drawdown = 0.0
    for trade in sorted(trades, key=lambda value: value["ts_out"]):
        cumulative += trade["net_usd"]
        peak = max(peak, cumulative)
        drawdown = min(drawdown, cumulative - peak)
    return round(drawdown, 6)


def _summary(trades: list[dict]) -> dict:
    count = len(trades)
    ids = sorted({str(trade.get("trade_id")) for trade in trades if trade.get("trade_id")})
    net = sum(float(trade.get("net_usd") or 0.0) for trade in trades)
    return {
        "n_trades": count,
        "positions_ouvertes": count,
        "positions_fermees": count,
        "gross_pnl_usd": round(sum(float(t.get("gross_signal_bps") or 0.0) / 1e4 * NOTIONAL_USD for t in trades), 6),
        "fees_usd": round(sum(float(t.get("fees_bps") or 0.0) / 1e4 * NOTIONAL_USD for t in trades), 6),
        "spread_cost_usd": round(sum(float(t.get("spread_cost_bps") or 0.0) / 1e4 * NOTIONAL_USD for t in trades), 6),
        "slippage_cost_usd": None,
        "latency_cost_usd": round(sum(float(t.get("latency_cost_bps") or 0.0) / 1e4 * NOTIONAL_USD for t in trades), 6),
        "net_total_usd": round(net, 6),
        "roi_pct": round(net / 1000.0 * 100.0, 6),
        "hit_rate": round(sum(1 for t in trades if float(t.get("net_usd") or 0.0) > 0) / count, 6) if count else 0.0,
        "profit_factor": _pf([float(t.get("net_bps") or 0.0) for t in trades]),
        "max_drawdown_usd": abs(_dd_usd(trades)),
        "trade_ids_count": len(ids),
        "trade_ids_sha256": hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest(),
        "duplicate_trade_ids": count - len(ids),
        "LIQUIDATABLE_NET": bool(count and all(t.get("LIQUIDATABLE_NET") is True for t in trades)),
        "all_positions_two_leg_closed": bool(count and all(t.get("two_leg") is True for t in trades)),
    }


def juger(trades: list[dict]) -> dict:
    count = len(trades)
    summary = _summary(trades)
    if count < 8:
        return {**summary, "verdict": "INSUFFISANT", "motif": "moins de 8 trades fermes"}
    nets = [trade["net_bps"] for trade in trades]
    ordered = sorted(trades, key=lambda trade: trade["ts_out"])
    middle = count // 2
    first = [trade["net_bps"] for trade in ordered[:middle]]
    second = [trade["net_bps"] for trade in ordered[middle:]]
    best = max(range(count), key=lambda index: nets[index])
    without_best = [value for index, value in enumerate(nets) if index != best]
    median = statistics.median(nets)
    median_first = statistics.median(first)
    median_second = statistics.median(second)
    median_loo = statistics.median(without_best)
    profit_factor = _pf(nets)
    armed = median_first > 0 and median_second > 0 and profit_factor > 1.2 and median_loo > 0
    return {
        **summary,
        "verdict": "ARME_COHORTE" if armed else "KILL",
        "net_median_bps": round(median, 4),
        "net_moyen_bps": round(sum(nets) / count, 4),
        "net_median_usd": round(statistics.median([t["net_usd"] for t in trades]), 6),
        "pf": profit_factor,
        "dd_usd": _dd_usd(trades),
        "median_moitie1_bps": round(median_first, 4),
        "median_moitie2_bps": round(median_second, 4),
        "median_sans_meilleur_bps": round(median_loo, 4),
        "regle_arme": "net+ 2 moities ET pf>1.2 ET positif sans meilleur trade",
    }


def _lignes(source):
    opener = gzip.open if str(source).endswith(".gz") else open
    try:
        with opener(source, "rt", encoding="utf-8", errors="ignore") as handle:
            yield from handle
    except OSError:
        return


def collecter_series(
    root: Path,
    *,
    ds_ms: float = 1000.0,
    coins=COINS_COMMUNS,
    budget_s: float = 0.0,
    current_only: bool = False,
) -> dict:
    """Stream local BBO sources with bounded work and explicit stop reason."""
    data_dir = root / "runtime" / "data"
    sources: list[Path | str] = [data_dir / "bbo_tape.jsonl"]
    if not current_only:
        sources += sorted(glob.glob(str(data_dir / "bbo_shards" / "*.jsonl.gz")))
        sources += sorted(glob.glob(str(data_dir / "bbo_shards_archive" / "*.jsonl.gz")))
        if (data_dir / "bbo_tape.jsonl.prev").exists():
            sources.append(data_dir / "bbo_tape.jsonl.prev")
    target_coins = set(coins)
    series = {coin: [] for coin in coins}
    last_bucket: dict[tuple[str, str], int] = {}
    started = time.monotonic()
    lines_read = 0
    sources_read = 0
    stopped_reason = "COMPLETED"
    stop_requested = False
    for source in sources:
        sources_read += 1
        for line in _lignes(source):
            lines_read += 1
            if budget_s and lines_read % 10_000 == 0 and time.monotonic() - started >= budget_s:
                stopped_reason = "TIME_BUDGET_REACHED"
                stop_requested = True
                break
            if not line or '"venue"' not in line:
                continue
            try:
                quote = json.loads(line)
            except ValueError:
                continue
            venue = quote.get("venue")
            coin = quote.get("coin")
            if venue not in ("HL", "BIN") or coin not in target_coins:
                continue
            ts = quote.get("ts_wall_ms")
            bid = quote.get("bid")
            ask = quote.get("ask")
            if ts is None or not bid or not ask or ask <= bid:
                continue
            bucket = int(float(ts) // ds_ms)
            key = (coin, venue)
            if last_bucket.get(key) == bucket:
                continue
            last_bucket[key] = bucket
            series[coin].append((float(ts), venue, float(bid), float(ask)))
        if stop_requested or (budget_s and time.monotonic() - started >= budget_s):
            stopped_reason = "TIME_BUDGET_REACHED"
            break
    series["_meta"] = {
        "lignes_lues": lines_read,
        "sources_decouvertes": len(sources),
        "sources_lues": sources_read,
        "secondes": round(time.monotonic() - started, 3),
        "stopped_reason": stopped_reason,
        "current_only": bool(current_only),
    }
    return series


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Two-leg cross-venue paper replay (read-only).")
    parser.add_argument("--root", default=str(RACINE))
    parser.add_argument("--ds-ms", type=float, default=1000.0)
    parser.add_argument("--budget-s", type=float, default=0.0)
    parser.add_argument("--current-only", action="store_true")
    parser.add_argument("--latence-ms", type=float, default=LATENCE_MS)
    parser.add_argument("--sortie", default=str(RACINE / "runtime" / "research" / "dislocation_final_verdict.json"))
    args = parser.parse_args(argv)
    root = Path(args.root)
    series = collecter_series(
        root, ds_ms=args.ds_ms, budget_s=max(0.0, args.budget_s), current_only=args.current_only,
    )
    meta = series.pop("_meta", {})
    quotes_by_coin = {coin: len(values) for coin, values in series.items() if values}
    trades = backtester(series, latence_ms=max(0.0, args.latence_ms))
    realistic = juger(trades)
    conservative = juger(backtester(series, fees_ar_bps=19.0, latence_ms=max(0.0, args.latence_ms)))
    output = {
        "schema_version": "hypersmart.cross_venue_campaign.v2",
        "meta": meta,
        "quotes_par_coin": quotes_by_coin,
        "n_coins_actifs": len(quotes_by_coin),
        "params": {
            "seuil_entree_bps": SEUIL_ENTREE_BPS,
            "seuil_sortie_bps": SEUIL_SORTIE_BPS,
            "horizon_max_s": HORIZON_MAX_S,
            "latence_ms": max(0.0, args.latence_ms),
            "fees_ar_bps": FEES_AR_BPS,
            "notional_usd": NOTIONAL_USD,
        },
        "verdict_realiste_16bps": realistic,
        "verdict_conservateur_19bps": conservative,
        "trade_ids": [trade["trade_id"] for trade in trades[:100]],
        "trades": trades[:100],
        "capacite_note": "BBO sans profondeur: slippage et capacite non mesurables; LIQUIDATABLE_NET=false",
        "paper_read_only": True,
        "real_execution": False,
    }
    target = Path(args.sortie)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
