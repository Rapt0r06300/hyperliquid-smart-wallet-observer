"""#242 / IDEA-85 — LA COINTEGRATION, MESUREE (2026-07-13).

🚩 D'ABORD, TROIS CORRECTIONS DE STATUT (verifiees par AST, pas par confiance) :

  1. **Ce n'est PAS Johansen.** `signal_processing.engle_granger_spread` implemente Engle-Granger
     (deux series, une regression). Johansen est multivarie. Le titre de la tache etait faux.
  2. **Le code est MORT** : `engle_granger_spread` n'est importe que par `strategies_extra.py`,
     qui n'est importe par **personne**. Deux morts qui se tiennent la main.
  3. **Et quatre autres statuts tombent avec** : `haar_wavelet_transform` (IDEA-86),
     `pairs_trade_signal` (IMPROVE-37), `rebalancing_premium` (IMPROVE-39),
     `cross_market_momentum` (IMPROVE-40) -- tous « completed », tous **sans aucun appelant et
     sans aucune mesure sur donnee reelle**. Il n'existe ni rapport, ni outil, ni doc : seulement
     des tests unitaires sur des series **synthetiques**.

     *Coder n'est pas mesurer. Un test ne cable rien.*

⚖️ POURQUOI JE NE L'ENTERRE PAS POUR AUTANT
Aucune de nos zones mortes ne couvre cette idee : elles ont mesure le **fill public d'un leader**
(-7,97 bps) et la **latence** (courbe plate). Ici l'entree est **une paire de series de prix**.
*Une mesure faite sur une autre entree ne tue pas cette idee : elle n'en parle pas.* (C'est la
regle posee ce matin apres que Flo a vu mes deux standards.)

Et on a la donnee : **102 907 relevés de mid, 1 011 coins.** Donc on MESURE.

CE MODULE (pur, sans dependance) :
  * `resampler`            -- grille temporelle commune (les mids arrivent a des instants
                              differents pour chaque coin : les apparier « ligne a ligne » serait
                              un bug silencieux) ;
  * `hedge_ratio`          -- OLS (beta), sur le TRAIN uniquement ;
  * `adf_tstat`            -- test de racine unitaire (Dickey-Fuller augmente, lag 1) sur le
                              residu : le spread revient-il, ou derive-t-il ?
  * `backtest_pairs`       -- z-score, entree/sortie, **couts REELS sur les DEUX jambes**, OOS.

🔴 LE PIEGE QU'ON A DEJA PAYE QUATRE FOIS : le beta ET le seuil doivent etre estimes sur le TRAIN
et appliques tels quels au TEST. Les estimer sur tout l'echantillon, c'est du lookahead -- et ca
fabrique un alpha fantome. La suite de ce projet contient deja 300 cellules d'edge fabriquees.

DENY-BY-DEFAULT : donnees insuffisantes -> `INSUFFICIENT_DATA`, jamais un chiffre invente.

Aucun ordre reel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

# --- Bornes honnetes -------------------------------------------------------------------------
MIN_POINTS_COMMUNS = 200        # sous 200 points appariés, une cointegration est du bruit
MIN_POINTS_TEST = 60            # un OOS de 20 points ne prouve rien
ADF_SEUIL_5PCT = -2.86          # valeur critique usuelle (Dickey-Fuller, constante, n grand)

# 🔴 LE PLANCHER QUE MON PROPRE OUTIL AVAIT OUBLIE (correctif du 2026-07-13, 1re execution).
#
# Ma 1re passe a imprime **« VIABLE : +95,29 bps »** sur la paire SOL/HYPE... avec **UN SEUL
# TRADE** hors echantillon. Un edge calcule sur un trade n'est pas une mesure : **c'est une
# anecdote**. J'avais ecrit, dans mes propres tests, « un seul essai chanceux ne prouve rien » --
# et j'ai laisse mon outil l'oublier trois heures plus tard.
#
# *Suspecter son PROPRE outil avant le code d'autrui.* (Lecon S1-S4, re-payee.)
MIN_TRADES_OOS = 20

MOTIF_INSUFFISANT = "INSUFFICIENT_DATA"
MOTIF_NON_COINTEGRE = "SPREAD_NON_STATIONNAIRE_PAS_DE_RETOUR_A_LA_MOYENNE"
MOTIF_PAS_DE_TRADE = "AUCUN_TRADE_DECLENCHE_SUR_LE_TEST"
MOTIF_TROP_PEU_DE_TRADES = "TROP_PEU_DE_TRADES_OOS_POUR_CONCLURE_ANECDOTE_PAS_MESURE"
MOTIF_NEGATIF = "EDGE_NET_NEGATIF_APRES_COUTS"
MOTIF_POSITIF = "EDGE_NET_POSITIF_APRES_COUTS_HORS_ECHANTILLON"


# =============================================================================================
# 1. APPARIER LES SERIES (le bug silencieux qu'on evite ici)
# =============================================================================================


def resampler(points: Sequence[tuple[float, float]], *, pas_s: float = 60.0) -> dict[int, float]:
    """(ts, prix) -> {bucket: dernier prix du bucket}.

    ⚠️ SANS CETTE ETAPE, apparier deux coins « ligne a ligne » comparerait le prix de BTC a
    10:00:03 avec celui d'ETH a 10:07:41. Le beta serait du bruit, et le backtest mentirait --
    sans jamais lever d'erreur. *Le pire bug est celui qui ne plante pas.*
    """
    out: dict[int, float] = {}
    for ts, p in points:
        try:
            t = float(ts)
            v = float(p)
        except (TypeError, ValueError):
            continue
        if not (v > 0) or not math.isfinite(v) or not math.isfinite(t):
            continue
        out[int(t // pas_s)] = v            # dernier prix du bucket
    return out


def apparier(a: Mapping[int, float], b: Mapping[int, float]) -> tuple[list[float], list[float]]:
    """Les buckets communs, dans l'ordre du temps. Rien d'autre."""
    communs = sorted(set(a) & set(b))
    return [a[k] for k in communs], [b[k] for k in communs]


# =============================================================================================
# 2. ENGLE-GRANGER
# =============================================================================================


def hedge_ratio(x: Sequence[float], y: Sequence[float]) -> tuple[float, float]:
    """OLS : y ~ alpha + beta.x. Rend (alpha, beta).

    Deny-by-default : variance nulle -> beta = 0 (pas de division par zero silencieuse).
    """
    n = len(x)
    if n < 2 or n != len(y):
        return 0.0, 0.0
    mx = sum(x) / n
    my = sum(y) / n
    sxx = sum((v - mx) ** 2 for v in x)
    if sxx <= 0:
        return my, 0.0
    sxy = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    beta = sxy / sxx
    return my - beta * mx, beta


def spread(x: Sequence[float], y: Sequence[float], *, alpha: float, beta: float) -> list[float]:
    """Le residu : y - (alpha + beta.x). S'il est stationnaire, la paire est cointegree."""
    return [y[i] - (alpha + beta * x[i]) for i in range(min(len(x), len(y)))]


def adf_tstat(s: Sequence[float]) -> float:
    """Dickey-Fuller augmente (1 lag) : regression de Δs_t sur s_{t-1}.

    On rend la **t-stat de la pente**. Tres negative -> le spread REVIENT (stationnaire).
    Proche de 0 -> marche aleatoire : *le « spread » derive, et le pairs trading est un pari
    directionnel deguise.*

    ⚠️ VERSION MINIMALE, ASSUMEE : pas de correction de p-valeur exacte, pas de lags multiples.
    On compare a la valeur critique usuelle (-2,86). Si un jour ce chiffre decide de vrai argent,
    il faudra une vraie table -- mais il n'y a PAS de vrai argent ici, et une approximation
    DECLAREE vaut mieux qu'une precision INVENTEE.
    """
    n = len(s)
    if n < 30:
        return 0.0
    y = [s[i] - s[i - 1] for i in range(1, n)]      # Δs_t
    x = list(s[:-1])                                # s_{t-1}
    m = len(y)
    mx = sum(x) / m
    my = sum(y) / m
    sxx = sum((v - mx) ** 2 for v in x)
    if sxx <= 0:
        return 0.0
    sxy = sum((x[i] - mx) * (y[i] - my) for i in range(m))
    b = sxy / sxx
    a = my - b * mx
    residus = [y[i] - (a + b * x[i]) for i in range(m)]
    ddl = m - 2
    if ddl <= 0:
        return 0.0
    s2 = sum(r * r for r in residus) / ddl
    se = math.sqrt(s2 / sxx) if s2 > 0 and sxx > 0 else 0.0
    return (b / se) if se > 0 else 0.0


# =============================================================================================
# 3. LE BACKTEST — AVEC LES COUTS DES DEUX JAMBES
# =============================================================================================


@dataclass(frozen=True, slots=True)
class ResultatPaire:
    a: str
    b: str
    n_communs: int
    beta: float
    adf: float
    cointegre: bool
    n_trades: int
    edge_brut_bps: float
    edge_net_bps: float
    viable: bool
    motif: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "a": self.a, "b": self.b, "n_communs": self.n_communs,
            "beta": round(self.beta, 6), "adf_tstat": round(self.adf, 3),
            "cointegre": self.cointegre, "n_trades": self.n_trades,
            "edge_brut_bps": round(self.edge_brut_bps, 3),
            "edge_net_bps": round(self.edge_net_bps, 3),
            "viable": self.viable, "motif": self.motif, "note": self.note,
            "real_execution": False,
        }


def evaluer_paire(
    nom_a: str,
    nom_b: str,
    serie_a: Sequence[float],
    serie_b: Sequence[float],
    *,
    entree_z: float = 2.0,
    sortie_z: float = 0.5,
    cout_aller_retour_bps: float = 12.0,   # 2 jambes x (frais + demi-spread) x aller-retour
    part_train: float = 0.5,
) -> ResultatPaire:
    """Le verdict d'UNE paire, hors echantillon, apres couts.

    🔴 `cout_aller_retour_bps` = 12 bps par DEFAUT et c'est deja optimiste :
    un pairs trade ouvre DEUX positions et les ferme -> **quatre** executions. A 1,5 bps de frais
    maker + un demi-spread chacune, on est deja au-dessus. Le mettre a 0 pour « voir le potentiel »
    serait exactement la faute de T2 (compter le rendement sans compter le capital).
    """
    n = min(len(serie_a), len(serie_b))
    if n < MIN_POINTS_COMMUNS:
        return ResultatPaire(nom_a, nom_b, n, 0.0, 0.0, False, 0, 0.0, 0.0, False,
                             MOTIF_INSUFFISANT,
                             "%d points communs < %d : on ne conclut pas." % (n, MIN_POINTS_COMMUNS))

    coupe = int(n * part_train)
    if n - coupe < MIN_POINTS_TEST:
        return ResultatPaire(nom_a, nom_b, n, 0.0, 0.0, False, 0, 0.0, 0.0, False,
                             MOTIF_INSUFFISANT, "OOS trop court (%d points)." % (n - coupe))

    xa_tr, yb_tr = list(serie_a[:coupe]), list(serie_b[:coupe])
    xa_te, yb_te = list(serie_a[coupe:]), list(serie_b[coupe:])

    # --- TRAIN : beta, moyenne et ecart-type du spread. RIEN d'autre ne traverse la coupe.
    alpha, beta = hedge_ratio(xa_tr, yb_tr)
    s_tr = spread(xa_tr, yb_tr, alpha=alpha, beta=beta)
    adf = adf_tstat(s_tr)
    mu = sum(s_tr) / len(s_tr)
    var = sum((v - mu) ** 2 for v in s_tr) / max(1, len(s_tr) - 1)
    sd = math.sqrt(var)
    cointegre = adf <= ADF_SEUIL_5PCT and sd > 0

    if not cointegre:
        return ResultatPaire(nom_a, nom_b, n, beta, adf, False, 0, 0.0, 0.0, False,
                             MOTIF_NON_COINTEGRE,
                             "ADF t=%.2f > %.2f : le spread ne revient pas. Un pairs trade "
                             "dessus serait un pari directionnel deguise." % (adf, ADF_SEUIL_5PCT))

    # --- TEST : on applique le beta et les seuils du TRAIN, tels quels.
    s_te = spread(xa_te, yb_te, alpha=alpha, beta=beta)
    position = 0            # +1 = long spread, -1 = short spread
    entree_prix = 0.0
    rendements: list[float] = []

    for v in s_te:
        z = (v - mu) / sd
        if position == 0:
            if z >= entree_z:
                position, entree_prix = -1, v      # spread trop haut -> on parie sur la baisse
            elif z <= -entree_z:
                position, entree_prix = 1, v
        else:
            if abs(z) <= sortie_z:
                gain = (v - entree_prix) * position
                # normalise en bps du notionnel de la jambe B (l'echelle du spread est celle de B)
                base = abs(yb_te[0]) or 1.0
                rendements.append(1e4 * gain / base)
                position = 0

    if not rendements:
        return ResultatPaire(nom_a, nom_b, n, beta, adf, True, 0, 0.0, 0.0, False,
                             MOTIF_PAS_DE_TRADE,
                             "cointegre, mais le z n'a jamais franchi %.1f sur l'OOS. "
                             "*Une paire qui ne trade pas ne rapporte pas.*" % entree_z)

    brut = sum(rendements) / len(rendements)
    net = brut - float(cout_aller_retour_bps)

    # 🔴 LE PLANCHER D'ANECDOTE. Un edge moyen calcule sur 1 trade n'est pas un edge : c'est un
    # tirage. On ne DECLARE PAS viable ce qu'on n'a pas mesure -- meme si le chiffre est beau.
    # (Il l'etait : +95,29 bps sur SOL/HYPE. Sur UN trade.)
    if len(rendements) < MIN_TRADES_OOS:
        return ResultatPaire(
            nom_a, nom_b, n, beta, adf, True, len(rendements), brut, net, False,
            MOTIF_TROP_PEU_DE_TRADES,
            "%d trade(s) OOS < %d : brut %+.2f bps, net %+.2f bps -- mais c'est une ANECDOTE, "
            "pas une mesure. On ne conclut pas."
            % (len(rendements), MIN_TRADES_OOS, brut, net),
        )

    viable = net > 0
    return ResultatPaire(
        nom_a, nom_b, n, beta, adf, True, len(rendements), brut, net, viable,
        MOTIF_POSITIF if viable else MOTIF_NEGATIF,
        "%d trades OOS ; brut %.2f bps ; couts %.1f bps (4 executions)."
        % (len(rendements), brut, cout_aller_retour_bps),
    )


__all__ = [
    "ADF_SEUIL_5PCT", "MIN_POINTS_COMMUNS", "MIN_POINTS_TEST", "MIN_TRADES_OOS",
    "MOTIF_INSUFFISANT", "MOTIF_NEGATIF", "MOTIF_NON_COINTEGRE", "MOTIF_PAS_DE_TRADE",
    "MOTIF_POSITIF", "MOTIF_TROP_PEU_DE_TRADES", "ResultatPaire",
    "adf_tstat", "apparier", "evaluer_paire", "hedge_ratio", "resampler", "spread",
]
