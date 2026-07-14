"""#543 / H-138 — LES FRAIS HYPERLIQUID. **LA SOURCE UNIQUE DE VÉRITÉ.**

═══════════════════════════════════════════════════════════════════════════════════════════════
🔴 POURQUOI CE FICHIER EXISTE
═══════════════════════════════════════════════════════════════════════════════════════════════

#543 demandait : *« nos frais maker sont-ils VRAIMENT 1,5 bps ? »*

**Reponse : OUI -- mais le code ne s'en servait pas.** Etat trouve le 2026-07-13 :

    copy_fidelity/fee_tiers.py          -> (4.5, 1.5)   ✅ juste
    copy_fidelity/exec_cost_model.py    -> 4.5          ✅ juste
    arbitrage/spread_formula.py         -> 6.0          ❌
    arbitrage/hyperliquid_cex_spread…   -> 6.0          ❌
    cli.py:1633                          -> 6            ❌
    cli.py:1683                          -> 4.0          ❌
    cli.py:3385                          -> taker 4      ❌ (c'est 4,5)
    backtest/ledger_replay_v9.py        -> **2.5**      ❌❌ ne correspond a RIEN

***Six endroits. Quatre valeurs. Aucune source citee. Et 2,5 bps ne figure NULLE PART dans la
grille officielle.***

> *Le nombre qui decide de CHAQUE trade etait invente, et duplique.*
> **La maladie du projet, encore : une capacite presente (fee_tiers.py, juste), un chainon
> manquant (personne ne l'appelle), personne qui se plaint.**

═══════════════════════════════════════════════════════════════════════════════════════════════
SOURCE : https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees  (lue le 2026-07-13)
═══════════════════════════════════════════════════════════════════════════════════════════════

PERPS, taux de base (« Base rate ») -- **c'est NOTRE tier : on n'a aucun volume** :

    Tier 0 (< 5 M$ de volume 14 j) : taker **0,045 % = 4,5 bps**   maker **0,015 % = 1,5 bps**

⚠️ **Le taker est 3x le maker.** Si on modelise du maker sur une execution qui aurait ete
prise au marche, on sous-estime le cout d'un **facteur 3**.

🔴 **LES REBATES MAKER NE NOUS SONT PAS ACCESSIBLES.** La doc les reserve aux comptes qui font
**> 0,5 % du volume maker de TOUT Hyperliquid sur 14 jours**. Pour un compte a 500 $, c'est
hors d'atteinte. **L'hypothese « aucun rebate » de T1b etait donc CORRECTE.**

🔴 **LE STAKING DONNE UNE REMISE -- MAIS DERISOIRE POUR NOUS.** Wood (> 10 HYPE) = **5 %** de
remise -> maker 1,425 bps au lieu de 1,5. **Gain : 0,075 bps. Ca ne change RIEN.** (Diamond
= 40 %, mais il faut 500 000 HYPE : plusieurs millions de dollars.)

🔴🔴 **HIP-3 « GROWTH MODE » : LES FRAIS SONT REDUITS DE 90 %.**
    « When growth mode is activated for an HIP-3 perp, protocol fees, rebates, volume
      contributions, and L1 user rate limit contributions are reduced by 90%. »
    -> maker **0,15 bps**, taker **0,45 bps**. **Un facteur 10.**
    ⚠️ MAIS le deployeur HIP-3 peut ajouter une part de 0 a 300 % (`deployerFeeScale`), ce qui
    **MULTIPLIE** les frais jusqu'a 2x. Les deux effets se composent.
    ⚖️ **Ca ne ressuscite PAS le market making** : T1b est mort sur le **RISQUE D'INVENTAIRE**
    (le prix bouge 5 a 30x plus que le spread capture), pas sur les frais. Diviser les frais par
    10 touche la porte B, pas la porte C -- **et c'est la porte C qui tue.** *Dire le contraire
    serait refaire la faute des 38 % d'APR.*
    ✅ Mais ma zone morte prevoit explicitement sa reouverture *« si une mesure montre que le
    risque d'inventaire est INFERIEUR au spread capture sur au moins un marche »*. **#517
    l'affirme pour les HIP-3 (20 bps de demi-spread). Il faut donc le MESURER, pas le supposer.**

🔴 **LE « BUILDER FEE » (#519) :** il n'existe que si on trade via un frontend « builder » qui
le prelieve. **Nous n'en utilisons aucun -> aucun builder fee.** Ce n'est PAS un cout manquant.

PUR : aucune valeur inventee, aucun appel reseau. Aucun ordre reel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SOURCE_DOC = "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees"
DATE_LECTURE = "2026-07-13"

# ── PERPS : la grille officielle, en bps. (tier, volume_min_usd, taker_bps, maker_bps) ────────
GRILLE_PERPS: tuple[tuple[int, float, float, float], ...] = (
    (0, 0.0,            4.5,  1.5),     # <- NOTRE TIER. Aucun volume.
    (1, 5_000_000.0,    4.0,  1.2),
    (2, 25_000_000.0,   3.5,  0.8),
    (3, 100_000_000.0,  3.0,  0.4),
    (4, 500_000_000.0,  2.8,  0.0),
    (5, 2_000_000_000.0, 2.6, 0.0),
    (6, 7_000_000_000.0, 2.4, 0.0),
)

# ── SPOT : idem (le carry HYPE de T2b utilise une jambe SPOT !) ───────────────────────────────
GRILLE_SPOT: tuple[tuple[int, float, float, float], ...] = (
    (0, 0.0,            7.0,  4.0),     # <- 🔴 SPOT MAKER = 4 bps, PAS 1,5 !
    (1, 5_000_000.0,    6.0,  3.0),
    (2, 25_000_000.0,   5.0,  2.0),
    (3, 100_000_000.0,  4.0,  1.0),
    (4, 500_000_000.0,  3.5,  0.0),
    (5, 2_000_000_000.0, 3.0, 0.0),
    (6, 7_000_000_000.0, 2.5, 0.0),
)

# ── Remises de staking (doc « Staking tiers »). Pour nous : ~0, on ne stake pas. ──────────────
REMISES_STAKING: tuple[tuple[str, float, float], ...] = (
    ("Wood", 10.0, 0.05), ("Bronze", 100.0, 0.10), ("Silver", 1_000.0, 0.15),
    ("Gold", 10_000.0, 0.20), ("Platinum", 100_000.0, 0.30), ("Diamond", 500_000.0, 0.40),
)

# HIP-3 growth mode : « fees ... reduced by 90% ».
FACTEUR_GROWTH_MODE = 0.10

# 🔒 NOTRE REALITE, declaree une seule fois. Tout le reste du code doit LIRE ceci.
NOTRE_TIER = 0
NOTRE_HYPE_STAKE = 0.0          # on ne stake rien
MAKER_PERP_BPS = 1.5
TAKER_PERP_BPS = 4.5
MAKER_SPOT_BPS = 4.0            # 🔴 le spot coute 2,7x plus cher en maker que le perp
TAKER_SPOT_BPS = 7.0

MOTIF_TIER_INCONNU = "TIER_DE_FRAIS_INCONNU"


@dataclass(frozen=True, slots=True)
class Frais:
    taker_bps: float
    maker_bps: float
    tier: int
    marche: str                 # "perp" | "spot"
    remise_staking: float = 0.0
    growth_mode: bool = False
    deployer_scale: float = 0.0

    def cout_aller_retour_bps(self, *, maker_entree: bool, maker_sortie: bool) -> float:
        """Le cout REEL d'un aller-retour. **Une jambe taker coute 3x une jambe maker.**"""
        e = self.maker_bps if maker_entree else self.taker_bps
        s = self.maker_bps if maker_sortie else self.taker_bps
        return e + s

    def as_dict(self) -> dict[str, Any]:
        return {"taker_bps": round(self.taker_bps, 4), "maker_bps": round(self.maker_bps, 4),
                "tier": self.tier, "marche": self.marche,
                "remise_staking": self.remise_staking, "growth_mode": self.growth_mode,
                "deployer_scale": self.deployer_scale,
                "source": SOURCE_DOC, "lu_le": DATE_LECTURE}


def remise_staking(hype_stake: float) -> float:
    """La remise obtenue en stakant `hype_stake` HYPE. 0 si on ne stake rien (notre cas)."""
    r = 0.0
    for _nom, seuil, remise in REMISES_STAKING:
        if float(hype_stake) > seuil:
            r = remise
    return r


def tier_pour_volume(volume_14j_usd: float, *, marche: str = "perp") -> int:
    grille = GRILLE_PERPS if marche == "perp" else GRILLE_SPOT
    t = 0
    for tier, seuil, _tk, _mk in grille:
        if float(volume_14j_usd) >= seuil:
            t = tier
    return t


def frais(
    *,
    marche: str = "perp",
    tier: int = NOTRE_TIER,
    hype_stake: float = NOTRE_HYPE_STAKE,
    growth_mode: bool = False,
    deployer_scale: float = 0.0,
) -> Frais:
    """Les frais officiels, pour un tier donne. **Aucune valeur inventee.**

    Formule HIP-3 (doc, `feeRates`) :
        scaleIfHip3 = deployerFeeScale < 1 ? deployerFeeScale + 1 : deployerFeeScale * 2
        growthModeScale = growthMode ? 0.1 : 1
    """
    m = str(marche).lower()
    if m not in ("perp", "spot"):
        raise ValueError("marche inconnu : %r (attendu 'perp' ou 'spot')" % marche)
    grille = GRILLE_PERPS if m == "perp" else GRILLE_SPOT
    ligne = next((l for l in grille if l[0] == int(tier)), None)
    if ligne is None:
        raise ValueError("%s : %r" % (MOTIF_TIER_INCONNU, tier))
    _t, _v, taker, maker = ligne

    d = float(deployer_scale)
    echelle_hip3 = 1.0
    if m == "perp" and d > 0.0:
        echelle_hip3 = (d + 1.0) if d < 1.0 else (d * 2.0)
    echelle_growth = FACTEUR_GROWTH_MODE if growth_mode else 1.0

    r = remise_staking(hype_stake)
    taker = taker * echelle_hip3 * echelle_growth * (1.0 - r)
    maker = maker * echelle_hip3 * echelle_growth * (1.0 - r)

    return Frais(taker_bps=taker, maker_bps=maker, tier=int(tier), marche=m,
                 remise_staking=r, growth_mode=bool(growth_mode), deployer_scale=d)


def nos_frais(marche: str = "perp") -> Frais:
    """**CE QU'ON PAIE REELLEMENT.** Tier 0, aucun stake, aucun rebate, aucun builder."""
    return frais(marche=marche, tier=NOTRE_TIER, hype_stake=NOTRE_HYPE_STAKE)


__all__ = [
    "DATE_LECTURE", "FACTEUR_GROWTH_MODE", "GRILLE_PERPS", "GRILLE_SPOT",
    "MAKER_PERP_BPS", "MAKER_SPOT_BPS", "MOTIF_TIER_INCONNU", "NOTRE_HYPE_STAKE", "NOTRE_TIER",
    "REMISES_STAKING", "SOURCE_DOC", "TAKER_PERP_BPS", "TAKER_SPOT_BPS",
    "Frais", "frais", "nos_frais", "remise_staking", "tier_pour_volume",
]
