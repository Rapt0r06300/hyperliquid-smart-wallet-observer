"""Rebuild the fixed v15 diagnostic variant and print causal trade diagnostics.

This is a finite TRAIN-only audit. It does not read validation, OOS, or forward
segments and does not perform network or exchange actions.
"""

from __future__ import annotations

import json
import ctypes
import sys
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_copy_v15_l2_aligned_add_train import (
    ROOT,
    first_action,
    first_fill_notional_usd,
    load_pipeline,
    settle_variant,
    signed_reference_depth_imbalance,
)
from hl_observer.backtesting import copy_vault_executable as cv


def main() -> None:
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
    pipeline = load_pipeline()
    entries, _ = pipeline.charger_entrees_alpha_notional_fixe_avec_audit(ROOT)
    metaorders, _ = cv.cluster_metaorders(entries)
    books, _ = cv.load_observed_books(ROOT, coins={str(row["coin"]) for row in metaorders})
    causal_metaorders, causal_books, _ = cv.select_causal_protocol_inputs(metaorders, books)
    continuous_books = {
        coin: sorted(
            [
                dict(row)
                for row in rows
                if row.get("causal_observation") is True
                and not row.get("checkpoint_id")
                and str(row.get("source") or "") == "HYPERLIQUID_L2_WS"
            ],
            key=lambda row: int(row["ts_ms"]),
        )
        for coin, rows in causal_books.items()
    }
    continuous_books = {coin: rows for coin, rows in continuous_books.items() if rows}
    bounds = cv.temporal_bounds(causal_metaorders, purge_ms=1_000 + 3_600_000 + 30_000)
    train_start_ms = int(bounds["train_start_ms"])
    train_end_ms = int(bounds["train_end_ms"])
    candidates = []
    for raw in causal_metaorders:
        row = dict(raw)
        if not (train_start_ms <= int(row["signal_ts_ms"]) <= train_end_ms):
            continue
        coin = str(row["coin"])
        if coin not in continuous_books or first_action(row) != "ADD":
            continue
        feature = signed_reference_depth_imbalance(row, continuous_books[coin])
        if feature is None:
            continue
        row["signed_reference_depth_imbalance"] = feature
        if feature < 0.0:
            continue
        candidates.append(row)

    trades, _, audit = settle_variant(
        candidates, continuous_books, horizon_ms=3_600_000, notional_usd=600.0
    )
    by_vault: dict[str, dict[str, object]] = defaultdict(
        lambda: {"trades": 0, "net_pnl_usd": 0.0, "days": Counter(), "coins": Counter()}
    )
    compact = []
    for trade in trades:
        vault = str(trade["vault"])
        day = int(trade["entry_ts_ms"]) // 86_400_000
        by_vault[vault]["trades"] += 1
        by_vault[vault]["net_pnl_usd"] += float(trade["net_pnl_usd"])
        by_vault[vault]["days"][str(day)] += 1
        by_vault[vault]["coins"][str(trade["coin"])] += 1
        compact.append(
            {
                key: trade.get(key)
                for key in (
                    "trade_id", "vault", "coin", "signal_action", "entry_ts_ms",
                    "exit_ts_ms", "net_pnl_usd", "first_fill_leader_notional_usd",
                    "signed_reference_depth_imbalance", "entry_capacity_usd",
                    "entry_price", "exit_price", "direction",
                )
            }
        )
    result = {
        "bounds": bounds,
        "candidate_count": len(candidates),
        "audit": audit,
        "by_vault": {
            key: {
                "trades": value["trades"],
                "net_pnl_usd": value["net_pnl_usd"],
                "days": dict(value["days"]),
                "coins": dict(value["coins"]),
            }
            for key, value in sorted(
                by_vault.items(), key=lambda item: float(item[1]["net_pnl_usd"]), reverse=True
            )
        },
        "trades": compact,
    }
    output = ROOT / "runtime/codex_research/copy_v15_trade_concentration_audit.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **{k: result[k] for k in ("candidate_count", "audit", "by_vault")}}, ensure_ascii=True))


if __name__ == "__main__":
    main()
