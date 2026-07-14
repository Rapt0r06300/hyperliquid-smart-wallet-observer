"""LE VERDICT DU MARKET MAKING : LE FLUX PAYE-T-IL LE RISQUE ? (2026-07-12)

LA SEULE EQUATION QUI COMPTE, PAR ALLER-RETOUR :

    PnL = capture_du_spread  -  frais_maker  -  SELECTION_ADVERSE

Les deux premiers termes sont faciles et rassurants. Le troisieme tue les market makers.

LA SELECTION ADVERSE, EN UNE PHRASE : on est rempli PRECISEMENT quand on a tort.
Quelqu'un achete a mon ask -> il achete parce qu'il pense que ca monte -> souvent, ca monte ->
je suis maintenant SHORT sur un marche qui monte. Le spread que j'ai capture (quelques bps) ne
compense pas le mouvement que je viens de subir (des dizaines de bps).

C'est mesurable, et c'est ce que fait ce module : pour chaque trade public, on regarde
ou va le prix APRES. Si le prix suit l'agresseur, le maker en face a perdu.

CE QU'ON NE PEUT PAS MESURER SANS ETRE DANS LE CARNET :
  * la position exacte dans la FILE d'attente (on serait derriere les MM pros) ;
  * le taux de fill reel de NOS ordres.
  On modelise donc une hypothese EXPLICITE et PESSIMISTE (`part_du_flux`), et on la nomme.
  Un modele qui cache son hypothese est un mensonge avec des decimales.

PUR, sans I/O. Aucun ordre reel.
"""
from __future__ import annotations

import bisect
import statistics
from dataclasses import dataclass
from typing import Any, Sequence

MAKER_BPS = 1.5                    # Hyperliquid : le maker PAIE. Verifie sur la doc officielle.
COUT_ALLER_RETOUR_BPS = 2 * MAKER_BPS

# Horizon de mesure de la selection adverse : ou est le prix N secondes apres le fill ?
HORIZON_ADVERSE_MS = 30_000

# Hypothese EXPLICITE : quelle part du flux nous remplit ? On est un retail sans colocation,
# derriere les MM pros dans la file. 10 % est deja optimiste.
PART_DU_FLUX_DEFAUT = 0.10

MIN_TRADES = 30                    # plancher pour MESURER la selection adverse
# Pour DECLARER un candidat, il en faut bien plus : 31 trades, c'est un pile ou face.
MIN_TRADES_POUR_CONCLURE = 300

# ON N'EXTRAPOLE PAS UN DEBIT HORAIRE DEPUIS UNE RAFALE (2026-07-12).
# CASHCAT : 86 trades en 14 SECONDES -> mon modele annonçait 9,5 M$/h. C'est une rafale, pas un
# debit. Sous cette fenetre d'observation, tout taux horaire est une fiction.
FENETRE_MIN_OBSERVATION_S = 1800.0        # 30 minutes minimum

MOTIF_SNAPSHOT = "SNAPSHOT_INITIAL_PAS_DU_FLUX"
MOTIF_FENETRE = "FENETRE_TROP_COURTE_POUR_UN_DEBIT"
MOTIF_FILE = "FILE_NON_FRANCHISSABLE"


@dataclass(frozen=True, slots=True)
class VerdictMM:
    coin: str
    n_trades: int
    trades_par_min: float
    volume_par_min_usd: float
    spread_capture_bps: float
    selection_adverse_bps: float | None
    pnl_net_bps: float | None
    fills_par_h_estimes: float
    pnl_par_h_usd: float | None
    verdict: str
    hypothese: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin,
            "n_trades": self.n_trades,
            "trades_par_min": self.trades_par_min,
            "volume_par_min_usd": self.volume_par_min_usd,
            "spread_capture_bps": self.spread_capture_bps,
            "selection_adverse_bps": self.selection_adverse_bps,
            "pnl_net_bps": self.pnl_net_bps,
            "fills_par_h_estimes": self.fills_par_h_estimes,
            "pnl_par_h_usd": self.pnl_par_h_usd,
            "verdict": self.verdict,
            "hypothese": self.hypothese,
            "real_execution": False,
        }


def selection_adverse_bps(
    trades: Sequence[dict],
    *,
    horizon_ms: int = HORIZON_ADVERSE_MS,
) -> tuple[float | None, int]:
    """Combien le prix bouge CONTRE le maker apres l'avoir rempli. En bps, positif = on perd.

    Pour chaque trade agressif, le maker en face a pris la position INVERSE :
      * agresseur BUY  -> le maker est SHORT -> il perd si le prix MONTE ;
      * agresseur SELL -> le maker est LONG  -> il perd si le prix BAISSE.
    """
    serie = sorted((float(t["ts"]), float(t["px"])) for t in trades
                   if t.get("ts") and t.get("px"))
    if len(serie) < MIN_TRADES:
        return None, 0

    ts = [x[0] for x in serie]
    pertes: list[float] = []
    for t in trades:
        try:
            t0 = float(t["ts"])
            p0 = float(t["px"])
            agresseur = str(t["aggressor"]).upper()
        except (KeyError, TypeError, ValueError):
            continue
        if p0 <= 0 or agresseur not in {"BUY", "SELL"}:
            continue

        i = bisect.bisect_left(ts, t0 + horizon_ms / 1000.0)
        if i >= len(serie):
            continue                       # pas de prix a cet horizon : on n'invente rien
        p1 = serie[i][1]

        variation_bps = (p1 - p0) / p0 * 10_000.0
        # le maker est du cote OPPOSE a l'agresseur
        perte = variation_bps if agresseur == "BUY" else -variation_bps
        pertes.append(perte)

    if len(pertes) < MIN_TRADES:
        return None, len(pertes)
    return statistics.median(pertes), len(pertes)


def evaluer_market_making(
    coin: str,
    trades: Sequence[dict],
    *,
    spread_bps: float,
    taille_usd: float = 500.0,
    part_du_flux: float = PART_DU_FLUX_DEFAUT,
    capture_du_spread: float = 0.5,
) -> VerdictMM:
    """Le flux paye-t-il le risque ? DENY-BY-DEFAULT : sans donnee, on refuse de conclure."""
    hypothese = (
        "on capture %.0f%% du spread et on prend %.0f%% du flux "
        "(retail, sans colocation, derriere les MM pros dans la file)"
        % (capture_du_spread * 100, part_du_flux * 100)
    )

    # 1) LE SNAPSHOT N'EST PAS DU FLUX. A la souscription, Hyperliquid renvoie les derniers
    #    trades : c'est de l'HISTORIQUE. Le compter comme du temps reel fabrique du volume.
    vivants = [t for t in trades if not t.get("snapshot")]
    if len(vivants) < MIN_TRADES:
        return VerdictMM(coin, len(vivants), 0.0, 0.0, 0.0, None, None, 0.0, None,
                         "%s : %d trades LIVE (hors snapshot) < %d"
                         % (MOTIF_SNAPSHOT if len(trades) > len(vivants) else "FLUX QUASI NUL",
                            len(vivants), MIN_TRADES),
                         hypothese)
    trades = vivants

    ts = sorted(float(t["ts"]) for t in trades if t.get("ts"))
    fenetre_s = ts[-1] - ts[0]

    # 2) ON N'EXTRAPOLE PAS UN DEBIT DEPUIS UNE RAFALE. CASHCAT : 86 trades en 14 secondes,
    #    extrapoles a 9,5 M$/h. Une rafale n'est pas un debit.
    if fenetre_s < FENETRE_MIN_OBSERVATION_S:
        return VerdictMM(coin, len(trades), 0.0, 0.0, 0.0, None, None, 0.0, None,
                         "%s (%.0f s < %.0f s) -- ecoute plus longtemps"
                         % (MOTIF_FENETRE, fenetre_s, FENETRE_MIN_OBSERVATION_S),
                         hypothese)

    duree_min = fenetre_s / 60.0
    n_par_min = len(trades) / duree_min
    vol_par_min = sum(float(t.get("notional_usd") or 0.0) for t in trades) / duree_min

    adverse, n_mesures = selection_adverse_bps(trades)
    capture = spread_bps * capture_du_spread

    if adverse is None:
        return VerdictMM(coin, len(trades), round(n_par_min, 2), round(vol_par_min, 1),
                         round(capture, 2), None, None, 0.0, None,
                         "SELECTION ADVERSE NON MESURABLE -> refus", hypothese)

    net_bps = capture - COUT_ALLER_RETOUR_BPS - adverse

    # BUG CORRIGE (2026-07-12) -- JE COMPTAIS LES FILLS, PAS LES DOLLARS.
    #
    # Ancienne formule : fills_h = trades/min x 60 x part_du_flux, puis x taille_usd.
    # Sur ACE, elle annonçait 6,6 fills de 500 $ = 3 300 $/h... sur un marche qui echange
    # 1 422 $/h AU TOTAL. Le modele remplissait DEUX FOIS le volume du marche entier.
    #
    # On ne peut pas etre rempli de plus de dollars qu'il n'en traverse le spread.
    # Le VOLUME est le plafond. Toujours.
    volume_capturable_h = vol_par_min * 60.0 * part_du_flux      # en DOLLARS, pas en fills
    pnl_h = volume_capturable_h * (net_bps / 10_000.0)
    # nombre de fills EQUIVALENTS a notre taille -- borne par le volume, pas par le comptage
    fills_h = volume_capturable_h / taille_usd if taille_usd > 0 else 0.0

    if len(trades) < MIN_TRADES_POUR_CONCLURE:
        v = ("ECHANTILLON TROP PETIT POUR CONCLURE (%d < %d) -- %+.1f bps, a confirmer"
             % (len(trades), MIN_TRADES_POUR_CONCLURE, net_bps))
        return VerdictMM(coin, len(trades), round(n_par_min, 2), round(vol_par_min, 1),
                         round(capture, 2), round(adverse, 2), round(net_bps, 2),
                         round(fills_h, 2), None, v, hypothese)

    if net_bps <= 0:
        v = "PERDANT (%.1f bps par aller-retour)" % net_bps
    elif pnl_h < 0.01:
        v = "RENTABLE mais NEGLIGEABLE (%.3f $/h)" % pnl_h
    else:
        v = "CANDIDAT REEL (%.2f $/h) -- a valider en paper" % pnl_h

    return VerdictMM(
        coin=coin, n_trades=len(trades),
        trades_par_min=round(n_par_min, 2), volume_par_min_usd=round(vol_par_min, 1),
        spread_capture_bps=round(capture, 2),
        selection_adverse_bps=round(adverse, 2),
        pnl_net_bps=round(net_bps, 2),
        fills_par_h_estimes=round(fills_h, 1),
        pnl_par_h_usd=round(pnl_h, 4),
        verdict=v, hypothese=hypothese,
    )


# =====================================================================================
#  T1 -- LE VERDICT SANS LE NOMBRE INVENTE (2026-07-12)
# =====================================================================================
#
#  LE PROBLEME QU'ON TRAINE DEPUIS `MM-FLUX` :
#    `part_du_flux = 0.10` est INVENTE. Aucune mesure ne le soutient. Tant qu'il est dans
#    l'equation, le "$/h" qui en sort est une decoration.
#
#  LA SORTIE, ET ELLE EST STRUCTURELLE :
#
#    net_bps = capture - frais - selection_adverse        <- NE CONTIENT PAS part_du_flux
#    pnl_h   = volume x part_du_flux x net_bps / 10 000   <- le contient
#
#    **Le SIGNE du verdict ne depend donc PAS du nombre invente.** Si `net_bps <= 0`, le market
#    making est mort sur ce marche -- quelle que soit notre place dans la file. On peut trancher
#    sans jamais ecrire 10 %.
#
#  ET POUR LES DOLLARS : on ne devine pas, on BORNE.
#    Le volume qui nous remplit ne peut pas depasser le volume qui traverse le spread. On calcule
#    donc le PLAFOND PHYSIQUE : "et si on capturait 100 % du flux qui nous atteint ?". C'est
#    impossible en pratique (les MM pros sont devant nous), donc le vrai chiffre est FORCEMENT
#    plus bas. Si meme ce plafond est derisoire, la question est reglee.
#
#  RESTE LA FILE. On ne la choisit pas : on l'ENCADRE (cf. H-95).
#    * DEVANT  : on est devant tout le monde -> TOUS les trades nous remplissent.
#    * MILIEU  : seuls les trades >= la taille MEDIANE nous atteignent.
#    * DERRIERE: seuls les GROS trades (dernier quartile) balayent la file jusqu'a nous.
#    Un retail sans colocation est DERRIERE. Et "derriere" est le pire endroit : les gros trades
#    sont precisement les plus informes. La selection adverse y est plus forte -- c'est mesurable,
#    et c'est mesure ici.

BORNES_FILE = (
    ("DEVANT", 0.00, "on est devant les MM pros (irrealiste, borne OPTIMISTE)"),
    ("MILIEU", 0.50, "seuls les trades >= taille mediane nous atteignent"),
    ("DERRIERE", 0.75, "seuls les gros trades (top 25 %) balayent la file jusqu'a nous -- "
                       "c'est la place d'un retail sans colocation"),
)

BOOTSTRAP_N = 2000
BOOTSTRAP_IC = 0.90            # intervalle a 90 %


def _quantile(valeurs: Sequence[float], q: float) -> float:
    if not valeurs:
        return 0.0
    s = sorted(valeurs)
    if q <= 0:
        return s[0]
    i = min(len(s) - 1, int(q * len(s)))
    return s[i]


def selection_par_rang(
    pertes: Sequence[tuple[float, str, float]], q: float
) -> tuple[list[tuple[float, float]], float]:
    """Les (1 - q) trades les PLUS GROS, choisis par RANG -- jamais par seuil de valeur.

    Rend (liste de (perte_bps, notionnel), notionnel minimum retenu).

    LE BUG QUE CETTE FONCTION REPARE (2026-07-12)
    ---------------------------------------------
    L'ancien code faisait `retenus = [t for t in pertes if t.notionnel >= _quantile(.., 0.75)]`.
    Ca semble evident. C'est FAUX des que la distribution des notionnels a un ATOME.

    Mesure reelle du diagnostic : 1 198 trades a EXACTEMENT 200 $ et 399 a 5 000 $.
    `_quantile(.., 0.75)` = **200 $**. Et `notionnel >= 200` retient... **100 % des trades**.

    La borne DERRIERE (« seuls les gros nous atteignent ») se degradait donc SILENCIEUSEMENT
    en borne DEVANT (« on est devant les MM pros ») -- et on imprimait le chiffre OPTIMISTE
    sous le nom du chiffre REALISTE. Trois bornes affichees, un seul chiffre derriere.

    C'est la pathologie recurrente du projet : une capacite presente, un interrupteur eteint,
    et personne qui rale.

    Le RANG, lui, tient toujours sa promesse : « les 25 % les plus gros » en font 25 %, que la
    distribution ait des atomes ou non. En cas d'egalite parfaite, la coupe est arbitraire --
    et c'est sans consequence : des trades de meme taille sont interchangeables.
    """
    if not pertes:
        return [], 0.0
    q = min(max(q, 0.0), 1.0)
    ordre = sorted(pertes, key=lambda x: x[2], reverse=True)      # du plus gros au plus petit
    k = max(1, int(round((1.0 - q) * len(ordre))))
    retenus = [(p, n) for p, _, n in ordre[:k]]
    return retenus, min(n for _, n in retenus)


def ic_bootstrap_mediane(
    valeurs: Sequence[float], *, n: int = BOOTSTRAP_N, ic: float = BOOTSTRAP_IC, graine: int = 12345
) -> tuple[float, float, float]:
    """(mediane, borne basse, borne haute) par bootstrap. DETERMINISTE (graine fixe).

    POURQUOI C'EST INDISPENSABLE : la selection adverse est une distribution a QUEUE LOURDE.
    Une mediane de -1,2 bps sur 300 trades peut parfaitement etre +3 ou -6 en verite. Sans
    intervalle, on lirait un signe dans du bruit -- exactement le mecanisme qui nous a fait
    croire a des edges qui n'existaient pas.
    """
    import random

    if not valeurs:
        return 0.0, 0.0, 0.0
    med = statistics.median(valeurs)
    rng = random.Random(graine)
    k = len(valeurs)
    medianes = []
    for _ in range(n):
        ech = [valeurs[rng.randrange(k)] for _ in range(k)]
        medianes.append(statistics.median(ech))
    medianes.sort()
    alpha = (1.0 - ic) / 2.0
    bas = medianes[int(alpha * n)]
    haut = medianes[min(n - 1, int((1.0 - alpha) * n))]
    return med, bas, haut


# UN TROU DANS LA DONNEE N'EST PAS UN HORIZON (bug trouve le 2026-07-12 en regardant l'UI).
#
# Les fichiers `trades*.jsonl` contiennent PLUSIEURS sessions d'ecoute, separees par des heures.
# `bisect(ts, t0 + 30 s)` renvoie le premier trade >= t0+30 s -- mais s'il y a un trou de 8 h,
# ce "prix 30 s apres" est en realite le prix 8 HEURES apres. La "selection adverse" mesuree
# devient alors le bruit d'une nuit entiere, pas l'impact du trade.
#
# On EXIGE donc que le prix trouve soit reellement proche de l'horizon vise. Sinon : on jette.
# On ne mesure pas ce qu'on n'a pas observe.
TOLERANCE_HORIZON = 3.0            # au-dela de 3 x l'horizon, ce n'est plus le meme evenement
TROU_DE_SESSION_S = 600.0          # 10 min sans un trade = une autre session d'ecoute


def fenetre_continue_s(horodatages: Sequence[float], *, trou_s: float = TROU_DE_SESSION_S) -> float:
    """La duree REELLEMENT observee : la somme des segments continus, trous exclus.

    Sans ca, trois sessions de 20 min separees par 4 h d'absence donnaient "8 h d'observation"
    -- et le verrou des 30 min etait franchi par une illusion.
    """
    ts = sorted(float(t) for t in horodatages)
    if len(ts) < 2:
        return 0.0
    total = 0.0
    debut = ts[0]
    for a, b in zip(ts, ts[1:]):
        if b - a > trou_s:
            total += a - debut
            debut = b
    total += ts[-1] - debut
    return total


def serie_de_mids(trades: Sequence[dict]) -> list[tuple[float, float]]:
    """(ts, mid estime) -- le MID, jamais le prix d'un trade.

    LE FAUX EDGE QUE CETTE FONCTION TUE (2026-07-12) -- LE PIRE PIEGE DE LA SOIREE
    ----------------------------------------------------------------------------
    La 1re version mesurait le markout contre **le prix du trade suivant**. Sur CASHCAT elle a
    sorti : selection adverse **-15,7 bps** (le prix irait EN NOTRE FAVEUR apres nous avoir
    remplis !) -> net **+31,4 bps** -> "CANDIDAT, 1 071 $/h".

    C'etait faux, et le chiffre le criait : le demi-spread de CASHCAT vaut 17,75 bps.
    **-15,7 ~ -(spread/2).**

    C'est du BID-ASK BOUNCE. Le prix des trades publics oscille MECANIQUEMENT entre le bid et
    l'ask : apres un achat a l'ask, le trade suivant est souvent une vente au bid -> on "mesure"
    une baisse qui n'existe pas. Le spread etait donc compte DEUX FOIS : une fois dans la
    capture, une fois dans ce faux markout negatif. Un edge de +31 bps sorti de rien.

    LA CORRECTION : on estime le mid par la moyenne du dernier prix ACHETE (~ ask) et du dernier
    prix VENDU (~ bid). Le bounce disparait : c'est la meme grandeur avant et apres.
    C'est la methode standard quand on n'a que le flux de trades (Roll, 1984).
    """
    dernier_ask: float | None = None
    dernier_bid: float | None = None
    out: list[tuple[float, float]] = []
    for t in sorted(trades, key=lambda x: float(x.get("ts") or 0.0)):
        try:
            ts = float(t["ts"])
            px = float(t["px"])
            cote = str(t["aggressor"]).upper()
        except (KeyError, TypeError, ValueError):
            continue
        if px <= 0:
            continue
        if cote == "BUY":                 # l'agresseur a PRIS l'ask
            dernier_ask = px
        elif cote == "SELL":              # l'agresseur a TAPE le bid
            dernier_bid = px
        else:
            continue
        if dernier_ask is None or dernier_bid is None:
            continue                      # tant qu'on n'a pas vu les DEUX cotes, pas de mid
        out.append((ts, (dernier_ask + dernier_bid) / 2.0))
    return out


def flux_qui_balaye_la_file(
    trades: Sequence[dict], profondeur_devant_usd: float
) -> tuple[int, float]:
    """(nb de trades, $ de flux) qui BALAYENT la file jusqu'a nous. La physique, pas un proxy.

    LE VERROU QUI MANQUAIT -- ET QUI A FAILLI NOUS FAIRE CROIRE A UN EDGE (2026-07-12)
    ---------------------------------------------------------------------------------
    La borne DERRIERE dit "les 25 % de trades les plus gros nous atteignent". C'est une
    HEURISTIQUE. La physique d'un carnet dit autre chose : un maker pose au meilleur prix,
    derriere `Q` dollars deja en file, n'est rempli QUE si un trade balaye ces `Q` dollars.

    Mesure reelle sur CASHCAT (4 641 trades, 382 releves de carnet) :
        profondeur au touch : bid 2 316 $ | ask 2 838 $
        trade median : 90 $ | p99 : 1 452 $
        trades qui balayent 2 577 $ : **9 sur 4 641 = 0,19 %**

    Le verdict affichait "CANDIDAT : net +7,7 bps, plafond 373 $/h" en supposant 1 032 fills.
    La verite physique : **9 fills en 55 minutes.** Le plafond ne portait pas sur un edge --
    il portait sur un evenement qui n'arrive quasiment pas.

    Et 9 < MIN_TRADES (30) : sur le flux qui nous atteint REELLEMENT, on ne peut meme pas
    MESURER la selection adverse. La reponse honnete n'est ni "oui" ni "non" : c'est
    INSUFFICIENT_DATA -> NO_TRADE.

    Ce verrou existe pour qu'aucun marche ne soit plus jamais declare CANDIDAT sans que la
    file ait ete jugee franchissable. Un edge dans une file qu'on n'atteint pas n'est pas un
    edge : c'est une decoration.
    """
    if profondeur_devant_usd <= 0:
        return 0, 0.0
    balayent = [float(t.get("notional_usd") or 0.0) for t in trades
                if not t.get("snapshot") and float(t.get("notional_usd") or 0.0) >= profondeur_devant_usd]
    return len(balayent), sum(balayent)


def _un_trade_dans(ts_cote: Sequence[float], apres: float, avant: float) -> bool:
    """Existe-t-il un trade de ce cote dans l'intervalle ]apres ; avant] ?"""
    i = bisect.bisect_right(ts_cote, apres)
    return i < len(ts_cote) and ts_cote[i] <= avant


def _pertes_maker(trades: Sequence[dict], horizon_ms: int = HORIZON_ADVERSE_MS) -> list[tuple[float, str, float]]:
    """(perte_bps, cote_agresseur, notionnel) pour chaque trade ou le maker aurait ete rempli.

    Le markout se mesure **du mid au mid** -- jamais du prix d'un trade au prix d'un trade
    (cf. `serie_de_mids` : ce serait mesurer le bid-ask bounce et l'appeler un edge).

    LA CONDITION DE DENSITE (deny-by-default, ajoutee le 2026-07-12)
    ---------------------------------------------------------------
    Un mid reconstruit depuis le flux n'est un mid QUE si les deux cotes sont fraiches. Si le
    dernier SELL date de 10 minutes, `(dernier_ask + dernier_bid) / 2` n'est pas le milieu du
    carnet : c'est la moitie d'une vieille cotation. Mesurer un markout la-dessus, c'est
    mesurer le RETARD de la cote figee, pas la selection adverse.

    Le diagnostic l'a montre noir sur blanc : sur un flux espace de 60 s avec un horizon de
    30 s, une seule cote se rafraichit -- et l'impact mesure vaut exactement la MOITIE de
    l'impact injecte. Un biais de facteur 2 **dans le sens OPTIMISTE** : le market making
    paraissait deux fois moins toxique qu'il ne l'est.

    On exige donc, pour CHAQUE mesure, que les deux cotes aient traite :
      * dans la fenetre ]t0 ; t1] -- sinon le mid d'arrivee est a moitie perime ;
      * dans la fenetre [t0 - horizon ; t0] -- sinon le mid de depart l'est.

    Un marche trop lent ne rend donc plus de chiffre. C'est une REPONSE, pas une panne :
    on ne peut pas mesurer un markout a 30 s sur un marche qui traite une fois par minute.
    """
    ordonnes = sorted(trades, key=lambda t: float(t.get("ts") or 0.0))
    mids = serie_de_mids(ordonnes)
    if len(mids) < 2:
        return []
    ts_mid = [x[0] for x in mids]
    horizon_s = horizon_ms / 1000.0

    ts_buy = [float(t["ts"]) for t in ordonnes
              if t.get("ts") and str(t.get("aggressor", "")).upper() == "BUY"]
    ts_sell = [float(t["ts"]) for t in ordonnes
               if t.get("ts") and str(t.get("aggressor", "")).upper() == "SELL"]

    out: list[tuple[float, str, float]] = []
    for t in ordonnes:
        try:
            t0 = float(t["ts"])
            agresseur = str(t["aggressor"]).upper()
            notionnel = float(t.get("notional_usd") or 0.0)
        except (KeyError, TypeError, ValueError):
            continue
        if agresseur not in {"BUY", "SELL"}:
            continue

        # le mid AU MOMENT du fill (le dernier connu a t0), et le mid A L'HORIZON
        i0 = bisect.bisect_right(ts_mid, t0) - 1
        if i0 < 0:
            continue                       # pas encore de mid : on n'invente rien
        i1 = bisect.bisect_left(ts_mid, t0 + horizon_s)
        if i1 >= len(mids):
            continue                       # pas de mid a cet horizon
        t1 = mids[i1][0]
        if t1 - t0 > horizon_s * TOLERANCE_HORIZON:
            continue                       # le "mid apres" est de l'autre cote d'un TROU -> jete

        # LES DEUX COTES DOIVENT ETRE FRAICHES -- sinon ce n'est pas un mid (cf. docstring)
        if not (_un_trade_dans(ts_buy, t0, t1) and _un_trade_dans(ts_sell, t0, t1)):
            continue
        debut = t0 - horizon_s
        if not (_un_trade_dans(ts_buy, debut, t0) and _un_trade_dans(ts_sell, debut, t0)):
            continue

        m0, m1 = mids[i0][1], mids[i1][1]
        if m0 <= 0:
            continue
        variation_bps = (m1 - m0) / m0 * 10_000.0
        # le maker est du cote OPPOSE a l'agresseur : il perd si le mid suit l'agresseur
        perte = variation_bps if agresseur == "BUY" else -variation_bps
        out.append((perte, agresseur, notionnel))
    return out


@dataclass(frozen=True, slots=True)
class BorneFile:
    """Un scenario de place dans la file. On ne CHOISIT pas -- on les rend TOUS."""

    nom: str
    explication: str
    seuil_notionnel_usd: float
    n_fills: int
    adverse_bps: float | None
    adverse_ic_bas: float | None
    adverse_ic_haut: float | None
    net_bps: float | None                 # capture - frais - adverse  (SANS aucune hypothese de file)
    net_ic_bas: float | None
    net_ic_haut: float | None
    volume_atteignable_par_h_usd: float   # PLAFOND PHYSIQUE : tout le flux qui nous atteint
    pnl_max_par_h_usd: float | None       # si on capturait 100 % de ce flux -- indepassable
    verdict: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "nom": self.nom, "explication": self.explication,
            "seuil_notionnel_usd": self.seuil_notionnel_usd,
            "n_fills": self.n_fills,
            "adverse_bps": self.adverse_bps,
            "adverse_ic_90": [self.adverse_ic_bas, self.adverse_ic_haut],
            "net_bps": self.net_bps,
            "net_ic_90": [self.net_ic_bas, self.net_ic_haut],
            "volume_atteignable_par_h_usd": self.volume_atteignable_par_h_usd,
            "pnl_max_par_h_usd": self.pnl_max_par_h_usd,
            "verdict": self.verdict,
            "real_execution": False,
        }


@dataclass(frozen=True, slots=True)
class VerdictBorne:
    coin: str
    n_trades: int
    fenetre_s: float
    spread_bps: float
    capture_bps: float
    adverse_cote_buy_bps: float | None
    adverse_cote_sell_bps: float | None
    bornes: tuple[BorneFile, ...]
    verdict: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin, "n_trades": self.n_trades, "fenetre_s": self.fenetre_s,
            "spread_bps": self.spread_bps, "capture_bps": self.capture_bps,
            "adverse_cote_buy_bps": self.adverse_cote_buy_bps,
            "adverse_cote_sell_bps": self.adverse_cote_sell_bps,
            "bornes": [b.as_dict() for b in self.bornes],
            "verdict": self.verdict,
            "hypothese_de_file": "AUCUNE -- les 3 bornes sont rendues, on n'en choisit pas une",
            "real_execution": False,
        }


def encadrer_le_market_making(
    coin: str,
    trades: Sequence[dict],
    *,
    spread_bps: float,
    capture_du_spread: float = 0.5,
    profondeur_devant_usd: float | None = None,
) -> VerdictBorne:
    """LE VERDICT T1. Aucun `part_du_flux` invente : on ENCADRE, on ne devine pas.

    DENY-BY-DEFAULT : donnee insuffisante -> aucun verdict, jamais un verdict optimiste.

    `profondeur_devant_usd` : les dollars deja poses au meilleur prix DEVANT nous. Si on la
    fournit, le verdict passe par le VERROU DE FILE (`flux_qui_balaye_la_file`) : un marche
    dont la file n'est pas franchissable ne peut PAS etre declare CANDIDAT, quel que soit son
    markout. Voir la docstring de `flux_qui_balaye_la_file` -- c'est ce verrou qui a tue le
    seul candidat positif que le projet ait jamais produit (CASHCAT, 0,19 % du flux).

    Ne pas la fournir reste possible (donnees de carnet absentes) : le verdict le DIT alors
    explicitement au lieu de faire semblant.
    """
    vivants = [t for t in trades if not t.get("snapshot")]
    capture = spread_bps * capture_du_spread

    if len(vivants) < MIN_TRADES:
        return VerdictBorne(coin, len(vivants), 0.0, spread_bps, capture, None, None, (),
                            "%s : %d trades LIVE < %d -- rien a mesurer"
                            % (MOTIF_SNAPSHOT if len(trades) > len(vivants) else "FLUX QUASI NUL",
                               len(vivants), MIN_TRADES))

    # LA FENETRE EST LA DUREE OBSERVEE, PAS L'ECART ENTRE LE 1er ET LE DERNIER TRADE.
    # Trois sessions de 20 min separees par 4 h ne font pas 8 h d'observation : elles font 1 h.
    fenetre_s = fenetre_continue_s([float(t["ts"]) for t in vivants if t.get("ts")])
    if fenetre_s < FENETRE_MIN_OBSERVATION_S:
        return VerdictBorne(coin, len(vivants), round(fenetre_s, 1), spread_bps, capture,
                            None, None, (),
                            "%s (%.0f s < %.0f s) -- une rafale n'est pas un debit"
                            % (MOTIF_FENETRE, fenetre_s, FENETRE_MIN_OBSERVATION_S))

    pertes = _pertes_maker(vivants)
    if len(pertes) < MIN_TRADES:
        return VerdictBorne(coin, len(vivants), round(fenetre_s, 1), spread_bps, capture,
                            None, None, (),
                            "SELECTION ADVERSE NON MESURABLE (%d points) -> refus" % len(pertes))

    # ---- VERROU DE FILE : un edge dans une file qu'on n'atteint pas n'est pas un edge -------
    if profondeur_devant_usd is not None:
        n_balayent, _ = flux_qui_balaye_la_file(vivants, profondeur_devant_usd)
        if n_balayent < MIN_TRADES:
            return VerdictBorne(
                coin, len(vivants), round(fenetre_s, 1), spread_bps, capture, None, None, (),
                "%s : %d trades sur %d (%.2f %%) balayent les %.0f $ poses devant nous. "
                "Moins de %d fills -> la selection adverse sur le flux qui nous atteint "
                "REELLEMENT n'est PAS mesurable. INSUFFICIENT_DATA -> NO_TRADE."
                % (MOTIF_FILE, n_balayent, len(vivants),
                   100.0 * n_balayent / max(1, len(vivants)),
                   profondeur_devant_usd, MIN_TRADES))

    # H-111 : le bid et l'ask n'ont PAS la meme toxicite. On les separe.
    buy = [p for p, c, _ in pertes if c == "BUY"]
    sell = [p for p, c, _ in pertes if c == "SELL"]
    adv_buy = statistics.median(buy) if len(buy) >= MIN_TRADES else None
    adv_sell = statistics.median(sell) if len(sell) >= MIN_TRADES else None

    notionnels = [n for _, _, n in pertes]
    heures = fenetre_s / 3600.0

    bornes: list[BorneFile] = []
    for nom, q, explication in BORNES_FILE:
        # PAR RANG, jamais par seuil de valeur : sinon un atome dans la distribution des
        # notionnels degrade DERRIERE en DEVANT sans un mot (cf. `selection_par_rang`).
        retenus, seuil = selection_par_rang(pertes, q)
        if len(retenus) < MIN_TRADES:
            bornes.append(BorneFile(nom, explication, round(seuil, 2), len(retenus),
                                    None, None, None, None, None, None, 0.0, None,
                                    "ECHANTILLON INSUFFISANT (%d < %d)" % (len(retenus), MIN_TRADES)))
            continue

        vals = [p for p, _ in retenus]
        adv, adv_bas, adv_haut = ic_bootstrap_mediane(vals)
        # net = capture - frais - adverse. L'IC de l'adverse se propage a l'envers.
        net = capture - COUT_ALLER_RETOUR_BPS - adv
        net_bas = capture - COUT_ALLER_RETOUR_BPS - adv_haut     # adverse haute -> net bas
        net_haut = capture - COUT_ALLER_RETOUR_BPS - adv_bas

        # PLAFOND PHYSIQUE : tout le flux qui nous atteint, capture a 100 % (impossible).
        vol_h = (sum(n for _, n in retenus) / heures) if heures > 0 else 0.0
        pnl_max_h = vol_h * (net / 10_000.0)

        if len(retenus) < MIN_TRADES_POUR_CONCLURE:
            v = "TROP PEU DE FILLS POUR CONCLURE (%d < %d)" % (len(retenus), MIN_TRADES_POUR_CONCLURE)
        elif net_haut <= 0:
            v = "PERDANT, ET L'IC LE CONFIRME (net <= %+.1f bps a 90 %%)" % net_haut
        elif net_bas <= 0 <= net_haut:
            v = ("INCONCLUSIF : l'IC 90 %% du net traverse zero [%+.1f ; %+.1f] bps -- "
                 "le signe est du BRUIT, pas un edge" % (net_bas, net_haut))
        elif pnl_max_h < 0.05:
            v = ("POSITIF MAIS SANS INTERET : meme en capturant 100 %% du flux qui nous "
                 "atteint (impossible), le PLAFOND est %.3f $/h" % pnl_max_h)
        else:
            v = ("CANDIDAT : net %+.1f bps [%+.1f ; %+.1f], plafond %.2f $/h "
                 "(le reel sera PLUS BAS : on n'aura jamais 100 %% du flux)"
                 % (net, net_bas, net_haut, pnl_max_h))

        bornes.append(BorneFile(
            nom, explication, round(seuil, 2), len(retenus),
            round(adv, 2), round(adv_bas, 2), round(adv_haut, 2),
            round(net, 2), round(net_bas, 2), round(net_haut, 2),
            round(vol_h, 1), round(pnl_max_h, 4), v,
        ))

    # LE VERDICT DU MARCHE = celui de la borne REALISTE (DERRIERE). On ne se raconte pas
    # l'histoire de la borne optimiste.
    derriere = next((b for b in bornes if b.nom == "DERRIERE"), None)
    global_ = derriere.verdict if derriere else "AUCUNE BORNE CALCULABLE"

    return VerdictBorne(
        coin=coin, n_trades=len(vivants), fenetre_s=round(fenetre_s, 1),
        spread_bps=round(spread_bps, 2), capture_bps=round(capture, 2),
        adverse_cote_buy_bps=None if adv_buy is None else round(adv_buy, 2),
        adverse_cote_sell_bps=None if adv_sell is None else round(adv_sell, 2),
        bornes=tuple(bornes), verdict=global_,
    )


__all__ = [
    "BOOTSTRAP_IC", "BOOTSTRAP_N", "BORNES_FILE",
    "COUT_ALLER_RETOUR_BPS", "HORIZON_ADVERSE_MS", "MAKER_BPS", "MIN_TRADES",
    "FENETRE_MIN_OBSERVATION_S", "MIN_TRADES_POUR_CONCLURE",
    "MOTIF_FENETRE", "MOTIF_FILE", "MOTIF_SNAPSHOT", "PART_DU_FLUX_DEFAUT",
    "TOLERANCE_HORIZON", "TROU_DE_SESSION_S",
    "BorneFile", "VerdictBorne", "VerdictMM",
    "encadrer_le_market_making", "evaluer_market_making", "fenetre_continue_s",
    "flux_qui_balaye_la_file", "ic_bootstrap_mediane", "selection_adverse_bps",
    "selection_par_rang", "serie_de_mids",
]
