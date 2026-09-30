"""Doctrine du projet — REECRIT a l'audit du 2026-07-11.

Ces tests exigeaient l'existence d'anciens fichiers .md (CODEX_MASTER_PLAN_V6, *_FUSION.md,
V23_*, RELEASE_*, REPO_IDEA_MATRIX...) SUPPRIMES VOLONTAIREMENT lors de la consolidation
documentaire (640 fichiers -> 7, commit 35703aa). Les ressusciter serait faux.

On garde l'INTENTION -- la doctrine doit rester ecrite quelque part et etre verifiable -- en la
testant la ou elle vit desormais : CLAUDE.md (regles), OBJECTIF.md, docs/ETAT_ET_FEUILLE_DE_ROUTE.md
(document maitre), docs/ARCHITECTURE.md.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "CLAUDE.md"
MASTER = ROOT / "docs" / "ETAT_ET_FEUILLE_DE_ROUTE.md"


def test_master_plan_present_and_states_doctrine():
    """Un document MAITRE doit exister et porter la doctrine (etat + feuille de route)."""
    assert MASTER.is_file(), "document maitre absent: docs/ETAT_ET_FEUILLE_DE_ROUTE.md"
    text = MASTER.read_text(encoding="utf-8", errors="replace")
    assert len(text) > 500, "document maitre trop pauvre pour servir de reference"
    assert RULES.is_file(), "CLAUDE.md (regles) absent"
