"""[DATA pépite 274] RESEARCH-STREAM SHEDDING : en surcharge, on abandonne D'ABORD la télémétrie / les flux
research non essentiels, JAMAIS les flux critiques (hedge, BBO/L2, execution state). La dégradation est
ordonnée et explicite : sous charge légère on lâche RESEARCH ; sous charge lourde on lâche aussi IMPORTANT ; le
CRITIQUE est protégé en toutes circonstances. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

CRITIQUE = "CRITIQUE"
IMPORTANT = "IMPORTANT"
RESEARCH = "RESEARCH"

# Niveau de surcharge à partir duquel chaque classe est abandonnée (CRITIQUE jamais).
_SEUIL_ABANDON = {RESEARCH: 1, IMPORTANT: 2}


def decider(flux: list[dict[str, Any]], niveau_surcharge: int) -> dict[str, Any]:
    """flux = [{"nom":.., "classe": CRITIQUE|IMPORTANT|RESEARCH}]. niveau 0 = rien lâché ; 1 = RESEARCH lâché ;
    ≥2 = RESEARCH + IMPORTANT lâchés. CRITIQUE toujours protégé. Classe inconnue → traitée comme RESEARCH
    (abandonnée en premier, prudence : on ne protège pas par défaut un flux non classé critique)."""
    abandonnes: list[str] = []
    proteges: list[str] = []
    for f in flux:
        classe = f.get("classe")
        if classe == CRITIQUE:
            proteges.append(f.get("nom"))
            continue
        seuil = _SEUIL_ABANDON.get(classe, 1)      # non classé -> comme RESEARCH
        if niveau_surcharge >= seuil:
            abandonnes.append(f.get("nom"))
        else:
            proteges.append(f.get("nom"))
    return {"abandonnes": abandonnes, "proteges": proteges, "critique_toujours_protege": True}


__all__ = ["decider", "CRITIQUE", "IMPORTANT", "RESEARCH"]
