"""R15 — convergence ledger vs snapshot. Paper/read-only ; INSUFFICIENT_DATA si manque."""

import json

from hl_observer.audit.pnl_convergence import convergence_check, convergence_from_logs


def test_convergent_within_tolerance():
    assert convergence_check(1.2345678, 1.2345679)["status"] == "CONVERGENT"


def test_divergent_flagged():
    r = convergence_check(10.0, 7.0)
    assert r["status"] == "DIVERGENT" and r["gap"] == 3.0


def test_insufficient_data_when_missing():
    assert convergence_check(None, 1.0)["status"] == "INSUFFICIENT_DATA"


def test_from_logs_matches_ledger(tmp_path):
    p = tmp_path / "dec.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        for v in (3.0, -1.0, 2.0):     # total ledger = 4.0
            fh.write(json.dumps({"exit_method": "x", "estimated_net_pnl_usdc": v}) + "\n")
    ok = convergence_from_logs(str(p), 4.0)
    assert ok["status"] == "CONVERGENT" and ok["trades"] == 3
    bad = convergence_from_logs(str(p), 99.0)
    assert bad["status"] == "DIVERGENT"


def test_from_logs_empty_is_insufficient(tmp_path):
    p = tmp_path / "empty.jsonl"; p.write_text("", encoding="utf-8")
    assert convergence_from_logs(str(p), 1.0)["status"] == "INSUFFICIENT_DATA"
