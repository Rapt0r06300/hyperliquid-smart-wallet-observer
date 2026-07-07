"""A5: runtime IA (mémoire persistante, ingestion refus shadow, analyste)."""

from __future__ import annotations

from hl_observer.integration.ia_runtime import IARuntime


def test_disabled_by_default_degrades_safely(monkeypatch, tmp_path):
    monkeypatch.delenv("HYPERSMART_IA_MEMORY", raising=False)
    ia = IARuntime(str(tmp_path / "ia.sqlite3"))
    assert ia.enabled is False
    assert ia.on_closed_trade("d1", 1000, {"edge": 40}, 0.5) is False   # ne casse pas
    assert ia.corpus_size() == 0
    assert "shadow" in ia.explain({"action": "OPEN", "coin": "HYPE"})   # analyste marche quand même


def test_enabled_persists_and_survives_reopen(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPERSMART_IA_MEMORY", "1")
    db = str(tmp_path / "ia.sqlite3")
    ia = IARuntime(db)
    assert ia.on_closed_trade("d1", 1000, {"edge": 40}, 0.5) is True
    assert ia.corpus_size() == 1
    del ia
    ia2 = IARuntime(db)                       # simule un restart serveur
    assert ia2.corpus_size() == 1            # mémoire intacte


def test_ingest_refusals_grows_corpus(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPERSMART_IA_MEMORY", "1")
    ia = IARuntime(str(tmp_path / "ia.sqlite3"))
    ts = 1_000_000
    refusals = [{
        "status": "REJECT_NO_TRADE", "paper_action_type": "NO_TRADE",
        "coin": "HYPE", "leader_side": "LONG", "leader_price": 100.0, "observed_at_ms": ts,
        "reason": "EDGE_TOO_SMALL", "edge_remaining_bps": 40, "liquidity_score": 0.8,
    }]
    marks = {"HYPE": [(ts / 1000.0 + i * 60, p) for i, p in enumerate([100.0, 100.5, 101.2])]}
    n = ia.ingest_refusals(refusals, marks)
    assert n == 1 and ia.corpus_size() == 1  # le refus est devenu un échantillon shadow
