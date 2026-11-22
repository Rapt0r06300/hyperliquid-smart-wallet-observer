r"""Socle commun de la chasse a l'alpha (mission 2) : fenetres figees, chargement, registre.

TOUT ESSAI PASSE PAR ICI, pour trois raisons :

1. **Les fenetres sont figees dans le code**, pas dans la tete du chercheur. Une etude ne peut pas
   « deborder » sur la validation ou l'OOS par un filtre de date oublie : `charger()` exige le
   nom du segment et refuse `oos_final` tant que `--ouvrir-oos-final` n'est pas donne en clair.
2. **Chaque essai est compte.** `enregistrer()` ajoute une ligne au registre chaine (meme
   mecanisme que l'etude de copiabilite : `append_ledger`, SHA du precedent). Le nombre total
   d'essais sert a corriger la significativite ; un essai non enregistre est un essai cache.
3. **Une seule source pour les couts.** Les frais viennent de `research.cost_model`, pas d'une
   constante recopiee.

Segments (figes le 22/11/2026, AVANT tout resultat) :

    exploration   26/04/2026 -> 31/08/2026   on y cherche
    validation    01/09/2026 -> 25/10/2026   consultee UNE fois par hypothese figee
    execution     26/10/2026 -> 12/11/2026   prix d'execution au BBO observe
    oos_final     13/11/2026 -> ...          VERROUILLE

⚠️ Biais de survie : l'univers est celui des « leaders lents » retenus en novembre 2026. Tout
resultat qui suit leur DIRECTION est flatte sur le passe ; seules les differences conditionnelles
et les effets de structure de marche s'y mesurent proprement.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys
import time
from typing import Any

RACINE = pathlib.Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

CACHE = RACINE / "runtime" / "research_lab" / "data" / "goal2_cache"
REGISTRE = RACINE / "runtime" / "reports" / "copy_vault_quant_lab" / "goal2" / "ESSAIS.ndjson"
HEURE_MS = 3_600_000
JOUR_MS = 86_400_000


def _ms(annee: int, mois: int, jour: int) -> int:
    return int(dt.datetime(annee, mois, jour, tzinfo=dt.UTC).timestamp() * 1000)


#: Bornes [debut, fin[ en millisecondes UTC. Ne JAMAIS les modifier apres un resultat.
SEGMENTS: dict[str, tuple[int, int]] = {
    "exploration": (_ms(2026, 4, 26), _ms(2026, 9, 1)),
    "validation": (_ms(2026, 9, 1), _ms(2026, 10, 26)),
    "execution": (_ms(2026, 10, 26), _ms(2026, 11, 13)),
    "oos_final": (_ms(2026, 11, 13), _ms(2027, 1, 1)),
    # Deux moities du segment d'execution, figees le 22/11 AVANT toute lecture (essai L2-fin) :
    # A pour chercher un horizon a la minute, B pour le confirmer une seule fois.
    "execution_a": (_ms(2026, 10, 26), _ms(2026, 11, 4)),
    "execution_b": (_ms(2026, 11, 4), _ms(2026, 11, 13)),
}
SEGMENTS_OUVERTS = ("exploration", "validation", "execution", "execution_a", "execution_b")


def bornes(segment: str, *, ouvrir_oos_final: bool = False) -> tuple[int, int]:
    if segment not in SEGMENTS:
        raise ValueError(f"segment inconnu : {segment!r} ; attendus : {sorted(SEGMENTS)}")
    if segment == "oos_final" and not ouvrir_oos_final:
        raise PermissionError(
            "OOS_FINAL_VERROUILLE : ce segment ne s'ouvre qu'une fois, pour une regle deja figee, "
            "et sur demande explicite (`ouvrir_oos_final=True`).")
    return SEGMENTS[segment]


def frais_aller_retour_bps() -> float:
    """Frais taker aller-retour Hyperliquid, lus a la source unique du depot."""
    from hl_observer.research.cost_model import fees_roundtrip_taker_bps

    return float(fees_roundtrip_taker_bps("hyperliquid"))


def charger(table: str, segment: str, *, marge_avant_ms: int = 0, marge_apres_ms: int = 0,
            ouvrir_oos_final: bool = False):
    """Une table du cache, bornee au segment. Les marges servent aux PRIX seulement.

    `marge_apres_ms` existe parce qu'un rendement futur a besoin de bougies posterieures au
    signal ; elle ne doit jamais servir a lire des SIGNAUX hors segment. Elle est en outre
    rabotee pour ne jamais mordre sur l'OOS final.
    """
    import pandas as pd

    debut, fin = bornes(segment, ouvrir_oos_final=ouvrir_oos_final)
    colonne = "t_ms" if table.startswith("candles") else "ts_ms"
    haut = fin + marge_apres_ms
    if not ouvrir_oos_final:
        haut = min(haut, SEGMENTS["oos_final"][0])
    df = pd.read_parquet(CACHE / f"{table}.parquet")
    return df[(df[colonne] >= debut - marge_avant_ms) & (df[colonne] < haut)].reset_index(drop=True)


def enregistrer(essai: dict[str, Any]) -> str:
    """Ajoute l'essai au registre chaine. Rend le SHA de la ligne."""
    from etude_copiabilite import append_ledger

    corps = {"schema": "alina.goal2.essai.v1", "enregistre_ms": int(time.time() * 1000), **essai}
    for clef in ("hypothese", "segment", "statut"):
        if clef not in corps:
            raise ValueError(f"essai sans `{clef}` : un essai se nomme, se situe et se conclut")
    return append_ledger(REGISTRE, corps)


def nombre_d_essais() -> int:
    if not REGISTRE.is_file():
        return 0
    return sum(1 for ligne in REGISTRE.read_text(encoding="utf-8").splitlines() if ligne.strip())


def ic_bootstrap_par_blocs(valeurs, blocs, *, tirages: int = 2000, graine: int = 20261122,
                           niveau: float = 0.95) -> tuple[float, float, float]:
    """(moyenne, borne basse, borne haute) par bootstrap de BLOCS entiers.

    Des evenements du meme jour ne sont pas independants (meme marche, memes leaders). Tirer les
    lignes une a une fabriquerait des intervalles trop etroits ; on tire donc les blocs (jours).
    """
    import numpy as np

    valeurs = np.asarray(valeurs, dtype=float)
    blocs = np.asarray(blocs)
    garde = np.isfinite(valeurs)
    valeurs, blocs = valeurs[garde], blocs[garde]
    if valeurs.size == 0:
        return float("nan"), float("nan"), float("nan")
    uniques, inverse = np.unique(blocs, return_inverse=True)
    sommes = np.bincount(inverse, weights=valeurs, minlength=uniques.size)
    comptes = np.bincount(inverse, minlength=uniques.size).astype(float)
    rng = np.random.default_rng(graine)
    tires = rng.integers(0, uniques.size, size=(tirages, uniques.size))
    moyennes = sommes[tires].sum(axis=1) / np.maximum(1.0, comptes[tires].sum(axis=1))
    bas, haut = np.quantile(moyennes, [(1 - niveau) / 2, 1 - (1 - niveau) / 2])
    return float(valeurs.mean()), float(bas), float(haut)
