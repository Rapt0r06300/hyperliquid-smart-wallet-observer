from __future__ import annotations

from hyper_smart_observer.wallet_universe.wallet_universe import import_wallet_universe_lines


def test_wallet_universe_imports_2000_dedupes_and_rejects_bad_addresses() -> None:
    lines = [f"0x{i:040x}" for i in range(1, 2_001)]
    lines.append(f"0x{1:040x}")
    lines.append("0x1234...abcd")
    lines.append("not-a-wallet")

    result = import_wallet_universe_lines(lines, source="test_import")

    assert result.imported == 2_000
    assert result.duplicates == 1
    assert result.rejected == 2
    assert "TRUNCATED_ADDRESS_REJECTED" in result.rejected_reasons
    assert "INVALID_ADDRESS_REJECTED" in result.rejected_reasons
    assert result.entries[0].sources == {"test_import"}
    assert result.entries[0].scan_priority == 10.0
