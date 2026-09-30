"""UN EDGE EST UN MOUVEMENT DE PRIX ATTENDU — pas un score de vote (2026-07-11).

LA CAUSE RACINE DU PnL NÉGATIF.

`fusion_paper_engine_adapter._consensus_edge_remaining_bps` calculait l'« edge » qui autorise
CHAQUE entrée de copie comme ceci :

    dominance    = |long_score - short_score| / total      # un score de VOTE entre wallets
    gross_signal = dominance * 45.0 + bonus                # <- 45. D'ou vient 45 ? De nulle part.
    edge         = gross_signal - 18.0

**Ce nombre n'a JAMAIS touche un prix.** Ce n'est pas un mouvement attendu, ce n'est pas une
mesure : c'est un score de consensus converti en points de base par une formule inventee.

Le code l'avoue lui-meme :

    "edge_source": "CONSENSUS_VOTE_PROXY_NOT_EMPIRICAL",
    "edge_is_empirical": False,

Consequence : le seuil `min_edge` comparait une VALEUR INVENTEE a un plancher. Tous les reglages de
ce seuil -- les miens, ceux de Codex -- portaient sur un chiffre qui ne decrit pas le marche. C'est
pourquoi aucun n'a jamais rien change. Et c'est pourquoi le bot ouvrait des positions que
l'`opportunity_report` (qui, lui, mesure un edge REEL) refusait au meme instant.

CE MODULE POSE LA REGLE :

    Un edge est soit MESURE sur des prix reels, soit il n'existe pas.
    Pas de mesure -> pas d'edge -> NO_TRADE.

Il ne fabrique aucun chiffre. Il ne promet aucun PnL. Il rend `is_empirical=False` quand la mesure
manque -- et le gate refuse. **Deny-by-default.**

⚠️ CONSEQUENCE ASSUMEE : tant qu'aucun edge empirique n'est calibre, le moteur de copie
**n'ouvrira plus rien**. C'est le resultat HONNETE : on a mesure (24 133 signaux, hors echantillon)
que le copy-trading n'a pas d'edge -- meme a cout zero. Un bot qui refuse de trader sans edge n'est
pas casse : il est enfin lucide.

PUR, sans I/O reseau. Aucun ordre reel.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

# Deny-by-default : exiger un edge EMPIRIQUE. Mettre "0" retablit l'ancien proxy (A/B seulement).
ENV_REQUIRE_EMPIRICAL = "HYPERSMART_REQUIRE_EMPIRICAL_EDGE"
# Table de calibration mesuree hors echantillon (produite par la recherche, jamais a la main).
ENV_CALIBRATION_PATH = "HYPERSMART_EDGE_CALIBRATION_PATH"
DEFAUT_CALIBRATION = "runtime/calibration/empirical_edge.json"

REFUS_NON_EMPIRIQUE = "EDGE_NOT_EMPIRICAL_NO_TRADE"
REFUS_CALIBRATION_ABSENTE = "EDGE_CALIBRATION_MISSING_NO_TRADE"
REFUS_ECHANTILLON_TROP_PETIT = "EDGE_CALIBRATION_SAMPLE_TOO_SMALL_NO_TRADE"

# Sous ce nombre d'observations, une "mesure" est du bruit deguise en science.
MIN_ECHANTILLON = 200


def _vrai(nom: str, defaut: str = "1") -> bool:
    return str(os.environ.get(nom, defaut)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class EmpiricalEdge:
    """Un edge, et la VERITE sur son origine. `is_empirical=False` => on ne trade pas."""

    value_bps: float
    is_empirical: bool
    source: str
    sample_size: int = 0
    horizon_ms: int = 0
    measured_at: str = ""
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "edge_remaining_bps": round(self.value_bps, 6),
            "edge_is_empirical": self.is_empirical,
            "edge_source": self.source,
            "edge_sample_size": self.sample_size,
            "edge_horizon_ms": self.horizon_ms,
            "edge_measured_at": self.measured_at,
            "edge_note": self.note,
        }


def no_empirical_edge(raison: str, *, note: str = "") -> EmpiricalEdge:
    """Aucun edge mesurable. On le DIT, on n'invente pas un chiffre a la place."""
    return EmpiricalEdge(
        value_bps=0.0,
        is_empirical=False,
        source=raison,
        note=note or "aucune mesure disponible : on ne fabrique pas un edge",
    )


def load_calibration(path: str | None = None) -> Mapping[str, Any] | None:
    """Charge la table d'edge MESURE (hors echantillon). Absente = etat vide honnete."""
    p = Path(path or os.environ.get(ENV_CALIBRATION_PATH, "") or DEFAUT_CALIBRATION)
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None                      # illisible = absente. On ne devine pas son contenu.
    return data if isinstance(data, dict) else None


def edge_from_calibration(
    *,
    signal_age_ms: float | None,
    calibration: Mapping[str, Any] | None = None,
) -> EmpiricalEdge:
    """Edge attendu, lu dans une table MESUREE -- indexee par la fraicheur du signal.

    La fraicheur est la seule dimension dont on ait prouve qu'elle compte (l'edge de copie
    s'evanouit avec l'age). Toute autre dimension devra etre AJOUTEE APRES avoir ete mesuree,
    jamais devinee.
    """
    table = calibration if calibration is not None else load_calibration()
    if not table:
        return no_empirical_edge(
            REFUS_CALIBRATION_ABSENTE,
            note="aucune table d'edge mesuree : le bot refuse de trader sur un chiffre invente",
        )

    bandes = table.get("bands")
    if not isinstance(bandes, list) or not bandes:
        return no_empirical_edge(REFUS_CALIBRATION_ABSENTE, note="table de calibration vide")

    age = float(signal_age_ms) if signal_age_ms is not None else None
    if age is None or not math.isfinite(age) or age < 0:
        return no_empirical_edge(
            REFUS_NON_EMPIRIQUE,
            note="age du signal inconnu : sans fraicheur, l'edge de copie n'est pas mesurable",
        )

    for bande in bandes:
        if not isinstance(bande, Mapping):
            continue
        try:
            amin = float(bande.get("age_min_ms", 0))
            amax = float(bande.get("age_max_ms", float("inf")))
            valeur = float(bande.get("edge_bps"))
            n = int(bande.get("sample_size", 0))
        except (TypeError, ValueError):
            continue
        if not (amin <= age < amax):
            continue
        if n < MIN_ECHANTILLON:
            return no_empirical_edge(
                REFUS_ECHANTILLON_TROP_PETIT,
                note=f"bande mesuree sur {n} observations (< {MIN_ECHANTILLON}) : c'est du bruit",
            )
        return EmpiricalEdge(
            value_bps=valeur,
            is_empirical=True,
            source=str(table.get("source") or "OUT_OF_SAMPLE_MEASUREMENT"),
            sample_size=n,
            horizon_ms=int(float(bande.get("horizon_ms", table.get("horizon_ms", 0)) or 0)),
            measured_at=str(table.get("measured_at") or ""),
            note=str(bande.get("note") or ""),
        )

    return no_empirical_edge(
        REFUS_NON_EMPIRIQUE,
        note=f"aucune bande mesuree ne couvre un signal de {age:.0f} ms",
    )


def empirical_edge_refusal(edge: EmpiricalEdge | None) -> str:
    """Le GATE. "" = on peut continuer. Sinon : le motif du refus.

    DENY-BY-DEFAULT : sans edge empirique, on ne trade pas. Le flag permet de retablir l'ancien
    proxy UNIQUEMENT pour une comparaison A/B -- jamais comme comportement par defaut.
    """
    if not _vrai(ENV_REQUIRE_EMPIRICAL, "1"):
        return ""                        # mode A/B explicite : l'ancien proxy reprend la main
    if edge is None:
        return REFUS_NON_EMPIRIQUE
    if not edge.is_empirical:
        return edge.source or REFUS_NON_EMPIRIQUE
    return ""


__all__ = [
    "DEFAUT_CALIBRATION",
    "ENV_CALIBRATION_PATH",
    "ENV_REQUIRE_EMPIRICAL",
    "MIN_ECHANTILLON",
    "REFUS_CALIBRATION_ABSENTE",
    "REFUS_ECHANTILLON_TROP_PETIT",
    "REFUS_NON_EMPIRIQUE",
    "EmpiricalEdge",
    "edge_from_calibration",
    "empirical_edge_refusal",
    "load_calibration",
    "no_empirical_edge",
]
