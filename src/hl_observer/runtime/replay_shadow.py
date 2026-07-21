"""#302 — REPLAY DÉTERMINISTE + SHADOW MODE (A/B ancien vs nouveau).

═══════════════════════════════════════════════════════════════════════════════════════════════
LE REPLAY : rejouer **exactement** ce que le moteur a vu
═══════════════════════════════════════════════════════════════════════════════════════════════

Le raw spool (#501) garde les **trames brutes**. Le bus (#312) leur donne un **ordre total
déterministe**. Ensemble, ils permettent enfin ceci :

    ***Rejouer une session à l'identique, et obtenir le MÊME résultat, bit pour bit.***

Si deux rejeux du même spool donnent des résultats différents, **le moteur n'est pas
déterministe** — et alors *aucune* comparaison n'a de sens : ni backtest, ni shadow, ni « avant /
après ». **C'est l'invariant le plus fondamental, et on ne l'avait jamais.**

═══════════════════════════════════════════════════════════════════════════════════════════════
LE SHADOW MODE : le nouveau moteur DÉCIDE, mais ne TRADE PAS
═══════════════════════════════════════════════════════════════════════════════════════════════

On fait tourner **les deux moteurs sur les MÊMES événements**. L'ancien décide pour de vrai (en
paper) ; le nouveau décide **dans l'ombre**. On compare les décisions, pas les PnL.

    🔴 **Pourquoi comparer les DÉCISIONS et pas les PnL ?**
    Parce que deux moteurs peuvent avoir le même PnL en prenant des trades **complètement
    différents** — et le PnL d'un échantillon court est du **bruit**. *Une divergence de décision
    est un FAIT ; une divergence de PnL est une opinion.*

⚠️ **ET LA RÈGLE DURE** : le moteur en shadow **NE PEUT PAS AGIR**. Il produit des décisions, on
les enregistre, point. *Un moteur en observation qui peut agir n'est pas en observation.*

PUR : aucun réseau, aucun ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from hl_observer.runtime.session_and_bus import (
    REPLAY,
    BusEvenements,
    Evenement,
    Session,
    empreinte_du_flux,
    nouvelle_session,
)

MOTIF_NON_DETERMINISTE = "DEUX_REJEUX_DONNENT_DES_RESULTATS_DIFFERENTS_MOTEUR_NON_DETERMINISTE"
MOTIF_DETERMINISTE = "REJEU_DETERMINISTE"
MOTIF_SHADOW_NE_PEUT_PAS_AGIR = "LE_MOTEUR_EN_SHADOW_NE_PEUT_PAS_AGIR"


@dataclass(frozen=True, slots=True)
class Decision:
    """Ce qu'un moteur DÉCIDE. **Jamais ce qu'il exécute.**"""
    t_ms: int
    action: str            # "ENTRER" | "SORTIR" | "NO_TRADE"
    coin: str = ""
    motif: str = ""

    def cle(self) -> tuple:
        return (self.t_ms, self.action, self.coin)


Moteur = Callable[[Evenement], Decision | None]


def rejouer(
    evenements: Sequence[tuple[int, str, Any]],     # (t_ms, type, charge)
    moteur: Moteur,
    *, session: Session | None = None,
) -> tuple[list[Decision], str]:
    """Rejoue des événements dans un bus, et rend `(décisions, empreinte du flux)`.

    🔒 La session est forcée en mode **REPLAY** : *on ne mélange JAMAIS un rejeu avec le live.*
    """
    s = session or nouvelle_session(REPLAY, graine="replay")
    if s.mode != REPLAY:
        raise ValueError("un rejeu doit tourner en mode REPLAY, pas %s "
                         "(**on ne melange pas les PnL**)" % s.mode)
    bus = BusEvenements(s)
    for t_ms, type_, charge in evenements:
        bus.publier(t_ms, type_, charge)

    vus: list[Evenement] = []
    decisions: list[Decision] = []
    for e in bus.drainer():
        vus.append(e)
        d = moteur(e)
        if d is not None:
            decisions.append(d)
    return decisions, empreinte_du_flux(vus)


def est_deterministe(
    evenements: Sequence[tuple[int, str, Any]],
    moteur: Moteur,
    *, n_rejeux: int = 3,
) -> dict[str, Any]:
    """🔑 **L'INVARIANT LE PLUS FONDAMENTAL, ET ON NE L'AVAIT JAMAIS.**

    Si deux rejeux du même flux donnent des résultats différents, **aucune** comparaison n'a de
    sens : ni backtest, ni shadow, ni « avant / après ».
    """
    resultats = [rejouer(evenements, moteur,
                         session=nouvelle_session(REPLAY, graine="rejeu-%d" % i))
                 for i in range(max(2, n_rejeux))]
    cles = [tuple(d.cle() for d in r[0]) for r in resultats]
    toutes_egales = all(c == cles[0] for c in cles)
    return {
        "deterministe": toutes_egales,
        "n_rejeux": len(resultats),
        "n_decisions": len(cles[0]),
        "motif": MOTIF_DETERMINISTE if toutes_egales else MOTIF_NON_DETERMINISTE,
        "detail": ("" if toutes_egales else
                   "🔴 **Le moteur n'est PAS deterministe.** Deux rejeux du MEME flux donnent des "
                   "decisions differentes. *Aucune comparaison -- backtest, shadow, avant/apres -- "
                   "n'a de sens tant que ce n'est pas corrige.*"),
        "real_execution": False,
    }


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LE SHADOW MODE
# ═══════════════════════════════════════════════════════════════════════════════════════════════
@dataclass(slots=True)
class ComparaisonShadow:
    n_evenements: int = 0
    accord: int = 0
    desaccord: int = 0
    seulement_ancien: list[Decision] = field(default_factory=list)
    seulement_nouveau: list[Decision] = field(default_factory=list)

    @property
    def taux_accord(self) -> float:
        t = self.accord + self.desaccord
        return (self.accord / t) if t else 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_evenements": self.n_evenements,
            "accord": self.accord, "desaccord": self.desaccord,
            "taux_accord": round(self.taux_accord, 4),
            "seulement_ancien": [d.cle() for d in self.seulement_ancien[:20]],
            "seulement_nouveau": [d.cle() for d in self.seulement_nouveau[:20]],
            "note": ("🔴 On compare les **DÉCISIONS**, pas les PnL. *Deux moteurs peuvent avoir le "
                     "même PnL en prenant des trades complètement différents — et le PnL d'un "
                     "échantillon court est du BRUIT.* **Une divergence de décision est un FAIT ; "
                     "une divergence de PnL est une opinion.**"),
            "shadow_peut_agir": False,
            "real_execution": False,
        }


def shadow(
    evenements: Sequence[tuple[int, str, Any]],
    ancien: Moteur,
    nouveau: Moteur,
) -> ComparaisonShadow:
    """Les DEUX moteurs voient **les mêmes événements**. Le nouveau **ne peut pas agir**.

    ⚠️ *Un moteur en observation qui peut agir n'est pas en observation.*
    Ici c'est structurel : `shadow()` ne rend que des **comparaisons**, jamais un ordre.
    """
    da, _ = rejouer(evenements, ancien, session=nouvelle_session(REPLAY, graine="ancien"))
    dn, _ = rejouer(evenements, nouveau, session=nouvelle_session(REPLAY, graine="nouveau"))

    ca = {d.cle() for d in da}
    cn = {d.cle() for d in dn}
    c = ComparaisonShadow(n_evenements=len(evenements))
    c.accord = len(ca & cn)
    c.desaccord = len(ca ^ cn)
    c.seulement_ancien = [d for d in da if d.cle() not in cn]
    c.seulement_nouveau = [d for d in dn if d.cle() not in ca]
    return c


__all__ = [
    "MOTIF_DETERMINISTE", "MOTIF_NON_DETERMINISTE", "MOTIF_SHADOW_NE_PEUT_PAS_AGIR",
    "ComparaisonShadow", "Decision", "Moteur",
    "est_deterministe", "rejouer", "shadow",
]
