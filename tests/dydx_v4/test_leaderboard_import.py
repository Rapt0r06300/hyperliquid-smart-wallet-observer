from __future__ import annotations

import json

from hyper_smart_observer.dydx_v4.leaderboard_import import imported_wallet_rows, read_leaderboard_file

ADDR1 = "dydx1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"
ADDR2 = "dydx1pppppppppppppppppppppppppppppppppppppp"


def test_read_leaderboard_csv(tmp_path) -> None:
    path = tmp_path / "dydx_whales.csv"
    path.write_text(
        "address,net_pnl_usdc,roi_pct,winrate,profit_factor,trade_count,usdc_balance\n"
        f"{ADDR1},12345,42,0.55,1.8,80,250000\n",
        encoding="utf-8",
    )

    rows = read_leaderboard_file(path)

    assert rows == [
        (
            ADDR1,
            {
                "net_pnl_usdc": "12345",
                "roi_pct": "42",
                "winrate": "0.55",
                "profit_factor": "1.8",
                "trade_count": "80",
                "usdc_balance": "250000",
            },
        )
    ]


def test_imported_wallet_rows_merges_duplicate_metrics(tmp_path) -> None:
    csv_path = tmp_path / "a.csv"
    json_path = tmp_path / "b.json"
    csv_path.write_text(f"address,net_pnl_usdc\n{ADDR2},100\n", encoding="utf-8")
    json_path.write_text(json.dumps([{"address": ADDR2, "usdc_balance": 5000}]), encoding="utf-8")

    rows = dict(imported_wallet_rows([csv_path, json_path]))

    assert rows[ADDR2]["net_pnl_usdc"] == "100"
    assert rows[ADDR2]["usdc_balance"] == 5000
