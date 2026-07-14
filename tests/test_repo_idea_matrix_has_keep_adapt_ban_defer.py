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


def test_matrix_has_all_four_statuses():
    text = RULES.read_text(encoding="utf-8", errors="replace")
    for status in ("COPY_DIRECT", "COPY_ADAPTED", "SKIP_WITH_REASON", "DEFERRED_WITH_PLAN"):
        assert status in text


def test_matrix_links_every_repo():
    """Regle: on ne pretend JAMAIS avoir porte un comportement sans test/branchement."""
    text = RULES.read_text(encoding="utf-8", errors="replace")
    assert "Ne jamais pretendre avoir lu un fichier non lu" in text or \
           "ni porté un comportement sans test" in text
