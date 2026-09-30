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
QUE des leaders individuellement prouvés ET une campagne Copy-Vault vNext frozen
explicitement certifiée. La whitelist legacy ne peut plus ouvrir la promotion : elle
RESTREINT seulement une preuve économique vNext valide.

DENY-BY-DEFAULT ABSOLU : fichier absent, vide, périmé, illisible, signal sans adresse,
leader hors liste, campagne vNext absente/illisible/invalide ou famille différente →
REFUS motivé. Aucun de ces cas n'est une exception silencieuse.
"""
from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path

from hl_observer.simulation.vnext_promotion_protocol import validate_certification_entry

#: au-delà, la liste est PÉRIMÉE : un markout mesuré il y a 3 jours ne vaut plus permission
AGE_MAX_WHITELIST_H = 24.0

CHEMIN_WHITELIST = Path("runtime") / "data" / "copy_whitelist.json"
CHEMIN_CERTIFICATION_VNEXT = (
    Path("runtime") / "reports" / "economic_campaigns" / "copy_vault.json"
)

MOTIF_ABSENTE = "COPY_WHITELIST_ABSENTE"
MOTIF_ILLISIBLE = "COPY_WHITELIST_ILLISIBLE"
MOTIF_VIDE = "COPY_WHITELIST_VIDE_VERROUILLEE"
MOTIF_PERIMEE = "COPY_WHITELIST_PERIMEE"
MOTIF_SANS_ADRESSE = "COPY_SIGNAL_SANS_ADRESSE"
MOTIF_HORS_LISTE = "COPY_LEADERS_HORS_WHITELIST"
MOTIF_CERTIFICATION_VNEXT_INVALIDE = "COPY_CERTIFICATION_VNEXT_ABSENTE_OU_INVALIDE"


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
        return {"adresses": frozenset(), "motif_indispo": MOTIF_VIDE}
    return {"adresses": adresses, "motif_indispo": None}


def _certification_vnext_copy_valide(root: str | Path) -> bool:
    """Vérifie la preuve canonique frozen ; toute ambiguïté refuse la promotion."""
    chemin = Path(root) / CHEMIN_CERTIFICATION_VNEXT
    try:
        campagne = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(campagne, Mapping):
        return False
    if str(campagne.get("family") or "").strip().lower() != "copy_vault":
        return False
    preuve = campagne.get("vnext_promotion")
    if not isinstance(preuve, Mapping):
        return False
    freeze = preuve.get("freeze_manifest")
    if not isinstance(freeze, Mapping):
        return False
    if str(freeze.get("family") or "").strip().lower() != "copy_vault":
        return False
    try:
        return bool(validate_certification_entry(preuve))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def signal_copy_autorise(adresses_votantes, root: str | Path = ".", *,
                         now: float | None = None) -> tuple[bool, str | None]:
    """(autorise, motif_de_refus). Whitelist restrictive + preuve vNext obligatoire.

    TOUS les votants gagnants doivent être whitelistés. Ensuite seulement, la campagne
    Copy-Vault frozen doit porter une entrée vNext certifiable liée à la même famille.
    Une whitelist legacy fraîche, même parfaite, n'est donc jamais une autorisation seule.
    """
    votants = [str(a or "").lower() for a in (adresses_votantes or []) if a]
    if not votants:
        return False, MOTIF_SANS_ADRESSE
    wl = charger_whitelist(root, now=now)
    if wl["motif_indispo"]:
        return False, wl["motif_indispo"]
    hors = [a for a in votants if a not in wl["adresses"]]
    if hors:
        return False, MOTIF_HORS_LISTE
    if not _certification_vnext_copy_valide(root):
        return False, MOTIF_CERTIFICATION_VNEXT_INVALIDE
    return True, None


__all__ = [
    "charger_whitelist", "signal_copy_autorise", "AGE_MAX_WHITELIST_H",
    "CHEMIN_WHITELIST", "CHEMIN_CERTIFICATION_VNEXT", "MOTIF_ABSENTE",
    "MOTIF_ILLISIBLE", "MOTIF_VIDE", "MOTIF_PERIMEE", "MOTIF_SANS_ADRESSE",
    "MOTIF_HORS_LISTE", "MOTIF_CERTIFICATION_VNEXT_INVALIDE",
]
