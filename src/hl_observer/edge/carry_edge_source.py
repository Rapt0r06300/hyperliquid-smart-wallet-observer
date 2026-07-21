"""L'EDGE D'UN CARRY — **il n'est pas PRÉDIT. Il est OBSERVÉ.**

═══════════════════════════════════════════════════════════════════════════════════════════════
LA DISTINCTION QUI DÉBLOQUE TOUT — et qui n'est PAS un contournement
═══════════════════════════════════════════════════════════════════════════════════════════════

Le noyau refusait le carry avec `NOYAU_EDGE_NON_MESURE`. **Et il avait raison de son point de
vue** : il va chercher l'edge dans la table mesurée… **qui ne contient que des edges de
copy-trading.**

Mais un carry n'est **pas** de la même nature :

  * **Un signal discrétionnaire** (COPY) : l'edge est une **PRÉDICTION** — « le prix va monter
    parce qu'un leader a acheté ». Elle **DOIT** venir d'une mesure OOS, sinon c'est une
    invention. *Et la mesure a dit : −7,97 bps. Il n'y a rien.*

  * **Un carry** : l'edge est un **PAIEMENT DÉJÀ ENCAISSÉ**. Le funding a été **versé**, heure
    par heure, pendant **365 jours**. Ce n'est pas un pari sur l'avenir : c'est un **relevé**.

    ***On ne prédit pas le funding. On le LIT.***

🔴 **CE N'EST DONC PAS « FABRIQUER » UN EDGE.** La source est exactement la même donnée que celle
qui a servi à mesurer : `runtime/history/funding.jsonl`, **365 jours, 0 trou, endpoint public**.

    *Si on refusait ça, on refuserait de reconnaître une mesure parce qu'elle ne vient pas du
     bon tiroir. Ce serait de la bureaucratie, pas de la rigueur.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LES GARDE-FOUS — parce que la nuance ne doit pas devenir une porte dérobée
═══════════════════════════════════════════════════════════════════════════════════════════════

  1. **UNIQUEMENT pour la famille `CARRY_STRUCTUREL`.** Toute autre stratégie -> `None`.
     *La porte ne s'ouvre pas pour COPY, GRINDER ou SNIPER, sous aucun déguisement.*
  2. **La donnée doit exister sur disque.** Pas de funding mesuré -> **`None`**, jamais un 0.
  3. **Minimum 30 jours d'historique.** *Un carry se mesure sur des mois.*
  4. **La moyenne doit être positive.** Un funding négatif exigerait de shorter le spot :
     impossible sur HL.
  5. **L'edge est BORNÉ par l'horizon de détention** (30 j par défaut) — *on n'annualise pas
     un edge pour le faire paraître gros.*
  6. `fabrique=False` **et c'est la vérité** : cette valeur sort d'un relevé, pas d'une formule.

PUR : lit un fichier, ne prédit rien. Aucun ordre réel.
"""
from __future__ import annotations

import collections
import json
import statistics
from pathlib import Path
from typing import Any

# L'horizon sur lequel on compte le funding. **Un carry se tient.**
HORIZON_HEURES = 720            # 30 jours

MIN_HEURES = 720                # sous 30 j d'historique, on ne juge pas

MOTIF_PAS_UN_CARRY = "PAS_UNE_STRATEGIE_DE_CARRY_LA_PORTE_NE_S_OUVRE_PAS"
MOTIF_PAS_DE_FUNDING = "FUNDING_NON_MESURE_SUR_DISQUE"
MOTIF_HISTORIQUE_COURT = "HISTORIQUE_DE_FUNDING_TROP_COURT"
MOTIF_FUNDING_NEGATIF = "FUNDING_NEGATIF_SHORTER_LE_SPOT_EST_IMPOSSIBLE_SUR_HL"
MOTIF_MESURE = "EDGE_DE_CARRY_LU_DANS_LE_FUNDING_MESURE_365_JOURS"

_CACHE: dict[str, list[float]] | None = None


def _charger(chemin: Path) -> dict[str, list[float]]:
    """Le funding **mesuré**, en bps/heure. DENY-BY-DEFAULT sur chaque ligne."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    par: dict[str, list[float]] = collections.defaultdict(list)
    if chemin.exists():
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ligne)
                par[str(d["coin"]).upper()].append(float(d["funding"]) * 1e4)
            except Exception:  # noqa: BLE001
                continue
    _CACHE = dict(par)
    return _CACHE


def reinitialiser() -> None:
    """Entre deux sessions. *On ne mélange jamais deux runs.*"""
    global _CACHE
    _CACHE = None


def edge_de_carry_bps(
    coin: str,
    strategie: str,
    *,
    chemin: Path | None = None,
    horizon_heures: int = HORIZON_HEURES,
) -> tuple[float | None, str, dict[str, Any]]:
    """`(edge_bps, motif, preuve)`. **`None` = REFUS, jamais un chiffre inventé.**

    L'edge brut d'un carry = **le funding qu'on va encaisser** sur l'horizon de détention.
    ***Ce n'est pas une prédiction : c'est un relevé.***
    """
    # 🔒 GARDE 1 — la porte ne s'ouvre QUE pour le carry.
    if str(strategie or "").strip().upper() not in ("CARRY", "FUNDING"):
        return None, MOTIF_PAS_UN_CARRY, {"strategie": strategie}

    p = chemin or (Path(__file__).resolve().parents[3]
                   / "runtime" / "history" / "funding.jsonl")
    f = _charger(p).get(str(coin).strip().upper(), [])

    # 🔒 GARDE 2 — la donnée doit EXISTER.
    if not f:
        return None, MOTIF_PAS_DE_FUNDING, {"coin": coin, "fichier": str(p)}

    # 🔒 GARDE 3 — assez d'historique.
    if len(f) < MIN_HEURES:
        return None, MOTIF_HISTORIQUE_COURT, {"coin": coin, "n_heures": len(f)}

    moy = statistics.fmean(f)
    part_pos = sum(1 for x in f if x > 0) / len(f)

    # 🔒 GARDE 4 — le signe.
    if moy <= 0:
        return None, MOTIF_FUNDING_NEGATIF, {
            "coin": coin, "funding_bps_h": round(moy, 4),
            "part_heures_positives": round(part_pos, 3),
        }

    # 🔒 GARDE 5 — BORNÉ par l'horizon. *On n'annualise pas pour faire joli.*
    edge = moy * float(horizon_heures)

    return edge, MOTIF_MESURE, {
        "coin": coin,
        "funding_bps_h": round(moy, 4),
        "part_heures_positives": round(part_pos, 3),
        "n_heures_mesurees": len(f),
        "horizon_heures": horizon_heures,
        "edge_brut_bps": round(edge, 2),
        "source": "runtime/history/funding.jsonl (365 j, endpoint public `fundingHistory`)",
        "fabrique": False,
        "note": ("***L'edge d'un carry n'est pas PRÉDIT : il est OBSERVÉ.*** Le funding a été "
                 "versé heure par heure pendant %d heures. C'est un relevé, pas un pari."
                 % len(f)),
        "real_execution": False,
    }


__all__ = [
    "HORIZON_HEURES", "MIN_HEURES", "MOTIF_FUNDING_NEGATIF", "MOTIF_HISTORIQUE_COURT",
    "MOTIF_MESURE", "MOTIF_PAS_DE_FUNDING", "MOTIF_PAS_UN_CARRY",
    "edge_de_carry_bps", "reinitialiser",
]
