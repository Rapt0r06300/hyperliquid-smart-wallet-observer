from __future__ import annotations

import json

from tools.freeze_copy_vault_selection import build_selection, load_fill_checkpoints


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


def test_selection_rotates_forward_poll_and_history_bootstrap_candidates():
    now_ms = 2_000_000_000_000
    created_ms = now_ms - 60 * 86_400_000
    payload = [_vault_row(i, created_ms=created_ms) for i in range(4)]
    addresses = [f"0x{i + 1:040x}" for i in range(4)]
    checkpoints = {
        addresses[0]: {
            "last_forward_end_ms": 1_000,
            "history_complete": True,
        },
        addresses[1]: {
            "last_forward_end_ms": 2_000,
            "history_complete": False,
            "history_status": "PARTIAL",
            "history_pending_windows": [[0, 500]],
            "history_last_attempt_ms": 10,
        },
        addresses[2]: {
            "last_forward_end_ms": 1_500,
            "history_complete": False,
        },
    }

    selection = build_selection(
        payload,
        now_ms=now_ms,
        fill_checkpoints=checkpoints,
        forward_reconcile_limit=3,
        history_bootstrap_limit=2,
    )

    assert selection["forward_reconcile_vaults"] == [
        addresses[3], addresses[0], addresses[2]
    ]
    assert selection["history_bootstrap_vaults"][0] == addresses[1]
    assert len(selection["history_bootstrap_vaults"]) == 2
    assert addresses[0] not in selection["history_bootstrap_vaults"]


def test_load_fill_checkpoints_uses_only_complete_same_epoch_campaigns(tmp_path):
    campaigns = tmp_path / "catalog" / "campaigns"
    campaigns.mkdir(parents=True)
    address = "0x" + "a" * 40

    def manifest(name, *, status, epoch, end_ms, complete=True):
        path = campaigns / name
        payload = {
            "kind": "copy_vault_collection",
            "status": status,
            "creation_phase": "COLLECT",
            "phase_epoch": epoch,
            "completed_units": {
                "0": {
                    "result": {
                        "collection_metrics": {
                            "vault_checkpoints": {
                                address: {
                                    "checkpoint_schema": "alina.copy_vault_fill_checkpoint.v1",
                                    "last_forward_start_ms": end_ms - 10,
                                    "last_forward_end_ms": end_ms,
                                    "last_forward_status": "SOURCE_CONTINUITY_VERIFIED",
                                    "history_complete": complete,
                                    "history_fill_count": 10,
                                    "history_last_attempt_ms": end_ms,
                                }
                            }
                        }
                    }
                }
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    manifest("copy-vault-1.json", status="COMPLETE", epoch=7, end_ms=100)
    manifest("copy-vault-2.json", status="RUNNING", epoch=7, end_ms=300)
    manifest("copy-vault-3.json", status="COMPLETE", epoch=6, end_ms=150)
    manifest("copy-vault-4.json", status="COMPLETE", epoch=7, end_ms=200, complete=False)

    checkpoints = load_fill_checkpoints(tmp_path, phase_epoch=7)

    assert checkpoints[address]["last_forward_end_ms"] == 200
    assert checkpoints[address]["history_complete"] is True
    assert checkpoints[address]["history_fill_count"] == 10
