"""#572 / H-167 — LE PROBLÈME INTRA-BOUGIE. **Il explique nos stops qui dérapent.**

═══════════════════════════════════════════════════════════════════════════════════════════════
LE PROBLÈME, ÉNONCÉ SIMPLEMENT
═══════════════════════════════════════════════════════════════════════════════════════════════

Une bougie donne **4 nombres** : open, high, low, close. Elle ne dit **PAS DANS QUEL ORDRE** le
high et le low ont été touchés.

Si un trade a un **stop** sous le low **et** un **take-profit** au-dessus du high :

    ***la bougie touche LES DEUX. Laquelle en premier ? LA BOUGIE NE LE SAIT PAS.***

  * Supposer le TP d'abord -> on encaisse le gain. **Backtest optimiste, faux.**
  * Supposer le SL d'abord -> on prend la perte. **Pessimiste, mais honnête.**
  * Ne pas trancher -> `INDETERMINE`. **La seule réponse vraie.**

🔴 **ET ÇA VIENT DE GROSSIR** : on a backfillé **208 jours de bougies 1 HEURE**.
Une heure entière est **immense** : un SL et un TP à quelques dizaines de bps peuvent être touchés
tous les deux dans la même bougie, des dizaines de fois par jour.

    ***Toute mesure de SL/TP faite sur des bougies 1 h est SUSPECTE par construction.***

Et ça a une conséquence directe sur une zone morte : `CALIBRAGE_SLTP` (« 0 configuration robuste »).
⚠️ **Le verdict ne change pas** -- il était NÉGATIF, et l'ambiguïté intra-bougie ne peut que
rendre les résultats **plus optimistes** qu'ils ne sont. *Un biais qui gonfle un résultat déjà
négatif ne le sauve pas.* Mais un futur calibrage qui trouverait du positif sur des bougies 1 h
devrait être **rejeté** tant qu'il n'est pas refait sur des données plus fines.

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QU'ON FAIT
═══════════════════════════════════════════════════════════════════════════════════════════════

  1. `resoudre_bougie()` -> `TP` / `SL` / **`INDETERMINE`** / `AUCUN`.
  2. **DENY-BY-DEFAULT** : en cas d'ambiguïté, le mode par défaut est **PESSIMISTE** (le SL
     d'abord). *On ne s'offre jamais le bénéfice du doute.*
  3. `compter_ambiguites()` -> combien de bougies sont ambiguës. **C'est le chiffre qui dit si
     une mesure vaut quelque chose.**

PUR : aucun appel réseau. Aucun ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

TP = "TP"
SL = "SL"
INDETERMINE = "INDETERMINE"
AUCUN = "AUCUN"

# ⚠️ DENY-BY-DEFAULT : en cas d'ambiguïté, on suppose le PIRE. Jamais le bénéfice du doute.
PESSIMISTE = "PESSIMISTE"
OPTIMISTE = "OPTIMISTE"
HONNETE = "HONNETE"          # rend INDETERMINE, ne tranche pas

MOTIF_AMBIGU = "LA_BOUGIE_TOUCHE_LE_SL_ET_LE_TP_ELLE_NE_DIT_PAS_DANS_QUEL_ORDRE"


@dataclass(frozen=True, slots=True)
class Bougie:
    open: float
    high: float
    low: float
    close: float

    def coherente(self) -> bool:
        return (self.low <= self.open <= self.high
                and self.low <= self.close <= self.high
                and self.low <= self.high)


@dataclass(frozen=True, slots=True)
class Resolution:
    issue: str                 # TP | SL | INDETERMINE | AUCUN
    ambigu: bool
    motif: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"issue": self.issue, "ambigu": self.ambigu, "motif": self.motif}


def resoudre_bougie(
    bougie: Bougie,
    *,
    sl: float,
    tp: float,
    long: bool = True,
    mode: str = PESSIMISTE,
) -> Resolution:
    """Le SL ou le TP a-t-il ete touche -- et **peut-on seulement le savoir** ?

    `mode=HONNETE` rend `INDETERMINE` quand les deux sont touches. **C'est la seule reponse vraie.**
    `mode=PESSIMISTE` (defaut) tranche pour le **SL** : on ne s'offre pas le benefice du doute.
    """
    if not bougie.coherente():
        return Resolution(AUCUN, False, "bougie incoherente : ECARTEE (jamais devinee)")

    if long:
        touche_sl = bougie.low <= sl
        touche_tp = bougie.high >= tp
    else:
        touche_sl = bougie.high >= sl
        touche_tp = bougie.low <= tp

    if not touche_sl and not touche_tp:
        return Resolution(AUCUN, False)
    if touche_sl and not touche_tp:
        return Resolution(SL, False)
    if touche_tp and not touche_sl:
        return Resolution(TP, False)

    # 🔴 LES DEUX. La bougie ne dit pas dans quel ordre.
    if mode == HONNETE:
        return Resolution(INDETERMINE, True, MOTIF_AMBIGU)
    if mode == OPTIMISTE:
        return Resolution(TP, True, MOTIF_AMBIGU + " (mode OPTIMISTE : **resultat GONFLE**)")
    return Resolution(SL, True, MOTIF_AMBIGU + " (mode PESSIMISTE : on suppose le pire)")


def compter_ambiguites(
    bougies: Iterable[Bougie],
    *,
    sl: float,
    tp: float,
    long: bool = True,
) -> dict[str, Any]:
    """**Le chiffre qui dit si une mesure SL/TP vaut quelque chose.**

    Si 30 % des bougies sont ambigues, un backtest optimiste et un backtest pessimiste donneront
    des PnL radicalement differents -- et **aucun des deux ne sera vrai**.
    """
    bs = list(bougies)
    n = len(bs)
    amb = sum(1 for b in bs
              if resoudre_bougie(b, sl=sl, tp=tp, long=long, mode=HONNETE).ambigu)
    return {
        "n_bougies": n,
        "n_ambigues": amb,
        "part_ambigue": round(amb / n, 4) if n else 0.0,
        "avertissement": (
            "⚠️ Une bougie ambigue touche le SL **et** le TP : elle ne dit pas lequel en premier. "
            "Sur des bougies **1 h**, c'est frequent. **Toute mesure SL/TP sur bougies 1 h est "
            "SUSPECTE.** Le mode PESSIMISTE ne ment pas -- il refuse juste de se faire un cadeau."
        ),
        "real_execution": False,
    }


def ecart_optimiste_pessimiste(
    bougies: Sequence[Bougie],
    *,
    sl: float,
    tp: float,
    long: bool = True,
) -> dict[str, int]:
    """**Le meme backtest, deux hypotheses, deux resultats.** L'ecart mesure le mensonge possible."""
    o = [resoudre_bougie(b, sl=sl, tp=tp, long=long, mode=OPTIMISTE).issue for b in bougies]
    p = [resoudre_bougie(b, sl=sl, tp=tp, long=long, mode=PESSIMISTE).issue for b in bougies]
    return {
        "tp_si_optimiste": o.count(TP),
        "tp_si_pessimiste": p.count(TP),
        "sl_si_optimiste": o.count(SL),
        "sl_si_pessimiste": p.count(SL),
        "trades_qui_changent_d_issue": sum(1 for a, b in zip(o, p) if a != b),
    }


__all__ = [
    "AUCUN", "HONNETE", "INDETERMINE", "MOTIF_AMBIGU", "OPTIMISTE", "PESSIMISTE", "SL", "TP",
    "Bougie", "Resolution", "compter_ambiguites", "ecart_optimiste_pessimiste", "resoudre_bougie",
]
