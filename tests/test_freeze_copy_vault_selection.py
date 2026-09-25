from __future__ import annotations

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
    assert selection["observation_only"] is True
    assert selection["read_only"] is True
    assert selection["real_execution"] is False
