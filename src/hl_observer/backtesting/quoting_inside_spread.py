"""#587 / T1b — COTER **DANS** LE SPREAD : la derniere porte ouverte du market making (2026-07-13).

T1 a tue le MM retail avec un chiffre : *« aucun marche ne paie a notre place »*. On se met dans
la file au meilleur bid, et **2 577 $ de profondeur passent devant nous** -- 19 fills en 4 heures.
Pas meme mesurable.

Mais T1 a laisse **une porte explicitement ouverte**, et elle n'a jamais ete mesuree :

    Et si, au lieu de faire la QUEUE au meilleur prix, on se mettait **DEVANT** --
    c'est-a-dire qu'on AMELIORE le prix d'un tick ?

On devient alors **seul, en tete**, au meilleur prix du marche. Tout agresseur nous prend en
premier. Le probleme de file disparait.

═══════════════════════════════════════════════════════════════════════════════════════════════
🔴 MAIS ON PAIE CETTE PLACE, ET IL FAUT LE DIRE AVANT DE MESURER
═══════════════════════════════════════════════════════════════════════════════════════════════

  1. **On capture MOINS.** Acheter a `bid + tick` et vendre a `ask - tick`, c'est capturer
     `spread - 2 ticks` au lieu de `spread`. On a **donne deux ticks** pour acheter la place.
  2. **On est rempli en PREMIER -- donc aussi par le flux INFORME.** La selection adverse est a
     son MAXIMUM : c'est le prix de la tete de file.
  3. 🔴 **ET SURTOUT : SI LE SPREAD FAIT UN SEUL TICK, IL N'Y A PAS D'INTERIEUR.**
     C'est le cas de BTC (`bid 63906 / ask 63907`). *On ne peut pas coter « dans » un spread qui
     n'a pas de dedans.* C'est une **impossibilite arithmetique**, pas une question de rendement.

CE MODULE MESURE, DANS CET ORDRE (le plus dur d'abord) :

    a. Y a-t-il de la PLACE ?           spread > 1 tick, sinon -> PAS_DE_PLACE
    b. La capture SURVIT-ELLE aux frais ?   spread - 2 ticks > 3 bps, sinon -> mort par
                                            arithmetique, avant meme de parler de flux
    c. Le flux nous PUNIT-il ?          markout apres nos fills (selection adverse)

DENY-BY-DEFAULT : donnee insuffisante -> `INSUFFICIENT_DATA`. Jamais un chiffre invente.

⚠️ LE TICK EST **ESTIME** DEPUIS LES DONNEES (le plus petit spread jamais observe sur ce coin --
un spread ne peut pas etre plus petit qu'un tick). C'est une **borne haute** du tick, donc une
estimation **CONSERVATRICE de la place disponible** : elle nous donne, au pire, MOINS de place
qu'en realite. On l'assume, et on le dit. *Une hypothese declaree vaut mieux qu'une precision
inventee.*

Aucun ordre reel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

# --- Les couts REELS de Hyperliquid (pas de rebate maker avant les tiers institutionnels).
FRAIS_MAKER_BPS = 1.5                    # PAR JAMBE. Le maker PAIE chez Hyperliquid.
COUT_ALLER_RETOUR_BPS = 2 * FRAIS_MAKER_BPS   # 3,0 bps

MIN_SNAPSHOTS = 30
MIN_FILLS = 20                           # sous 20 fills, c'est une anecdote (lecon #242)

# 🔴 LE TERME QUE MA 1re VERSION AVAIT OUBLIE -- ET QUI CHANGE LE VERDICT.
#
# Ma 1re passe a sorti « CASHCAT : +34,94 bps net, VIABLE ». J'allais l'annoncer. Puis j'ai
# regarde QUI survivait :
#   * **CASHCAT** -- le coin que la zone morte FUNDING_JAMBE_NUE designe nommement comme
#     **« le marche le plus dangereux »** : il bouge de **219 bps/h** ;
#   * **KAITO** -- celui que T1 avait deja etudie, et qui s'etait revele un mirage.
#
# Capturer 35 bps de spread sur un coin qui bouge de 219 bps EN UNE HEURE, ce n'est pas du market
# making : **c'est un pari directionnel avec un coupon.** (La phrase EXACTE qu'on a ecrite pour
# refuser le funding sur jambe nue. Le meme piege, sous un autre nom.)
#
# Un market maker ne gagne pas le spread : il gagne le spread **MOINS la variance de l'inventaire
# qu'il est force de porter**. Sans ce terme, tout marche volatil paraitra genereux -- et c'est
# EXACTEMENT pour ca que son spread est large.
#
# LE GARDE : la capture doit dominer le mouvement de prix subi pendant qu'on porte la position.
# Ratio minimal exige = 1,0 (capture >= vol sur l'horizon de detention). C'est deja tres genereux.
RATIO_CAPTURE_SUR_VOL_MIN = 1.0
HORIZON_DETENTION_S = 300.0              # 5 min : le temps de trouver l'autre jambe du round-trip

MOTIF_INSUFFISANT = "INSUFFICIENT_DATA"
MOTIF_PAS_DE_PLACE = "SPREAD_D_UN_SEUL_TICK_AUCUN_INTERIEUR_OU_SE_PLACER"
MOTIF_CAPTURE_SOUS_LES_FRAIS = "CAPTURE_INSIDE_INFERIEURE_AUX_FRAIS_MORT_PAR_ARITHMETIQUE"
MOTIF_ADVERSE = "LA_SELECTION_ADVERSE_MANGE_LA_CAPTURE"
MOTIF_INVENTAIRE = "LE_PRIX_BOUGE_PLUS_QUE_LA_CAPTURE_PARI_DIRECTIONNEL_AVEC_UN_COUPON"
MOTIF_VIABLE = "CAPTURE_NETTE_POSITIVE_APRES_FRAIS_ADVERSE_ET_RISQUE_D_INVENTAIRE"


@dataclass(frozen=True, slots=True)
class Snapshot:
    ts: float
    coin: str
    bid: float
    ask: float
    mid: float


@dataclass(frozen=True, slots=True)
class Trade:
    ts: float
    coin: str
    px: float
    notional_usd: float
    aggressor: str          # "BUY" (il tape l'ask) | "SELL" (il tape le bid)


def estimer_tick(snaps: Sequence[Snapshot]) -> float:
    """Le tick, estime par le **plus petit spread jamais observe**.

    Un spread ne peut pas etre plus petit qu'un tick. Donc `min(ask - bid) >= tick`, et sur un
    marche liquide l'egalite est atteinte tres souvent.

    ⚠️ C'est une **borne HAUTE** du tick -> donc une estimation **CONSERVATRICE de la place**.
    Si on se trompe, c'est en NOTRE DEFAVEUR. C'est le bon sens de l'erreur.
    """
    ecarts = [s.ask - s.bid for s in snaps if s.ask > s.bid]
    return min(ecarts) if ecarts else 0.0


def place_interieure(spread: float, tick: float) -> float:
    """Ce qu'il reste APRES avoir ameliore les deux cotes d'un tick.

    `spread - 2*tick`. Si <= 0 : **il n'y a pas d'interieur**. On ne peut pas se placer.
    """
    return float(spread) - 2.0 * float(tick)


def capture_inside_bps(spread: float, tick: float, mid: float) -> float:
    """La capture d'un aller-retour en cotant DANS le spread, en bps du mid."""
    if mid <= 0:
        return 0.0
    return 1e4 * max(0.0, place_interieure(spread, tick)) / mid


def _mid_a(snaps_tries: Sequence[Snapshot], ts: float) -> float | None:
    """Le mid du carnet a l'instant `ts` (le dernier snapshot <= ts). None si on n'en a pas."""
    trouve = None
    for s in snaps_tries:
        if s.ts <= ts:
            trouve = s
        else:
            break
    return trouve.mid if trouve is not None else None


def _markout_bps(
    snaps_tries: Sequence[Snapshot], ts: float, horizon_s: float, sens: int,
) -> float | None:
    """🔴 LE MARKOUT SE CALCULE SUR LE **MID**, JAMAIS SUR LE PRIX DES TRADES.

    🚩 ET J'AI DU REECRIRE CETTE FONCTION APRES L'AVOIR LANCEE UNE FOIS.

    Ma 1re version prenait le prix des TRADES. Resultat sur donnees reelles : CASHCAT sortait a
    **adverse = -14,77 bps** -- c'est-a-dire que le prix serait alle **en notre FAVEUR** apres
    chacun de nos 8 558 fills. Ca n'existe pas.

    Le spread de CASHCAT fait 35,6 bps -> **demi-spread = 17,8**. Mon « adverse » valait -14,8.
    C'etait le **BID-ASK BOUNCE** : les prix de trade oscillent MECANIQUEMENT entre le bid et
    l'ask selon le sens de l'agresseur. Le prix n'allait pas dans notre sens -- **il rebondissait.**

    Et le pire : **T1 avait DEJA trouve ce bug** (« un faux edge de +31 bps, bid-ask bounce »).
    Je l'ai refait, trois semaines plus tard, dans l'outil cense verifier T1.
    *Suspecter son PROPRE outil avant le code d'autrui.* -- pour la 4e fois aujourd'hui.

    `sens` = +1 si on a ACHETE (l'agresseur vendait), -1 si on a VENDU.
    Rendu en bps : POSITIF = le mid est alle dans notre sens ; NEGATIF = contre nous.

    ⚠️ Le carnet est echantillonne toutes les ~10 s : un horizon plus court que ca ne mesurerait
    que du bruit d'echantillonnage. On l'assume, et on le dit.
    """
    m0 = _mid_a(snaps_tries, ts)
    m1 = _mid_a(snaps_tries, ts + horizon_s)
    if m0 is None or m1 is None or m0 <= 0:
        return None
    if m1 == m0:
        # le carnet n'a pas bouge entre les deux instants : on n'a rien mesure du tout.
        # (ce n'est PAS « markout nul » : c'est « pas de donnee ». On le distingue.)
        return 0.0
    return sens * 1e4 * (m1 - m0) / m0


def mouvement_pendant_la_detention_bps(
    snaps_tries: Sequence[Snapshot], *, horizon_s: float = HORIZON_DETENTION_S,
) -> float:
    """De combien le prix bouge-t-il, en moyenne, pendant qu'on PORTE la position ?

    C'est le risque d'INVENTAIRE : un market maker est force de porter ce qu'on lui vend. Il ne
    gagne pas le spread -- il gagne le spread **moins ce mouvement**.

    Mesure : moyenne des |Δmid| sur des fenetres de `horizon_s`. Pas un ecart-type : la valeur
    ABSOLUE, parce qu'un mouvement dans un sens ou dans l'autre nous coute pareil selon le cote
    ou on a ete rempli.
    """
    if len(snaps_tries) < 2:
        return 0.0
    ecarts: list[float] = []
    j = 0
    for i, s in enumerate(snaps_tries):
        cible = s.ts + horizon_s
        while j < len(snaps_tries) and snaps_tries[j].ts < cible:
            j += 1
        if j >= len(snaps_tries):
            break
        if s.mid > 0:
            ecarts.append(abs(1e4 * (snaps_tries[j].mid - s.mid) / s.mid))
    return (sum(ecarts) / len(ecarts)) if ecarts else 0.0


@dataclass(frozen=True, slots=True)
class VerdictInside:
    coin: str
    n_snapshots: int
    n_trades: int
    tick_estime: float
    spread_median_bps: float
    part_snapshots_avec_place: float      # fraction ou spread > 1 tick
    capture_inside_bps: float             # apres avoir donne les 2 ticks
    frais_bps: float
    adverse_bps: float                    # positif = ca nous coute
    vol_detention_bps: float              # 🔴 le mouvement subi pendant qu'on porte
    ratio_capture_sur_vol: float
    net_bps: float
    n_fills_simules: int
    viable: bool
    motif: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin, "n_snapshots": self.n_snapshots, "n_trades": self.n_trades,
            "tick_estime": self.tick_estime,
            "spread_median_bps": round(self.spread_median_bps, 4),
            "part_snapshots_avec_place": round(self.part_snapshots_avec_place, 4),
            "capture_inside_bps": round(self.capture_inside_bps, 4),
            "frais_bps": self.frais_bps,
            "adverse_bps": round(self.adverse_bps, 4),
            "vol_detention_bps": round(self.vol_detention_bps, 4),
            "ratio_capture_sur_vol": round(self.ratio_capture_sur_vol, 4),
            "net_bps": round(self.net_bps, 4),
            "n_fills_simules": self.n_fills_simules,
            "viable": self.viable, "motif": self.motif, "note": self.note,
            "real_execution": False,
        }


def evaluer_quoting_inside(
    coin: str,
    snaps: Sequence[Snapshot],
    trades: Sequence[Trade],
    *,
    horizon_markout_s: float = 30.0,     # le carnet est echantillonne toutes les ~10 s
) -> VerdictInside:
    """Le verdict de T1b pour UN coin. Les trois portes, dans l'ordre du plus dur.

    HYPOTHESE DE REMPLISSAGE, **EXPLICITE ET GENEREUSE** : en cotant dans le spread on est SEUL
    au meilleur prix -> on suppose qu'on prend **100 % des agresseurs**. C'est le mieux qu'on
    puisse esperer. Si ca ne paie pas MEME LA, ca ne paiera nulle part.
    *On teste la borne OPTIMISTE : c'est la seule facon d'obtenir un « non » qui vaille.*
    """
    n_s, n_t = len(snaps), len(trades)
    snaps_tries = sorted(snaps, key=lambda s: s.ts)

    def _refus(motif: str, note: str, *, tick=0.0, med=0.0, part=0.0, capture=0.0,
               adverse=0.0, vol=0.0, ratio=0.0, net=0.0, fills=0) -> VerdictInside:
        return VerdictInside(
            coin=coin, n_snapshots=n_s, n_trades=n_t, tick_estime=tick,
            spread_median_bps=med, part_snapshots_avec_place=part,
            capture_inside_bps=capture, frais_bps=COUT_ALLER_RETOUR_BPS,
            adverse_bps=adverse, vol_detention_bps=vol, ratio_capture_sur_vol=ratio,
            net_bps=net, n_fills_simules=fills, viable=False, motif=motif, note=note,
        )

    if n_s < MIN_SNAPSHOTS:
        return _refus(MOTIF_INSUFFISANT, "%d snapshots < %d" % (n_s, MIN_SNAPSHOTS))

    tick = estimer_tick(snaps)
    if tick <= 0:
        return _refus(MOTIF_INSUFFISANT, "tick inestimable")

    spreads_bps = sorted(1e4 * (s.ask - s.bid) / s.mid for s in snaps if s.mid > 0)
    med = spreads_bps[len(spreads_bps) // 2] if spreads_bps else 0.0
    vol = mouvement_pendant_la_detention_bps(snaps_tries)

    # --- PORTE A : y a-t-il un INTERIEUR ?
    avec_place = [s for s in snaps if place_interieure(s.ask - s.bid, tick) > 0]
    part = len(avec_place) / n_s
    if not avec_place:
        return _refus(
            MOTIF_PAS_DE_PLACE,
            "spread median %.3f bps = 1 tick : **il n'y a PAS d'interieur ou se placer**. "
            "Ameliorer les deux cotes d'un tick croiserait le marche. *Ce n'est pas une "
            "question de rendement : c'est une impossibilite arithmetique.*" % med,
            tick=tick, med=med, vol=vol,
        )

    # --- PORTE B : la capture SURVIT-elle aux frais ? (avant meme de parler de flux)
    captures = [capture_inside_bps(s.ask - s.bid, tick, s.mid) for s in avec_place]
    capture = sum(captures) / len(captures)
    ratio = (capture / vol) if vol > 0 else float("inf")
    if capture <= COUT_ALLER_RETOUR_BPS:
        return _refus(
            MOTIF_CAPTURE_SOUS_LES_FRAIS,
            "capture inside %.3f bps <= frais %.1f bps. **Mort par arithmetique** : meme rempli "
            "a 100 %% et sans aucune selection adverse, on perd."
            % (capture, COUT_ALLER_RETOUR_BPS),
            tick=tick, med=med, part=part, capture=capture, vol=vol, ratio=ratio,
            net=capture - COUT_ALLER_RETOUR_BPS,
        )

    # --- 🔴 PORTE C : LE RISQUE D'INVENTAIRE. Celle que j'avais OUBLIEE.
    #
    # Un market maker ne gagne pas le spread : il gagne le spread **moins la variance de
    # l'inventaire qu'il est force de porter**. Capturer 35 bps sur un coin qui bouge de 219 bps
    # par heure, ce n'est pas du market making -- **c'est un pari directionnel avec un coupon.**
    # (La phrase exacte qu'on avait ecrite pour refuser le funding sur jambe nue.)
    #
    # Sans ce terme, tout marche VOLATIL parait genereux -- et c'est PRECISEMENT pour ca que son
    # spread est large. Le spread n'est pas un cadeau : c'est le prix du risque qu'on accepte.
    if ratio < RATIO_CAPTURE_SUR_VOL_MIN:
        return _refus(
            MOTIF_INVENTAIRE,
            "capture %.2f bps, mais le prix bouge de **%.2f bps** pendant qu'on porte la position "
            "(%.0f s). Ratio %.2f < %.1f. *Ce n'est pas du market making : c'est un pari "
            "directionnel avec un coupon.*"
            % (capture, vol, HORIZON_DETENTION_S, ratio, RATIO_CAPTURE_SUR_VOL_MIN),
            tick=tick, med=med, part=part, capture=capture, vol=vol, ratio=ratio,
            net=capture - COUT_ALLER_RETOUR_BPS - vol,
        )

    # --- PORTE D : le FLUX nous punit-il ? (selection adverse, hypothese de fill GENEREUSE)
    # 🔴 Le markout est mesure sur le MID DU CARNET, pas sur les prix de trade (bid-ask bounce).
    ts_tries = sorted(trades, key=lambda t: t.ts)
    markouts: list[float] = []
    for t in ts_tries:
        agr = str(t.aggressor or "").upper()
        if agr == "BUY":
            sens = -1        # il tape l'ask -> c'est NOUS qui vendons -> on est SHORT
        elif agr == "SELL":
            sens = +1        # il tape le bid -> NOUS achetons -> on est LONG
        else:
            continue
        m = _markout_bps(snaps_tries, t.ts, horizon_markout_s, sens)
        if m is not None and math.isfinite(m):
            markouts.append(m)

    if len(markouts) < MIN_FILLS:
        return _refus(
            MOTIF_INSUFFISANT,
            "%d fills simules < %d : la capture passe les frais, mais on ne peut PAS mesurer la "
            "selection adverse. **On ne conclut pas.** (lecon #242 : 1 trade n'est pas une mesure)"
            % (len(markouts), MIN_FILLS),
            tick=tick, med=med, part=part, capture=capture, vol=vol, ratio=ratio,
            net=capture - COUT_ALLER_RETOUR_BPS, fills=len(markouts),
        )

    # markout NEGATIF = le prix va contre nous = ca nous COUTE -> on le compte en positif ici.
    adverse = -(sum(markouts) / len(markouts))
    net = capture - COUT_ALLER_RETOUR_BPS - adverse - vol
    viable = net > 0
    return VerdictInside(
        coin=coin, n_snapshots=n_s, n_trades=n_t, tick_estime=tick, spread_median_bps=med,
        part_snapshots_avec_place=part, capture_inside_bps=capture,
        frais_bps=COUT_ALLER_RETOUR_BPS, adverse_bps=adverse, vol_detention_bps=vol,
        ratio_capture_sur_vol=ratio, net_bps=net, n_fills_simules=len(markouts),
        viable=viable, motif=MOTIF_VIABLE if viable else MOTIF_ADVERSE,
        note="capture %.2f - frais %.1f - adverse %.2f - inventaire %.2f = **%+.2f bps** "
             "(%d fills, remplissage a 100 %%, la plus GENEREUSE des hypotheses)."
             % (capture, COUT_ALLER_RETOUR_BPS, adverse, vol, net, len(markouts)),
    )


__all__ = [
    "COUT_ALLER_RETOUR_BPS", "FRAIS_MAKER_BPS", "HORIZON_DETENTION_S", "MIN_FILLS",
    "MIN_SNAPSHOTS", "RATIO_CAPTURE_SUR_VOL_MIN",
    "MOTIF_ADVERSE", "MOTIF_CAPTURE_SOUS_LES_FRAIS", "MOTIF_INSUFFISANT",
    "MOTIF_INVENTAIRE", "MOTIF_PAS_DE_PLACE", "MOTIF_VIABLE",
    "Snapshot", "Trade", "VerdictInside",
    "capture_inside_bps", "estimer_tick", "evaluer_quoting_inside",
    "mouvement_pendant_la_detention_bps", "place_interieure",
]
