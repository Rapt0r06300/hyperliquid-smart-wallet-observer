"""Le rapport unifié agrège les flux détaillés + statut replay, sans jamais lever."""

from __future__ import annotations

from hl_observer.runtime import detailed_logger as dl
from hl_observer.runtime import detailed_report as dr


def test_gather_and_render_reflect_logged_events(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSMART_UI_STATE_DIR", str(tmp_path))
    dl.log_trade("CLOSE", "HYPE", "LONG", net_pnl_usdc=0.8, reason="TP", runtime_data_dir=tmp_path)
    dl.log_error("poll", ValueError("boom"), runtime_data_dir=tmp_path)
    rep = dr.gather(runtime_data_dir=tmp_path)
    assert rep["summary"]["trade"]["count"] >= 1
    assert rep["summary"]["error"]["count"] >= 1
    txt = dr.render_text(rep)
    assert "RAPPORT ULTRA-DÉTAILLÉ" in txt and "ERREURS" in txt
    assert "HYPE" in txt and "boom" in txt


def test_replay_status_flags_off_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPERSMART_V26_RECORD_CANDIDATES", raising=False)
    monkeypatch.setenv("HYPERSMART_V26_RECORD_PATH", str(tmp_path / "replay"))
    rep = dr.gather(runtime_data_dir=tmp_path)
    assert rep["replay"]["enabled"] is False
    assert "recording OFF" in dr.render_text(rep)


def test_replay_status_on_when_env_set(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSMART_V26_RECORD_CANDIDATES", "1")
    monkeypatch.setenv("HYPERSMART_V26_RECORD_PATH", str(tmp_path / "replay"))
    rep = dr.gather(runtime_data_dir=tmp_path)
    assert rep["replay"]["enabled"] is True
