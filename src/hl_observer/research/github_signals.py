r"""LE TRI DU MOISSONNEUR — *ce qui distingue une IDÉE d'un README bavard.*

═══════════════════════════════════════════════════════════════════════════════════════════════
🔴 CE QUI N'ALLAIT PAS — mesuré sur la moisson réelle de 5 617 repos
═══════════════════════════════════════════════════════════════════════════════════════════════

L'ancien tri comptait **combien de CONCEPTS un README mentionne**. Résultat mesuré :

    n_concepts = 0   ->  médiane **15 étoiles**
    n_concepts = 12  ->  médiane **5 étoiles**

    ***Le compte de concepts est ANTI-CORRÉLÉ à l'adoption réelle.***

Le champion (12 concepts sur 13, `AshJha0/Quant-Finance-Library`) a **5 étoiles** et un README
qui **récite le catalogue du métier**.

    🔑 ***Mon grep mesurait la VERBOSITÉ du README, pas la SUBSTANCE.***

C'est exactement la faute qu'on traque partout ailleurs : **une métrique qui a l'air rigoureuse
et qui mesure autre chose.** (Comme `signal_age` qui était une tautologie, ou le voyant sécurité
qui était soudé au vert.)

Et les **étoiles** ne mesurent pas la crédibilité non plus : les 4 repos les plus **exactement**
sur cible avaient **1, 2, 3 et 3 étoiles**.

═══════════════════════════════════════════════════════════════════════════════════════════════
✅ CE QU'ON MESURE À LA PLACE — trois signaux qu'un README bavard ne peut PAS simuler
═══════════════════════════════════════════════════════════════════════════════════════════════

**1. LES FORMULES.** Citer « Avellaneda-Stoikov » est gratuit. Écrire `λ(δ) = A·e^(−κδ)` veut
   dire que quelqu'un a **calculé** quelque chose. *Un nom propre se copie ; une formule se pose.*

**2. 🔑 LES AVEUX DE LIMITE.** LE signal le plus fort, et le plus contre-intuitif.
   `tfrmma/cross-venue-arbitrage` écrit : *« not a substitute for real VPIN »*.

       ***Dans un corpus où TOUT LE MONDE promet de l'alpha, avouer une limite est la seule
       signature possible de l'honnêteté.*** Un arnaqueur ne dit jamais ce qui ne marche pas.

   Et c'est **exactement notre propre critère** : ce projet a passé deux jours à valoriser les
   gens qui disent « je ne sais pas » plutôt que ceux qui affirment.

**3. LES CHIFFRES VÉRIFIABLES.** « améliore le PnL » ne coûte rien. « **−7,97 bps sur 24 133
   signaux OOS** » engage celui qui l'écrit. *Un chiffre précis est une prise.*

═══════════════════════════════════════════════════════════════════════════════════════════════
🚩 CE QUE CE MODULE **NE PRÉTEND PAS** FAIRE
═══════════════════════════════════════════════════════════════════════════════════════════════

    ***TRIER NE REMPLACERA JAMAIS LIRE.***

Le chiffre le plus important de toute la moisson :

    **8 passes de tri** sur **5 617 repos**  ->  **3 idées**
    **20 minutes** à lire le code d'**UN SEUL** repo (hftbacktest)  ->  **5 bugs** dans notre simu

Donc ce module ne cherche pas à produire un meilleur CLASSEMENT.
**Il cherche à produire une LISTE DE LECTURE** : *quels fichiers ouvrir, à quelle ligne, et
pourquoi.* Un score n'a jamais corrigé un bug ; une ligne de code lue, si.

PUR : aucun réseau. Aucun ordre réel. Lecture seule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 1. LES FORMULES — *un nom propre se copie ; une formule se pose.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
FORMULES: dict[str, tuple[str, ...]] = {
    "kappa_intensite_de_fill": (
        r"e\s*\^\s*\(?\s*-\s*(kappa|κ|k)",       # e^(-kappa·delta)
        r"exp\s*\(\s*-\s*(kappa|κ|k)\b",
        r"\bA\s*\*\s*(exp|e\^)",                 # lambda = A * exp(...)
        r"lambda\s*\(\s*(delta|δ)\s*\)",
        r"\bkappa\b\s*=", r"κ\s*=",
        r"arrival\s*(rate|intensity)\s*[=:]",
    ),
    "gueant_lehalle_glft": (
        r"\bglft\b", r"sinh\s*\(", r"\bcosh\s*\(",
        r"gueant.{0,20}lehalle", r"fernandez[\s-]*tapia",
    ),
    "position_dans_la_file": (
        r"qty[_\s-]*ahead", r"queue[_\s-]*ahead", r"cum[_\s-]*qty",
        r"ahead[_\s-]*(of|qty|volume)", r"chg\s*-=", r"prob[_\s-]*queue",
    ),
    "impact_racine_carree": (
        r"sqrt\s*\(\s*(v|q|vol|size)", r"square[\s-]*root\s*(law|impact)",
        r"\bY\s*\*\s*sigma", r"impact\s*=\s*.*sqrt",
    ),
    "cout_chiffre_en_bps": (
        r"\d+(\.\d+)?\s*bps\b", r"\d+(\.\d+)?\s*basis\s*points?\b",
    ),
    "controle_stochastique": (
        r"hamilton[\s-]*jacobi", r"\bhjb\b", r"bellman", r"viscosity\s*solution",
    ),
    "microprix": (
        r"micro[\s-]*price", r"weighted\s*mid", r"imbalance\s*[=:]",
        r"\bofi\b", r"order\s*flow\s*imbalance",
    ),
}

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 2. 🔑 LES AVEUX DE LIMITE — *la seule signature possible de l'honnêteté.*
#
#    Dans un corpus où TOUT LE MONDE promet de l'alpha, celui qui écrit « ça n'a pas marché »
#    est le seul qui ait quelque chose à nous apprendre.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
AVEUX: tuple[str, ...] = (
    r"lost\s+money", r"didn'?t\s+work", r"does\s*n'?o?t\s+work", r"doesn'?t\s+work",
    r"not\s+profitable", r"unprofitable", r"negative\s+(pnl|returns?|expectancy)",
    r"post[\s-]*mortem", r"failed", r"failure",
    r"not\s+a\s+substitute", r"is\s+not\s+(a\s+)?real\b", r"only\s+an?\s+approximation",
    r"overfit", r"over[\s-]*fitted", r"curve[\s-]*fit",
    r"unrealistic", r"too\s+optimistic", r"overly\s+optimistic",
    r"known\s+(issue|limitation|bug)", r"\blimitations?\b", r"\bcaveats?\b",
    r"simplif\w+\s+(assumption|model)", r"assumes?\s+(perfect|instant|zero)",
    r"do\s*n'?o?t\s+use\s+(this\s+)?in\s+production", r"educational\s+(purposes?|only)",
    r"backtest\s+(is|was)\s+(not|misleading)", r"paper\s+only",
    r"ne\s+marche\s+pas", r"n'?a\s+pas\s+marche", r"limites?\s+connues?",
)

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 3. LES CHIFFRES VÉRIFIABLES — *un chiffre précis est une prise.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
CHIFFRES: tuple[str, ...] = (
    r"sharpe\s*(ratio)?\s*[:=]?\s*-?\d+(\.\d+)?",
    r"(profit\s*factor|\bpf\b)\s*[:=]?\s*\d+(\.\d+)?",
    r"win\s*rate\s*[:=]?\s*\d+(\.\d+)?\s*%",
    r"(max\s*)?drawdown\s*[:=]?\s*-?\d+(\.\d+)?\s*%",
    r"-?\d+(\.\d+)?\s*bps\b",
    r"\b\d{3,}\s+(trades|fills|samples|signals)\b",
    r"(apr|apy)\s*[:=]?\s*-?\d+(\.\d+)?\s*%",
)

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🚩 LES MENSONGES — un README qui promet sans jamais douter.
#    *Signature d'arnaque relevée sur du VRAI : 2 repos HL (321⭐, 567⭐) en bourrage de mots-clés.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
PROMESSES_CREUSES: tuple[str, ...] = (
    r"guaranteed\s+profit", r"risk[\s-]*free\s+(profit|money|returns?)",
    r"\b\d{3,}\s*%\s+(monthly|weekly|daily)\b",
    r"passive\s+income", r"money\s+printer", r"never\s+lose",
    r"100\s*%\s+win", r"\bholy\s+grail\b",
)

# Les chemins de fichiers qui MÉRITENT une lecture. *Le README est du marketing ; le code est la vérité.*
CHEMINS_INTERESSANTS: tuple[str, ...] = (
    r"queue", r"fill", r"latenc", r"impact", r"slippage", r"funding", r"basis", r"carry",
    r"backtest", r"replay", r"orderbook", r"order_book", r"\block\b", r"depth",
    r"avellaneda", r"stoikov", r"glft", r"quote", r"maker", r"inventory",
    r"liquidat", r"risk", r"cost", r"fee", r"execut", r"lookahead", r"leak",
)

_EXT_CODE = (".py", ".rs", ".cpp", ".hpp", ".c", ".h", ".go", ".ts", ".js", ".jl", ".ipynb")


def _trouver(motifs: Iterable[str], texte: str, *, maxi: int = 3) -> list[str]:
    """Les extraits qui matchent. **La PREUVE, jamais un simple booléen.**

    *Un score sans preuve est un score qu'on ne peut pas contester -- donc qu'on ne peut pas
    corriger.*
    """
    out: list[str] = []
    for m in motifs:
        for x in re.finditer(m, texte, re.IGNORECASE):
            a, b = max(0, x.start() - 45), min(len(texte), x.end() + 45)
            extrait = " ".join(texte[a:b].split())
            if extrait not in out:
                out.append(extrait)
            if len(out) >= maxi:
                return out
    return out


@dataclass(slots=True)
class Signaux:
    """Ce qu'un texte révèle **vraiment**. Chaque signal porte sa preuve."""
    formules: dict[str, list[str]] = field(default_factory=dict)
    aveux: list[str] = field(default_factory=list)
    chiffres: list[str] = field(default_factory=list)
    promesses_creuses: list[str] = field(default_factory=list)

    @property
    def n_formules(self) -> int:
        return len(self.formules)

    def as_dict(self) -> dict[str, Any]:
        return {
            "formules": {k: v for k, v in self.formules.items()},
            "aveux_de_limite": self.aveux,
            "chiffres_verifiables": self.chiffres,
            "promesses_creuses": self.promesses_creuses,
            "n_formules": self.n_formules,
        }


def analyser(texte: str) -> Signaux:
    """Les 3 signaux + le drapeau rouge. **Sur le TEXTE, pas sur les métadonnées.**"""
    t = texte or ""
    return Signaux(
        formules={k: p for k, m in FORMULES.items() if (p := _trouver(m, t))},
        aveux=_trouver(AVEUX, t, maxi=5),
        chiffres=_trouver(CHIFFRES, t, maxi=5),
        promesses_creuses=_trouver(PROMESSES_CREUSES, t, maxi=3),
    )


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  LE SCORE — *et ce qu'il n'est PAS.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

POIDS_FORMULE = 10.0        # quelqu'un a CALCULÉ quelque chose
POIDS_AVEU = 12.0           # 🔑 le plus fort : la seule signature de l'honnêteté
POIDS_CHIFFRE = 4.0         # un chiffre précis est une prise
PENALITE_PROMESSE = -25.0   # promettre sans jamais douter = signature d'arnaque

# 🔴 LES ÉTOILES PÈSENT PEU, ET C'EST DÉLIBÉRÉ.
#    Les 4 repos les plus exactement sur cible avaient **1, 2, 3 et 3 étoiles**.
#    hftbacktest (4 270⭐) était bon *malgré* ses étoiles, pas grâce à elles.
POIDS_ETOILES = 0.35        # sqrt(étoiles) x 0,35 -> 4 270⭐ ne vaut que ~23 points


def score(sig: Signaux, *, etoiles: int = 0) -> float:
    """Ce qui mérite qu'on **LISE LE CODE**. *Ce n'est PAS un score de qualité d'idée.*

    ***Un repo bien classé n'est pas une idée qui marche.*** C'est un repo dont on peut prouver
    qu'il mérite vingt minutes de lecture.
    """
    s = 0.0
    s += POIDS_FORMULE * sig.n_formules
    s += POIDS_AVEU * min(len(sig.aveux), 3)          # plafonné : 10 aveux ne valent pas 10x
    s += POIDS_CHIFFRE * min(len(sig.chiffres), 4)
    s += PENALITE_PROMESSE * len(sig.promesses_creuses)
    s += POIDS_ETOILES * (max(int(etoiles), 0) ** 0.5)
    return round(s, 2)


def fichiers_a_lire(chemins: Sequence[str], *, maxi: int = 12) -> list[str]:
    """Les fichiers de CODE qui méritent d'être ouverts. *Le README est du marketing.*

    On ne lit pas tout un repo : on lit les fichiers dont **le chemin** annonce le sujet.
    """
    out: list[str] = []
    for c in chemins:
        bas = str(c).lower()
        if not bas.endswith(_EXT_CODE):
            continue
        if any(x in bas for x in ("/test", "test_", "example", "sample", "/doc", "vendor/")):
            continue                                   # les tests et exemples : plus tard
        if any(re.search(m, bas) for m in CHEMINS_INTERESSANTS):
            out.append(str(c))
        if len(out) >= maxi:
            break
    return out


@dataclass(frozen=True, slots=True)
class Lecture:
    """**LA SORTIE QUI COMPTE** : un fichier, une ligne, et pourquoi."""
    repo: str
    fichier: str
    ligne: int
    code: str
    pourquoi: str

    def as_dict(self) -> dict[str, Any]:
        return {"repo": self.repo, "fichier": self.fichier, "ligne": self.ligne,
                "code": self.code, "pourquoi": self.pourquoi}


def liste_de_lecture(repo: str, fichier: str, source: str,
                     *, maxi: int = 6) -> list[Lecture]:
    """Grep le **CODE** (pas le README) et renvoie **les lignes exactes à lire**.

    🔑 ***C'est LA raison d'être de tout le moissonneur.***

    Le chiffre qui décide : *8 passes de tri sur 5 617 repos -> 3 idées.
    20 minutes à lire le code d'UN repo -> 5 bugs trouvés dans notre simu.*

    -> le livrable n'est pas un CLASSEMENT. C'est **une liste de fichiers à ouvrir**.
    """
    out: list[Lecture] = []
    lignes = (source or "").splitlines()
    for i, ligne in enumerate(lignes, 1):
        if len(ligne) > 400:
            continue                                   # ligne minifiée / données : pas du code lisible
        for concept, motifs in FORMULES.items():
            if any(re.search(m, ligne, re.IGNORECASE) for m in motifs):
                out.append(Lecture(repo, fichier, i, ligne.strip()[:200],
                                   "FORMULE %s" % concept))
                break
        else:
            if any(re.search(m, ligne, re.IGNORECASE) for m in AVEUX):
                out.append(Lecture(repo, fichier, i, ligne.strip()[:200],
                                   "AVEU DE LIMITE — *la seule signature de l'honnetete*"))
        if len(out) >= maxi:
            break
    return out


def trier(repos: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Le classement final. **Par SUBSTANCE, jamais par bavardage.**"""
    return sorted(repos, key=lambda r: float(r.get("score_substance", 0.0)), reverse=True)


__all__ = [
    "AVEUX", "CHEMINS_INTERESSANTS", "CHIFFRES", "FORMULES", "PROMESSES_CREUSES",
    "PENALITE_PROMESSE", "POIDS_AVEU", "POIDS_CHIFFRE", "POIDS_ETOILES", "POIDS_FORMULE",
    "Lecture", "Signaux",
    "analyser", "fichiers_a_lire", "liste_de_lecture", "score", "trier",
]
