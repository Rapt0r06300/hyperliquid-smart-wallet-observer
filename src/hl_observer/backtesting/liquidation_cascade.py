"""#530 / H-125 — LES LIQUIDATIONS : un flux FORCÉ, donc NON INFORMÉ.

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI C'EST LA MEILLEURE PISTE QUI RESTE
═══════════════════════════════════════════════════════════════════════════════════════════════

Toute la thèse du copy-trading est morte parce que **le flux qu'on suivait n'avait aucune
information** (le leader est CONTRARIEN : −7,97 bps, même à coût ZÉRO).

Une liquidation, c'est l'inverse exact :

    ***Le liquidé ne CHOISIT pas de vendre. Il est VENDU.***

Un vendeur forcé ne détient **aucune information** sur la valeur. Il subit une contrainte
mécanique. **Prendre l'autre côté d'un flux non informé est la seule source d'edge honnête qui
existe en microstructure** -- c'est littéralement le métier du teneur de marché, mais **sans le
problème qui a tué T1b** : on ne s'engage pas en permanence, on n'intervient que sur l'événement.

Et **on a la donnée** : `clearinghouseState` rend `liquidationPx` (X-11, branché le 2026-07-13).
On peut donc construire une **carte des prix de liquidation** des wallets qu'on suit.

═══════════════════════════════════════════════════════════════════════════════════════════════
🚩 LES QUATRE PIÈGES — dits AVANT la mesure
═══════════════════════════════════════════════════════════════════════════════════════════════

*(Parce que la règle est : quand un résultat est beau, regarde qui survit AVANT de l'annoncer.)*

  1. 🔴 **LE COUTEAU QUI TOMBE.** Prendre l'autre côté d'une cascade, c'est acheter pendant que
     le prix s'effondre. **Si la cascade continue, on est dedans.** L'edge n'existe que si le
     **rebond** dépasse la **continuation**. *C'est une question empirique, pas une évidence.*
  2. 🔴 **NOTRE CARTE EST BORGNE.** On ne voit `liquidationPx` que des wallets **qu'on suit**.
     La vraie carte, c'est *tous* les comptes de Hyperliquid. **Un cluster qu'on ne voit pas
     nous liquide quand même.** → toute mesure faite sur notre carte est une **borne basse** de
     la vraie densité, jamais une image fidèle. **On le dit.**
  3. 🔴 **LE BACKSTOP LIQUIDATOR.** Doc HIP-3 : Hyperliquid a des **liquidateurs backstop
     on-chain** (`0x400..00 + dex_index`) qui *absorbent* les positions liquidables. **Une partie
     du flux forcé ne passe donc JAMAIS par le carnet** — elle nous est invisible ET
     inaccessible.
  4. 🔴 **LA CONCURRENCE.** Si le flux forcé était de l'argent gratuit, il serait déjà ramassé.
     Le carnet autour d'un cluster de liquidations est probablement **le plus adverse du marché**.

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QU'ON MESURE (et rien d'autre)
═══════════════════════════════════════════════════════════════════════════════════════════════

Quand le prix **traverse** un cluster de liquidations :

    markout(h) = (prix[t+h] − prix[t]) / prix[t]   **du point de vue de CELUI QUI ABSORBE**

  * Si le flux est non informé -> **le markout de l'absorbeur est POSITIF** (le prix rebondit).
  * Si le flux est informé (ou si la cascade continue) -> **négatif**. *Et alors la piste meurt.*

⚠️ **Le markout se calcule sur le MID, JAMAIS sur les prix de trade.** *(Le bid-ask bounce a
fabriqué un faux edge de +31 bps dans T1, et je l'ai REFAIT dans T1b. Deux fois suffit.)*

PUR : aucun appel réseau. Aucun ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

# Un cluster : des prix de liquidation serrés dans une bande étroite.
LARGEUR_CLUSTER_BPS = 50.0        # 0,5 % : au-delà, ce n'est plus le même événement
MIN_COMPTES_PAR_CLUSTER = 3       # 1 ou 2 comptes ne font pas une cascade

# Horizons de markout. On regarde le REBOND, pas la seconde qui suit.
HORIZONS_S = (30.0, 300.0, 900.0)

MIN_EVENEMENTS = 20               # *un seul essai chanceux ne prouve rien*

MOTIF_PAS_ASSEZ_D_EVENEMENTS = "PAS_ASSEZ_DE_TRAVERSEES_DE_CLUSTER"
MOTIF_COUTEAU_QUI_TOMBE = "LE_PRIX_CONTINUE_DE_TOMBER_ABSORBER_PERD"
MOTIF_FLUX_NON_INFORME = "MARKOUT_POSITIF_POUR_L_ABSORBEUR_FLUX_FORCE_NON_INFORME"


@dataclass(frozen=True, slots=True)
class NiveauLiquidation:
    coin: str
    adresse: str
    liquidation_px: float
    notionnel_usd: float
    long: bool                    # un LONG est liquidé EN DESSOUS ; un SHORT AU-DESSUS


@dataclass(frozen=True, slots=True)
class Cluster:
    coin: str
    prix_centre: float
    n_comptes: int
    notionnel_total_usd: float
    long: bool                    # le côté qui va être forcé à VENDRE (long) ou à ACHETER (short)

    def as_dict(self) -> dict[str, Any]:
        return {"coin": self.coin, "prix_centre": round(self.prix_centre, 6),
                "n_comptes": self.n_comptes,
                "notionnel_total_usd": round(self.notionnel_total_usd, 2),
                "cote_force": "VENTE" if self.long else "ACHAT"}


@dataclass(frozen=True, slots=True)
class VerdictCascade:
    coin: str
    n_evenements: int
    markout_par_horizon_bps: dict[float, float]
    viable: bool
    motif: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin, "n_evenements": self.n_evenements,
            "markout_par_horizon_bps": {str(h): round(v, 4)
                                        for h, v in self.markout_par_horizon_bps.items()},
            "viable": self.viable, "motif": self.motif, "note": self.note,
            "carte_borgne": (
                "⚠️ Notre carte ne voit que les wallets QU'ON SUIT. C'est une **borne basse** de "
                "la densité réelle, jamais une image fidèle. Et le **backstop liquidator** de HL "
                "absorbe une partie du flux **hors carnet** : elle nous est invisible."
            ),
            "real_execution": False,
        }


def construire_clusters(
    niveaux: Iterable[NiveauLiquidation],
    *,
    largeur_bps: float = LARGEUR_CLUSTER_BPS,
    min_comptes: int = MIN_COMPTES_PAR_CLUSTER,
) -> list[Cluster]:
    """Regroupe les prix de liquidation proches. **Un compte isolé n'est pas une cascade.**"""
    par_cle: dict[tuple[str, bool], list[NiveauLiquidation]] = {}
    for n in niveaux:
        if n.liquidation_px <= 0 or n.notionnel_usd <= 0:
            continue                       # deny-by-default : donnée absurde ECARTEE
        par_cle.setdefault((n.coin, n.long), []).append(n)

    out: list[Cluster] = []
    for (coin, long), ns in par_cle.items():
        ns.sort(key=lambda x: x.liquidation_px)
        courant: list[NiveauLiquidation] = []
        for n in ns:
            if courant and abs(n.liquidation_px - courant[0].liquidation_px) \
                    / courant[0].liquidation_px * 1e4 > largeur_bps:
                if len(courant) >= min_comptes:
                    out.append(_fermer(coin, long, courant))
                courant = []
            courant.append(n)
        if len(courant) >= min_comptes:
            out.append(_fermer(coin, long, courant))
    return sorted(out, key=lambda c: c.notionnel_total_usd, reverse=True)


def _fermer(coin: str, long: bool, ns: list[NiveauLiquidation]) -> Cluster:
    notionnel = sum(n.notionnel_usd for n in ns)
    centre = sum(n.liquidation_px * n.notionnel_usd for n in ns) / notionnel
    return Cluster(coin=coin, prix_centre=centre, n_comptes=len(ns),
                   notionnel_total_usd=notionnel, long=long)


def markout_absorbeur_bps(
    mids: Sequence[tuple[float, float]],      # (time_s, MID -- **jamais un prix de trade**)
    *, t_evenement: float, horizon_s: float, cote_force_vend: bool,
) -> float | None:
    """Le markout de **CELUI QUI ABSORBE** le flux forcé.

    Si les liquidés sont forcés de **VENDRE**, l'absorbeur **ACHÈTE** : il gagne si le prix MONTE.
    S'ils sont forcés d'**ACHETER**, l'absorbeur **VEND** : il gagne si le prix BAISSE.

    ⚠️ **Sur le MID.** Un markout sur des prix de trade oscille bid↔ask et fabrique un edge.
    *Je l'ai fait deux fois. Pas une troisième.*
    """
    if not mids:
        return None
    avant = [m for m in mids if m[0] <= t_evenement]
    apres = [m for m in mids if m[0] >= t_evenement + horizon_s]
    if not avant or not apres:
        return None
    p0 = avant[-1][1]
    p1 = apres[0][1]
    if p0 <= 0:
        return None
    r = (p1 - p0) / p0 * 1e4
    return r if cote_force_vend else -r        # l'absorbeur est du côté opposé


def juger(
    coin: str,
    markouts_par_horizon: dict[float, list[float]],
    *, min_evenements: int = MIN_EVENEMENTS,
) -> VerdictCascade:
    """**On compte. On ne raconte pas.**"""
    n = min((len(v) for v in markouts_par_horizon.values()), default=0)
    if n < min_evenements:
        return VerdictCascade(
            coin, n, {}, False,
            "%s : %d < %d" % (MOTIF_PAS_ASSEZ_D_EVENEMENTS, n, min_evenements),
            "*Un seul essai chanceux ne prouve rien.*",
        )
    moy = {h: (sum(v) / len(v)) for h, v in markouts_par_horizon.items() if v}
    meilleur = max(moy.values()) if moy else 0.0

    if meilleur <= 0.0:
        return VerdictCascade(
            coin, n, moy, False, MOTIF_COUTEAU_QUI_TOMBE,
            "**Le prix CONTINUE de tomber.** Absorber le flux forcé PERD de l'argent : le "
            "couteau ne rebondit pas assez. *La piste meurt ici, et c'est une vraie réponse.*",
        )
    return VerdictCascade(
        coin, n, moy, True, MOTIF_FLUX_NON_INFORME,
        "Markout POSITIF pour l'absorbeur (+%.2f bps au meilleur horizon). **Le flux forcé est "
        "bien NON informé.** ⚠️ MAIS il reste à payer les frais (9 bps taker / 3 bps maker) et "
        "à survivre au fait que **notre carte est borgne**. *Un markout brut n'est pas un edge "
        "net.*" % meilleur,
    )


__all__ = [
    "HORIZONS_S", "LARGEUR_CLUSTER_BPS", "MIN_COMPTES_PAR_CLUSTER", "MIN_EVENEMENTS",
    "MOTIF_COUTEAU_QUI_TOMBE", "MOTIF_FLUX_NON_INFORME", "MOTIF_PAS_ASSEZ_D_EVENEMENTS",
    "Cluster", "NiveauLiquidation", "VerdictCascade",
    "construire_clusters", "juger", "markout_absorbeur_bps",
]
