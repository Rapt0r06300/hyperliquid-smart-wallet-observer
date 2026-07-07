import json

import pytest

from hl_observer.paper_trading.journal import PaperTradeJournal
from hl_observer.paper_trading.position_tracking import PaperPositionTracker
from hl_observer.paper_trading.order_types import MaeMfeTracker, OrderType, PaperOrder, time_stop_hit
from hl_observer.risk.breach_alerts import check_breaches


def test_journal_records_and_summarizes():
    j = PaperTradeJournal()
    j.record(kind="OPEN", coin="btc", side="long", notional_usdt=40, price=60000, now_ms=1)
    j.record(kind="CLOSE", coin="btc", side="long", realized_net_pnl_usdc=1.2, now_ms=2)
    s = j.summary()
    assert s["trades"] == 2 and s["closes"] == 1 and s["winning_closes"] == 1
    assert s["realized_net_pnl_usdc"] == 1.2
    json.dumps(j.rows())


def test_position_tracking_avg_and_unrealized():
    t = PaperPositionTracker()
    t.open_or_add(coin="BTC", side="LONG", size=1, price=100)
    t.open_or_add(coin="BTC", side="LONG", size=1, price=110)
    pos = t.position("BTC", "LONG")
    assert pos["size"] == 2 and pos["avg_price"] == 105
    assert t.unrealized_pnl_usdc({"BTC": 115}) == 20.0   # (115-105)*2
    t.reduce_or_close(coin="BTC", side="LONG", size=2)
    assert t.open_count() == 0


def test_breach_alerts_warn_and_breach():
    alerts = check_breaches(daily_loss_pct=5.5, monthly_loss_pct=12.5)  # daily breach, monthly warn(>=12)
    by = {a["layer"]: a["severity"] for a in alerts}
    assert by.get("daily") == "BREACH" and by.get("monthly") == "WARN"
    assert check_breaches() == []


def test_paper_order_types_are_simulation_only():
    assert PaperOrder(order_type=OrderType.MARKET, side="LONG", notional_usdt=40).simulation_only is True
    PaperOrder(order_type=OrderType.LIMIT, side="LONG", limit_price=100.0)
    with pytest.raises(ValueError):
        PaperOrder(order_type=OrderType.LIMIT, side="LONG")          # missing limit price
    with pytest.raises(ValueError):
        PaperOrder(order_type=OrderType.MARKET, side="LONG", external_action=True)  # forbidden


def test_time_stop_and_mae_mfe():
    assert time_stop_hit(1000, 1000 + 60_000, max_hold_ms=60_000) is True
    assert time_stop_hit(1000, 1500, max_hold_ms=60_000) is False
    m = MaeMfeTracker()
    for v in (5, -8, 12, -3):
        m.update(v)
    assert m.mae_bps == -8 and m.mfe_bps == 12
