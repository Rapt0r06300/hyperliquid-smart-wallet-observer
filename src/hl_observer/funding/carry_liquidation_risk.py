"""T2b / #588 — LA JAMBE PERP D'UN CARRY PEUT ETRE LIQUIDEE (2026-07-13).

CE QUE `delta_neutral_carry.py` AFFIRMAIT, ET QUI EST INCOMPLET
--------------------------------------------------------------
    « LONG spot + SHORT perp, meme taille -> le prix s'annule. »

C'est vrai au niveau du **PORTEFEUILLE**. C'est FAUX au niveau du **COMPTE PERP**.

Le gain de la jambe spot est en HYPE, pas en USDC. Il **ne recharge pas** la marge du short.
Si le prix monte assez, le compte perp passe sous sa marge de maintenance et **il est liquide** --
pendant que la jambe spot, elle, est parfaitement en profit. Le portefeuille est neutre ; le
compte, lui, meurt.

    *Une couverture qui ne peut pas payer sa propre marge n'est pas une couverture : c'est un pari
    sur le fait que le prix ne bougera pas trop avant la fin.*

LA DOC OFFICIELLE (hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations, lue le 13/07)
---------------------------------------------------------------------------------------------
  * « The maintenance margin is **half of the initial margin at max leverage** » -> mm = 1/(2*L).
    Entre 1,25 % (levier max 40x) et 16,7 % (levier max 3x).
  * Liquidation d'abord **par le carnet** : si ca passe, « any remaining collateral remains with
    the trader » -- et « unlike CEXs there is **no clearance fee** on liquidations ».
  * Mais si l'equity tombe sous **2/3 de la marge de maintenance** sans liquidation reussie :
    **BACKSTOP** par le vault liquidateur. Et la : « the isolated position and isolated margin
    are transferred to the liquidator [...] **the maintenance margin is not returned to the
    user** ». C'est une perte SECHE.
  * Formule exacte : `liq_price = price - side * margin_available / position_size / (1 - l*side)`
    avec `l = 1/MAINTENANCE_LEVERAGE` et `side = -1` pour un short.

CE QU'IL FAUT DIRE HONNETEMENT, ET QUE JE NE VEUX PAS EXAGERER
-------------------------------------------------------------
A la liquidation, le short realise une perte de N*r -- mais le spot a gagne N*r. **Le choc en
dollars est donc largement absorbe.** Le carry ne « perd pas tout ». Ce serait malhonnete de le
pretendre. Les vrais couts sont ailleurs, et ils sont bien reels :

  1. **LE CARRY S'ARRETE.** Plus de short, plus de funding. La seule source de revenu disparait.
  2. **ON DEVIENT NU (LONG SPOT SEC).** C'est *exactement* la zone morte `FUNDING_JAMBE_NUE`,
     deja mesuree et deja enterree : 281 bps de bruit de prix subi pour 1 bps encaisse.
  3. **LE BACKSTOP CONFISQUE la marge de maintenance restante** (~mm x N), sans contrepartie.
  4. **RE-COUVRIR COUTE UN ALLER-RETOUR DE PLUS** (frais + spread + une base nouvelle).

ET LE COUT QUE PERSONNE N'AVAIT COMPTE : LE CAPITAL IMMOBILISE
-------------------------------------------------------------
T2 annoncait « +33,6 bps nets sur 500 $ ». Mais un carry delta-neutre immobilise **DEUX** poches :

    capital total  =  N (le spot, paye CASH -- il n'y a pas de levier sur le spot)
                   +  M (la marge du perp)

Le rendement reel se calcule sur `N + M`, pas sur `N`. Donc :

    rendement_sur_capital  =  funding_bps / (1 + m)      avec m = M/N

Et voila le PIEGE, qui est un vrai arbitrage, pas une formalite :
  * m PETIT  -> rendement flatteur... et liquidation a la moindre secousse ;
  * m GRAND  -> on survit aux secousses... et le rendement est divise par (1+m).

**On ne peut pas avoir les deux.** Le vrai APR du carry est celui qui survit au pire mouvement
qu'on a REELLEMENT observe -- pas celui qu'on obtient en supposant que le prix reste sage.

PUR, sans I/O. Aucun ordre reel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- doc officielle : maintenance = moitie de la marge initiale au levier MAX.
def fraction_marge_maintenance(levier_max: float) -> float:
    """mm = 1 / (2 * levier_max). 3x -> 16,7 %. 40x -> 1,25 %. (Doc Hyperliquid.)"""
    lev = float(levier_max)
    if lev <= 0:
        raise ValueError("levier_max doit etre > 0")
    return 1.0 / (2.0 * lev)


# En dessous de 2/3 de la marge de maintenance, c'est le BACKSTOP : la marge restante est
# CONFISQUEE (doc : « the maintenance margin is not returned to the user »).
SEUIL_BACKSTOP = 2.0 / 3.0

MOTIF_DONNEE_MANQUANTE = "RISQUE_LIQUIDATION_NON_MESURE_NO_TRADE"
MOTIF_MARGE_SOUS_MAINTENANCE = "MARGE_INFERIEURE_A_LA_MAINTENANCE_LIQUIDABLE_DES_L_ENTREE"
MOTIF_LIQUIDE_PAR_LE_PASSE = "LE_PIRE_MOUVEMENT_OBSERVE_AURAIT_LIQUIDE_LA_JAMBE_PERP"
MOTIF_OK = "JAMBE_PERP_SURVIT_AU_PIRE_MOUVEMENT_OBSERVE"


def mouvement_adverse_de_liquidation(marge_ratio: float, mm: float) -> float:
    """De combien le prix doit-il MONTER (en fraction) pour liquider un SHORT perp isole ?

    Derive de la formule officielle, `side = -1` :

        liq_price = P0 + margin_available / size / (1 + l)
        margin_available = M - mm * N          (isole)
        r_liq = (liq_price - P0)/P0 = (m - mm) / (1 + mm)      avec m = M/N

    Rend une valeur NEGATIVE si m <= mm : la position est deja liquidable a l'entree.
    (Le funding encaisse par le short recharge la marge au fil des heures et repousse ce seuil.
    On l'IGNORE : ca ne joue que dans notre sens. Une borne pessimiste, assumee.)
    """
    m = float(marge_ratio)
    f = float(mm)
    return (m - f) / (1.0 + f)


def marge_requise_pour_survivre(mouvement_adverse: float, mm: float) -> float:
    """L'inverse : quel m faut-il pour encaisser une hausse de `mouvement_adverse` sans liquidation ?

        m = r * (1 + mm) + mm
    """
    r = max(0.0, float(mouvement_adverse))
    f = float(mm)
    return r * (1.0 + f) + f


def rendement_sur_capital_total(rendement_bps_sur_notionnel: float, marge_ratio: float) -> float:
    """🔴 LE COUT QUE T2 N'AVAIT PAS COMPTE.

    Le spot est paye CASH (aucun levier sur le spot Hyperliquid). Le capital reellement immobilise
    est donc `N + M`, pas `N`. Un carry juge sur `N` seul est un carry juge sur la moitie de sa
    facture.
    """
    m = max(0.0, float(marge_ratio))
    return float(rendement_bps_sur_notionnel) / (1.0 + m)


def backstop_declenche(marge_restante_ratio: float, mm: float) -> bool:
    """Doc Hyperliquid : sous **2/3 de la marge de maintenance**, la liquidation passe par le
    vault de backstop et *« the maintenance margin is not returned to the user »*.

    🔴 CETTE FONCTION EXISTE PARCE QUE LE MUTATION TESTING (#250) A TROUVE QUE `SEUIL_BACKSTOP`
    N'ETAIT **UTILISEE NULLE PART** -- 24 h apres que je l'aie ecrite (#588). Le mutant
    `2.0/3.0 -> 2.0*3.0` survivait : aucun test ne s'en apercevait.

    ⚠️ MAIS ATTENTION : la brancher dans le calcul ADOUCIRAIT notre modele (entre `mm` et
    `2/3*mm`, on serait liquide SANS confiscation). **On ne l'a pas fait, et c'est deliberé :**
    `evaluer_risque_liquidation` suppose que le backstop se declenche **TOUJOURS**. C'est la borne
    PESSIMISTE, et sur un projet qui a deja fabrique trois edges, la borne pessimiste est la seule
    honnete tant qu'on n'a pas mesure la distribution des gaps de prix.

    *Une hypothese pessimiste ASSUMEE vaut mieux qu'une precision INVENTEE.*
    Un test (`test_notre_hypothese_backstop_est_bien_la_borne_PESSIMISTE`) verrouille ce sens :
    on ne pourra pas « optimiser » ce modele sans mesure.
    """
    return float(marge_restante_ratio) < SEUIL_BACKSTOP * float(mm)


def perte_seche_si_backstop(mm: float, notionnel_usd: float) -> float:
    """La marge de maintenance CONFISQUEE par le vault liquidateur (doc officielle).

    Ce n'est PAS « on perd tout » -- le spot absorbe la perte de prix du short. C'est la marge de
    maintenance restante, et elle seule, qui part. Il faut le dire exactement : ni plus, ni moins.
    """
    return max(0.0, float(mm)) * max(0.0, float(notionnel_usd))


@dataclass(frozen=True, slots=True)
class RisqueLiquidationCarry:
    coin: str
    levier_max: float
    mm: float                             # fraction de marge de maintenance
    marge_ratio: float                    # m = M / N
    mouvement_liquidant: float            # r_liq : hausse (fraction) qui liquide le short
    pire_mouvement_observe: float         # mesure sur des prix REELS
    survit: bool
    perte_seche_backstop_usd: float
    rendement_brut_bps: float             # sur le NOTIONNEL (ce que T2 annoncait)
    rendement_sur_capital_bps: float      # sur N + M (la verite)
    viable: bool
    motif: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin,
            "levier_max": self.levier_max,
            "marge_maintenance_pct": round(self.mm * 100.0, 3),
            "marge_ratio": round(self.marge_ratio, 4),
            "mouvement_liquidant_pct": round(self.mouvement_liquidant * 100.0, 2),
            "pire_mouvement_observe_pct": round(self.pire_mouvement_observe * 100.0, 2),
            "survit": self.survit,
            "perte_seche_backstop_usd": round(self.perte_seche_backstop_usd, 2),
            "rendement_brut_bps": round(self.rendement_brut_bps, 3),
            "rendement_sur_capital_bps": round(self.rendement_sur_capital_bps, 3),
            "viable": self.viable,
            "motif": self.motif,
            "note": self.note,
            "real_execution": False,
        }


def evaluer_risque_liquidation(
    *,
    coin: str,
    levier_max: float | None,
    marge_ratio: float | None,
    pire_mouvement_observe: float | None,
    rendement_brut_bps: float | None,
    notionnel_usd: float = 500.0,
) -> RisqueLiquidationCarry:
    """DENY-BY-DEFAULT. Un carry dont on n'a pas mesure le risque de liquidation est un carry
    qu'on n'a evalue que sur ses BONNES nouvelles."""
    if (levier_max is None or marge_ratio is None or pire_mouvement_observe is None
            or rendement_brut_bps is None):
        return RisqueLiquidationCarry(
            coin=coin, levier_max=0.0, mm=0.0, marge_ratio=0.0, mouvement_liquidant=0.0,
            pire_mouvement_observe=0.0, survit=False, perte_seche_backstop_usd=0.0,
            rendement_brut_bps=0.0, rendement_sur_capital_bps=0.0, viable=False,
            motif=MOTIF_DONNEE_MANQUANTE,
            note="un risque qu'on ne mesure pas est un risque qu'on subit",
        )

    mm = fraction_marge_maintenance(levier_max)
    r_liq = mouvement_adverse_de_liquidation(marge_ratio, mm)
    pire = max(0.0, float(pire_mouvement_observe))
    rdt_capital = rendement_sur_capital_total(rendement_brut_bps, marge_ratio)
    perte = perte_seche_si_backstop(mm, notionnel_usd)

    if r_liq <= 0.0:
        return RisqueLiquidationCarry(
            coin=coin, levier_max=float(levier_max), mm=mm, marge_ratio=float(marge_ratio),
            mouvement_liquidant=r_liq, pire_mouvement_observe=pire, survit=False,
            perte_seche_backstop_usd=perte, rendement_brut_bps=float(rendement_brut_bps),
            rendement_sur_capital_bps=rdt_capital, viable=False,
            motif=MOTIF_MARGE_SOUS_MAINTENANCE,
            note="marge %.1f %% <= maintenance %.1f %% : liquidable des la premiere seconde"
                 % (marge_ratio * 100.0, mm * 100.0),
        )

    # 🚩 BORNE, ET C'ETAIT UN BUG DANS MON PROPRE VERDICT : avec un `>` strict, la marge calculee
    # pour survivre EXACTEMENT au pire mouvement etait declaree insuffisante (a 1e-16 pres), et le
    # rapport imprimait « il aurait fallu +95,6 % ; le prix a monte de +95,6 % » -- une phrase qui
    # se contredit elle-meme. *Une mesure juste, mal bornee, redevient une mesure fausse.*
    survit = r_liq >= pire - 1e-12
    viable = survit and rdt_capital > 0.0
    if not survit:
        note = ("le tampon n'est que de +%.1f %% ; le prix a REELLEMENT monte de +%.1f %% sur la "
                "periode de detention. La jambe perp aurait ete liquidee -- et on serait retombe "
                "LONG SPOT SEC, c'est-a-dire dans la zone morte FUNDING_JAMBE_NUE."
                % (r_liq * 100.0, pire * 100.0))
    else:
        note = ("liquide a +%.1f %% ; pire hausse reellement observee +%.1f %%. Le tampon tient. "
                "MAIS le rendement tombe de %.2f a %.2f bps une fois le capital du spot ET la "
                "marge du perp comptes (m = %.2f)."
                % (r_liq * 100.0, pire * 100.0, rendement_brut_bps, rdt_capital, marge_ratio))

    return RisqueLiquidationCarry(
        coin=coin, levier_max=float(levier_max), mm=mm, marge_ratio=float(marge_ratio),
        mouvement_liquidant=r_liq, pire_mouvement_observe=pire, survit=survit,
        perte_seche_backstop_usd=perte, rendement_brut_bps=float(rendement_brut_bps),
        rendement_sur_capital_bps=rdt_capital, viable=viable,
        motif=MOTIF_OK if survit else MOTIF_LIQUIDE_PAR_LE_PASSE,
        note=note,
    )


def pire_hausse_sur_fenetre(prix: list[float], fenetre: int) -> float:
    """La pire hausse (fraction) subie par un SHORT entre l'entree et un point de la fenetre.

    CAUSAL : pour chaque entree i, on ne regarde que `prix[i+1 : i+1+fenetre]`. Aucun lookahead --
    on ne choisit pas l'entree en connaissant la suite, on ENUMERE toutes les entrees possibles et
    on prend la pire. C'est le pire des cas historiques, pas une strategie.
    """
    n = len(prix)
    f = int(max(1, fenetre))
    pire = 0.0
    for i in range(n):
        p0 = float(prix[i])
        if p0 <= 0:
            continue
        haut = max(prix[i + 1: i + 1 + f], default=p0)
        r = (float(haut) - p0) / p0
        if r > pire:
            pire = r
    return pire


__all__ = [
    "MOTIF_DONNEE_MANQUANTE", "MOTIF_LIQUIDE_PAR_LE_PASSE", "MOTIF_MARGE_SOUS_MAINTENANCE",
    "MOTIF_OK", "SEUIL_BACKSTOP", "backstop_declenche",
    "RisqueLiquidationCarry", "evaluer_risque_liquidation", "fraction_marge_maintenance",
    "marge_requise_pour_survivre", "mouvement_adverse_de_liquidation", "perte_seche_si_backstop",
    "pire_hausse_sur_fenetre", "rendement_sur_capital_total",
]
