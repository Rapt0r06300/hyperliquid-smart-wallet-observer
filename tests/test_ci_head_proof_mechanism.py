"""AUD-042 — la MECANIQUE de preuve CI liee au HEAD est verrouillee (SHA-tie).

La preuve CI-verte PUBLIQUE d'un HEAD est un artefact produit PAR la CI au run (push requis). Ce
test verrouille la mecanique LOCALE qui la produit et la valide, pour qu'un push produise
automatiquement une preuve liee au bon SHA : le workflow verifie checkout HEAD == GITHUB_SHA, emet
CI_HEAD_PROOF.json (schema hypersmart.ci_head_proof.v1) lie a GITHUB_SHA, et le validateur
(validation_portable.CI_SCHEMA) attend EXACTEMENT ce schema. 0 reseau.
"""
from __future__ import annotations
from pathlib import Path

from hl_observer.ops.validation_portable import CI_SCHEMA

RACINE = Path(__file__).resolve().parents[1]
WF = (RACINE / ".github" / "workflows" / "portable-release-windows.yml").read_text(encoding="utf-8")


def test_le_workflow_lie_le_checkout_au_sha():
    assert "GITHUB_SHA" in WF
    assert "Checkout HEAD does not match GITHUB_SHA" in WF


def test_le_workflow_emet_la_preuve_ci_head():
    assert "CI_HEAD_PROOF.json" in WF
    assert "hypersmart.ci_head_proof.v1" in WF
    assert "Emit exact-head CI proof" in WF


def test_le_validateur_attend_le_meme_schema():
    assert CI_SCHEMA == "hypersmart.ci_head_proof.v1"
    assert CI_SCHEMA in WF
