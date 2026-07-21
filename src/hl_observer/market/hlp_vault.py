"""#398 / #544 — LE VAULT HLP : **le rendement de « l'autre côté »**.

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI CETTE TÂCHE EST PLUS MALIGNE QU'ELLE N'EN A L'AIR
═══════════════════════════════════════════════════════════════════════════════════════════════

HLP n'est pas un vault comme un autre.

    ***HLP EST LE MARKET MAKER DE HYPERLIQUID.*** Il cote, il absorbe le flux, il liquide.

Donc son rendement est **le PnL du market making sur Hyperliquid, mesuré par le protocole
lui-même, en argent réel, sur des mois.**

    🔑 ***C'est un TEST DIRECT de T1b, fait par quelqu'un d'autre, avec de l'argent réel.***

T1b a conclu : le MM retail est mort (0/29 à 100 % de fill, le prix bouge 5 à 30× plus que le
spread capturé). **Si HLP gagne de l'argent, deux lectures — et il faut choisir la bonne :**

  **(A) T1b se trompe.** → *Alors il faut le savoir, et vite.*
  **(B) HLP gagne pour des raisons AUXQUELLES ON N'A PAS ACCÈS.** ← **c'est l'hypothèse à battre**

═══════════════════════════════════════════════════════════════════════════════════════════════
🚩 CE QUE HLP A ET QUE NOUS N'AURONS JAMAIS — dit AVANT de mesurer
═══════════════════════════════════════════════════════════════════════════════════════════════

  1. 🔴 **HLP ENCAISSE UNE PART DES FRAIS DU PROTOCOLE.** Doc officielle : *« fees are entirely
     directed to the community (**HLP**, the assistance fund, and deployers) »*.
     ***Il est payé pour exister.*** Nous, on PAIE 1,5 bps par jambe.
  2. 🔴 **HLP EST LE LIQUIDATEUR.** Il récupère les positions liquidées **à un prix imposé**,
     pas au marché. C'est un flux forcé qu'il reçoit **par privilège**, pas par compétition.
  3. 🔴 **HLP A UNE TAILLE ET UNE PERMANENCE** qu'aucun compte de 500 $ n'aura : il tient
     l'inventaire à travers les chocs sans être liquidé.
  4. 🔴 **HLP N'A PAS DE FILE D'ATTENTE** au même sens que nous : il est structurellement du bon
     côté du carnet.

    ***Un rendement HLP positif ne réfute donc PAS T1b. Il MESURE le prix du privilège.***

**Si je trouve que HLP gagne, je n'annoncerai pas « le MM marche ». J'annoncerai : "le MM marche
POUR CELUI QUI EST PAYÉ POUR LE FAIRE".** *(C'est la règle : quand un résultat est beau, regarde
QUI survit — ici, qui gagne, et POURQUOI.)*

Et une conclusion **actionnable** existe quand même :
    🎯 **Si HLP rapporte X % APR sans risque de compétition, y DÉPOSER (en paper) est un
    benchmark honnête** — et il faut le comparer au CASH et au buy-and-hold (#571).
    *On ne le fera pas en vrai : rien de payant, rien de réel. Mais on peut le MESURER.*

PUR : parsing et arithmétique. Aucun appel réseau. Aucun dépôt. Aucun ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

MOTIF_PAS_ASSEZ = "PAS_ASSEZ_D_HISTORIQUE"
MOTIF_HLP_GAGNE = "HLP_GAGNE_MAIS_IL_EST_PAYE_POUR_EXISTER"
MOTIF_HLP_PERD = "HLP_PERD_MALGRE_SES_PRIVILEGES"

MIN_JOURS = 30

# Les privilèges de HLP, énumérés — **aucun ne nous est accessible**.
PRIVILEGES = (
    "encaisse une PART DES FRAIS du protocole (doc : « fees are entirely directed to HLP… »)",
    "est le LIQUIDATEUR : il reçoit le flux forcé à un prix imposé, par privilège",
    "a la taille et la permanence pour porter l'inventaire à travers les chocs",
    "est structurellement du bon côté du carnet",
)


@dataclass(frozen=True, slots=True)
class PointVault:
    time_ms: int
    valeur_part: float          # la valeur d'une part (accountValue / nParts)


@dataclass(frozen=True, slots=True)
class VerdictHLP:
    n_points: int
    jours: float
    rendement_total: float
    apr: float
    drawdown_max: float
    motif: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_points": self.n_points, "jours": round(self.jours, 1),
            "rendement_total_pct": round(self.rendement_total * 100, 3),
            "apr_pct": round(self.apr * 100, 2),
            "drawdown_max_pct": round(self.drawdown_max * 100, 2),
            "motif": self.motif, "note": self.note,
            "privileges_de_HLP_inaccessibles": list(PRIVILEGES),
            "avertissement": (
                "🔴 **Un rendement HLP positif ne REFUTE PAS T1b.** HLP **est payé pour exister** "
                "(part des frais) et **est le liquidateur**. Il ne joue pas notre jeu. "
                "*Le MM marche — POUR CELUI QUI EST PAYÉ POUR LE FAIRE.*"
            ),
            "real_execution": False,
        }


def _drawdown(vals: Sequence[float]) -> float:
    if not vals:
        return 0.0
    sommet, pire = vals[0], 0.0
    for v in vals:
        sommet = max(sommet, v)
        if sommet > 0:
            pire = max(pire, (sommet - v) / sommet)
    return pire


def parser_vault(payload: Any) -> list[PointVault]:
    """`vaultDetails` → historique de la valeur de part.

    DENY-BY-DEFAULT : un point illisible est **ÉCARTÉ**, jamais deviné.
    """
    out: list[PointVault] = []
    if isinstance(payload, Mapping):
        payload = payload.get("portfolio") or payload.get("history") or []
    if not isinstance(payload, (list, tuple)):
        return out
    for p in payload:
        if isinstance(p, Mapping):
            t, v = p.get("time"), p.get("value") or p.get("pnl")
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            t, v = p[0], p[1]
        else:
            continue
        try:
            tm, val = int(t), float(v)
        except (TypeError, ValueError):
            continue
        if tm > 0 and val > 0:
            out.append(PointVault(tm, val))
    return sorted(out, key=lambda p: p.time_ms)


def evaluer(points: Sequence[PointVault], *, min_jours: int = MIN_JOURS) -> VerdictHLP | None:
    """Le rendement RÉEL de HLP. `None` = **état vide honnête**, jamais un chiffre inventé."""
    ps = [p for p in points if p.valeur_part > 0]
    if len(ps) < 2:
        return None
    jours = (ps[-1].time_ms - ps[0].time_ms) / 86_400_000.0
    if jours < min_jours:
        return VerdictHLP(len(ps), jours, 0.0, 0.0, 0.0,
                          "%s : %.1f j < %d j" % (MOTIF_PAS_ASSEZ, jours, min_jours),
                          "*Un rendement sur quelques jours n'est pas un rendement.*")

    vals = [p.valeur_part for p in ps]
    r = vals[-1] / vals[0] - 1.0
    apr = ((1.0 + r) ** (365.0 / jours) - 1.0) if jours > 0 else 0.0
    dd = _drawdown(vals)

    if r <= 0:
        return VerdictHLP(
            len(ps), jours, r, apr, dd, MOTIF_HLP_PERD,
            "🔴 **HLP PERD, malgré tous ses privilèges** (part des frais, liquidations, taille). "
            "***Si même le market maker PAYÉ pour l'être perd de l'argent, T1b est CONFIRMÉ de la "
            "manière la plus forte qui soit.***",
        )
    return VerdictHLP(
        len(ps), jours, r, apr, dd, MOTIF_HLP_GAGNE,
        "HLP gagne **%.2f %% APR** (drawdown max %.1f %%). ⚠️ **Ça ne réfute PAS T1b** : HLP "
        "encaisse une part des frais du protocole et **EST le liquidateur**. *Le market making "
        "marche — pour celui qui est PAYÉ pour le faire.* 🎯 Ce chiffre est en revanche un "
        "**benchmark honnête** : toute stratégie qu'on invente doit le battre, sinon autant "
        "déposer dans HLP. (À comparer au CASH et au buy-and-hold, cf. #571.)"
        % (apr * 100, dd * 100),
    )


def comparer_a_nos_pistes(apr_hlp: float, *, apr_carry_hype: float = 0.02) -> dict[str, Any]:
    """🎯 **La question qui tue** : notre meilleure piste bat-elle le simple dépôt dans HLP ?

    T2b (le carry HYPE) est **le seul résultat positif du projet** : ~2 % APR.
    """
    return {
        "apr_hlp": round(apr_hlp * 100, 2),
        "apr_carry_hype_T2b": round(apr_carry_hype * 100, 2),
        "notre_meilleure_piste_bat_HLP": apr_carry_hype > apr_hlp,
        "verdict": (
            "🔴 **Notre meilleure piste (T2b, ~%.1f %% APR) NE BAT PAS le simple dépôt dans HLP "
            "(%.1f %%).** *Toute la complexité qu'on a construite est dominée par un dépôt "
            "passif.* **Il faut le dire.**" % (apr_carry_hype * 100, apr_hlp * 100)
            if apr_carry_hype <= apr_hlp else
            "Notre meilleure piste (%.1f %%) bat HLP (%.1f %%)."
            % (apr_carry_hype * 100, apr_hlp * 100)
        ),
        "reserve": (
            "⚠️ HLP n'est PAS sans risque : il porte l'inventaire et absorbe les liquidations. "
            "Son drawdown doit être comparé, pas seulement son APR."
        ),
        "real_execution": False,
    }


__all__ = [
    "MIN_JOURS", "MOTIF_HLP_GAGNE", "MOTIF_HLP_PERD", "MOTIF_PAS_ASSEZ", "PRIVILEGES",
    "PointVault", "VerdictHLP", "comparer_a_nos_pistes", "evaluer", "parser_vault",
]
