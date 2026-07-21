"""LE SCANNER CARRY — **le maillon qui manquait.**

═══════════════════════════════════════════════════════════════════════════════════════════════
LE CONSTAT
═══════════════════════════════════════════════════════════════════════════════════════════════

Le noyau **accepte** la famille `CARRY_STRUCTUREL` (elle n'est pas une zone morte).
Le moteur `carry_runtime` sait **juger** un candidat carry.

    ***Mais RIEN ne PRODUISAIT de candidat carry.***

La boucle live ne fabrique que des candidats **COPY** (depuis les fills publics des wallets) —
que le noyau refuse, à juste titre (zone morte prouvée : −7,97 bps, même à coût zéro).

    ***Résultat : le bot ne pouvait ouvrir AUCUNE position. Le seul trade mesuré positif du
    projet n'avait personne pour le proposer.***

*Une capacité présente, un chaînon manquant, personne qui se plaint.* **Encore.**

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE CE SCANNER FAIT — et les QUATRE portes qu'il ferme
═══════════════════════════════════════════════════════════════════════════════════════════════

  **PORTE 1 — LE SPOT.** Le coin doit avoir un marché **spot ET perp** sur HL.
      *Sans spot, on n'est pas delta-neutre : on est short le perp **à nu**.*
      Sur **232 perps, seuls 8** passent. **Mesuré via `spotMeta`, jamais supposé.**

  **PORTE 2 — LE SIGNE DU FUNDING.** Il doit être **positif**.
      *Un funding négatif exigerait de **shorter le spot** — impossible sur HL.*

  **PORTE 3 — LA STABILITÉ.** Au moins **80 % d'heures positives** sur l'historique.
      🔴 **AZTEC a 83 % d'heures positives et une moyenne NÉGATIVE (−0,84 bps/h).**
      Des centaines de petites heures qui rapportent, et quelques-unes qui arrachent tout.
      ***Sur 120 jours il paraissait à +5,7 % APR. Sur son historique complet, il PERD.***
      -> **on exige les DEUX : moyenne positive ET stabilité.**

  **PORTE 4 — L'ÉCONOMIE.** Le funding doit amortir les **23 bps** de coûts (4 exécutions,
      spot + perp) en moins de 30 jours. *Un carry se tient ; il ne se scalpe pas.*

Puis le candidat passe au **noyau**, qui rejuge tout (frais, prix exécutables, session, VPIN,
contraintes d'exchange). **Ce scanner PROPOSE. Il n'autorise rien.**

PUR : aucun réseau ici. Aucun ordre réel. Paper-only.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from hl_observer.strategies.carry_ranking import CarryClasse, classer
from hl_observer.strategies.carry_runtime import (
    COUT_ALLER_RETOUR_TAKER_BPS,
    CandidatCarry,
    evaluer,
)

# Au moins 80 % des heures doivent payer. **Et la moyenne doit être positive AUSSI.**
PART_HEURES_POSITIVES_MIN = 0.80

# Sous 30 jours d'historique, on ne juge pas. *Un carry se mesure sur des mois.*
MIN_HEURES_HISTORIQUE = 720

MOTIF_PAS_DE_SPOT = "PAS_DE_SPOT_HL_UN_CARRY_SANS_SPOT_EST_UN_SHORT_PERP_A_NU"
MOTIF_FUNDING_NEGATIF = "FUNDING_NEGATIF_IL_FAUDRAIT_SHORTER_LE_SPOT_IMPOSSIBLE_SUR_HL"
MOTIF_INSTABLE = "FUNDING_INSTABLE_QUELQUES_HEURES_ARRACHENT_TOUT_LE_RESTE"
MOTIF_HISTORIQUE_COURT = "HISTORIQUE_TROP_COURT_POUR_JUGER_UN_CARRY"
MOTIF_RETENU = "CARRY_RETENU_A_SOUMETTRE_AU_NOYAU"


@dataclass(frozen=True, slots=True)
class Proposition:
    """Un candidat CARRY **proposé** au noyau. *Le scanner propose ; le noyau dispose.*"""
    coin: str
    strategie: str
    direction: str
    funding_bps_h: float
    part_heures_positives: float
    n_heures: int
    apr_sur_capital: float
    retenu: bool
    motif: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin, "strategie": self.strategie, "direction": self.direction,
            "funding_bps_h": round(self.funding_bps_h, 4),
            "part_heures_positives": round(self.part_heures_positives, 3),
            "n_heures": self.n_heures,
            "apr_sur_capital_pct": round(self.apr_sur_capital * 100, 2),
            "retenu": self.retenu, "motif": self.motif,
            "paper_only": True, "real_execution": False,
        }


def charger_spot_carryables(chemin: Path) -> set[str]:
    """La liste **MESURÉE** (via `spotMeta`). Absente -> **set vide**, et on le dit.

    *Je l'avais SUPPOSÉE ({HYPE, PURR}). Elle en a 8. On demande, on ne devine pas.*
    """
    if not chemin.exists():
        return set()
    try:
        d = json.loads(chemin.read_text(encoding="utf-8"))
        return {str(c).upper() for c in d.get("carryables", [])}
    except Exception:  # noqa: BLE001
        return set()


def scanner(
    funding_par_coin: dict[str, Sequence[float]],   # coin -> fundings HORAIRES en bps
    *,
    spot_carryables: set[str],
    notional_usd: float = 500.0,
) -> list[Proposition]:
    """Les 4 portes, dans l'ordre où elles peuvent tuer. **Deny-by-default partout.**"""
    out: list[Proposition] = []

    for coin, f in sorted(funding_par_coin.items()):
        c = coin.upper()
        n = len(f)

        def _refus(motif: str, moy: float = 0.0, part: float = 0.0) -> Proposition:
            return Proposition(c, "CARRY", "SHORT", moy, part, n, 0.0, False, motif)

        # ── PORTE 1 : le SPOT ────────────────────────────────────────────────────────────────
        if c not in spot_carryables:
            out.append(_refus(MOTIF_PAS_DE_SPOT))
            continue

        # ── historique suffisant ? ───────────────────────────────────────────────────────────
        if n < MIN_HEURES_HISTORIQUE:
            out.append(_refus(MOTIF_HISTORIQUE_COURT))
            continue

        moy = statistics.fmean(f)
        part = sum(1 for x in f if x > 0) / n

        # ── PORTE 2 : le SIGNE ───────────────────────────────────────────────────────────────
        if moy <= 0:
            out.append(_refus(MOTIF_FUNDING_NEGATIF, moy, part))
            continue

        # ── PORTE 3 : la STABILITÉ ───────────────────────────────────────────────────────────
        # 🔴 AZTEC : 83 % d'heures positives, moyenne **-0,84**. On exige les DEUX.
        if part < PART_HEURES_POSITIVES_MIN:
            out.append(_refus(MOTIF_INSTABLE, moy, part))
            continue

        # ── PORTE 4 : l'ÉCONOMIE ─────────────────────────────────────────────────────────────
        v = evaluer(CandidatCarry(coin=c, funding_bps_h=moy, notional_usd=notional_usd))
        if not v.ouvrable:
            out.append(_refus(v.motif, moy, part))
            continue

        out.append(Proposition(c, "CARRY", "SHORT", moy, part, n,
                               v.apr_sur_capital, True, MOTIF_RETENU))

    return sorted(out, key=lambda p: (not p.retenu, -p.apr_sur_capital))


def rapport(props: Sequence[Proposition]) -> dict[str, Any]:
    retenus = [p for p in props if p.retenu]
    return {
        "n_scannes": len(props),
        "n_retenus": len(retenus),
        "retenus": [p.as_dict() for p in retenus],
        "cout_aller_retour_bps": COUT_ALLER_RETOUR_TAKER_BPS,
        "note": (
            "🔴 **Le scanner PROPOSE. Le noyau DISPOSE.** Chaque proposition repasse ensuite par "
            "`noyau_unique.decider()` : frais réels, prix exécutables, disjoncteur de session, "
            "VPIN, contraintes d'exchange. *Aucune porte n'est sautée.*"
        ),
        "avertissement": (
            "⚠️ Ces coins sont de **petits marchés**. Leur funding est élevé **précisément parce "
            "que les détenir est dangereux.** Reste à vérifier la **profondeur du carnet** : "
            "*un edge sur un carnet de 3 $ n'existe pas.*"
        ),
        "paper_only": True, "real_execution": False,
    }


def classement_shortlist(
    funding_par_coin: dict[str, Sequence[float]],
    *,
    spot_carryables: set[str],
    cout_amorti_bps_h: float,
    notional_usd: float = 500.0,
) -> list[CarryClasse]:
    """Classe la SHORTLIST du scanner par carry NET predit (via carry_ranking).

    Le scanner dit OUI/NON (4 portes). « Moins de trades, plus propres » demande de RANGER les
    retenus et de n'ouvrir que le haut du panier. On compose donc : scanner -> retenus ->
    carry_ranking.classer (funding net predit, deny-by-default). Rien n'est ouvert ici -- le noyau
    garde l'autorite sur chaque entree.
    """
    props = scanner(funding_par_coin, spot_carryables=spot_carryables, notional_usd=notional_usd)
    retenus = {p.coin for p in props if p.retenu}
    fundings_retenus = {c.upper(): f for c, f in funding_par_coin.items() if c.upper() in retenus}
    return classer(fundings_retenus, cout_amorti_bps_h=cout_amorti_bps_h)


__all__ = [
    "MIN_HEURES_HISTORIQUE", "MOTIF_FUNDING_NEGATIF", "MOTIF_HISTORIQUE_COURT",
    "MOTIF_INSTABLE", "MOTIF_PAS_DE_SPOT", "MOTIF_RETENU",
    "PART_HEURES_POSITIVES_MIN",
    "CarryClasse", "Proposition", "charger_spot_carryables", "classement_shortlist",
    "rapport", "scanner",
]
