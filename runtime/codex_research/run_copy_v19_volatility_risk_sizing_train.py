from __future__ import annotations

import bisect
import ctypes
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"C:\Users\flo\Desktop\Projet invest")
RESEARCH = ROOT / "runtime" / "codex_research"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(RESEARCH))

from hl_observer.backtesting import copy_vault_executable as cv  # noqa: E402
from hl_observer.backtesting.copy_vault_protocol import (  # noqa: E402
    COPY_DELAY_MS,
    MAX_OPEN_POSITIONS,
    MAX_REFERENCE_LAG_MS,
    MAX_TARGET_LAG_MS,
)
from hl_observer.backtesting.copy_vault_v4_train import assess_train_variant  # noqa: E402
from run_copy_v11_first_fill_checkpoint_train import first_action, load_pipeline  # noqa: E402

SIGNED_DEPTH_IMBALANCE_MINIMUMS = (0.0, 0.20)
DOLLAR_RISK_TARGETS_USD = (1.0, 2.0, 3.0)
HORIZON_MS = 3_600_000
VOLATILITY_LOOKBACK_MS = 1_800_000
MAX_VOLATILITY_GAP_MS = 300_000
MIN_VOLATILITY_OBSERVATIONS = 10
VOLATILITY_FLOOR_BPS = 25.0
MIN_NOTIONAL_USD = 75.0
MAX_NOTIONAL_USD = 600.0
VAULT_DAILY_LIMIT = 1
COIN_DAILY_LIMIT = 1
PRIOR_TRIALS = 424
NEW_TRIALS = 6
TRIALS = PRIOR_TRIALS + NEW_TRIALS


def first_fill_notional_usd(metaorder: dict) -> float:
    members = list(metaorder.get("member_events") or ())
    return float(members[0].get("taille_usd") or 0.0) if members else 0.0


def reference_depth_features(metaorder: dict, rows: list[dict]) -> tuple[float, float, float] | None:
    if not rows:
        return None
    timestamps = [int(row["ts_ms"]) for row in rows]
    signal_ms = int(metaorder["signal_ts_ms"])
    index = bisect.bisect_left(timestamps, signal_ms)
    if index >= len(rows) or timestamps[index] - signal_ms > MAX_REFERENCE_LAG_MS:
        return None
    row = rows[index]
    bids = list(row.get("bids5") or ())
    asks = list(row.get("asks5") or ())
    if not bids or not asks:
        return None
    bid_usd = sum(float(level[0]) * float(level[1]) for level in bids if len(level) >= 2)
    ask_usd = sum(float(level[0]) * float(level[1]) for level in asks if len(level) >= 2)
    total = bid_usd + ask_usd
    direction = int(metaorder.get("direction") or 0)
    two_sided_capacity = min(bid_usd, ask_usd)
    if total <= 0 or two_sided_capacity <= 0 or direction not in (-1, 1):
        return None
    start = bisect.bisect_left(timestamps, int(row["ts_ms"]) - VOLATILITY_LOOKBACK_MS)
    window = rows[start : index + 1]
    if len(window) < MIN_VOLATILITY_OBSERVATIONS:
        return None
    window_ts = [int(item["ts_ms"]) for item in window]
    if any(b - a > MAX_VOLATILITY_GAP_MS for a, b in zip(window_ts, window_ts[1:])):
        return None
    mids = []
    for item in window:
        item_bids = list(item.get("bids5") or ())
        item_asks = list(item.get("asks5") or ())
        if not item_bids or not item_asks:
            continue
        mids.append((float(item_bids[0][0]) + float(item_asks[0][0])) / 2.0)
    if len(mids) < MIN_VOLATILITY_OBSERVATIONS or mids[-1] <= 0:
        return None
    volatility_bps = (max(mids) - min(mids)) / mids[-1] * 10_000.0
    return direction * (bid_usd - ask_usd) / total, two_sided_capacity, volatility_bps


def settle_variant(
    candidates: list[dict], books_by_coin: dict[str, list[dict]],
    *, dollar_risk_target_usd: float,
) -> tuple[list[dict], list[dict], dict[str, int]]:
    completed: list[tuple[dict, dict, dict]] = []
    audit: dict[str, int] = defaultdict(int)
    for metaorder in sorted(candidates, key=lambda row: (int(row["signal_ts_ms"]), str(row["metaorder_id"]))):
        rows = books_by_coin.get(str(metaorder["coin"]), [])
        notional_usd = min(
            MAX_NOTIONAL_USD,
            float(metaorder["reference_two_sided_capacity_usd"]),
            dollar_risk_target_usd * 10_000.0
            / max(VOLATILITY_FLOOR_BPS, float(metaorder["trailing_volatility_bps"])),
        )
        if notional_usd < MIN_NOTIONAL_USD:
            audit["VOLATILITY_SIZED_NOTIONAL_BELOW_MINIMUM"] += 1
            continue
        actual, actual_reason = cv.execute_metaorder(
            metaorder, rows, horizon_ms=HORIZON_MS, direction_multiplier=1,
            notional_usd=notional_usd, require_causal_books=True,
        )
        placebo, placebo_reason = cv.execute_metaorder(
            metaorder, rows, horizon_ms=HORIZON_MS, direction_multiplier=-1,
            notional_usd=notional_usd, require_causal_books=True,
        )
        if actual is None or placebo is None:
            audit[f"ACTUAL_PROVENANCE_REFUSAL_{actual_reason}"] += int(actual is None)
            audit[f"PLACEBO_PROVENANCE_REFUSAL_{placebo_reason}"] += int(placebo is None)
            audit["INCOMPLETE_EPISODE_REJECTED"] += 1
            continue
        completed.append((actual, placebo, metaorder))
        audit["COMPLETE_CAUSAL_EPISODE"] += 1

    trades: list[dict] = []
    placebos: list[dict] = []
    vault_day: dict[tuple[str, int], int] = defaultdict(int)
    coin_day: dict[tuple[str, int], int] = defaultdict(int)
    active_exit_times: list[int] = []
    for actual, placebo, metaorder in sorted(completed, key=lambda item: (int(item[0]["entry_ts_ms"]), str(item[0]["metaorder_id"]))):
        entry_ms = int(actual["entry_ts_ms"])
        day = entry_ms // 86_400_000
        vault_key = (str(actual["vault"]), day)
        coin_key = (str(actual["coin"]), day)
        if vault_day[vault_key] >= VAULT_DAILY_LIMIT:
            audit["VAULT_DAILY_BUDGET_REJECTED"] += 1
            continue
        if coin_day[coin_key] >= COIN_DAILY_LIMIT:
            audit["COIN_DAILY_BUDGET_REJECTED"] += 1
            continue
        active_exit_times = [timestamp for timestamp in active_exit_times if timestamp > entry_ms]
        if len(active_exit_times) >= MAX_OPEN_POSITIONS:
            audit["PORTFOLIO_CAPACITY_REJECTED"] += 1
            continue
        common = {
            "walk_forward_segment": "train",
            "signal_action": first_action(metaorder),
            "first_fill_leader_notional_usd": first_fill_notional_usd(metaorder),
            "signed_reference_depth_imbalance": float(metaorder["signed_reference_depth_imbalance"]),
            "reference_two_sided_capacity_usd": float(metaorder["reference_two_sided_capacity_usd"]),
            "trailing_volatility_bps": float(metaorder["trailing_volatility_bps"]),
            "dollar_risk_target_usd": dollar_risk_target_usd,
            "volatility_sized_notional_usd": float(actual["notional_usd"]),
            "paper_read_only": True,
            "real_execution": False,
        }
        trades.append({**actual, **common, "mechanism": "copy_v19_volatility_risk_sizing"})
        placebos.append({**placebo, **common, "mechanism": "copy_v19_volatility_risk_sizing_placebo"})
        vault_day[vault_key] += 1
        coin_day[coin_key] += 1
        active_exit_times.append(int(actual["exit_ts_ms"]))
        audit["ADMITTED_CLOSED_POSITION"] += 1
    return trades, placebos, dict(audit)


def mean_daily(statistics: dict) -> float | None:
    values = list(statistics.get("daily_net_pnl_usd") or ())
    return sum(values) / len(values) if values else None


def compact(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {key: value for key, value in row.items() if key not in {"trades", "placebos"}}


def main() -> None:
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
    pipeline = load_pipeline()
    entries, entries_audit = pipeline.charger_entrees_alpha_notional_fixe_avec_audit(ROOT)
    metaorders, metaorder_audit = cv.cluster_metaorders(entries)
    books, books_audit = cv.load_observed_books(ROOT, coins={str(row["coin"]) for row in metaorders})
    causal_metaorders, causal_books, protocol_audit = cv.select_causal_protocol_inputs(metaorders, books)
    continuous_books = {
        coin: sorted(
            [dict(row) for row in rows if row.get("causal_observation") is True and not row.get("checkpoint_id") and str(row.get("source") or "") == "HYPERLIQUID_L2_WS"],
            key=lambda row: int(row["ts_ms"]),
        )
        for coin, rows in causal_books.items()
    }
    continuous_books = {coin: rows for coin, rows in continuous_books.items() if rows}
    purge_ms = COPY_DELAY_MS + HORIZON_MS + MAX_TARGET_LAG_MS
    bounds = cv.temporal_bounds(causal_metaorders, purge_ms=purge_ms)
    train_start_ms, train_end_ms = int(bounds["train_start_ms"]), int(bounds["train_end_ms"])
    train_adds: list[dict] = []
    feature_audit: dict[str, int] = defaultdict(int)
    for raw in causal_metaorders:
        row = dict(raw)
        if not (train_start_ms <= int(row["signal_ts_ms"]) <= train_end_ms):
            continue
        coin = str(row["coin"])
        if coin not in continuous_books or first_action(row) != "ADD":
            continue
        features = reference_depth_features(row, continuous_books[coin])
        if features is None:
            feature_audit["REFERENCE_DEPTH_FEATURE_UNMEASURABLE"] += 1
            continue
        row["signed_reference_depth_imbalance"] = features[0]
        row["reference_two_sided_capacity_usd"] = features[1]
        row["trailing_volatility_bps"] = features[2]
        train_adds.append(row)
        feature_audit["REFERENCE_DEPTH_FEATURE_MEASURED"] += 1

    variants: list[dict] = []
    for minimum_alignment in SIGNED_DEPTH_IMBALANCE_MINIMUMS:
        candidates = [
            row for row in train_adds
            if float(row["signed_reference_depth_imbalance"]) >= minimum_alignment
        ]
        for dollar_risk_target_usd in DOLLAR_RISK_TARGETS_USD:
                    trades, placebos, replay_audit = settle_variant(
                        candidates, continuous_books, dollar_risk_target_usd=dollar_risk_target_usd,
                    )
                    assessment = assess_train_variant(trades, placebos, trial_count=TRIALS)
                    daily = mean_daily(assessment["statistics"])
                    reasons = list(assessment["reasons"])
                    if daily is None or daily < 4.0:
                        reasons.append("DAILY_MEAN_NET_BELOW_4_USD")
                    variants.append({
                        "signed_depth_imbalance_minimum": minimum_alignment,
                        "dollar_risk_target_usd": dollar_risk_target_usd,
                        "horizon_ms": HORIZON_MS,
                        "minimum_notional_usd": MIN_NOTIONAL_USD,
                        "maximum_notional_usd": MAX_NOTIONAL_USD,
                        "max_entries_per_vault_day": VAULT_DAILY_LIMIT,
                        "max_entries_per_coin_day": COIN_DAILY_LIMIT,
                        "candidate_count": len(candidates), **assessment,
                        "daily_mean_net_pnl_usd": daily, "replay_audit": replay_audit,
                        "eligible": not reasons, "reasons": reasons,
                        "trades": trades, "placebos": placebos,
                    })
    eligible = [row for row in variants if row["eligible"]]
    selected = max(eligible, key=lambda row: (float(row["statistics"].get("total_lcb_usd") or 0.0), float(row["statistics"].get("net_pnl_usd") or 0.0)), default=None)
    best = max(variants, key=lambda row: float(row["statistics"].get("net_pnl_usd") or 0.0), default=None)
    report = {
        "schema_version": "hypersmart.copy_v19_volatility_risk_sizing_train.v1",
        "mechanism": "copy_v19_volatility_risk_sizing",
        "status": "TRAIN_ELIGIBLE_TO_FREEZE" if selected else "NO_ROBUST_TRAIN_CANDIDATE",
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE", "heldout_evaluated": False,
        "bounds": bounds,
        "input_audit": {
            "entries": entries_audit, "metaorders": metaorder_audit,
            "books": books_audit, "protocol": protocol_audit,
            "feature": dict(feature_audit), "train_add_metaorders": len(train_adds),
            "continuous_causal_rows": sum(len(rows) for rows in continuous_books.values()),
        },
        "fixed_grid": {
            "signed_depth_imbalance_minimums": SIGNED_DEPTH_IMBALANCE_MINIMUMS,
            "dollar_risk_targets_usd": DOLLAR_RISK_TARGETS_USD,
            "horizon_ms": HORIZON_MS,
            "volatility_lookback_ms": VOLATILITY_LOOKBACK_MS,
            "maximum_volatility_gap_ms": MAX_VOLATILITY_GAP_MS,
            "minimum_volatility_observations": MIN_VOLATILITY_OBSERVATIONS,
            "volatility_floor_bps": VOLATILITY_FLOOR_BPS,
            "minimum_notional_usd": MIN_NOTIONAL_USD,
            "maximum_notional_usd": MAX_NOTIONAL_USD,
            "vault_daily_limit": VAULT_DAILY_LIMIT, "coin_daily_limit": COIN_DAILY_LIMIT,
            "prior_family_trial_count": PRIOR_TRIALS, "new_trial_count": NEW_TRIALS,
            "bonferroni_trial_count": TRIALS,
        },
        "selected": selected, "diagnostic_best": compact(best),
        "diagnostic_best_trades": list((best or {}).get("trades") or ()),
        "diagnostic_best_placebos": list((best or {}).get("placebos") or ()),
        "variant_summaries": [compact(row) for row in variants],
        "paper_read_only": True, "real_execution": False, "carry_pnl_usd": 0.0,
    }
    output = ROOT / "runtime/reports/economic_campaigns/research_vnext/copy_vault_v19_volatility_risk_sizing_train.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output), "status": report["status"],
        "selected": compact(selected), "diagnostic_best": compact(best),
        "train_add_metaorders": len(train_adds), "feature_audit": dict(feature_audit),
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
