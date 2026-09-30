"""#531 / H-126 + #560 / H-155 — « ENCAISSER LE FUNDING AVANT LA PUBLICATION ».

═══════════════════════════════════════════════════════════════════════════════════════════════
LE MECANISME — il est REEL, et la doc le dit noir sur blanc
═══════════════════════════════════════════════════════════════════════════════════════════════

Doc officielle (`trading/funding`) :

    « the funding payment **at the end of the interval** is
      `position_size * oracle_price * funding_rate` »
    « The funding rate is added or subtracted from the balance of contract holders
      **at the funding interval**. »

-> **Celui qui detient la position A L'INSTANT DU PRELEVEMENT encaisse l'HEURE ENTIERE de
   funding.** Meme s'il a ouvert une seconde avant. Le funding n'est PAS proratise.

C'est ca, la « capture avant publication » (#531). **Le mecanisme existe.**
Et #560 (saisonnalite) en decoule : le prelevement horaire cree un **flux mecanique** de
positions qui s'ouvrent juste avant et se ferment juste apres.

═══════════════════════════════════════════════════════════════════════════════════════════════
🔴 ET VOICI POURQUOI CA NE MARCHE (PROBABLEMENT) PAS — L'ARITHMETIQUE, PAS UN PREJUGE
═══════════════════════════════════════════════════════════════════════════════════════════════

Pour encaisser **UNE heure** de funding, il faut **UN aller-retour** :

    * en TAKER  (perp) : 2 x 4,5 = **9,0 bps**
    * en MAKER  (perp) : 2 x 1,5 = **3,0 bps**   <- mais etre maker = etre dans le carnet =
                                                    faire du market making. **T1b : mort.**

Or le funding MEDIAN sur Hyperliquid est de **~0,125 bps/h**.

    ***Il faut donc une heure ou |funding| > 9 bps -- soit 72x la mediane.***

**Ce module MESURE combien d'heures, sur des mois de `fundingHistory`, franchissent ce seuil.**
Ce n'est pas une opinion : c'est un comptage.

⚠️ ET DEUX RISQUES NON MODELISES, qui ne sont PAS petits :
  1. **Le prix.** On porte la position quelques secondes/minutes autour du prelevement. Le prix
     bouge de ~35 bps par heure en median. Meme sur 1 minute, c'est ~4,5 bps de bruit --
     **du meme ordre que le funding qu'on vient chercher.** *C'est exactement la maladie de T1b :
     le prix bouge plus que ce qu'on capture.*
  2. **La concurrence.** Si le mecanisme est trivial et documente, d'autres le font. Le carnet
     autour du prelevement est probablement le plus adverse de l'heure.

***On ne promet rien. On compte les heures qui passent le seuil, et on le dit honnetement.***

PUR : aucun appel reseau. Aucun ordre reel.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from hl_observer.collection.funding_backfill import PointFunding
from hl_observer.fees.hyperliquid_fees import nos_frais

_PERP = nos_frais("perp")

# Un aller-retour, pour capturer UNE heure de funding.
COUT_TAKER_ALLER_RETOUR_BPS = 2 * _PERP.taker_bps      # 9,0
COUT_MAKER_ALLER_RETOUR_BPS = 2 * _PERP.maker_bps      # 3,0

# Le bruit de prix qu'on subit en portant la position autour du prelevement.
# ~35 bps/h median (mesure du projet) -> sur 1 minute : 35 / sqrt(60) ~ 4,5 bps.
BRUIT_PRIX_1MIN_BPS = 4.5

MOTIF_AUCUNE_HEURE_RENTABLE = "AUCUNE_HEURE_NE_COUVRE_UN_ALLER_RETOUR"
MOTIF_HEURES_TROUVEES = "DES_HEURES_COUVRENT_LE_COUT_MAIS_PAS_FORCEMENT_LE_RISQUE_DE_PRIX"


@dataclass(frozen=True, slots=True)
class CaptureCoin:
    coin: str
    n_heures: int
    n_au_dessus_taker: int          # |funding| > 9,0 bps
    n_au_dessus_maker: int          # |funding| > 3,0 bps
    n_au_dessus_taker_et_bruit: int  # |funding| > 9,0 + 4,5  <- le test HONNETE
    max_bps_h: float
    median_bps_h: float

    @property
    def taux_taker(self) -> float:
        return self.n_au_dessus_taker / self.n_heures if self.n_heures else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin, "n_heures": self.n_heures,
            "n_au_dessus_taker": self.n_au_dessus_taker,
            "n_au_dessus_maker": self.n_au_dessus_maker,
            "n_au_dessus_taker_et_bruit": self.n_au_dessus_taker_et_bruit,
            "taux_taker": round(self.taux_taker, 6),
            "max_bps_h": round(self.max_bps_h, 4),
            "median_bps_h": round(self.median_bps_h, 4),
            "seuil_taker_bps": COUT_TAKER_ALLER_RETOUR_BPS,
            "seuil_taker_et_bruit_bps": COUT_TAKER_ALLER_RETOUR_BPS + BRUIT_PRIX_1MIN_BPS,
            "real_execution": False,
        }


def _median(xs: Sequence[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def evaluer_coin(coin: str, points: Iterable[PointFunding]) -> CaptureCoin | None:
    """Combien d'heures, sur l'historique, paient un aller-retour ? **On COMPTE.**

    `None` = etat vide honnete (jamais un 0 inventé qui ferait croire a une mesure).
    """
    bps = [abs(p.bps_h) for p in points if p.coin == coin.upper()]
    if not bps:
        return None
    seuil_honnete = COUT_TAKER_ALLER_RETOUR_BPS + BRUIT_PRIX_1MIN_BPS
    return CaptureCoin(
        coin=coin.upper(),
        n_heures=len(bps),
        n_au_dessus_taker=sum(1 for b in bps if b > COUT_TAKER_ALLER_RETOUR_BPS),
        n_au_dessus_maker=sum(1 for b in bps if b > COUT_MAKER_ALLER_RETOUR_BPS),
        n_au_dessus_taker_et_bruit=sum(1 for b in bps if b > seuil_honnete),
        max_bps_h=max(bps),
        median_bps_h=_median(bps),
    )


def evaluer(points: Iterable[PointFunding]) -> list[CaptureCoin]:
    par_coin: dict[str, list[PointFunding]] = defaultdict(list)
    for p in points:
        par_coin[p.coin].append(p)
    out = [c for coin, pts in par_coin.items() if (c := evaluer_coin(coin, pts))]
    return sorted(out, key=lambda c: c.n_au_dessus_taker, reverse=True)


def verdict(captures: Sequence[CaptureCoin]) -> dict[str, Any]:
    total_h = sum(c.n_heures for c in captures)
    n_taker = sum(c.n_au_dessus_taker for c in captures)
    n_honnete = sum(c.n_au_dessus_taker_et_bruit for c in captures)
    return {
        "n_coins": len(captures),
        "n_heures_total": total_h,
        "n_heures_qui_paient_un_aller_retour": n_taker,
        "n_heures_qui_paient_AR_ET_le_bruit_de_prix": n_honnete,
        "part": round(n_taker / total_h, 6) if total_h else 0.0,
        "motif": MOTIF_HEURES_TROUVEES if n_honnete else MOTIF_AUCUNE_HEURE_RENTABLE,
        "avertissement": (
            "⚠️ Meme les heures qui passent le seuil ne sont PAS un edge : (1) le prix bouge "
            "pendant qu'on porte la position -- c'est exactement ce qui a tue T1b ; (2) si le "
            "mecanisme est trivial et documente, le carnet y est le plus adverse de l'heure. "
            "**Compter des heures n'est pas gagner de l'argent.**"
        ),
        "real_execution": False,
    }


__all__ = [
    "BRUIT_PRIX_1MIN_BPS", "COUT_MAKER_ALLER_RETOUR_BPS", "COUT_TAKER_ALLER_RETOUR_BPS",
    "MOTIF_AUCUNE_HEURE_RENTABLE", "MOTIF_HEURES_TROUVEES",
    "CaptureCoin", "evaluer", "evaluer_coin", "verdict",
]
