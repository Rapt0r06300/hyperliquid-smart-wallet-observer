"""Fail-closed held-out-vault proof for executable Copy-Vault campaigns.

A vault counts as held-out only if no executable trade from that vault appears
before the OOS boundary.  Economics are then measured exclusively on OOS and
forward trades from those genuinely unseen vaults.  This module never creates
fills or market data and cannot turn an empty/negative sample into a proof.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any


def _finite_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def derive_heldout_vault_generalization(
    trades: Iterable[Mapping[str, Any]],
    *,
    oos_start_ms: int | None,
) -> dict[str, Any] | None:
    """Return strict held-out proof or ``None`` when the boundary is unavailable."""

    if oos_start_ms is None:
        return None
    try:
        boundary = int(oos_start_ms)
    except (TypeError, ValueError, OverflowError):
        return None
    if boundary <= 0:
        return None

    rows: list[dict[str, Any]] = []
    for raw in trades:
        vault = str(raw.get("vault") or "").strip()
        try:
            ts_ms = int(raw.get("signal_ts_ms") or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        net = _finite_float(raw.get("net_pnl_usd"))
        notional = _finite_float(raw.get("notional_usd"))
        trade_id = str(raw.get("trade_id") or "").strip()
        if not vault or ts_ms <= 0 or net is None or notional is None or notional <= 0:
            continue
        if raw.get("liquidatable_net") is not True or len(trade_id) != 64:
            continue
        rows.append(
            {
                "vault": vault,
                "signal_ts_ms": ts_ms,
                "net_pnl_usd": net,
                "notional_usd": notional,
                "trade_id": trade_id,
            }
        )

    # Stricter than merely excluding TRAIN: any vault observed in executable
    # evidence before OOS (TRAIN or validation) is not held-out.
    pre_oos_vaults = {row["vault"] for row in rows if row["signal_ts_ms"] < boundary}
    heldout_rows = [
        row for row in rows
        if row["signal_ts_ms"] >= boundary and row["vault"] not in pre_oos_vaults
    ]
    if not heldout_rows:
        return {
            "sample_count": 0,
            "net_bps": None,
            "vaults_held_out": [],
            "heldout_vault_count": 0,
            "heldout_profit_vault_count": 0,
            "min_heldout_vault_net_pnl_usd": None,
            "net_pnl_usd": 0.0,
            "notional_usd": 0.0,
            "trade_ids_count": 0,
            "trade_ids_sha256": hashlib.sha256(b"").hexdigest(),
            "definition": "vault_absent_from_all_pre_oos_executable_trades_then_measured_oos_forward_only",
            "role": "SECONDARY_ROBUSTNESS_REQUIRED_FOR_ECONOMIC_CLAIM",
        }

    by_vault: dict[str, dict[str, float | int]] = {}
    ids: list[str] = []
    total_net = 0.0
    total_notional = 0.0
    for row in heldout_rows:
        vault = row["vault"]
        bucket = by_vault.setdefault(vault, {"sample_count": 0, "net_pnl_usd": 0.0, "notional_usd": 0.0})
        bucket["sample_count"] = int(bucket["sample_count"]) + 1
        bucket["net_pnl_usd"] = float(bucket["net_pnl_usd"]) + float(row["net_pnl_usd"])
        bucket["notional_usd"] = float(bucket["notional_usd"]) + float(row["notional_usd"])
        total_net += float(row["net_pnl_usd"])
        total_notional += float(row["notional_usd"])
        ids.append(row["trade_id"])

    vault_rows = []
    for vault in sorted(by_vault):
        bucket = by_vault[vault]
        notional = float(bucket["notional_usd"])
        net = float(bucket["net_pnl_usd"])
        vault_rows.append(
            {
                "vault": vault,
                "sample_count": int(bucket["sample_count"]),
                "net_pnl_usd": round(net, 8),
                "notional_usd": round(notional, 8),
                "net_bps": round(net / notional * 10_000.0, 8) if notional > 0 else None,
            }
        )

    unique_ids = sorted(set(ids))
    min_net = min(float(row["net_pnl_usd"]) for row in vault_rows)
    return {
        "sample_count": len(heldout_rows),
        "net_bps": round(total_net / total_notional * 10_000.0, 8) if total_notional > 0 else None,
        "vaults_held_out": [row["vault"] for row in vault_rows],
        "heldout_vault_count": len(vault_rows),
        "heldout_profit_vault_count": sum(1 for row in vault_rows if float(row["net_pnl_usd"]) > 0),
        "min_heldout_vault_net_pnl_usd": round(min_net, 8),
        "net_pnl_usd": round(total_net, 8),
        "notional_usd": round(total_notional, 8),
        "trade_ids_count": len(unique_ids),
        "trade_ids_sha256": hashlib.sha256("\n".join(unique_ids).encode("utf-8")).hexdigest(),
        "per_vault": vault_rows,
        "definition": "vault_absent_from_all_pre_oos_executable_trades_then_measured_oos_forward_only",
        "role": "SECONDARY_ROBUSTNESS_REQUIRED_FOR_ECONOMIC_CLAIM",
    }


__all__ = ["derive_heldout_vault_generalization"]
