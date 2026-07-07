"""OPS: alertes opérateur + GO/NO-GO + backup/restore avec intégrité."""

from __future__ import annotations

from hl_observer.ops.operator_alerts import CRITICAL, WARN, alerts_summary, evaluate_alerts
from hl_observer.ops.session_verify import go_no_go
from hl_observer.ops.state_backup import backup_state, restore_state


def test_alerts_detect_critical_conditions():
    status = {
        "halt_state": "RED",
        "kill_switch": {"active": True},
        "last_data_update_ms": 100_000,
        "session_drawdown_usd": 25.0,
        "disk_free_pct": 5.0,
    }
    alerts = evaluate_alerts(status, now_ms=200_000, max_source_silence_ms=60_000)
    codes = {a["code"] for a in alerts}
    assert {"HALT_RED", "KILL_SWITCH", "SOURCE_DEAD", "DRAWDOWN_CRIT", "DISK_LOW"} <= codes
    assert alerts[0]["severity"] == CRITICAL  # trié: critique d'abord
    s = alerts_summary(alerts)
    assert s["critical"] >= 4 and s["worst"] == CRITICAL


def test_alerts_quiet_when_healthy():
    status = {"halt_state": "GREEN", "last_data_update_ms": 195_000, "session_drawdown_usd": 0.5, "disk_free_pct": 80.0}
    assert evaluate_alerts(status, now_ms=200_000) == []


def test_restart_detected_via_boot_id():
    alerts = evaluate_alerts({"boot_id": "B"}, now_ms=1, prev_boot_id="A")
    assert any(a["code"] == "SERVER_RESTARTED" for a in alerts)


def test_go_no_go_blocks_on_safety():
    assert go_no_go({"pytest": True, "safety_audit": True, "no_real_trade": True})["verdict"] == "GO"
    bad = go_no_go({"pytest": True, "safety_audit": False, "no_real_trade": True})
    assert bad["verdict"] == "NO_GO" and "safety_audit" in bad["blocking_failures"]
    warn = go_no_go({"pytest": True, "safety_audit": True, "no_real_trade": True, "doctor": False})
    assert warn["verdict"] == "GO" and "doctor" in warn["non_blocking_warnings"]


def test_backup_restore_roundtrip_and_corruption(tmp_path):
    state = {"equity": 1000.0, "positions": [{"coin": "HYPE", "size": 0.5}], "nested": {"a": [1, 2, 3]}}
    path = str(tmp_path / "state.json")
    res = backup_state(state, path)
    assert res["ok"] is True
    back = restore_state(path)
    assert back["ok"] is True and back["state"] == state
    # corruption → refus
    import json
    env = json.loads(open(path, encoding="utf-8").read())
    env["state"]["equity"] = 9999.0  # altère sans recalculer le checksum
    open(path, "w", encoding="utf-8").write(json.dumps(env))
    assert restore_state(path)["reason"] == "CHECKSUM_MISMATCH_CORRUPT"


def test_restore_missing_is_honest(tmp_path):
    assert restore_state(str(tmp_path / "nope.json"))["reason"] == "BACKUP_NOT_FOUND"
