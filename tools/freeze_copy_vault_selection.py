#!/usr/bin/env python3
"""Freeze the complete qualifying public Hyperliquid vault universe for hosted lanes."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
sys.path.insert(0,str(ROOT/"src"))

import collecter_vaults as CV  # noqa: E402


def _safe_timestamp(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def load_fill_checkpoints(repo_root: Path, *, phase_epoch: int) -> dict[str, dict[str, Any]]:
    """Aggregate only durable successful Copy-Vault campaign receipts."""
    checkpoints: dict[str, dict[str, Any]] = {}
    campaign_root = repo_root / "catalog" / "campaigns"
    for path in sorted(campaign_root.glob("copy-vault-*.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(manifest, Mapping):
            continue
        if (
            manifest.get("kind") != "copy_vault_collection"
            or str(manifest.get("status") or "").upper() != "COMPLETE"
            or str(manifest.get("creation_phase") or "").upper() != "COLLECT"
        ):
            continue
        units = manifest.get("completed_units")
        if not isinstance(units, Mapping):
            continue
        for unit in units.values():
            result = unit.get("result") if isinstance(unit, Mapping) else None
            metrics = result.get("collection_metrics") if isinstance(result, Mapping) else None
            updates = metrics.get("vault_checkpoints") if isinstance(metrics, Mapping) else None
            if not isinstance(updates, Mapping):
                continue
            for raw_address, raw_checkpoint in updates.items():
                address = str(raw_address or "").strip().lower()
                if not re.fullmatch(r"0x[0-9a-f]{40}", address) or not isinstance(raw_checkpoint, Mapping):
                    continue
                incoming = dict(raw_checkpoint)
                if incoming.get("checkpoint_schema") != "alina.copy_vault_fill_checkpoint.v1":
                    continue
                current = checkpoints.setdefault(address, {})
                current["checkpoint_schema"] = "alina.copy_vault_fill_checkpoint.v1"
                forward_end = _safe_timestamp(incoming.get("last_forward_end_ms"))
                current_end = _safe_timestamp(current.get("last_forward_end_ms"))
                if forward_end is not None and (current_end is None or forward_end > current_end):
                    for key in ("last_forward_start_ms", "last_forward_end_ms", "last_forward_status"):
                        if key in incoming:
                            current[key] = incoming[key]
                attempt = _safe_timestamp(incoming.get("last_forward_attempt_ms"))
                current_attempt = _safe_timestamp(current.get("last_forward_attempt_ms"))
                if attempt is not None and (current_attempt is None or attempt >= current_attempt):
                    for key in (
                        "last_forward_attempt_ms", "forward_pending_start_ms",
                        "forward_retry_after_ms",
                        "forward_failure_count",
                    ):
                        if key in incoming:
                            current[key] = incoming[key]
                        elif key in {"forward_pending_start_ms", "forward_retry_after_ms"}:
                            current.pop(key, None)
                attempt = _safe_timestamp(incoming.get("history_last_attempt_ms"))
                current_attempt = _safe_timestamp(current.get("history_last_attempt_ms"))
                if incoming.get("history_complete") is True:
                    current.update({
                        "history_complete": True,
                        "history_status": "COMPLETE",
                        "history_fill_count": max(
                            _safe_timestamp(current.get("history_fill_count")) or 0,
                            _safe_timestamp(incoming.get("history_fill_count")) or 0,
                        ),
                        "history_coverage_end_ms": max(
                            _safe_timestamp(current.get("history_coverage_end_ms")) or 0,
                            _safe_timestamp(incoming.get("history_coverage_end_ms")) or 0,
                        ),
                        "history_pending_windows": [],
                    })
                elif current.get("history_complete") is not True and (
                    attempt is not None and (current_attempt is None or attempt >= current_attempt)
                ):
                    for key in (
                        "history_complete", "history_status", "history_fill_count",
                        "history_coverage_end_ms", "history_pending_windows",
                        "history_last_attempt_ms", "history_retry_after_ms",
                        "history_last_audit", "history_failure_count",
                    ):
                        if key in incoming:
                            current[key] = incoming[key]
    return checkpoints


def build_selection(
    payload: Any,
    *,
    now_ms: int | None=None,
    fill_checkpoints: Mapping[str, Mapping[str, Any]] | None = None,
    forward_reconcile_limit: int = 256,
    history_bootstrap_limit: int = 2,
) -> dict[str,Any]:
    selected_at_ms=int(time.time()*1000) if now_ms is None else int(now_ms)
    raw_count=len(payload) if isinstance(payload,list) else 0
    rows=CV.parser_univers_public(
        payload,
        now_ms=selected_at_ms,
        min_tvl_usd=0.0,
        min_age_days=0.0,
        max_vaults=max(1,raw_count),
    )
    if not rows:
        raise RuntimeError("public Copy-Vault observation universe is empty")
    supplied = fill_checkpoints or {}
    normalized_checkpoints = {
        str(address).strip().lower(): dict(checkpoint)
        for address, checkpoint in supplied.items()
        if re.fullmatch(r"0x[0-9a-fA-F]{40}", str(address).strip())
        and isinstance(checkpoint, Mapping)
    }
    indexed_rows = list(enumerate(rows))
    forward_candidates = sorted(
        (
            item for item in indexed_rows
            if (_safe_timestamp(
                normalized_checkpoints.get(
                    str(item[1].get("address") or "").lower(), {}
                ).get("forward_retry_after_ms")
            ) or 0) <= selected_at_ms
        ),
        key=lambda item: (
            _safe_timestamp(normalized_checkpoints.get(str(item[1].get("address") or "").lower(), {}).get("last_forward_end_ms")) or 0,
            -float(item[1].get("tvl_usd") or 0.0),
            item[0],
        ),
    )[:max(1, int(forward_reconcile_limit))]
    history_pending_candidates = []
    history_unseen_candidates = []
    history_retry_candidates = []
    for index, row in indexed_rows:
        address = str(row.get("address") or "").lower()
        checkpoint = normalized_checkpoints.get(address, {})
        if checkpoint.get("history_complete") is True:
            continue
        retry_after = _safe_timestamp(checkpoint.get("history_retry_after_ms")) or 0
        if retry_after > selected_at_ms:
            continue
        has_pending = bool(checkpoint.get("history_pending_windows"))
        candidate = (
            _safe_timestamp(checkpoint.get("history_last_attempt_ms")) or 0,
            -float(row.get("tvl_usd") or 0.0),
            index,
            address,
        )
        if has_pending:
            history_pending_candidates.append(candidate)
        elif not checkpoint.get("history_last_attempt_ms"):
            history_unseen_candidates.append(candidate)
        else:
            history_retry_candidates.append(candidate)
    for candidates in (
        history_pending_candidates,
        history_unseen_candidates,
        history_retry_candidates,
    ):
        candidates.sort()
    history_candidates = (
        history_pending_candidates
        + history_unseen_candidates
        + history_retry_candidates
    )
    limit = max(0, int(history_bootstrap_limit))
    history_vaults = []
    if limit and history_pending_candidates:
        history_vaults.append(history_pending_candidates[0][-1])
    history_fill_order = (
        history_unseen_candidates
        + history_retry_candidates
        + history_pending_candidates[1:]
    )
    for candidate in history_fill_order:
        if candidate[-1] not in history_vaults and len(history_vaults) < limit:
            history_vaults.append(candidate[-1])
    return {
        "schema":"alina.copy_vault_selection.v2",
        "selected_at_ms":selected_at_ms,
        "source":CV.URL_VAULTS,
        "filters":{
            "min_tvl_usd":0.0,
            "min_age_days":0.0,
            "relationship":"normal",
            "is_closed":False,
            "max_vaults":None,
        },
        "raw_public_rows":raw_count,
        "vault_count":len(rows),
        "vaults":rows,
        "fill_checkpoints":normalized_checkpoints,
        "forward_reconcile_vaults":[
            str(row.get("address") or "").lower()
            for _, row in forward_candidates
        ],
        "history_bootstrap_vaults":history_vaults,
        "fill_checkpoint_summary":{
            "known_wallets":len(normalized_checkpoints),
            "forward_poll_candidates":len(forward_candidates),
            "history_bootstrap_candidates":len(history_candidates),
        },
        "observation_only":True,
        "read_only":True,
        "real_execution":False,
    }


def main(argv: list[str] | None=None) -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True)
    parser.add_argument("--phase-epoch", type=int)
    args=parser.parse_args(argv)
    payload=CV._get_vaults_public()
    out=Path(args.output)
    epoch = args.phase_epoch
    if epoch is None:
        match = re.fullmatch(r"e(\d+)", out.parent.name)
        epoch = int(match.group(1)) if match else None
    checkpoints = (
        load_fill_checkpoints(ROOT, phase_epoch=epoch)
        if epoch is not None else {}
    )
    selection=build_selection(payload, fill_checkpoints=checkpoints)
    out.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(selection,indent=2,sort_keys=True)+"\n").encode()
    out.write_bytes(raw)
    print(json.dumps({
        "path":str(out),
        "vault_count":selection["vault_count"],
        "lane_count":(int(selection["vault_count"])+CV.MAX_UNIQUE_USERS_PER_IP-1)//CV.MAX_UNIQUE_USERS_PER_IP
            if hasattr(CV,"MAX_UNIQUE_USERS_PER_IP") else (int(selection["vault_count"])+9)//10,
        "sha256":hashlib.sha256(raw).hexdigest(),
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
