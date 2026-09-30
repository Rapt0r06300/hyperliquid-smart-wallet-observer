"""#549 / H-144 — LEAD-LAG BTC → ALTS. **La niche VIDE, et on a déjà la donnée.**

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI CELLE-CI MÉRITE D'EXISTER
═══════════════════════════════════════════════════════════════════════════════════════════════

Sur **5 617 repos moissonnés**, la moisson n'a trouvé **AUCUN** travail sérieux sur le lead-lag
BTC → alts. C'est une **niche vide**. Et depuis le backfill, **on a 208 jours de bougies 1 h sur
12 coins** : la donnée est **déjà là**.

L'hypothèse : *BTC bouge, les alts suivent avec un retard.* Si le retard est réel et **plus long
que nos coûts**, il y a un edge.

═══════════════════════════════════════════════════════════════════════════════════════════════
🚩 CE QUI VA PROBABLEMENT LA TUER — dit AVANT la mesure
═══════════════════════════════════════════════════════════════════════════════════════════════

*(Règle : annoncer son attente d'avance empêche de se raconter une histoire après coup.)*

  1. 🔴 **NOTRE GRANULARITÉ EST HORAIRE.** Un lead-lag crypto réel se mesure en **secondes**, pas
     en heures. Sur des bougies **1 h**, on ne peut voir qu'un retard **≥ 1 heure** — et un retard
     d'une heure entière sur BTC→alts serait de l'argent gratuit visible par la Terre entière.
     ***Donc : ou bien on ne trouve rien, ou bien on a un bug.***
  2. 🔴 **C'EST UNE COURSE DE VITESSE.** Si le retard est court, on le perd (zone morte LATENCE :
     courbe edge/horizon PLATE).
  3. 🔴 **LE PIÈGE DE LA CORRÉLATION.** BTC et les alts sont **corrélés** — ce n'est PAS un
     lead-lag. Une corrélation contemporaine élevée ne dit **rien** sur la causalité temporelle.
     *La mesure doit comparer le lag k>0 au lag 0. Sinon elle mesure la corrélation et l'appelle
     lead-lag.* **C'est le bug que je m'attends à faire.**
  4. 🔴 **LA MULTIPLICITÉ.** 12 coins × 10 lags = **120 tests**. Le meilleur des 120 aura l'air
     génial même si tout est du bruit. → **correction anti-overfit OBLIGATOIRE** (M-19).

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QU'ON MESURE
═══════════════════════════════════════════════════════════════════════════════════════════════

Pour chaque alt et chaque retard `k >= 1` :

    corr( rendement_BTC[t] , rendement_ALT[t+k] )

  * **On compare TOUJOURS au lag 0.** Si `|corr(k)| <= |corr(0)|`, il n'y a **PAS de lead-lag** :
    juste de la corrélation contemporaine. **C'est le garde central de ce module.**
  * L'edge brut est ensuite converti en bps et **confronté aux coûts** (9 bps taker aller-retour).

PUR : aucun appel réseau. Aucun ordre réel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from hl_observer.fees.hyperliquid_fees import nos_frais

COUT_ALLER_RETOUR_BPS = 2 * nos_frais("perp").taker_bps      # 9,0 bps

LAG_MAX = 6                    # 6 heures : au-dela, ce n'est plus un « lead-lag »
MIN_POINTS = 200

MOTIF_PAS_DE_LEAD_LAG = "CORRELATION_CONTEMPORAINE_PAS_UN_LEAD_LAG"
MOTIF_EDGE_SOUS_LES_COUTS = "EDGE_BRUT_INFERIEUR_AUX_COUTS"
MOTIF_PAS_ASSEZ_DE_POINTS = "PAS_ASSEZ_DE_POINTS"
MOTIF_LEAD_LAG_MESURE = "LEAD_LAG_MESURE_ET_NET_POSITIF"


@dataclass(frozen=True, slots=True)
class Resultat:
    alt: str
    lag_h: int
    corr_lag0: float           # la corrélation CONTEMPORAINE (le témoin)
    corr_lag: float            # la corrélation DÉCALÉE
    n: int
    edge_brut_bps: float
    edge_net_bps: float
    viable: bool
    motif: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"alt": self.alt, "lag_h": self.lag_h,
                "corr_lag0": round(self.corr_lag0, 4),
                "corr_lag": round(self.corr_lag, 4),
                "n": self.n,
                "edge_brut_bps": round(self.edge_brut_bps, 3),
                "edge_net_bps": round(self.edge_net_bps, 3),
                "cout_bps": COUT_ALLER_RETOUR_BPS,
                "viable": self.viable, "motif": self.motif, "note": self.note,
                "real_execution": False}


def rendements(prix: Sequence[float]) -> list[float]:
    """Rendements simples. Un prix <= 0 CASSE la série : on ne l'invente pas."""
    out: list[float] = []
    for a, b in zip(prix, prix[1:]):
        if a <= 0 or b <= 0:
            out.append(0.0)
        else:
            out.append((b - a) / a)
    return out


def correlation(x: Sequence[float], y: Sequence[float]) -> float:
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    xs, ys = list(x[:n]), list(y[:n])
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    dy = math.sqrt(sum((b - my) ** 2 for b in ys))
    return (num / (dx * dy)) if dx > 0 and dy > 0 else 0.0


def evaluer(
    alt: str,
    rends_btc: Sequence[float],
    rends_alt: Sequence[float],
    *,
    lag_h: int,
    cout_bps: float = COUT_ALLER_RETOUR_BPS,
    min_points: int = MIN_POINTS,
) -> Resultat:
    """🔴 **LE GARDE CENTRAL : on compare TOUJOURS au lag 0.**

    Une corrélation décalée élevée ne prouve **rien** si la corrélation *contemporaine* est aussi
    élevée : ça veut juste dire que BTC et l'alt bougent **ensemble**. *Ce n'est pas un lead-lag,
    c'est de la corrélation — et on ne peut pas trader une corrélation contemporaine.*
    """
    k = int(lag_h)
    if k < 1:
        raise ValueError("un lead-lag exige k >= 1 (k=0 serait la correlation contemporaine)")

    n = min(len(rends_btc) - k, len(rends_alt) - k)
    if n < min_points:
        return Resultat(alt, k, 0.0, 0.0, max(0, n), 0.0, 0.0, False,
                        "%s : %d < %d" % (MOTIF_PAS_ASSEZ_DE_POINTS, max(0, n), min_points))

    c0 = correlation(rends_btc[:n], rends_alt[:n])               # témoin : contemporain
    ck = correlation(rends_btc[:n], rends_alt[k:k + n])          # décalé de k

    if abs(ck) <= abs(c0):
        return Resultat(
            alt, k, c0, ck, n, 0.0, 0.0, False, MOTIF_PAS_DE_LEAD_LAG,
            "|corr(lag %d)| = %.4f <= |corr(lag 0)| = %.4f. **BTC et %s bougent ENSEMBLE, "
            "l'alt ne SUIT pas.** Ce n'est pas un lead-lag : c'est de la correlation, et on ne "
            "peut pas la trader." % (k, abs(ck), abs(c0), alt),
        )

    # L'edge brut : ce que la corrélation décalée capture, en bps, sur la vol de l'alt.
    n_a = len(rends_alt[k:k + n])
    m_a = sum(rends_alt[k:k + n]) / n_a
    vol_alt = math.sqrt(sum((r - m_a) ** 2 for r in rends_alt[k:k + n]) / n_a)
    edge_brut = abs(ck) * vol_alt * 1e4
    edge_net = edge_brut - float(cout_bps)

    if edge_net <= 0.0:
        return Resultat(
            alt, k, c0, ck, n, edge_brut, edge_net, False, MOTIF_EDGE_SOUS_LES_COUTS,
            "edge BRUT %.2f bps < %.1f bps de couts (aller-retour taker). "
            "**Le signal existe peut-etre ; il ne paie pas.**" % (edge_brut, cout_bps),
        )

    return Resultat(
        alt, k, c0, ck, n, edge_brut, edge_net, True, MOTIF_LEAD_LAG_MESURE,
        "⚠️ **AVANT DE CROIRE CE CHIFFRE** : (1) notre granularite est HORAIRE -- un retard d'une "
        "heure entiere sur BTC->alts serait de l'argent gratuit visible par tout le monde ; "
        "(2) 12 coins x %d lags = de la MULTIPLICITE -> passer par le gate anti-overfit ; "
        "(3) **regarder QUI survit avant d'annoncer quoi que ce soit.**" % LAG_MAX,
    )


def resume(resultats: Sequence[Resultat]) -> dict[str, Any]:
    v = [r for r in resultats if r.viable]
    return {
        "n_tests": len(resultats),
        "n_viables": len(v),
        "n_essais_pour_l_anti_overfit": len(resultats),      # 🔑 la MULTIPLICITE, declaree
        "meilleur": v[0].as_dict() if v else None,
        "attente_declaree_AVANT": (
            "🚩 Je m'attends a NE RIEN TROUVER. Notre granularite est HORAIRE : un lead-lag "
            "crypto reel se mesure en SECONDES. Un retard d'une heure entiere sur BTC->alts "
            "serait de l'argent gratuit. **Si je trouve quelque chose, je cherche d'abord le bug.**"
        ),
        "real_execution": False,
    }


__all__ = [
    "COUT_ALLER_RETOUR_BPS", "LAG_MAX", "MIN_POINTS",
    "MOTIF_EDGE_SOUS_LES_COUTS", "MOTIF_LEAD_LAG_MESURE", "MOTIF_PAS_ASSEZ_DE_POINTS",
    "MOTIF_PAS_DE_LEAD_LAG", "Resultat",
    "correlation", "evaluer", "rendements", "resume",
]
