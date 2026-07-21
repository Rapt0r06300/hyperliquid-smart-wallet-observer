r"""#2 #4 #5 #6 #12 — LA MINE QUE PERSONNE N'EXPLOITE.

═══════════════════════════════════════════════════════════════════════════════════════════════
LE README RACONTE L'INTENTION. LE RESTE RACONTE LA VÉRITÉ.
═══════════════════════════════════════════════════════════════════════════════════════════════

Le moissonneur lisait le README — **la page de vente**. Il ignorait quatre gisements où
l'auteur ne peut **pas** mentir :

  **#2 — LES MESSAGES DE COMMIT.**  🔑 *Le gisement le plus précieux, et personne ne le fouille.*
      Un commit `fix: double counting of fills` est **littéralement** le bug qu'on a trouvé chez
      hftbacktest. **Le corpus des commits est la liste des erreurs que le métier a déjà commises
      — et déjà payées.**
      *On paierait vingt fois moins cher les bugs qu'on peut lire chez les autres.*

  **#4 — LES ISSUES.**
      Le README est écrit par l'auteur **pour vendre**. Les issues sont écrites par les
      utilisateurs **pour se plaindre**. C'est là que quelqu'un dit : *« ton modèle de fill est
      faux, voilà pourquoi »*.
      ***Les issues sont des aveux INVOLONTAIRES.*** Et l'aveu est notre signal le plus fort.

  **#5 — LES TESTS.**
      Les tests disent ce que l'auteur a **PEUR** de casser. Un repo avec `test_no_lookahead.py`
      a pensé à un danger auquel on n'avait pas pensé.
      ***Les tests sont la carte des peurs de l'auteur — et ses peurs valent mieux que ses
      promesses.***

  **#6 — LES CONSTANTES.**
      `TAKER_FEE = 0.00045` · `LATENCY_MS = 50` · `MIN_SPREAD_BPS = 2`…
      Un tableau comparatif de **toutes** les constantes du corpus dit instantanément si nos
      **9 bps** sont dans la norme, si notre latence est crédible.
      ***C'est du calibrage gratuit, volé à des gens qui l'ont payé.***
      *(Rappel : notre nombre de frais a vécu dans **6 fichiers, 4 valeurs**, dont un 2,5 bps
      qui n'existe nulle part chez Hyperliquid.)*

  **#12 — LA REPRODUCTIBILITÉ.**
      Le repo joint-il ses **données** ? ***Un backtest qu'on ne peut pas rejouer est une
      affirmation, pas une preuve.***

PUR : aucun réseau. Aucun code exécuté. Lecture seule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #2 — LES COMMITS. *La liste des erreurs que le métier a déjà payées.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
COMMITS_QUI_COMPTENT: dict[str, tuple[str, ...]] = {
    "bug_de_fill": (
        r"fix.{0,25}(fill|queue|match)", r"(double|twice).{0,20}(count|fill)",
        r"fill.{0,20}too\s*(early|often|fast)", r"(over|under).{0,10}estimat.{0,15}fill",
        r"cum_trade_qty", r"qty[_\s]ahead",
    ),
    "bug_de_frais": (
        r"fix.{0,25}(fee|commission|rebate)", r"(wrong|incorrect|missing).{0,15}fee",
        r"maker.{0,10}taker.{0,15}(wrong|swap|invert)", r"forgot.{0,15}fee",
    ),
    "bug_de_lookahead": (
        r"fix.{0,25}(lookahead|look[\s-]ahead|leak|future)", r"data\s*leak",
        r"peek.{0,15}future", r"repaint", r"shift.{0,10}(1|one).{0,10}bar",
    ),
    "bug_de_latence": (
        r"fix.{0,25}latenc", r"(wrong|missing).{0,15}timestamp",
        r"(exchange|local).{0,10}time.{0,15}(wrong|mismatch)", r"clock\s*drift",
    ),
    "bug_de_pnl": (
        r"fix.{0,25}(pnl|p&l|profit)", r"(wrong|incorrect).{0,15}(pnl|equity|balance)",
        r"(sign|side).{0,15}(bug|error|flip|invert)", r"short.{0,15}(pnl|sign).{0,15}wrong",
    ),
    "bug_de_funding": (
        r"fix.{0,25}funding", r"funding.{0,20}(interval|8h|1h|wrong)",
        r"(annualiz|8\s*hour).{0,20}(wrong|fix)",
    ),
    "bug_de_slippage": (
        r"fix.{0,25}(slippage|impact)", r"walk.{0,15}(book|depth)",
        r"(assume|assumed).{0,20}(best|top).{0,10}(price|level)",
    ),
    "aveu_de_regression": (
        r"revert", r"this\s*(was|is)\s*wrong", r"my\s*bad", r"oops",
        r"broke\s*(the|our)", r"regression",
    ),
}


@dataclass(frozen=True, slots=True)
class Commit:
    sha: str
    message: str
    categorie: str
    pourquoi: str

    def as_dict(self) -> dict[str, Any]:
        return {"sha": self.sha[:8], "message": self.message[:160],
                "categorie": self.categorie, "pourquoi": self.pourquoi}


_POURQUOI_COMMIT = {
    "bug_de_fill": "🔑 **Notre fill maker est un chiffre INVENTÉ** (« 10 % du flux »). "
                   "Quelqu'un a déjà payé ce bug — lisons sa facture.",
    "bug_de_frais": "Notre nombre de frais a vécu dans **6 fichiers, 4 valeurs**, dont un "
                    "**2,5 bps inexistant** chez Hyperliquid.",
    "bug_de_lookahead": "**Notre coupe train/test FUYAIT** (ni purge ni embargo, 68 % de fuite).",
    "bug_de_latence": "On confondait la latence du **FLUX** et celle des **ORDRES**.",
    "bug_de_pnl": "**L'APR affiché était le BRUT** : les coûts étaient vérifiés à la porte puis "
                  "jamais soustraits du chiffre.",
    "bug_de_funding": "🔴 **Le piège d'unité** : 8 h vs 1 h → un faux **38 % APR** annoncé.",
    "bug_de_slippage": "**Le carnet spot de PUMP porte 473 $** pour 500 $ voulus. On ne le "
                       "vérifiait pas.",
    "aveu_de_regression": "🔑 *Un auteur qui dit « je me suis trompé » est un auteur qui mesure.*",
}


def fouiller_commits(messages: Sequence[tuple[str, str]]) -> list[Commit]:
    """`[(sha, message)]` → **les bugs que d'autres ont déjà payés.**

    ***Le README raconte l'intention. Le commit raconte la DOULEUR.***
    """
    out: list[Commit] = []
    for sha, msg in messages:
        m = str(msg or "")
        for cat, motifs in COMMITS_QUI_COMPTENT.items():
            if any(re.search(p, m, re.IGNORECASE) for p in motifs):
                out.append(Commit(str(sha or ""), " ".join(m.split()), cat,
                                  _POURQUOI_COMMIT.get(cat, "")))
                break
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #4 — LES ISSUES. *Écrites par les utilisateurs pour se PLAINDRE.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
ISSUES_QUI_COMPTENT: tuple[str, ...] = (
    r"(doesn'?t|does\s*not|didn'?t)\s*(work|match|reproduce)",
    r"(wrong|incorrect|inaccurate|unrealistic)\s*(fill|fee|pnl|result|backtest|latency)",
    r"backtest.{0,30}(differ|diverge|mismatch).{0,20}live",
    r"live.{0,30}(differ|diverge|mismatch).{0,20}backtest",
    r"(over|under)estimat", r"too\s*(optimistic|good\s*to\s*be\s*true)",
    r"lookahead|look[\s-]ahead|data\s*leak",
    r"(lost|losing)\s*money", r"blew\s*up", r"got\s*liquidated",
    r"(can'?t|cannot)\s*reproduce", r"results?\s*(don'?t|do\s*not)\s*match",
)


@dataclass(frozen=True, slots=True)
class Issue:
    numero: int
    titre: str
    extrait: str
    ferme: bool

    def as_dict(self) -> dict[str, Any]:
        return {"numero": self.numero, "titre": self.titre[:140],
                "extrait": self.extrait[:200], "ferme": self.ferme,
                "pourquoi": ("🔑 **Un aveu INVOLONTAIRE.** Le README vend ; l'issue se plaint. "
                             "*Et l'aveu est notre signal le plus fort.*")}


def fouiller_issues(issues: Sequence[dict[str, Any]]) -> list[Issue]:
    """Les issues où **quelqu'un dit que ça ne marche pas**. *Le README ne le dira jamais.*"""
    out: list[Issue] = []
    for it in issues:
        txt = "%s %s" % (it.get("title") or "", it.get("body") or "")
        for m in ISSUES_QUI_COMPTENT:
            x = re.search(m, txt, re.IGNORECASE)
            if x:
                a, b = max(0, x.start() - 60), min(len(txt), x.end() + 90)
                out.append(Issue(int(it.get("number") or 0),
                                 str(it.get("title") or "")[:140],
                                 " ".join(txt[a:b].split()),
                                 str(it.get("state") or "") == "closed"))
                break
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #5 — LES TESTS. *La carte des PEURS de l'auteur.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
PEURS: dict[str, str] = {
    "lookahead": "il a **peur du lookahead** — *et nous, notre coupe train/test FUYAIT*",
    "leak": "idem — la fuite de données",
    "queue": "il a peur de son **modèle de file** — *le nôtre est un chiffre inventé*",
    "fill": "il a peur de son **modèle de fill**",
    "latenc": "il a peur de la **latence** — *on confondait flux et ordres*",
    "fee": "il a peur des **frais** — *les nôtres ont vécu dans 6 fichiers, 4 valeurs*",
    "slippage": "il a peur du **slippage** — *le carnet de PUMP porte 473 $*",
    "impact": "il a peur de l'**impact de marché**",
    "funding": "il a peur du **funding** — *le piège d'unité 8 h vs 1 h*",
    "parity": "🔑 il a peur que **backtest ≠ live** — *le critère qu'on n'a JAMAIS appliqué*",
    "reconcil": "idem — la réconciliation",
    "determin": "il a peur du **non-déterminisme** — *le replay déterministe, on ne l'avait pas*",
    "overfit": "il a peur de l'**overfit** — *nos 7 garde-fous avaient ZÉRO appelant*",
    "liquidat": "il a peur de la **liquidation** — *notre jambe perp est liquidable (X-08)*",
}


def peurs_de_l_auteur(chemins_de_tests: Sequence[str]) -> list[dict[str, str]]:
    """***Les tests sont la carte des peurs de l'auteur. Ses peurs valent mieux que ses promesses.***"""
    out: list[dict[str, str]] = []
    vus: set[str] = set()
    for c in chemins_de_tests:
        bas = str(c).lower()
        for cle, pourquoi in PEURS.items():
            if cle in bas and cle not in vus:
                vus.add(cle)
                out.append({"peur": cle, "fichier": str(c), "pourquoi": pourquoi})
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #6 — LES CONSTANTES. *Du calibrage gratuit, volé à des gens qui l'ont payé.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
CONSTANTES: dict[str, tuple[str, ...]] = {
    "frais": (r"\b(?:TAKER|MAKER)_?FEE\w*\s*[:=]\s*([\d.eE-]+)",
              r"\bfee_?(?:rate|bps)\s*[:=]\s*([\d.eE-]+)",
              r"\bcommission\s*[:=]\s*([\d.eE-]+)"),
    "latence_ms": (r"\bLATENC\w*(?:_MS)?\s*[:=]\s*([\d.eE-]+)",
                   r"\b(?:order|feed|round_?trip)_?latency\w*\s*[:=]\s*([\d.eE-]+)"),
    "spread_bps": (r"\b(?:MIN_)?SPREAD_?BPS\s*[:=]\s*([\d.eE-]+)",
                   r"\bhalf_?spread\s*[:=]\s*([\d.eE-]+)"),
    "kappa": (r"\bkappa\s*[:=]\s*([\d.eE-]+)", r"\bk\s*=\s*([\d.]+)\s*#.*intensit"),
    "slippage_bps": (r"\bslippage\w*\s*[:=]\s*([\d.eE-]+)",),
    "levier": (r"\b(?:MAX_)?LEVERAGE\s*[:=]\s*([\d.eE-]+)",),
    "taux_de_fill": (r"\bfill_?(?:rate|ratio|prob\w*)\s*[:=]\s*([\d.eE-]+)",),
}

# Nos valeurs, pour la comparaison. *On se compare, on ne se contemple pas.*
LES_NOTRES: dict[str, str] = {
    "frais": "perp taker **4,5 bps** / maker **1,5** · spot taker **7,0** / maker **4,0** "
             "(source unique : `fees/hyperliquid_fees.py`)",
    "latence_ms": "**non mesurée** — *et la courbe edge/horizon est PLATE : la latence n'a "
                  "jamais été notre problème*",
    "spread_bps": "**non fixé** — le MM est mort (T1b : 0/29 à 100 % de fill)",
    "kappa": "🔴 **JAMAIS MESURÉ.** *C'est le trou n°1.*",
    "slippage_bps": "**mesuré** : PURR ~69 bps sur 4 jambes · HYPE ~0,02",
    "levier": "**×10** (marge 50 $ → notionnel 500 $)",
    "taux_de_fill": "🔴 **« 10 % du flux » — UN CHIFFRE INVENTÉ.** *Jamais mesuré.*",
}


@dataclass(frozen=True, slots=True)
class Constante:
    genre: str
    valeur: float
    ligne: str
    fichier: str

    def as_dict(self) -> dict[str, Any]:
        return {"genre": self.genre, "valeur": self.valeur,
                "ligne": self.ligne[:120], "fichier": self.fichier,
                "la_notre": LES_NOTRES.get(self.genre, "—")}


def extraire_constantes(fichier: str, source: str) -> list[Constante]:
    """Les nombres que **d'autres ont calibrés**. *On ne les copie pas : on se compare.*"""
    out: list[Constante] = []
    for ligne in (source or "").splitlines():
        if len(ligne) > 300:
            continue
        for genre, motifs in CONSTANTES.items():
            for m in motifs:
                x = re.search(m, ligne, re.IGNORECASE)
                if x:
                    try:
                        v = float(x.group(1))
                    except (IndexError, ValueError):
                        continue
                    out.append(Constante(genre, v, ligne.strip(), fichier))
                    break
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #12 — LA REPRODUCTIBILITÉ. *Un backtest qu'on ne peut pas rejouer est une AFFIRMATION.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
_DONNEES = (".parquet", ".csv", ".feather", ".h5", ".npz", ".arrow", ".jsonl", ".pkl")
_TELECHARGE = ("makefile", "download", "fetch_data", "get_data", "dvc.yaml", "data.py")


@dataclass(frozen=True, slots=True)
class Reproductible:
    a_des_donnees: bool
    a_un_telechargeur: bool
    a_des_tests: bool
    a_un_notebook: bool
    score: float
    verdict: str

    def as_dict(self) -> dict[str, Any]:
        return {"a_des_donnees": self.a_des_donnees,
                "a_un_telechargeur": self.a_un_telechargeur,
                "a_des_tests": self.a_des_tests, "a_un_notebook": self.a_un_notebook,
                "score": self.score, "verdict": self.verdict}


def reproductibilite(chemins: Sequence[str]) -> Reproductible:
    """***Un backtest qu'on ne peut pas rejouer est une affirmation, pas une preuve.***"""
    bas = [str(c).lower() for c in chemins]
    donnees = any(b.endswith(_DONNEES) for b in bas)
    telech = any(any(t in b for t in _TELECHARGE) for b in bas)
    tests = any(("test" in b and b.endswith((".py", ".rs", ".ts"))) for b in bas)
    nb = any(b.endswith(".ipynb") for b in bas)

    s = 40.0 * donnees + 30.0 * telech + 20.0 * tests + 10.0 * nb
    if s >= 60:
        v = ("✅ **Rejouable.** Il joint de quoi refaire ses chiffres. "
             "*C'est rare, et ça vaut cher.*")
    elif s >= 30:
        v = "⚠️ Partiellement rejouable — il faudra reconstruire les données."
    else:
        v = ("🔴 **Non rejouable.** Aucune donnée, aucun téléchargeur. "
             "***Ses chiffres sont une affirmation, pas une preuve.***")
    return Reproductible(donnees, telech, tests, nb, s, v)


__all__ = [
    "COMMITS_QUI_COMPTENT", "CONSTANTES", "ISSUES_QUI_COMPTENT", "LES_NOTRES", "PEURS",
    "Commit", "Constante", "Issue", "Reproductible",
    "extraire_constantes", "fouiller_commits", "fouiller_issues", "peurs_de_l_auteur",
    "reproductibilite",
]
