from __future__ import annotations

import hashlib
import json

from tools.freeze_copy_vault_selection import build_selection


def _vault_row(index: int, *, created_ms: int) -> dict:
    return {
        "summary": {
            "isClosed": False,
            "relationship": {"type": "normal"},
            "vaultAddress": f"0x{index + 1:040x}",
            "tvl": "250000",
            "createTimeMillis": created_ms,
            "name": f"vault-{index}",
        },
        "apr": "0.10",
    }


def test_complete_public_universe_is_not_truncated_at_legacy_hundred_cap():
    now_ms = 2_000_000_000_000
    created_ms = now_ms - 60 * 86_400_000
    payload = [_vault_row(i, created_ms=created_ms) for i in range(137)]
    selection = build_selection(payload, now_ms=now_ms)
    assert selection["raw_public_rows"] == 137
    assert selection["vault_count"] == 137
    assert len(selection["vaults"]) == 137
    assert selection["filters"]["max_vaults"] is None
    assert selection["filters"]["min_tvl_usd"] == 0.0
    assert selection["filters"]["min_age_days"] == 0.0
    assert selection["observation_only"] is True
    assert selection["read_only"] is True
    assert selection["real_execution"] is False


def test_frozen_selection_carries_only_a_verified_same_epoch_fill_checkpoint(tmp_path):
    address = "0x" + "1" * 40
    report = {
        "status": "COMPLETE",
        "checkpoint_advance_allowed": True,
        "retention_cap_reached": False,
        "requested_start_ms": 100,
        "requested_end_ms": 200,
        "rows": 0,
        "requests": 1,
        "pending_windows": 0,
        "request_budget_exhausted": False,
        "invalid_fill_count": 0,
        "failed_windows": [],
        "cap_blocked_windows": [],
        "unresolved_gaps": [],
    }
    summary = {"historical_backfill": {address: report}}
    result = {
        "durable_persisted": True,
        "release_tag": "data-v2-campaign-test",
        "stdout": json.dumps(summary),
    }
    digest = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    campaign = {
        "campaign_id": "copy-vault-e7-test",
        "kind": "copy_vault_collection",
        "creation_phase": "COLLECT",
        "phase_epoch": 7,
        "status": "COMPLETE",
        "completed_units": {"unit-0": {"sha256": digest, "result": result}},
    }
    (tmp_path / "copy-vault-e7-test.json").write_text(
        json.dumps(campaign), encoding="utf-8"
    )
    payload = [_vault_row(0, created_ms=1)]
    payload[0]["summary"]["vaultAddress"] = address

    selection = build_selection(
        payload,
        now_ms=2_000_000_000_000,
        campaign_dir=tmp_path,
        phase_epoch=7,
    )

    assert selection["history_checkpoint_count"] == 1
    assert (
        selection["vaults"][0]["copy_vault_history_checkpoint"][
            "last_reconciled_end_ms"
        ]
        == 200
    )
