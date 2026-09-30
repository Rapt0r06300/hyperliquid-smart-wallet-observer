"""AUD-101 — le rapport est HIÉRARCHISÉ par niveau de preuve (du plus fort au plus faible)."""
from __future__ import annotations

from hl_observer.ops import lab_rapport as LR


def test_rang_preuve_ordonne_du_fort_au_faible():
    assert (LR.rang_preuve("VALIDATED_POSITIVE_PAPER")
            < LR.rang_preuve("VALIDE_PARTIEL")
            < LR.rang_preuve("MORE_DATA")
            < LR.rang_preuve("KILL")
            < LR.rang_preuve("UNMEASURABLE"))
    assert LR.rang_preuve("verdict_inconnu") >= LR.rang_preuve("UNMEASURABLE")


def test_rapport_ordonne_les_candidats_par_niveau_de_preuve():
    rech = {"verdict_global": "NEGATIF", "candidats": [
        {"verdict": "KILL", "config": {"a": 1}},
        {"verdict": "VALIDATED_POSITIVE_PAPER", "config": {"a": 2}},
        {"verdict": "MORE_DATA", "config": {"a": 3}},
        {"verdict": "UNMEASURABLE", "config": {"a": 4}},
    ]}
    md = LR.construire_markdown(horodatage="T", source="REEL", periode=None, inv={}, audit={}, rech=rech)
    assert "Hiérarchie par niveau de preuve" in md
    section = md.split("Hiérarchie par niveau de preuve", 1)[1]
    i_val = section.index("### VALIDATED_POSITIVE_PAPER")
    i_more = section.index("### MORE_DATA")
    i_kill = section.index("### KILL")
    i_unm = section.index("### UNMEASURABLE")
    assert i_val < i_more < i_kill < i_unm


def test_section_absente_si_aucun_candidat():
    md = LR.construire_markdown(horodatage="T", source="REEL", periode=None, inv={}, audit={},
                               rech={"verdict_global": "NON_MESURABLE", "candidats": []})
    assert "Hiérarchie par niveau de preuve" not in md
