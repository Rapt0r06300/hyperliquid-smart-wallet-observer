from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.ops import portable_smoke as PS  # noqa: E402
from hl_observer.ops import session_catalog as SC  # noqa: E402


def test_portable_smoke_uses_real_normalizer_ledger_and_session(tmp_path):
    result = PS.executer_smoke_portable(
        tmp_path,
        horloge=lambda: 1_700_000_000.0,
        run_id="portable-smoke-test",
    )
    assert result["ok"] is True
    assert result["data_origin"] == "SYNTHETIQUE"
    assert result["presented_as_real_market_data"] is False
    assert result["network_used"] is False and result["real_execution"] is False
    assert result["ledger_reconciliation"]["ok"] is True
    assert result["ledger"]["positions"] == {}
    assert result["ledger"]["event_count"] >= 5
    session = SC.scanner_sessions(tmp_path)
    assert session[0]["statut"] == SC.STATUT_COMPLETE
    report = Path(result["report_json"])
    assert report.is_file()
    assert json.loads(report.read_text(encoding="utf-8"))["run_id"] == "portable-smoke-test"


def test_portable_smoke_cli_returns_nonzero_on_unusable_root(monkeypatch, capsys):
    monkeypatch.setattr(PS, "executer_smoke_portable", lambda _root: (_ for _ in ()).throw(RuntimeError("boom")))
    assert PS.main(["--root", "."]) == 1
    assert "PORTABLE_SMOKE_FAILED" in capsys.readouterr().out
