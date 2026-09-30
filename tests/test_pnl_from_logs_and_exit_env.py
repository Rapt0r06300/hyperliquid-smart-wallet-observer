"""R1 câblage réel (juge sur logs jsonl, robuste au tronqué) + config exit par env.
Paper / read-only ; ne modifie aucun log."""

import json

from hl_observer.backtest.pnl_from_logs import ab_logs, load_realized_pnls, summarize_log
from hl_observer.exits.exit_policy import exit_policy_config_from_env


def _write(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_load_skips_malformed_and_reads_closed(tmp_path):
    p = tmp_path / "dec.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"exit_method": "SLTP_TAKE_PROFIT", "estimated_net_pnl_usdc": 3.0}) + "\n")
        fh.write(json.dumps({"exit_method": "SLTP_STOP_LOSS", "estimated_net_pnl_usdc": -1.0}) + "\n")
        fh.write(json.dumps({"paper_action_type": "OPEN", "estimated_net_pnl_usdc": 0.0}) + "\n")  # pas clôture
        fh.write('{"exit_method": "SLTP_TAKE_PROFIT", "estimated_net_pnl_usdc": 2.\n')  # tronque
    pnls = load_realized_pnls(str(p))
    assert sorted(pnls) == [-1.0, 3.0]  # ligne tronquée ignorée, OPEN ignoré


def test_summarize_log_profit_factor(tmp_path):
    p = tmp_path / "dec.jsonl"
    _write(p, [
        {"exit_method": "TP", "estimated_net_pnl_usdc": 4.0},
        {"exit_method": "SL", "estimated_net_pnl_usdc": -1.0},
        {"exit_method": "TP", "estimated_net_pnl_usdc": 2.0},
    ])
    s = summarize_log(str(p))
    assert s["total_trades"] == 3
    assert s["gross_profit"] == 6.0 and s["gross_loss"] == 1.0
    assert s["profit_factor"] == 6.0


def test_ab_logs_verdict(tmp_path):
    base = tmp_path / "a.jsonl"; var = tmp_path / "b.jsonl"
    _write(base, [{"exit_method": "x", "estimated_net_pnl_usdc": v} for v in (3.0, -3.0, 2.0, -2.0)])
    _write(var, [{"exit_method": "x", "estimated_net_pnl_usdc": v} for v in (4.0, -1.0, 4.0, -1.0)])
    r = ab_logs(str(base), str(var))
    assert r["verdict"] == "KEEP_VARIANT"


def test_exit_policy_env_deny_by_default():
    assert exit_policy_config_from_env({}) is None
    cfg = exit_policy_config_from_env({"HYPERSMART_EXIT_POLICY_ENABLED": "1",
                                       "HYPERSMART_EXIT_TRAILING_BPS": "25"})
    assert cfg is not None and cfg.trailing_bps == 25.0
