"""A6: runtime OPS (payload dashboard alertes+refus+coût, backup throttlé)."""

from __future__ import annotations

from hl_observer.integration.ops_runtime import build_ops_payload, maybe_backup


def test_ops_payload_merges_alerts_and_refusal_cost():
    status = {"halt_state": "RED", "session_drawdown_usd": 25.0}
    ledger = [
        {"status": "REJECT_NO_TRADE", "paper_action_type": "NO_TRADE", "reason": "EDGE_TOO_SMALL", "coin": "MON", "leader_notional_usdc": 25},
        {"status": "REJECT_NO_TRADE", "paper_action_type": "NO_TRADE", "reason": "EDGE_TOO_SMALL", "coin": "LIT", "leader_notional_usdc": 30},
    ]
    shadow = [{"reason": "EDGE_TOO_SMALL", "shadow_net_pnl_usdc": 0.5}, {"reason": "EDGE_TOO_SMALL", "shadow_net_pnl_usdc": 0.4}]
    payload = build_ops_payload(status=status, ledger_events=ledger, now_ms=200_000, refusal_shadow_rows=shadow)
    assert payload["alerts_summary"]["worst"] == "CRITICAL"
    assert payload["refusal_breakdown"]["total_refusals"] == 2
    # le coût du gate est fusionné dans le breakdown
    edge_row = next(r for r in payload["refusal_breakdown"]["rows"] if r["reason"] == "EDGE_TOO_SMALL")
    assert "net_benefit_usdc" in edge_row and edge_row["verdict"] == "GATE_TOO_STRICT_COSTS_PNL"
    assert "EDGE_TOO_SMALL" in payload["costly_gates"]
    assert payload["read_only"] is True


def test_ops_payload_healthy_no_alerts():
    payload = build_ops_payload(status={"halt_state": "GREEN"}, ledger_events=[], now_ms=1)
    assert payload["alerts"] == [] and payload["refusal_breakdown"]["total_refusals"] == 0


def test_backup_off_by_default(monkeypatch):
    monkeypatch.delenv("HYPERSMART_OPS_BACKUP", raising=False)
    assert maybe_backup({"x": 1}, "/tmp/none.json")["reason"] == "BACKUP_OFF"


def test_backup_writes_and_throttles(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPERSMART_OPS_BACKUP", "1")
    import hl_observer.integration.ops_runtime as ops
    ops._LAST_BACKUP_MS = 0
    path = str(tmp_path / "state.json")
    first = maybe_backup({"equity": 1000.0}, path, min_interval_ms=300_000)
    assert first["ok"] is True
    second = maybe_backup({"equity": 1001.0}, path, min_interval_ms=300_000)
    assert second["reason"] == "THROTTLED"    # pas de spam disque
