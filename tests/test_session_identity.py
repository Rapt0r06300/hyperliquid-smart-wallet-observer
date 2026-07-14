"""#286 — identite de session : manifeste, priorite env, et LE LECTEUR (melange detecte)."""
from __future__ import annotations

import json

from hl_observer.runtime.session_identity import (
    SESSION_ENV, demarrer_session, lire_manifest, session_courante, verifier_coherence,
)


def test_demarrer_et_lire(tmp_path, monkeypatch):
    monkeypatch.delenv(SESSION_ENV, raising=False)
    sid = demarrer_session(tmp_path, now_ms=1_000_000)
    assert sid.startswith("S")
    m = lire_manifest(tmp_path)
    assert m and m["session_id"] == sid and m["started_at_ms"] == 1_000_000
    assert m["real_execution"] is False
    assert session_courante(tmp_path) == sid


def test_env_prioritaire_et_jamais_inventee(tmp_path, monkeypatch):
    monkeypatch.setenv(SESSION_ENV, "S-ENV")
    assert session_courante(tmp_path) == "S-ENV"
    monkeypatch.delenv(SESSION_ENV, raising=False)
    assert session_courante(tmp_path) == ""      # pas de manifeste -> VIDE, pas d'invention


def test_verifier_manifeste_absent(tmp_path, monkeypatch):
    monkeypatch.delenv(SESSION_ENV, raising=False)
    ok, motifs = verifier_coherence(tmp_path)
    assert not ok and "MANIFEST_SESSION_ABSENT" in motifs[0]


def test_verifier_engine_status_autre_session(tmp_path, monkeypatch):
    monkeypatch.delenv(SESSION_ENV, raising=False)
    demarrer_session(tmp_path, session_id="S-A", now_ms=2_000_000)
    es = tmp_path / "runtime" / "data" / "hypersmart_engine_status.json"
    es.write_text(json.dumps({"session_id": "S-B"}), encoding="utf-8")
    ok, motifs = verifier_coherence(tmp_path)
    assert not ok and any("ENGINE_STATUS_AUTRE_SESSION" in m for m in motifs)


def test_verifier_ledger_melange_detecte(tmp_path, monkeypatch):
    """LE test qui compte : un ledger qui contient une session PRECEDENTE doit faire echouer."""
    monkeypatch.delenv(SESSION_ENV, raising=False)
    START = 1_783_500_000_000                     # epoch ms realiste (2026)
    demarrer_session(tmp_path, session_id="S-A", now_ms=START)
    ledger = tmp_path / "logs" / "logs à envoyer" / "simulation_pnl_ledger_latest.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({"ts_ms": START - 3_600_000, "event": "OPEN"}) + "\n", encoding="utf-8")
    ok, motifs = verifier_coherence(tmp_path)
    assert not ok and any("LEDGER_MELANGE_DE_SESSIONS" in m for m in motifs)
    # le meme ledger en SECONDES epoch doit etre detecte pareil (conversion 1e9..1e12)
    ledger.write_text(json.dumps({"ts": (START - 3_600_000) / 1000.0, "event": "OPEN"}) + "\n", encoding="utf-8")
    ok_s, motifs_s = verifier_coherence(tmp_path)
    assert not ok_s and any("LEDGER_MELANGE_DE_SESSIONS" in m for m in motifs_s)
    # et un ledger de LA session passe
    ledger.write_text(json.dumps({"ts_ms": START + 60_000, "event": "OPEN"}) + "\n", encoding="utf-8")
    ok2, motifs2 = verifier_coherence(tmp_path)
    assert ok2 and motifs2 == []
