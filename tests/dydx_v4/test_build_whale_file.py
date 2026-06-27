from __future__ import annotations

from hyper_smart_observer.dydx_v4.build_whale_file import write_csv


def test_write_csv_creates_importable_whale_file(tmp_path) -> None:
    out = tmp_path / "dydx_whales.csv"
    path = write_csv(
        [
            {
                "address": "dydx1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq",
                "subaccount_number": 0,
                "net_pnl_usdc": 123.45,
                "pnl_ticks": 10,
                "usdc_balance": 5000,
                "open_positions": 2,
                "markets": "BTC-USD;ETH-USD",
                "sides": "LONG;SHORT",
                "source": "test",
                "fetched_at_ms": 1,
            }
        ],
        out,
    )

    text = path.read_text(encoding="utf-8")
    assert "address,subaccount_number,net_pnl_usdc" in text
    assert "BTC-USD;ETH-USD" in text
