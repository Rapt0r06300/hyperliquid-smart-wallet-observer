"""Winrate must be counted PER POSITION (round-trip), not per partial REDUCE event.
A position reduced several times = ONE trade, classed win/loss on its TOTAL realized PnL.
This is the 2026-06-26 fix for the artificially-low winrate. Pure logic spec."""

from __future__ import annotations

EXIT_ACTIONS = {"PAPER_CLOSE_REPLAYED", "PAPER_REDUCE_REPLAYED", "PAPER_CONSENSUS_REDUCE_REPLAYED"}


def _winrate_per_position(events):
    pos = {}
    for e in events:
        if e.get("status") != "LOCAL_REPLAY" or e.get("bot_replay_action") not in EXIT_ACTIONS:
            continue
        k = str(e.get("matched_position_key") or e.get("coin") or "")
        pos[k] = pos.get(k, 0.0) + float(e.get("estimated_net_pnl_usdc") or 0.0)
    rt = list(pos.values())
    w = sum(1 for p in rt if p > 0); l = sum(1 for p in rt if p < 0)
    closed = sum(1 for p in rt if p != 0)
    gw = sum(p for p in rt if p > 0); gl = -sum(p for p in rt if p < 0)
    return {"winning": w, "losing": l, "winrate": round(100 * w / closed, 1) if closed else 0.0,
            "profit_factor": round(gw / gl, 3) if gl > 0 else None}


def _winrate_per_event_OLD(events):  # the buggy way (each reduce = a trade)
    pnls = [float(e.get("estimated_net_pnl_usdc") or 0.0) for e in events
            if e.get("status") == "LOCAL_REPLAY" and e.get("bot_replay_action") in EXIT_ACTIONS]
    pnls = [p for p in pnls if p != 0]
    w = sum(1 for p in pnls if p > 0)
    return round(100 * w / len(pnls), 1) if pnls else 0.0


def test_reduces_of_one_winning_position_count_as_one_win():
    # ONE HYPE position, reduced 3x: -0.1, -0.1, then +0.5 -> total +0.3 = a WINNER
    evs = [
        {"status": "LOCAL_REPLAY", "bot_replay_action": "PAPER_REDUCE_REPLAYED", "matched_position_key": "w|HYPE|LONG", "estimated_net_pnl_usdc": -0.1},
        {"status": "LOCAL_REPLAY", "bot_replay_action": "PAPER_REDUCE_REPLAYED", "matched_position_key": "w|HYPE|LONG", "estimated_net_pnl_usdc": -0.1},
        {"status": "LOCAL_REPLAY", "bot_replay_action": "PAPER_CLOSE_REPLAYED",  "matched_position_key": "w|HYPE|LONG", "estimated_net_pnl_usdc": 0.5},
    ]
    r = _winrate_per_position(evs)
    assert r["winning"] == 1 and r["losing"] == 0 and r["winrate"] == 100.0   # ONE winning position
    assert _winrate_per_event_OLD(evs) == 33.3                                # old buggy: 1/3 = 33% (looked terrible)


def test_profit_factor_rewards_let_winners_run_even_below_50pct_winrate():
    # 1 winner +3.0, 2 losers -1.0 each -> 33% winrate but profit_factor 1.5 (PROFITABLE)
    evs = [
        {"status": "LOCAL_REPLAY", "bot_replay_action": "PAPER_CLOSE_REPLAYED", "matched_position_key": "A", "estimated_net_pnl_usdc": 3.0},
        {"status": "LOCAL_REPLAY", "bot_replay_action": "PAPER_CLOSE_REPLAYED", "matched_position_key": "B", "estimated_net_pnl_usdc": -1.0},
        {"status": "LOCAL_REPLAY", "bot_replay_action": "PAPER_CLOSE_REPLAYED", "matched_position_key": "C", "estimated_net_pnl_usdc": -1.0},
    ]
    r = _winrate_per_position(evs)
    assert r["winrate"] == 33.3 and r["profit_factor"] == 1.5   # low WR but PF>1 => net positive
