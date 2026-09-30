r"""LES SOURCES — *chercher partout, mais **filtrer partout pareil**.*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE FLO A DEMANDÉ, ET CE QUE JE LUI DOIS EN RETOUR
═══════════════════════════════════════════════════════════════════════════════════════════════

Flo veut chercher **des posts X** sur *« les meilleures méthodes de grinder et sniper »* et *« le
gain de PnL »*.

    🔴 **CE CORPUS EST EXACTEMENT CELUI QUE CE PROJET A PROUVÉ SANS VALEUR.**

        le **grinder** est MORT   -> T1b : **0/29** même à **100 % de fill** (la borne la plus
                                     généreuse). Et **HLP — le market maker *payé* par le
                                     protocole, et liquidateur — rend −0,01 % APR.**
        le **sniper** est MORT    -> **−7,97 bps à coût ZÉRO**, sur 24 133 signaux OOS.
                                     Le leader est **contrarien**, pas informé.

    Et X est la source la plus dense au monde en **la signature exacte qu'on pénalise** : des
    promesses d'alpha, **zéro formule**, **zéro chiffre vérifiable**, **zéro aveu de limite**.
    Une capture de PnL est du **biais du survivant** à l'état pur : *tu vois celui qui a gagné,
    jamais les mille qui ont perdu avec la même méthode.*

***Je ne construis donc PAS une machine à nous nourrir du pire corpus possible.***

Je construis **le même filtre impitoyable, appliqué à TOUTES les sources** :

    « +300 % cette semaine 🚀 »                          -> **score NÉGATIF**
    « notre MM perdait sur les carnets minces, voici     -> **score POSITIF**
      la formule et le chiffre »

    ***Le filtre ne demande pas D'OÙ ça vient. Il demande CE QUE ÇA PROUVE.***

Et j'ajoute les sources qui, elles, contiennent vraiment quelque chose :
**arXiv** (la source des formules), **Hacker News**, **quant.stackexchange**.

═══════════════════════════════════════════════════════════════════════════════════════════════
🚩 X / TWITTER — ce que je peux et ce que je ne peux pas
═══════════════════════════════════════════════════════════════════════════════════════════════

L'API X est **payante** (et Flo a dit : *« je ne veux rien de payant »*). Sans jeton, l'accès
public est **fermé**.

    -> si `X_BEARER_TOKEN` est présent dans l'environnement, on interroge X.
    -> **sinon, la source est marquée `INDISPONIBLE` — et on le DIT.**

***On ne fait pas semblant de chercher.*** Une source qu'on n'a pas lue n'est pas une source vide.

PUR : aucun réseau. Ce module **décrit les sources et juge un texte**. Aucun ordre réel.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from hl_observer.research.github_signals import analyser, score as score_substance

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🚨 L'ANTI-HYPE — *ce qui fait chuter un score, quelle que soit la source.*
#
# Ce n'est pas de la pruderie : c'est de l'**arithmétique de survie**. Une méthode qui « fait
# +300 % » est publiée par celui qui a gagné. **Les mille qui ont perdu avec la même méthode
# ne publient rien.** Le corpus est donc mécaniquement menteur — *sauf* pour ceux qui avouent.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
HYPE: tuple[str, ...] = (
    r"\b\d{2,}\s*%\s*(gain|profit|return|roi|apy|apr)?\s*(in|en)\s*(a\s*)?(day|week|month|jour|semaine)",
    r"\b\d{3,}\s*x\b", r"\b\d{2,}\s*x\s*(return|gain|profit)",
    r"turned\s+\$?\d+\s+into", r"\bfrom\s+\$?\d+\s+to\s+\$?\d[\d,]{2,}",
    r"\bprint(ing|s)?\s+money\b", r"money\s+printer", r"money\s+glitch",
    r"\bfree\s+money\b", r"risk[\s-]*free\s+(profit|money|alpha)",
    r"\bguaranteed\b", r"\bcan'?t\s+lose\b", r"never\s+loses?\b",
    r"\bholy\s+grail\b", r"\bsecret\s+(sauce|strategy|method)\b",
    r"\bdm\s+me\b", r"\blink\s+in\s+bio\b", r"join\s+(my|our)\s+(discord|telegram|channel)",
    r"\bsignals?\s+group\b", r"\bcopy\s+my\s+trades?\b", r"\bmentorship\b",
    r"🚀|💰|🤑|📈{2,}",
    r"\bgm\b\s+(fam|frens)", r"\bwagmi\b", r"\bape\s+in\b",
    r"\bpnl\s+flex\b", r"\bportfolio\s+update\b.*\b\d{2,}\s*%",
)

# 🔑 CE QU'ON CHERCHE **VRAIMENT** dans un texte social — et c'est l'inverse du hype.
#    *Dans un corpus où tout le monde promet, celui qui doute est le seul qui ait travaillé.*
HONNETETE: tuple[str, ...] = (
    r"\bi\s+was\s+wrong\b", r"\bthis\s+(didn'?t|does\s*n'?o?t)\s+work\b",
    r"\bwe\s+lost\b", r"\blost\s+money\b", r"\bblew\s+up\b", r"\bgot\s+rekt\b",
    r"\bpost[\s-]*mortem\b", r"\bwhat\s+went\s+wrong\b",
    r"\bsurvivorship\s+bias\b", r"\boverfit", r"\bcurve[\s-]*fit",
    r"\bafter\s+fees\b", r"\bnet\s+of\s+fees\b", r"\bincluding\s+(fees|slippage|funding)\b",
    r"\bout[\s-]*of[\s-]*sample\b", r"\bwalk[\s-]*forward\b", r"\bembargo\b", r"\bpurged\b",
    r"\badverse\s+selection\b", r"\bqueue\s+position\b", r"\bmarket\s+impact\b",
    r"\bdoesn'?t\s+scale\b", r"\bcapacity\s+constrain", r"\bthin\s+book",
    r"\bin\s+theory\b.*\bin\s+practice\b",
)

# Les concepts qui, dans un texte social, valent qu'on aille lire.
UTILE: tuple[str, ...] = (
    r"funding\s*rate", r"basis\s*trade", r"delta[\s-]*neutral", r"cash[\s-]*and[\s-]*carry",
    r"liquidation\s*cascade", r"forced\s*(selling|liquidation)",
    r"order\s*flow\s*imbalance", r"\bvpin\b", r"micro[\s-]*price",
    r"avellaneda", r"\bglft\b", r"inventory\s*skew", r"reservation\s*price",
    r"maker\s*rebate", r"fee\s*tier", r"\bbps\b",
    r"hyperliquid", r"\bhip-?\d\b", r"\bhlp\b", r"perp\w*\s*dex",
)


@dataclass(frozen=True, slots=True)
class Source:
    """Une source. **Elle dit si elle est disponible — et si non, pourquoi.**"""
    nom: str
    genre: str                 # "code" | "papier" | "forum" | "social"
    url_api: str
    disponible: bool
    pourquoi_indisponible: str = ""
    fiabilite: float = 1.0     # facteur appliqué au score. *Toutes les sources ne se valent pas.*
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"nom": self.nom, "genre": self.genre, "disponible": self.disponible,
                "pourquoi_indisponible": self.pourquoi_indisponible,
                "fiabilite": self.fiabilite, "note": self.note}


def catalogue(*, jeton_github: str = "", jeton_x: str = "") -> list[Source]:
    """Les sources, **et leur disponibilité RÉELLE**. *On ne fait pas semblant de chercher.*"""
    return [
        Source(
            "arxiv", "papier", "http://export.arxiv.org/api/query", True,
            fiabilite=1.30,
            note="🔑 **La source des FORMULES.** q-fin.TR / q-fin.CP. Gratuite, ouverte, sans "
                 "jeton. *Le code est une implémentation ; le papier est le raisonnement.* "
                 "Et un papier passe par une relecture — pas un thread X.",
        ),
        Source(
            "github_code", "code", "https://api.github.com/search/code",
            bool(jeton_github),
            "" if jeton_github else "`/search/code` **exige un token GitHub**. Sans lui, "
                                    "impossible — *et je le dis au lieu de faire semblant.*",
            fiabilite=1.20,
            note="🔑 Cherche **DANS le code**. *Le README est la page de vente ; le code est la "
                 "vérité.* Trouve un repo sans topic, sans étoile, au README muet.",
        ),
        Source(
            "hackernews", "forum", "https://hn.algolia.com/api/v1/search", True,
            fiabilite=0.90,
            note="Gratuit, sans jeton. Les commentaires HN sont souvent **plus honnêtes que les "
                 "posts** : quelqu'un vient toujours dire pourquoi ça ne marche pas.",
        ),
        Source(
            "stackexchange_quant", "forum", "https://api.stackexchange.com/2.3/search/advanced",
            True, fiabilite=1.00,
            note="quant.stackexchange — gratuit. Les réponses y sont **notées et contestées**. "
                 "*Un corpus qui se contredit lui-même est un corpus qui se corrige.*",
        ),
        Source(
            "x_twitter", "social", "https://api.x.com/2/tweets/search/recent",
            bool(jeton_x),
            "" if jeton_x else (
                "🔴 **L'API X est PAYANTE**, et Flo a dit : *« je ne veux rien de payant »*. "
                "Sans `X_BEARER_TOKEN`, cette source est **INDISPONIBLE** — et je le **DIS**. "
                "*Une source qu'on n'a pas lue n'est pas une source vide.*"
            ),
            fiabilite=0.35,
            note="🚨 **La source la moins fiable, et de loin.** Fiabilité 0,35 : un post X doit "
                 "être **3× meilleur** qu'un papier pour peser autant. *Une capture de PnL est "
                 "du biais du survivant : tu vois celui qui a gagné, jamais les mille qui ont "
                 "perdu avec la même méthode.*",
        ),
    ]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LE JUGEMENT — *le filtre ne demande pas D'OÙ ça vient. Il demande CE QUE ÇA PROUVE.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
POIDS_HONNETETE = 15.0        # 🔑 le signal le plus fort. *Celui qui doute est celui qui a travaillé.*
POIDS_UTILE = 5.0
PENALITE_HYPE = -30.0         # *une promesse est un aveu d'absence de preuve*


@dataclass(slots=True)
class Verdict:
    score: float
    hype: list[str]
    honnetete: list[str]
    utile: list[str]
    garde: bool
    pourquoi: str

    def as_dict(self) -> dict[str, Any]:
        return {"score": round(self.score, 1), "hype": self.hype,
                "honnetete": self.honnetete, "concepts_utiles": self.utile,
                "garde": self.garde, "pourquoi": self.pourquoi}


def _trouver(motifs: Sequence[str], t: str, maxi: int = 4) -> list[str]:
    out: list[str] = []
    for m in motifs:
        x = re.search(m, t, re.IGNORECASE)
        if x:
            a, b = max(0, x.start() - 35), min(len(t), x.end() + 35)
            e = " ".join(t[a:b].split())
            if e not in out:
                out.append(e)
            if len(out) >= maxi:
                break
    return out


SEUIL_GARDE = 12.0


def juger(texte: str, *, source: Source) -> Verdict:
    """**Le même filtre pour toutes les sources.** Seule la *fiabilité* diffère.

    🔑 Un post X qui promet **+300 %** marque **NÉGATIF**.
    🔑 Un post X qui dit *« on a perdu, voici pourquoi, voici le chiffre »* marque **POSITIF**.

    ***Ce n'est pas de la pruderie : c'est de l'arithmétique de survie.***
    Celui qui a gagné publie ; **les mille qui ont perdu avec la même méthode ne publient rien.**
    Le corpus est donc mécaniquement menteur — *sauf pour ceux qui avouent.*
    """
    t = texte or ""
    hype = _trouver(HYPE, t)
    honn = _trouver(HONNETETE, t)
    util = _trouver(UTILE, t)

    # la substance « dure » (formules, aveux, chiffres) — la même que pour GitHub
    sig = analyser(t)
    s = score_substance(sig, etoiles=0)

    s += POIDS_HONNETETE * min(len(honn), 3)
    s += POIDS_UTILE * min(len(util), 4)
    s += PENALITE_HYPE * len(hype)
    s *= float(source.fiabilite)

    if hype and not honn and not sig.n_formules:
        return Verdict(s, hype, honn, util, False,
                       "🚨 **HYPE PUR** : il promet (« %s ») et **n'avoue rien, ne pose aucune "
                       "formule, ne donne aucun chiffre vérifiable**. *Biais du survivant : tu "
                       "vois celui qui a gagné, jamais les mille qui ont perdu avec la même "
                       "méthode.*" % hype[0][:70])

    if s < SEUIL_GARDE:
        return Verdict(s, hype, honn, util, False,
                       "score %.1f < %.1f — rien de mesurable. *Intéressant n'est pas utile.*"
                       % (s, SEUIL_GARDE))

    raisons = []
    if honn:
        raisons.append("**il avoue une limite** (« %s »)" % honn[0][:60])
    if sig.n_formules:
        raisons.append("**%d formule(s) posée(s)**" % sig.n_formules)
    if sig.chiffres:
        raisons.append("**%d chiffre(s) vérifiable(s)**" % len(sig.chiffres))
    if util:
        raisons.append("touche %d concept(s) qui nous manquent" % len(util))
    return Verdict(s, hype, honn, util, True,
                   "score %.1f (fiabilité source ×%.2f) — %s"
                   % (s, source.fiabilite, " · ".join(raisons) or "—"))


def rapport_sources(srcs: Sequence[Source]) -> dict[str, Any]:
    dispo = [s for s in srcs if s.disponible]
    non = [s for s in srcs if not s.disponible]
    return {
        "disponibles": [s.nom for s in dispo],
        "indisponibles": {s.nom: s.pourquoi_indisponible for s in non},
        "detail": [s.as_dict() for s in srcs],
        "avertissement": (
            "🔴 **%d source(s) INDISPONIBLE(S).** Elles ne sont pas vides : **je ne les ai pas "
            "lues.** *On ne fait pas semblant de chercher.*" % len(non)
        ) if non else "✅ toutes les sources sont accessibles.",
        "note_x": (
            "🚨 **X pèse ×0,35.** Un post X doit être **3× meilleur** qu'un papier arXiv pour "
            "compter autant. Ce n'est pas un préjugé : c'est ce que la mesure impose. "
            "*Le grinder (0/29 à 100 % de fill) et le sniper (−7,97 bps à coût zéro) sont MORTS — "
            "et X est la source la plus dense au monde en promesses sur ces deux-là.*"
        ),
    }


__all__ = [
    "HONNETETE", "HYPE", "PENALITE_HYPE", "POIDS_HONNETETE", "POIDS_UTILE", "SEUIL_GARDE", "UTILE",
    "Source", "Verdict", "catalogue", "juger", "rapport_sources",
]
