"""AUD-041 — registre GIT_HEAD_AUDIT_TRAIL present et bien forme (SHA de reprise + pointeur journal)."""
from __future__ import annotations
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DOC = RACINE / "docs" / "audit" / "GIT_HEAD_AUDIT_TRAIL.md"
REF = "8e899a20cd05d7b0c689a447f086b0bdae9d18ca"


def test_registre_existe():
    assert DOC.is_file()


def test_nomme_le_sha_de_reprise():
    assert REF in DOC.read_text(encoding="utf-8")


def test_pointe_le_journal_des_commits():
    t = DOC.read_text(encoding="utf-8")
    assert "TACHES_HYPERSMART_V6_COMPLET.md" in t and "git log" in t
