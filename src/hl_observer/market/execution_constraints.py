"""#576 + #496 + #498 + #540 — LES CONTRAINTES RÉELLES DE L'EXCHANGE.

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI : notre PnL simulé est-il PHYSIQUEMENT RÉALISABLE ?
═══════════════════════════════════════════════════════════════════════════════════════════════

On simule des entrées et des sorties à des prix arbitraires, à des tailles arbitraires. Or
Hyperliquid **REFUSE** une partie de ces ordres. **Un trade qui aurait été rejeté et qu'on compte
quand même est un trade INVENTÉ** -- et son PnL est un mensonge.

SOURCES (doc officielle, lue le 2026-07-13) :
  * `for-developers/api/tick-and-lot-size`
  * `for-developers/api/error-responses`
  * `trading/contract-specifications`

═══════════════════════════════════════════════════════════════════════════════════════════════
LES RÈGLES, CITÉES
═══════════════════════════════════════════════════════════════════════════════════════════════

**#576 — TAILLE ET PRIX**

  « Prices can have up to **5 significant figures**, but no more than `MAX_DECIMALS - szDecimals`
    decimal places where MAX_DECIMALS is **6 for perps** and **8 for spot**.
    **Integer prices are always allowed**, regardless of the number of significant figures. »

  « Sizes are rounded to the `szDecimals` of that asset. »   (`szDecimals` vient de `meta`)

  « **MinTradeNtl** : Order must have minimum value of **$10**. »
  « **MinTradeSpotNtl** : Order must have minimum value of 10 {quote_token}. »

  ✅ **VERIFIE : notre sizing est de 500 $ de notionnel** (marge 50 $ x levier 10).
     **Le minimum de 10 $ ne nous mord PAS.** C'est constate, pas suppose.

**#498 + #540 — `alo` (post-only) : le piège**

  « **BadAloPx** : Post only order would have immediately matched, bbo was {bbo}. »

  🔴 Un ordre post-only qui croiserait le carnet est **REJETE**. Il n'est **PAS** execute en taker.
  ***Si la simulation suppose un fill maker la ou la realite REJETTE, elle compte un trade qui
  n'a jamais existe.*** Et si elle suppose un fill taker au tarif maker, elle se trompe d'un
  **facteur 3** (4,5 bps contre 1,5).

**#496 — LES REJETS (la liste officielle, aucune inventee)**

  Tick · MinTradeNtl · MinTradeSpotNtl · PerpMargin · ReduceOnly · BadAloPx · IocCancel ·
  BadTriggerPx · MarketOrderNoLiquidity · PositionIncreaseAtOpenInterestCap ·
  PositionFlipAtOpenInterestCap · TooAggressiveAtOpenInterestCap · OpenInterestIncrease ·
  InsufficientSpotBalance · **Oracle (« Order price too far from oracle »)** · PerpMaxPosition

  🔴 **`Oracle`** est une contrainte qu'on ne modelise **pas du tout** : on ne peut pas coter
  arbitrairement loin du prix oracle. Un backtest qui place des ordres tres loin du marche
  fabrique des fills impossibles.

PUR : aucun appel reseau, aucun ordre. Ce module VALIDE, il n'execute rien.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from typing import Any

SOURCE_DOC = "hyperliquid-docs/for-developers/api/{tick-and-lot-size,error-responses}"
DATE_LECTURE = "2026-07-13"

# « MAX_DECIMALS is 6 for perps and 8 for spot »
MAX_DECIMALS_PERP = 6
MAX_DECIMALS_SPOT = 8

# « Prices can have up to 5 significant figures »
CHIFFRES_SIGNIFICATIFS_MAX = 5

# « Order must have minimum value of $10. »
NOTIONNEL_MIN_USD = 10.0

# Notre sizing reel : marge 50 $ x levier 10.
NOTRE_NOTIONNEL_USD = 500.0

# La liste OFFICIELLE des rejets (doc `error-responses`). **Aucun invente.**
REJETS_OFFICIELS: tuple[str, ...] = (
    "Tick", "MinTradeNtl", "MinTradeSpotNtl", "PerpMargin", "ReduceOnly", "BadAloPx",
    "IocCancel", "BadTriggerPx", "MarketOrderNoLiquidity", "PositionIncreaseAtOpenInterestCap",
    "PositionFlipAtOpenInterestCap", "TooAggressiveAtOpenInterestCap", "OpenInterestIncrease",
    "InsufficientSpotBalance", "Oracle", "PerpMaxPosition",
)

MOTIF_OK = "ORDRE_VALIDE"
MOTIF_NOTIONNEL_TROP_PETIT = "MinTradeNtl"
MOTIF_PRIX_INVALIDE = "Tick"
MOTIF_TAILLE_NULLE_APRES_ARRONDI = "TAILLE_NULLE_APRES_ARRONDI_szDecimals"
MOTIF_POST_ONLY_AURAIT_CROISE = "BadAloPx"


@dataclass(frozen=True, slots=True)
class Verdict:
    valide: bool
    motif: str
    prix_arrondi: float | None = None
    taille_arrondie: float | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"valide": self.valide, "motif": self.motif,
                "prix_arrondi": self.prix_arrondi, "taille_arrondie": self.taille_arrondie,
                "detail": self.detail, "source": SOURCE_DOC, "real_execution": False}


def arrondir_taille(taille: float, *, sz_decimals: int) -> float:
    """« Sizes are rounded to the szDecimals of that asset. »

    ⚠️ On arrondit **VERS LE BAS** : on ne peut pas trader plus que ce qu'on a decide.
    Une simulation qui arrondit vers le haut s'offre de la taille gratuite.
    """
    if sz_decimals < 0:
        raise ValueError("sz_decimals negatif : %r" % sz_decimals)
    q = Decimal(1).scaleb(-int(sz_decimals))
    return float(Decimal(str(float(taille))).quantize(q, rounding=ROUND_DOWN))


def arrondir_prix(prix: float, *, sz_decimals: int, spot: bool = False) -> float | None:
    """Le prix valide le plus proche, ou `None` si aucun n'existe.

    DEUX contraintes, cumulatives :
      1. au plus **5 chiffres significatifs** ;
      2. au plus `MAX_DECIMALS - szDecimals` decimales (6 pour les perps, 8 pour le spot).
    « Integer prices are always allowed, regardless of the number of significant figures. »
    """
    p = float(prix)
    if p <= 0:
        return None
    max_dec = (MAX_DECIMALS_SPOT if spot else MAX_DECIMALS_PERP) - int(sz_decimals)
    if max_dec < 0:
        max_dec = 0

    d = Decimal(str(p))
    # (1) 5 chiffres significatifs
    exposant = d.adjusted()                       # position du 1er chiffre significatif
    dec_pour_5_sig = CHIFFRES_SIGNIFICATIFS_MAX - 1 - exposant
    decimales = min(max_dec, dec_pour_5_sig)
    if decimales < 0:
        # le prix est deja gros : seules les valeurs ENTIERES sont permises
        # (« Integer prices are always allowed »)
        return float(d.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
    q = Decimal(1).scaleb(-int(decimales))
    r = float(d.quantize(q, rounding=ROUND_HALF_EVEN))
    return r if r > 0 else None


def valider_ordre(
    *,
    prix: float,
    taille: float,
    sz_decimals: int,
    spot: bool = False,
    post_only: bool = False,
    meilleur_oppose: float | None = None,   # le bid (si on vend) ou l'ask (si on achete)
    achat: bool = True,
) -> Verdict:
    """L'ordre serait-il **ACCEPTE** par Hyperliquid ? Sinon, **il n'a jamais existe.**"""
    p = arrondir_prix(prix, sz_decimals=sz_decimals, spot=spot)
    if p is None:
        return Verdict(False, MOTIF_PRIX_INVALIDE, detail="prix <= 0 ou non representable")

    t = arrondir_taille(taille, sz_decimals=sz_decimals)
    if t <= 0.0:
        return Verdict(False, MOTIF_TAILLE_NULLE_APRES_ARRONDI, prix_arrondi=p,
                       taille_arrondie=t,
                       detail="szDecimals=%d ecrase la taille a zero. **Le trade n'existe pas.**"
                              % sz_decimals)

    notionnel = p * t
    if notionnel < NOTIONNEL_MIN_USD:
        return Verdict(False, MOTIF_NOTIONNEL_TROP_PETIT, prix_arrondi=p, taille_arrondie=t,
                       detail="notionnel %.2f $ < %.0f $ (doc : « Order must have minimum value "
                              "of $10 »)" % (notionnel, NOTIONNEL_MIN_USD))

    # 🔴 #498 / #540 -- `BadAloPx` : un post-only qui CROISERAIT est **REJETE**, pas converti.
    if post_only and meilleur_oppose is not None:
        croise = (p >= float(meilleur_oppose)) if achat else (p <= float(meilleur_oppose))
        if croise:
            return Verdict(
                False, MOTIF_POST_ONLY_AURAIT_CROISE, prix_arrondi=p, taille_arrondie=t,
                detail="doc : « Post only order would have immediately matched ». "
                       "**REJETE -- PAS execute en taker.** Une simulation qui compte un fill "
                       "ici invente un trade.",
            )

    return Verdict(True, MOTIF_OK, prix_arrondi=p, taille_arrondie=t)


def notre_sizing_passe_le_minimum() -> bool:
    """✅ Constate, pas suppose : 500 $ >> 10 $. La contrainte ne nous mord pas."""
    return NOTRE_NOTIONNEL_USD >= NOTIONNEL_MIN_USD


__all__ = [
    "CHIFFRES_SIGNIFICATIFS_MAX", "DATE_LECTURE", "MAX_DECIMALS_PERP", "MAX_DECIMALS_SPOT",
    "MOTIF_NOTIONNEL_TROP_PETIT", "MOTIF_OK", "MOTIF_POST_ONLY_AURAIT_CROISE",
    "MOTIF_PRIX_INVALIDE", "MOTIF_TAILLE_NULLE_APRES_ARRONDI",
    "NOTIONNEL_MIN_USD", "NOTRE_NOTIONNEL_USD", "REJETS_OFFICIELS", "SOURCE_DOC",
    "Verdict", "arrondir_prix", "arrondir_taille", "notre_sizing_passe_le_minimum",
    "valider_ordre",
]
