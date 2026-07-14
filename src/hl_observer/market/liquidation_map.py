"""#372 / X-11 — LA CARTE DES LIQUIDATIONS : un flux FORCÉ, donc NON INFORMÉ.

═══════════════════════════════════════════════════════════════════════════════════════════════
🔴 D'ABORD : JE M'ETAIS TROMPE. CE N'EST **PAS** BLOQUE SUR UNE DONNEE QU'ON NE COLLECTE PAS.
═══════════════════════════════════════════════════════════════════════════════════════════════

J'ai ecrit trois fois que X-11 etait « bloque sur une donnee qu'on ne collecte pas ». **Faux.**

`clearinghouseState` -- **un appel qu'on fait DEJA** (`rest_info_client.py:290`) -- rend, pour
chaque position de chaque wallet :

    coin, szi, entryPx, positionValue, unrealizedPnl, **liquidationPx**, marginUsed, maxLeverage

Et le mot **`liquidationPx` n'apparaissait NULLE PART dans le code.** `snapshot_service` ne garde
que `coin / szi / entryPx` : **le reste est jete.**

*Ce n'etait pas une donnee manquante. C'etait une donnee RECUE ET EFFACEE.* La maladie du projet,
une fois de plus : une capacite presente, un chainon manquant, personne qui se plaint.

═══════════════════════════════════════════════════════════════════════════════════════════════
LA THESE -- ET POURQUOI ELLE N'EST **PAS** TUEE PAR T1b
═══════════════════════════════════════════════════════════════════════════════════════════════

Un liquide **ne sait rien**. Il ne choisit pas, il SUBIT. Son flux est donc **NON INFORME** --
l'exact inverse du fill d'un leader (qui, lui, est CONTRARIEN : le prix court contre lui AVANT
son execution).

    fournir de la liquidite a un flux INFORME   -> on se fait ramasser (T1, T1b)
    fournir de la liquidite a un flux FORCE     -> ???  **jamais mesure**

⚠️ ATTENTION, LE PIEGE EST EVIDENT : T1b a prouve que **fournir de la liquidite perd**, parce que
l'inventaire qu'on porte bouge 5 a 30x plus que le spread capture.

Alors pourquoi celle-ci survivrait-elle ? **Parce que l'entree n'est pas la meme.**
  * T1b consomme le **carnet L2** : on capture un SPREAD.
  * Ici on consomme la **carte des liquidations** : on capture un **DEPASSEMENT** (le prix va
    trop loin sous la pression forcee, puis revient).
C'est un mecanisme different, sur une entree qui **n'a jamais ete mesuree**. La regle du registre
s'applique : *une mesure faite sur une autre entree ne tue pas cette idee -- elle n'en parle pas.*

**MAIS ELLE NE LA SAUVE PAS NON PLUS.** Le depassement doit etre plus grand que le mouvement subi
en portant l'inventaire. C'est **exactement** le meme test que T1b, sur un autre nombre. Et il
n'est PAS encore fait.

═══════════════════════════════════════════════════════════════════════════════════════════════
CE MODULE : construit la carte (pur). Il ne PROMET rien.

⚠️ ETAT HONNETE : **l'instrument existe, la mesure PAS.** On n'a jamais enregistre `liquidationPx`,
donc on n'a **aucun historique**. Il faut un run de collecte. C'est IMPROVE-08 : *le temps, pas le
code.*

Aucun ordre reel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

# En dessous, une « grappe » de liquidations est du bruit : un seul wallet ne fait pas un flux.
MIN_WALLETS_PAR_GRAPPE = 2
MIN_NOTIONNEL_GRAPPE_USD = 10_000.0

MOTIF_PAS_DE_LIQ_PX = "AUCUN_liquidationPx_DANS_LES_POSITIONS_RIEN_A_CARTOGRAPHIER"


@dataclass(frozen=True, slots=True)
class PositionForcee:
    """Une position qui SERA liquidee si le prix atteint `liq_px`. Ce n'est pas une prediction :
    c'est une **mecanique** publiee par l'exchange."""

    wallet: str
    coin: str
    szi: float              # >0 = LONG (liquidation = vente forcee) ; <0 = SHORT (achat force)
    entry_px: float
    liq_px: float
    notionnel_usd: float

    @property
    def sens_du_flux_force(self) -> str:
        """Quand ca saute, l'exchange fait QUOI ?

        Un LONG liquide -> **VENTE** forcee (le prix est DESCENDU jusqu'a lui).
        Un SHORT liquide -> **ACHAT** force (le prix est MONTE).
        """
        return "SELL" if self.szi > 0 else "BUY"


def parser_positions(
    wallet: str, clearinghouse_state: Mapping[str, Any],
) -> list[PositionForcee]:
    """Extrait les positions AVEC leur prix de liquidation, depuis la reponse BRUTE de l'API.

    🔴 C'EST LE CHAINON QUI MANQUAIT. Le champ etait la, dans une reponse qu'on recevait deja.

    DENY-BY-DEFAULT : pas de `liquidationPx` (ex. une position en cross sans levier) -> on n'invente
    RIEN, on ecarte la ligne. *Une carte avec des prix inventes est pire qu'aucune carte.*
    """
    out: list[PositionForcee] = []
    rows = clearinghouse_state.get("assetPositions")
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        pos = row.get("position")
        if not isinstance(pos, Mapping):
            continue
        try:
            coin = str(pos.get("coin") or "")
            szi = float(pos.get("szi") or 0.0)
            liq = pos.get("liquidationPx")
            if coin == "" or szi == 0.0 or liq in (None, "", "null"):
                continue                                    # on n'invente RIEN
            liq_px = float(liq)
            entry = float(pos.get("entryPx") or 0.0)
            notionnel = abs(float(pos.get("positionValue") or (abs(szi) * (entry or liq_px))))
        except (TypeError, ValueError):
            continue
        if liq_px <= 0:
            continue
        out.append(PositionForcee(
            wallet=str(wallet), coin=coin, szi=szi, entry_px=entry,
            liq_px=liq_px, notionnel_usd=notionnel,
        ))
    return out


@dataclass(frozen=True, slots=True)
class Grappe:
    """Un AMAS de liquidations autour d'un prix : c'est LUI qui fait un flux, pas une position."""

    coin: str
    prix: float
    sens: str                       # SELL = ventes forcees (des longs sautent)
    notionnel_usd: float
    n_wallets: int
    distance_bps: float             # a quelle distance du prix courant

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin, "prix": self.prix, "sens": self.sens,
            "notionnel_usd": round(self.notionnel_usd, 2),
            "n_wallets": self.n_wallets,
            "distance_bps": round(self.distance_bps, 2),
            "real_execution": False,
        }


def construire_carte(
    positions: Sequence[PositionForcee],
    prix_courant: Mapping[str, float],
    *,
    largeur_grappe_bps: float = 50.0,
    max_distance_bps: float = 1000.0,
) -> list[Grappe]:
    """Regroupe les liquidations en GRAPPES : un seul wallet ne fait pas un flux.

    `largeur_grappe_bps` : deux liquidations a moins de 50 bps l'une de l'autre partent ensemble
    (une cascade ne fait pas la difference).
    `max_distance_bps` : au-dela de 10 %, la grappe est trop loin pour etre actionnable
    aujourd'hui -- on ne l'affiche pas, on ne la nie pas.
    """
    par_coin: dict[str, list[PositionForcee]] = {}
    for p in positions:
        par_coin.setdefault(p.coin, []).append(p)

    grappes: list[Grappe] = []
    for coin, ps in par_coin.items():
        px = float(prix_courant.get(coin) or 0.0)
        if px <= 0:
            continue                                        # sans prix courant, aucune distance
        for sens in ("SELL", "BUY"):
            cote = sorted(
                (p for p in ps if p.sens_du_flux_force == sens),
                key=lambda p: p.liq_px,
            )
            i = 0
            while i < len(cote):
                base = cote[i].liq_px
                seuil = base * (1.0 + largeur_grappe_bps / 1e4)
                bloc = []
                while i < len(cote) and cote[i].liq_px <= seuil:
                    bloc.append(cote[i])
                    i += 1
                notionnel = sum(b.notionnel_usd for b in bloc)
                wallets = len({b.wallet for b in bloc})
                prix_grappe = sum(b.liq_px * b.notionnel_usd for b in bloc) / notionnel \
                    if notionnel > 0 else base
                dist = abs(1e4 * (prix_grappe - px) / px)
                if (wallets >= MIN_WALLETS_PAR_GRAPPE
                        and notionnel >= MIN_NOTIONNEL_GRAPPE_USD
                        and dist <= max_distance_bps):
                    grappes.append(Grappe(
                        coin=coin, prix=prix_grappe, sens=sens,
                        notionnel_usd=notionnel, n_wallets=wallets, distance_bps=dist,
                    ))
    grappes.sort(key=lambda g: (-g.notionnel_usd, g.distance_bps))
    return grappes


def resume(grappes: Iterable[Grappe]) -> dict[str, Any]:
    gs = list(grappes)
    return {
        "n_grappes": len(gs),
        "notionnel_total_usd": round(sum(g.notionnel_usd for g in gs), 2),
        "grappes": [g.as_dict() for g in gs[:50]],
        # ⚠️ CE QUE CETTE CARTE **NE DIT PAS** :
        "avertissement": (
            "Cette carte dit OU le flux force tombera, pas s'il est RENTABLE de le prendre. "
            "Le depassement de prix doit dominer le mouvement subi en portant l'inventaire -- "
            "c'est exactement le test qui a tue le market making (T1b). IL N'EST PAS FAIT."
        ),
        "mesure_manquante": (
            "markout apres le franchissement d'une grappe : le prix depasse-t-il, puis "
            "revient-il ? Exige un HISTORIQUE de liquidationPx, qu'on n'a jamais enregistre."
        ),
        "real_execution": False,
    }


__all__ = [
    "MIN_NOTIONNEL_GRAPPE_USD", "MIN_WALLETS_PAR_GRAPPE", "MOTIF_PAS_DE_LIQ_PX",
    "Grappe", "PositionForcee", "construire_carte", "parser_positions", "resume",
]
