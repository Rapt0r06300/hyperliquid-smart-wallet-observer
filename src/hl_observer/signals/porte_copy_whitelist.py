"""PORTE COPY-WHITELIST (#185, 20/07) — le DEUXIÈME verrou du copy-follow.

CONTEXTE
--------
Le copy global est mort et enterré : −7,97 bps sur 24 133 signaux OOS, à coût ZÉRO
(loi du 11/07 — le leader moyen est contrarien). Le premier verrou (edge empirique,
fusion_runtime) bloque donc le chemin. MAIS la mesure C12 a montré qu'une MINORITÉ de
leaders a un markout forward positif individuel : `tools/ecrire_copy_whitelist.py` les
sélectionne (deny-by-default : peu d'événements → rejeté) dans
`runtime/data/copy_whitelist.json`.

CE MODULE = la porte qui impose : même si le verrou d'edge s'ouvrait un jour, on ne suit
QUE des leaders individuellement prouvés. Une whitelist n'invente jamais un edge — elle
RESTREINT. Les deux verrous sont en SÉRIE, jamais en parallèle.

DENY-BY-DEFAULT ABSOLU : fichier absent, vide, périmé, illisible, signal sans adresse,
ou leaders hors liste → REFUS motivé. Aucun de ces cas n'est une exception silencieuse.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

#: au-delà, la liste est PÉRIMÉE : un markout mesuré il y a 3 jours ne vaut plus permission
AGE_MAX_WHITELIST_H = 24.0

CHEMIN_WHITELIST = Path("runtime") / "data" / "copy_whitelist.json"

MOTIF_ABSENTE = "COPY_WHITELIST_ABSENTE"
MOTIF_ILLISIBLE = "COPY_WHITELIST_ILLISIBLE"
MOTIF_VIDE = "COPY_WHITELIST_VIDE_VERROUILLEE"
MOTIF_PERIMEE = "COPY_WHITELIST_PERIMEE"
MOTIF_SANS_ADRESSE = "COPY_SIGNAL_SANS_ADRESSE"
MOTIF_HORS_LISTE = "COPY_LEADERS_HORS_WHITELIST"


def charger_whitelist(root: str | Path = ".", *, now: float | None = None) -> dict:
    """{adresses: frozenset, motif_indispo: str|None}. Ne lève jamais — elle REFUSE."""
    chemin = Path(root) / CHEMIN_WHITELIST
    if not chemin.exists():
        return {"adresses": frozenset(), "motif_indispo": MOTIF_ABSENTE}
    try:
        d = json.loads(chemin.read_text(encoding="utf-8"))
        gardes = d.get("gardes") or []
        genere = float(d.get("genere_ts") or 0.0)
    except (ValueError, OSError, TypeError):
        return {"adresses": frozenset(), "motif_indispo": MOTIF_ILLISIBLE}
    age_h = ((now if now is not None else time.time()) - genere) / 3600.0
    if genere <= 0 or age_h > AGE_MAX_WHITELIST_H:
        return {"adresses": frozenset(), "motif_indispo": MOTIF_PERIMEE}
    adresses = frozenset(
        str(g.get("adresse") or "").lower() for g in gardes if g.get("adresse")
    )
    if not adresses:
        # liste vide = verrouillé PAR CONSTRUCTION (aucun leader prouvé -> personne à suivre)
        return {"adresses": frozenset(), "motif_indispo": MOTIF_VIDE}
    return {"adresses": adresses, "motif_indispo": None}


def signal_copy_autorise(adresses_votantes, root: str | Path = ".", *,
                         now: float | None = None) -> tuple[bool, str | None]:
    """(autorise, motif_de_refus). TOUS les votants gagnants doivent être whitelistés.

    Pourquoi TOUS et pas « au moins un » : le consensus C14 compte des voix ; si une seule
    voix vient d'un leader non prouvé, le consensus est contaminé par du bruit contrarien
    mesuré. On ne moyenne pas un leader prouvé avec un leader réfuté."""
    votants = [str(a or "").lower() for a in (adresses_votantes or []) if a]
    if not votants:
        return False, MOTIF_SANS_ADRESSE
    wl = charger_whitelist(root, now=now)
    if wl["motif_indispo"]:
        return False, wl["motif_indispo"]
    hors = [a for a in votants if a not in wl["adresses"]]
    if hors:
        return False, MOTIF_HORS_LISTE
    return True, None


__all__ = ["charger_whitelist", "signal_copy_autorise", "AGE_MAX_WHITELIST_H",
           "CHEMIN_WHITELIST", "MOTIF_ABSENTE", "MOTIF_ILLISIBLE", "MOTIF_VIDE",
           "MOTIF_PERIMEE", "MOTIF_SANS_ADRESSE", "MOTIF_HORS_LISTE"]
