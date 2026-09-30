"""LE MOTEUR CARRY — **la seule stratégie mesurée POSITIVE du projet.**

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI CELLE-CI, ET AUCUNE AUTRE
═══════════════════════════════════════════════════════════════════════════════════════════════

Sur ~600 idées, **une seule** a survécu à la falsification :

    **T2 / T2b — le carry delta-neutre sur HYPE. +33,6 bps dans son PIRE mois.**

Elle franchit le noyau parce que sa famille (`CARRY_STRUCTUREL`) est **VALIDE_PARTIEL**, pas une
zone morte. Et la raison est de NATURE, pas de degré :

    ***Ce n'est PAS une prédiction. C'est un PAIEMENT pour détenir une position.***
    On n'a pas besoin de savoir où va le prix : on se couvre, et on encaisse le flux.

C'est l'exact opposé du copy-trading, qui pariait qu'un leader savait quelque chose — **et la
mesure a dit qu'il ne savait rien** (−7,97 bps, même à coût ZÉRO).

═══════════════════════════════════════════════════════════════════════════════════════════════
🚩 CE QU'IL FAUT DIRE AVANT DE L'ALLUMER
═══════════════════════════════════════════════════════════════════════════════════════════════

  1. **~2 % APR, pas 4 %.** T2b l'a divisé par deux : le capital est immobilisé sur **DEUX**
     jambes (spot + perp), pas une.
  2. **−15 % de plus** après correction des frais : le **SPOT** coûte **4,0 bps** maker (le perp
     1,5). L'aller-retour réel est de **23 bps**, pas 18.
  3. 🔴 **UN SEUL MARCHÉ.** HYPE. Sept des huit candidats sont morts. *Une stratégie qui ne tient
     que sur un actif n'est pas une stratégie : c'est une observation.*
  4. 🔴 **LA JAMBE PERP PEUT ÊTRE LIQUIDÉE** (X-08). Le carry n'est « delta-neutre » que tant
     qu'on tient les deux jambes.
  5. 🎯 **ET IL DOIT BATTRE UN DÉPÔT PASSIF DANS HLP.** *Sinon toute notre complexité est
     dominée par un virement.*

***Je ne promets aucun PnL. Je branche la seule chose qui a été mesurée positive, et je la
soumets aux mêmes juges que tout le reste : le cash, le buy-and-hold, et HLP.***

PUR : aucun réseau, aucun ordre réel. Paper-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from hl_observer.fees.hyperliquid_fees import nos_frais

_PERP = nos_frais("perp")
_SPOT = nos_frais("spot")

# 🔴 Le vrai coût : DEUX jambes (spot + perp) x DEUX passages (entrée + sortie).
#    Le spot coûte 2,7x le perp en maker — c'est ce qui a fait sous-estimer T2b de 5 bps.
COUT_ALLER_RETOUR_TAKER_BPS = 2 * _PERP.taker_bps + 2 * _SPOT.taker_bps      # 23,0
COUT_ALLER_RETOUR_MAKER_BPS = 2 * _PERP.maker_bps + 2 * _SPOT.maker_bps      # 11,0

# Le capital est immobilisé sur DEUX venues/jambes. Juger sur une seule = doubler le chiffre.
CAPITAL_SUR_DEUX_JAMBES = 2.0

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔴 CALIBRAGE CORRIGE PAR LE PREMIER RUN REEL (2026-07-14) — **mon gate rejetait le seul
#    trade valable du projet.**
#
# AVANT : MIN_FUNDING = 0,20 bps/h · HEURES_MAX = **24 h**.
#         -> HYPE (+0,1043 bps/h, **+4,28 % APR**, et **il a du spot**) etait REFUSE
#            au motif « funding trop faible ».
#
# LA FAUTE : j'avais copie la borne de 24 h depuis la capture de funding HORAIRE (#531),
#            ou l'on tient **une heure**.
#
#     ***UN CARRY SE TIENT. IL NE SE SCALPE PAS.***
#     Amortir 23 bps en 9 jours, puis encaisser toute l'annee : **c'est exactement ce qu'un
#     carry EST.** Le juger avec l'horloge d'un scalp, c'est le tuer par erreur de cadran.
#
# APRES : on tient jusqu'a **30 jours** pour amortir. Le vrai risque n'est pas la duree --
#         c'est que **le funding s'inverse** (OP : -0,089 bps/h) ou que la **jambe perp soit
#         LIQUIDEE** (X-08).
# ═══════════════════════════════════════════════════════════════════════════════════════════════
MIN_FUNDING_BPS_H = 0.05          # au-dessous, meme sur 30 jours, ca ne paie pas

# Un carry se tient des MOIS. 30 jours pour amortir les couts d'entree, c'est normal.
HEURES_MAX_POUR_AMORTIR = 720.0   # 30 jours

MOTIF_FUNDING_TROP_FAIBLE = "FUNDING_TROP_FAIBLE_POUR_AMORTIR_4_EXECUTIONS"
MOTIF_CARRY_OUVRABLE = "CARRY_OUVRABLE_FUNDING_MESURE_ET_COUTS_AMORTISSABLES"
MOTIF_PAS_DE_DONNEE = "FUNDING_NON_MESURE"


@dataclass(frozen=True, slots=True)
class CandidatCarry:
    """Un candidat CARRY. Sa famille est `CARRY_STRUCTUREL` -> il **franchit** le noyau."""
    coin: str
    funding_bps_h: float          # HORAIRE (HL paie à l'heure — pas le taux 8 h des CEX !)
    notional_usd: float
    strategie: str = "CARRY"
    direction: str = "SHORT"      # short le PERP (on encaisse le funding), long le SPOT

    @property
    def heures_pour_amortir(self) -> float | None:
        f = abs(self.funding_bps_h)
        return (COUT_ALLER_RETOUR_TAKER_BPS / f) if f > 0 else None

    @property
    def apr_brut_sur_capital(self) -> float:
        """Le funding annualisé, **AVANT coûts**. *Ce chiffre ne doit JAMAIS être affiché seul.*"""
        return (abs(self.funding_bps_h) / CAPITAL_SUR_DEUX_JAMBES) * 24 * 365 / 1e4

    def apr_net_sur_capital(self, *, cout_bps: float = None,          # type: ignore[assignment]
                            horizon_heures: float = None) -> float:   # type: ignore[assignment]
        """🔴🔴 **L'APR NET.** Le seul chiffre qu'on a le droit de montrer à Flo.

        ═══════════════════════════════════════════════════════════════════════════════════════
        LE BUG QUE CETTE METHODE REPARE — *la maladie du projet, 17e fois*
        ═══════════════════════════════════════════════════════════════════════════════════════

        L'ancien `apr_sur_capital` valait :

            (funding / 2 jambes) x 24 x 365

        ***Les 23 bps de couts ne figuraient NULLE PART.*** Ils etaient verifies a la porte
        (`heures_pour_amortir <= 720`)... puis **jamais soustraits du nombre affiche**.

        *Une capacite presente (les couts SONT calcules), un chainon manquant (ils ne descendent
        pas dans le chiffre), personne qui se plaint.* **Exactement la forme du plancher a zero.**

        Ecart mesure :  PURR 12,71 % -> **11,31 %**  ·  PUMP 6,63 % -> **5,23 %**
                        HYPE  5,87 % -> **4,48 %**

        🔴 Et ce n'est pas cosmetique : a 4,5 % net, **HYPE et PUMP perdent contre un depot
        passif dans HLP.** Le chiffre BRUT les faisait passer pour des gagnants.

        ***Un cout qu'on verifie mais qu'on ne soustrait pas est un cout qu'on cache.***
        """
        c = COUT_ALLER_RETOUR_TAKER_BPS if cout_bps is None else float(cout_bps)
        h = HEURES_MAX_POUR_AMORTIR if horizon_heures is None else float(horizon_heures)
        if h <= 0:
            return 0.0
        brut_sur_horizon = abs(float(self.funding_bps_h)) * h      # ce qu'on ENCAISSE
        net_sur_horizon = brut_sur_horizon - c                     # les 4 EXECUTIONS
        if net_sur_horizon <= 0:
            return 0.0                                             # jamais un APR negatif maquille
        par_unite_de_capital = net_sur_horizon / CAPITAL_SUR_DEUX_JAMBES
        return (par_unite_de_capital / 1e4) * (24 * 365 / h)

    @property
    def apr_sur_capital(self) -> float:
        """**Alias NET.** *Le nom historique pointe desormais sur le chiffre HONNETE.*

        🔒 On ne renomme pas : on **corrige la valeur**. Tout appelant existant (scanner, noyau,
        dashboard, exports) recoit maintenant le **NET**, sans avoir a etre modifie.
        *Si on avait juste ajoute une methode, l'ancien chiffre faux aurait survecu quelque part.*
        """
        return self.apr_net_sur_capital()


@dataclass(frozen=True, slots=True)
class VerdictCarry:
    coin: str
    ouvrable: bool
    motif: str
    funding_bps_h: float
    heures_pour_amortir: float | None
    apr_sur_capital: float
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin, "ouvrable": self.ouvrable, "motif": self.motif,
            "funding_bps_h": round(self.funding_bps_h, 4),
            "heures_pour_amortir": (round(self.heures_pour_amortir, 1)
                                    if self.heures_pour_amortir is not None else None),
            "apr_sur_capital_pct": round(self.apr_sur_capital * 100, 2),
            "cout_aller_retour_bps": COUT_ALLER_RETOUR_TAKER_BPS,
            "note": self.note,
            "avertissement": (
                "⚠️ **UN SEUL MARCHÉ (HYPE) a survécu sur 8.** Et la jambe PERP peut être "
                "LIQUIDÉE. *Une stratégie qui ne tient que sur un actif n'est pas une stratégie : "
                "c'est une observation.* 🎯 Elle doit battre le CASH, le buy-and-hold **et un "
                "dépôt passif dans HLP** — sinon elle est dominée."
            ),
            "paper_only": True, "real_execution": False,
        }


def evaluer(candidat: CandidatCarry,
            *, cout_bps: float = COUT_ALLER_RETOUR_TAKER_BPS,
            min_funding: float = MIN_FUNDING_BPS_H,
            heures_max: float = HEURES_MAX_POUR_AMORTIR) -> VerdictCarry:
    """Le carry paie-t-il ses **4 exécutions** ? **On compte. On ne raconte pas.**"""
    f = abs(float(candidat.funding_bps_h))

    if f <= 0.0:
        return VerdictCarry(candidat.coin, False, MOTIF_PAS_DE_DONNEE, 0.0, None, 0.0,
                            "funding non mesuré — **état vide honnête**, jamais un 0 supposé")

    h = candidat.heures_pour_amortir
    if f < min_funding or h is None or h > heures_max:
        return VerdictCarry(
            candidat.coin, False, MOTIF_FUNDING_TROP_FAIBLE, candidat.funding_bps_h, h,
            candidat.apr_sur_capital,
            "funding %.3f bps/h → il faudrait tenir **%s** pour amortir %.1f bps de coûts "
            "(4 exécutions : spot + perp, aller-retour)."
            % (f, ("%.0f h" % h) if h else "l'infini", cout_bps),
        )

    return VerdictCarry(
        candidat.coin, True, MOTIF_CARRY_OUVRABLE, candidat.funding_bps_h, h,
        candidat.apr_sur_capital,
        "funding %.3f bps/h → coûts amortis en **%.0f h**. APR sur le capital des DEUX jambes : "
        "**%.2f %%**. ⚠️ *Ce n'est pas une promesse : c'est un funding OBSERVÉ, et il peut "
        "s'inverser.*" % (f, h, candidat.apr_sur_capital * 100),
    )


def selectionner(candidats: Sequence[CandidatCarry]) -> list[VerdictCarry]:
    """Les carrys ouvrables, du meilleur au pire. *Moins de trades, beaucoup plus propres.*"""
    vs = [evaluer(c) for c in candidats]
    return sorted([v for v in vs if v.ouvrable],
                  key=lambda v: v.apr_sur_capital, reverse=True)


__all__ = [
    "CAPITAL_SUR_DEUX_JAMBES", "COUT_ALLER_RETOUR_MAKER_BPS", "COUT_ALLER_RETOUR_TAKER_BPS",
    "HEURES_MAX_POUR_AMORTIR", "MIN_FUNDING_BPS_H",
    "MOTIF_CARRY_OUVRABLE", "MOTIF_FUNDING_TROP_FAIBLE", "MOTIF_PAS_DE_DONNEE",
    "CandidatCarry", "VerdictCarry", "evaluer", "selectionner",
]
