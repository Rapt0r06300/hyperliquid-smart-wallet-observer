"""Tests de l'archivage des tapes (reset de session sans perte)."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import archiver_tapes as A  # noqa: E402


def test_archive_deplace_les_tapes_et_vide_data(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "vault_fills_live.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    (data / "copy_vault_trades_lane.jsonl").write_text('{"b":2}\n', encoding="utf-8")
    (data / "collecteurs.lock").write_text("123", encoding="utf-8")       # operationnel -> reste
    (data / "explorer_autonome.pid").write_text("456", encoding="utf-8")  # operationnel -> reste
    rap = A.archiver(tmp_path)
    assert rap["deplaces"] == 2
    # les tapes ont quitte runtime/data
    assert not (data / "vault_fills_live.jsonl").exists()
    assert not (data / "copy_vault_trades_lane.jsonl").exists()
    # les operationnels restent
    assert (data / "collecteurs.lock").exists()
    assert (data / "explorer_autonome.pid").exists()
    # elles sont dans l'archive (rien perdu)
    dest = Path(rap["dest"])
    assert (dest / "vault_fills_live.jsonl").read_text(encoding="utf-8") == '{"a":1}\n'
    assert (dest / "copy_vault_trades_lane.jsonl").exists()


def test_archive_vide_ne_fait_rien(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    rap = A.archiver(tmp_path)
    assert rap["deplaces"] == 0 and rap["dest"] is None
