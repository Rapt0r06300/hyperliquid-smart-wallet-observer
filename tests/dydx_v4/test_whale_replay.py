from __future__ import annotations

from hyper_smart_observer.dydx_v4.whale_replay import replay_whale_file

ADDR1 = "dydx1aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
ADDR2 = "dydx1bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def test_whale_replay_reads_and_ranks_import_file(tmp_path) -> None:
    path = tmp_path / "dydx_whales.csv"
    path.write_text(
        "address,net_pnl_usdc,usdc_balance,open_positions,markets\n"
        f"{ADDR1},100,1000,1,BTC-USD\n"
        f"{ADDR2},500000,500000,2,ETH-USD;SOL-USD\n",
        encoding="utf-8",
    )

    report = replay_whale_file(path, limit=2)

    assert report["wallets_loaded"] == 2
    assert report["wallets_selected"] == 2
    assert report["top_wallets"][0]["address"] == ADDR2
    assert report["top_markets"]["ETH-USD"] == 1
