from __future__ import annotations


def format_paper_report(report: dict[str, float | int]) -> str:
    return (
        "LOCAL PAPER SIMULATION ONLY\n"
        f"starting_equity={report['starting_equity']}\n"
        f"current_equity={report['current_equity']}\n"
        f"open_trades={report['open_trades']}\n"
        f"closed_trades={report['closed_trades']}\n"
        f"realized_pnl={report['realized_pnl']}\n"
        f"total_fees={report['total_fees']}\n"
        "not a trading signal; not an order"
    )
