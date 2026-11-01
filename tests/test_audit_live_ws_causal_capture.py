from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "audit_live_ws_causal_capture.py"


def _run(tmp_path: Path, rows: list[dict]) -> tuple[int, dict]:
    source = tmp_path / "vault_fills_live.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    output = tmp_path / "receipt.json"
    result = subprocess.run(
        [sys.executable, str(TOOL), str(source), "--output", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode, json.loads(output.read_text(encoding="utf-8"))


def test_missing_ack_epoch_fails_closed(tmp_path: Path) -> None:
    code, receipt = _run(tmp_path, [{
        "source": "LIVE_WS",
        "isSnapshot": False,
        "received_at_ms": 1010,
        "stable_event_id": "event-1",
        "ts_ms": 1000,
        "coin": "SOL",
        "tid": 7,
    }])
    assert code == 2
    assert receipt["validation"]["status"] == "NOT_PROVEN"
    assert receipt["claims"]["causal_live_fill_rows"] == 0
    assert any("ACK_RECEIVED_AT_MS_MISSING" in item for item in receipt["capture"]["missing_evidence"])


def test_real_row_contract_can_be_proven(tmp_path: Path) -> None:
    code, receipt = _run(tmp_path, [{
        "source": "LIVE_WS",
        "isSnapshot": False,
        "received_at_ms": 1010,
        "ack_received_at_ms": 1005,
        "capture_epoch": "socket-A-epoch-1",
        "post_ack": True,
        "stable_event_id": "event-1",
        "ts_ms": 1000,
        "coin": "SOL",
        "tid": 7,
    }])
    assert code == 0
    assert receipt["validation"]["status"] == "PROVEN"
    assert receipt["claims"]["anti_double_count"] is True
