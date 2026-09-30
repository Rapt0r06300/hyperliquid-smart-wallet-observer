from __future__ import annotations

import json
from pathlib import Path

from hl_observer.runtime.protections import DedupDurable, JournalIncidents, scanner_ledger


def test_dedup_charge_en_streaming_sans_read_text(tmp_path, monkeypatch):
    dossier = tmp_path / "dedup"
    dossier.mkdir()
    (dossier / "dedup_journal.jsonl").write_text("a\nb\nc\n", encoding="utf-8")

    def interdit(*args, **kwargs):
        raise AssertionError("read_text ne doit pas etre utilise pour charger la dedup")

    monkeypatch.setattr(Path, "read_text", interdit)
    dedup = DedupDurable(dossier, max_ids=10)
    assert dedup.vu("a") is True
    assert dedup.vu("c") is True


def test_dedup_est_bornee_et_compaction_persiste_la_fenetre(tmp_path):
    dossier = tmp_path / "dedup"
    dedup = DedupDurable(dossier, max_ids=3, compact_every=2)
    for cle in ("a", "b", "c", "d"):
        dedup.marquer(cle)
    assert dedup.stats()["n_ids_en_memoire"] == 3
    assert dedup.vu("a") is False
    assert dedup.vu("b") is True
    recharge = DedupDurable(dossier, max_ids=3, compact_every=2)
    assert recharge.stats()["n_ids_en_memoire"] <= 3
    assert recharge.vu("d") is True


def test_journal_incidents_resume_en_streaming(tmp_path, monkeypatch):
    journal = JournalIncidents(tmp_path / "op")
    journal.enregistrer("WS_GAP", detail="x")
    journal.enregistrer("DATA_MISSING", detail="y")

    def interdit(*args, **kwargs):
        raise AssertionError("read_text ne doit pas etre utilise pour les incidents")

    monkeypatch.setattr(Path, "read_text", interdit)
    resume = journal.resume()
    assert resume["n_incidents"] == 2
    assert resume["promotion_interdite"] is True


def test_journal_read_only_absent_ne_cree_aucun_dossier(tmp_path):
    dossier = tmp_path / "absent"
    journal = JournalIncidents(dossier, create=False)
    assert journal.resume() == {
        "n_incidents": 0,
        "par_type": {},
        "promotion_interdite": False,
    }
    assert not dossier.exists()
    try:
        journal.enregistrer("WS_GAP")
    except RuntimeError as exc:
        assert "read-only" in str(exc)
    else:
        raise AssertionError("un lecteur read-only ne doit jamais pouvoir ecrire")


def test_journal_refuse_taxonomie_floue(tmp_path):
    journal = JournalIncidents(tmp_path / "op")
    try:
        journal.enregistrer("TRUC_INVENTE")
    except ValueError as exc:
        assert "inconnu" in str(exc)
    else:
        raise AssertionError("un type inconnu doit etre refuse")


def test_scanner_ledger_streaming_offsets_bytes_exacts(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    lignes = [b'{"ok":1}\n', b'PAS_JSON\n', '["é"]\n'.encode("utf-8"), b'{"ok":2}\n']
    ledger.write_bytes(b"".join(lignes))

    def interdit(*args, **kwargs):
        raise AssertionError("read_text ne doit pas etre utilise pour un ledger")

    monkeypatch.setattr(Path, "read_text", interdit)
    result = scanner_ledger(ledger)
    assert result["statut"] == "CORROMPU"
    assert result["n_erreurs"] == 2
    assert result["erreurs"][0]["ligne"] == 2
    assert result["erreurs"][0]["offset"] == len(lignes[0])
    assert result["erreurs"][1]["ligne"] == 3
    assert result["erreurs"][1]["offset"] == len(lignes[0]) + len(lignes[1])


def test_scanner_ledger_valide_un_gros_flux_sans_accumuler_les_lignes(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    with ledger.open("w", encoding="utf-8") as handle:
        for i in range(20_000):
            handle.write(json.dumps({"i": i}) + "\n")
    result = scanner_ledger(ledger)
    assert result["statut"] == "OK"
    assert result["n_lignes"] == 20_000
    assert result["n_erreurs"] == 0
