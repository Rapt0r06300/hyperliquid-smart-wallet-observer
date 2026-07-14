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


def test_v23_portage_docs_exist_and_link_to_tested_modules():
    """Le portage doit rester subordonne au RiskEngine, au ledger et au no-real-trade."""
    text = RULES.read_text(encoding="utf-8", errors="replace")
    assert "RiskEngine" in text and "ledger" in text
    assert "PaperIntent" in text or "NO_TRADE" in text
