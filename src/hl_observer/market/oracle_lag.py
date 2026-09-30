"""#556 / H-151 — L'ORACLE HYPERLIQUID SUIT LES CEX. **Mesurer, pas rêver.**

═══════════════════════════════════════════════════════════════════════════════════════════════
LE MÉCANISME EST RÉEL, ET DOCUMENTÉ
═══════════════════════════════════════════════════════════════════════════════════════════════

Doc officielle (`trading/funding`, `hypercore/clearinghouse`) :

    « the oracle prices are computed by each validator as the **weighted median of CEX spot
      prices** for each asset, with weights depending on the liquidity of the CEX »

**Les CEX mènent. L'oracle HL suit.** Le lag est *mécanique*, pas une opinion.

═══════════════════════════════════════════════════════════════════════════════════════════════
🚩 CE QUE JE REFUSE DE FAIRE AVEC ÇA — dit tout de suite
═══════════════════════════════════════════════════════════════════════════════════════════════

La forme naïve de cette piste, c'est : *« on lit Binance, on devance l'oracle HL, on gagne »*.

    ***C'est une COURSE DE VITESSE. Et on la perd par construction.***

  * On est un bot Python en paper trading, sans colocation, sans accès direct.
  * Des professionnels colocalisés font ce trade **depuis toujours**. C'est même leur métier :
    l'écart CEX↔HL n'existe que le temps qu'il leur faut pour le fermer.
  * **Et la latence est une ZONE MORTE de ce projet** : la courbe edge/horizon est **PLATE**
    (−3,74 bps à 500 ms). *La vitesse n'a jamais été notre problème.*

**Si on entre dans cette course, on est le pigeon.** Je le dis avant de mesurer, pas après.

═══════════════════════════════════════════════════════════════════════════════════════════════
✅ CE QUI EST MESURABLE, ET QUI NE DEMANDE **AUCUNE** VITESSE
═══════════════════════════════════════════════════════════════════════════════════════════════

Le prix **MARK** du perp HL et le prix **ORACLE** divergent. Deux questions, deux natures :

  **(A) Le mark REVIENT-IL vers l'oracle ?**  (retour à la moyenne, horizon minutes)
      Si oui, un écart mark−oracle large est un signal de *retour*, pas de *vitesse*.
      ⚠️ Mais c'est le trade de tout le monde, et il est comprimé par l'arbitrage.

  **(B) 🔑 L'écart mark−oracle EST le premium — donc il PILOTE LE FUNDING.**
      Doc : `premium = impact_price_difference / oracle_price`, et
      `Funding = Average Premium + clamp(...)`, **moyenné sur l'heure**.
      -> Un écart persistant **prédit mécaniquement** le funding de l'heure en cours.
      ***Et le funding se paie à l'heure : on a UNE HEURE pour agir. Aucune course.***

**C'est (B) qui est notre angle.** Pas la vitesse : le **funding prévisible**.

⚠️ HONNÊTETÉ : prédire le funding ne suffit pas. Il faut encore que le funding **paie
l'aller-retour** (9 bps taker contre 0,125 bps/h de médiane → il faut 72× la médiane, cf.
`funding/snapshot_capture.py`). **Prédire un revenu minuscule reste un revenu minuscule.**

PUR : aucun appel réseau. Aucun ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

MOTIF_COURSE_DE_VITESSE = "COURSE_DE_VITESSE_PERDUE_D_AVANCE_ON_SERAIT_LE_PIGEON"
MOTIF_PAS_ASSEZ_DE_POINTS = "PAS_ASSEZ_DE_POINTS_POUR_UNE_MESURE_HONNETE"
MIN_POINTS = 60


@dataclass(frozen=True, slots=True)
class PointOracle:
    coin: str
    time_ms: int
    mark: float
    oracle: float

    @property
    def premium_bps(self) -> float:
        """(mark − oracle) / oracle, en bps. **C'est ce qui pilote le funding.**"""
        return ((self.mark - self.oracle) / self.oracle) * 1e4 if self.oracle > 0 else 0.0


@dataclass(frozen=True, slots=True)
class RetourVersOracle:
    """(A) Le mark revient-il vers l'oracle ? Retour a la moyenne, PAS de vitesse requise."""
    coin: str
    n: int
    premium_moyen_bps: float
    premium_absolu_median_bps: float
    # quand |premium| est GRAND, le premium suivant est-il PLUS PETIT ? (retour a la moyenne)
    part_qui_se_resserre: float
    suffisant: bool
    motif: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"coin": self.coin, "n": self.n,
                "premium_moyen_bps": round(self.premium_moyen_bps, 4),
                "premium_absolu_median_bps": round(self.premium_absolu_median_bps, 4),
                "part_qui_se_resserre": round(self.part_qui_se_resserre, 4),
                "suffisant": self.suffisant, "motif": self.motif,
                "avertissement": (
                    "⚠️ Le retour du mark vers l'oracle est le trade de TOUT LE MONDE. "
                    "S'il payait, il n'existerait pas. **Ce chiffre DECRIT, il ne promet rien.**"
                ),
                "real_execution": False}


def _median(xs: Sequence[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def mesurer_retour(coin: str, points: Iterable[PointOracle],
                   *, min_points: int = MIN_POINTS) -> RetourVersOracle:
    """(A) Retour a la moyenne du premium. `None`-safe : un echantillon court est DIT court."""
    ps = sorted((p for p in points if p.coin == coin and p.oracle > 0),
                key=lambda p: p.time_ms)
    n = len(ps)
    if n < min_points:
        return RetourVersOracle(coin, n, 0.0, 0.0, 0.0, False,
                                "%s : %d < %d" % (MOTIF_PAS_ASSEZ_DE_POINTS, n, min_points))
    prems = [p.premium_bps for p in ps]
    abs_prems = [abs(x) for x in prems]
    med = _median(abs_prems)

    # quand |premium| depasse la mediane, se resserre-t-il au pas suivant ?
    grands = [(a, b) for a, b in zip(abs_prems, abs_prems[1:]) if a > med]
    part = (sum(1 for a, b in grands if b < a) / len(grands)) if grands else 0.0

    return RetourVersOracle(
        coin=coin, n=n,
        premium_moyen_bps=sum(prems) / n,
        premium_absolu_median_bps=med,
        part_qui_se_resserre=part,
        suffisant=True,
    )


def funding_predit_bps_h(points: Sequence[PointOracle]) -> float | None:
    """(B) 🔑 **L'ANGLE SANS COURSE DE VITESSE.**

    Doc : `Funding = **Average** Premium Index + clamp(interest − premium, −0.0005, 0.0005)`,
    « the premium is sampled every 5 seconds and **averaged over the hour** ».

    -> La moyenne des premiums observes DANS l'heure **predit** le funding de cette heure.
    ***Et le funding se paie a la FIN de l'heure : on a une HEURE pour agir. Aucune vitesse.***

    Rend le taux **HORAIRE** en bps (HL paie a l'heure, pas sur 8 h -- cf. le piege d'unite).
    `None` si aucun point : **etat vide honnete**, jamais un 0 fabrique.
    """
    ps = [p for p in points if p.oracle > 0]
    if not ps:
        return None
    premium_moyen = sum(p.premium_bps for p in ps) / len(ps)   # en bps
    interet_8h_bps = 1.0                                        # 0,01 % sur 8 h (doc)
    borne = 5.0                                                 # clamp +/- 0,05 % = 5 bps
    clamp = max(-borne, min(borne, interet_8h_bps - premium_moyen))
    funding_8h_bps = premium_moyen + clamp
    return funding_8h_bps / 8.0            # 🔴 HL paie a l'HEURE : un huitieme du taux 8 h


def verdict_course_de_vitesse() -> dict[str, Any]:
    """La forme naive de #556, refusee **avant** toute mesure. On ne se ment pas apres coup."""
    return {
        "motif": MOTIF_COURSE_DE_VITESSE,
        "explication": (
            "« Lire Binance, devancer l'oracle HL » est une COURSE DE VITESSE. On est un bot "
            "Python paper, sans colocation. Des professionnels colocalises ferment cet ecart "
            "pour vivre. **Si on entre dans cette course, on est le pigeon.** "
            "Et la latence est une ZONE MORTE : la courbe edge/horizon est PLATE (-3,74 bps a "
            "500 ms). *La vitesse n'a jamais ete notre probleme.*"
        ),
        "angle_retenu": (
            "L'ecart mark-oracle EST le premium -> il **pilote le funding**, qui se paie a "
            "l'HEURE. **On a une heure pour agir. Aucune vitesse requise.**"
        ),
        "reserve": (
            "⚠️ Predire le funding ne suffit pas : il faut qu'il paie l'aller-retour "
            "(9 bps taker contre 0,125 bps/h de mediane -> 72x). "
            "**Predire un revenu minuscule reste un revenu minuscule.**"
        ),
        "real_execution": False,
    }


__all__ = [
    "MIN_POINTS", "MOTIF_COURSE_DE_VITESSE", "MOTIF_PAS_ASSEZ_DE_POINTS",
    "PointOracle", "RetourVersOracle",
    "funding_predit_bps_h", "mesurer_retour", "verdict_course_de_vitesse",
]
