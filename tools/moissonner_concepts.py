#!/usr/bin/env python3
"""MOISSONNEUR v2 — LIRE 494 README SANS EN LIRE UN SEUL (2026-07-12).

LE PROBLEME
-----------
Le moissonneur v1 a retenu 494 repos. Les lire a la main : ~500 heures, et 95 % de bruit.
Ne PAS les lire : on rate peut-etre la piece manquante.

LA SOLUTION
-----------
On telecharge les README et on les GREPPE sur les 13 concepts qui nous manquent REELLEMENT.
Pas des mots a la mode : des trous MESURES dans notre bot.

    L'OEIL N'EST PAS EXHAUSTIF. LE GREP L'EST.

Un repo qui touche 3 concepts ou plus merite une heure humaine. Les autres, non — et on peut
le PROUVER, au lieu de l'esperer.

LES 13 CONCEPTS, ET POURQUOI CHACUN
-----------------------------------
Chaque concept correspond a un echec DOCUMENTE, pas a une intuition.

    file_attente      notre MM suppose « 10 % du flux » : un CHIFFRE INVENTE (tache M-01)
    selection_adverse le maker est rempli quand il a TORT : mesure, jamais modelise
    avellaneda        coter autour d'un prix de reservation, pas du mid (GH-04)
    latence_modele    latence du FLUX vs latence des ORDRES : deux choses differentes
    carnet_rejeu      on lit des snapshots, on ne REJOUE rien (M-02)
    impact_marche     l'hypothese qui expliquerait nos -7,97 bps (M-28)
    funding_carry     la seule piste a structure reelle
    mempool           le flux d'ordres AVANT execution (X-09)
    liquidation       flux FORCE, previsible depuis l'etat public (X-11)
    biais_backtest    150 M de scenarios sans garde-fou branche (G1, M-19)
    validation_oos    8 garde-fous codes, combien branches ? (M-19)
    protections       global_stop / stop_per_pair : on n'a RIEN (GH-01)
    kappa             P(fill | distance au mid) : jamais mesure (M-26)

    python tools/moissonner_concepts.py
    python tools/moissonner_concepts.py --min-concepts 2 --max-repos 200

Entree  : data/reports/github_moisson.json  (produit par MOISSONNER-GITHUB.cmd)
Sortie  : data/reports/github_concepts.json + un tableau trie

LECTURE SEULE. Aucun clone. Aucun code execute. Aucun ordre. JAMAIS.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTREE = ROOT / "data" / "reports" / "github_moisson.json"
SORTIE = ROOT / "data" / "reports" / "github_concepts.json"

# ---------------------------------------------------------------------------------------------
# LES 13 CONCEPTS. Chacun = un trou MESURE dans notre bot, pas un mot a la mode.
# Les motifs sont des regex, insensibles a la casse, EN + FR.
# ---------------------------------------------------------------------------------------------
# ELARGI apres un test sur des README REELS (2026-07-12).
#
# Ma 1re version a RATE les deux tiers de hftbacktest — le repo le plus important de la moisson.
# Elle a vu « queue positions », mais PAS :
#     « latencies »      (mon motif exigeait « latency MODEL »)
#     « Level-3 »        (j'exigeais « L3 data »)
#     « full tick data » (j'exigeais « tick-by-tick »)
#
# UN FILTRE TROP ETROIT RATE EN SILENCE. C'est exactement la pathologie de ce projet.
# Regle : on prefere 10 faux positifs (un humain les ecarte en 10 secondes) a UN faux negatif
# (personne ne saura jamais qu'on est passe a cote).
CONCEPTS: dict[str, tuple[str, ...]] = {
    "file_attente": (
        r"queue\s*posit", r"queue\s*model", r"queue\s*simul", r"order\s*queue", r"\bqueue\b",
        r"fill\s*probab", r"probab\w*\s+of\s+fill", r"fill\s*rate", r"fill\s*model",
        r"fifo", r"time\s*priority", r"price[\s-]*time",
        r"position\s+dans\s+la\s+file",
    ),
    "selection_adverse": (
        r"adverse\s*select", r"toxic", r"informed\s*trad", r"informed\s*flow",
        r"selection\s+adverse", r"glosten", r"milgrom", r"\bvpin\b", r"pin\s*model",
        r"pick(ed)?\s*off", r"stale\s*quote",
    ),
    "avellaneda": (
        r"avellaneda", r"stoikov", r"reservation\s*price", r"inventory\s*skew",
        r"gueant", r"guéant", r"lehalle", r"fernandez[\s-]*tapia",
        r"optimal\s*spread", r"optimal\s*quot", r"inventory\s*risk", r"inventory\s*manag",
        r"stochastic\s*control", r"hamilton[\s-]*jacobi",
    ),
    "latence_modele": (
        r"latenc",                                   # latency / latencies / latence : TOUT
        r"round[\s-]*trip", r"\brtt\b", r"jitter",
        r"network\s*delay", r"propagation\s*delay", r"co[\s-]*locat",
    ),
    "carnet_rejeu": (
        r"order\s*book", r"orderbook", r"\blob\b", r"limit\s*order\s*book",
        r"matching\s*engine", r"book\s*reconstruct", r"book\s*replay", r"depth\s*data",
        r"level[\s-]*[23]", r"\bl[23]\b", r"tick\s*data", r"tick[\s-]*by[\s-]*tick",
        r"market\s*by\s*order", r"\bmbo\b", r"\bmbp\b", r"full\s*depth",
    ),
    "impact_marche": (
        r"market\s*impact", r"price\s*impact", r"impact\s*model", r"impact\s*function",
        r"kyle", r"almgren", r"chriss", r"temporary\s*impact", r"permanent\s*impact",
        r"square[\s-]*root\s*law", r"propagator", r"impact\s+de\s+marche",
        r"slippage\s*model", r"execution\s*cost",
    ),
    "funding_carry": (
        r"funding\s*rate", r"funding\s*arb", r"cash[\s-]*and[\s-]*carry", r"basis\s*trad",
        r"basis\s*spread", r"delta[\s-]*neutral", r"market[\s-]*neutral",
        r"perp\w*[\s-]*spot", r"carry\s*trade", r"contango", r"backwardation",
    ),
    "mempool": (
        r"mempool", r"mem[\s-]*pool", r"pending\s*tx", r"pending\s*transact",
        r"pre[\s-]*trade", r"pre[\s-]*execution", r"front[\s-]*run", r"back[\s-]*run",
        r"sandwich", r"\bmev\b", r"order\s*flow\s*auction", r"private\s*mempool",
        r"priority\s*gas", r"searcher", r"bundle",
    ),
    "liquidation": (
        r"liquidat", r"forced\s*(close|exit|sell)", r"auto[\s-]*deleverag", r"\badl\b",
        r"margin\s*call", r"cascade", r"maintenance\s*margin", r"insurance\s*fund",
        r"bankrupt", r"socializ\w*\s*loss",
    ),
    "biais_backtest": (
        r"look[\s-]*ahead", r"lookahead", r"survivorship", r"data\s*snoop", r"peek",
        r"future\s*(leak|data|info)", r"biais\s+de\s+futur", r"recursive\s*bias",
        r"forward\s*bias", r"repaint", r"leakage", r"in[\s-]*sample\s*bias",
    ),
    "validation_oos": (
        r"walk[\s-]*forward", r"out[\s-]*of[\s-]*sample", r"\boos\b", r"purged", r"embargo",
        r"deflated\s*sharpe", r"reality\s*check", r"overfit", r"cross[\s-]*valid",
        r"combinatorial", r"monte[\s-]*carlo", r"bootstrap", r"holdout", r"hold[\s-]*out",
        r"multiple\s*testing", r"p[\s-]*hack", r"white'?s?\s*test",
    ),
    "protections": (
        r"cooldown", r"cool[\s-]*down", r"drawdown", r"stop\s*loss\s*guard", r"stoploss\s*guard",
        r"circuit\s*breaker", r"kill\s*switch", r"risk\s*guard", r"risk\s*manag",
        r"position\s*limit", r"exposure\s*limit", r"max\s*loss", r"daily\s*loss",
        r"protection", r"safeguard",
    ),
    "kappa": (
        r"\bkappa\b", r"\bκ\b", r"arrival\s*(rate|intensit|process)", r"order\s*arrival",
        r"\bintensit", r"hawkes", r"poisson", r"self[\s-]*excit",
        r"exponential\s*decay", r"queue\s*depletion", r"decay\s*rate",
    ),
}

# Concepts DEJA fermes par une mesure : les signaler, mais NE PAS les compter comme une trouvaille.
CONCEPTS_EN_ZONE_MORTE = {"copy_trading"}

# 🔴 LES BRANCHES ET LES NOMS QU'ON RATAIT.
#    L'ancienne version ne tentait que `README.md` sur `main`/`master`.
#    -> 235 repos perdus EN SILENCE, dont **hftbacktest (4 270 etoiles, notre cible n°1)**,
#       backtrader (22 413), zipline (19 967)... et 19 repos a plus de 1 000 etoiles.
BRANCHES = ("main", "master", "develop", "dev", "trunk")
NOMS_README = (
    "README.md", "readme.md", "Readme.md", "README.MD",
    "README.rst", "readme.rst",
    "README.markdown", "README.txt", "README",
    "docs/README.md", ".github/README.md",
)
PAUSE = 0.35            # raw.githubusercontent est bien plus permissif que l'API search


@dataclass
class Trouvaille:
    nom: str
    url: str
    etoiles: int
    licence: str
    statut_licence: str
    concepts: list[str] = field(default_factory=list)
    extraits: dict[str, str] = field(default_factory=dict)
    erreur: str = ""

    @property
    def score(self) -> int:
        return len(self.concepts)

    def as_dict(self) -> dict:
        return {
            "nom": self.nom, "url": self.url, "etoiles": self.etoiles,
            "licence": self.licence, "statut_licence": self.statut_licence,
            "n_concepts": self.score, "concepts": self.concepts,
            "extraits": self.extraits, "erreur": self.erreur,
        }


def _readme(nom: str) -> str:
    r"""Recupere le README. **Par l'API, qui resout nom + extension + branche.**

    ═══════════════════════════════════════════════════════════════════════════════════════════
    🔴🔴🔴 LE BUG LE PLUS CHER DU MOISSONNEUR — et il a dure 2 jours de plus.
    ═══════════════════════════════════════════════════════════════════════════════════════════

    L'ancienne version ne tentait QUE :

        https://raw.githubusercontent.com/{repo}/{main|master}/**README.md**

    Elle ratait donc, **EN SILENCE** :
        `README.rst` · `README.markdown` · `readme.md` (minuscules) · `docs/README.md`
        · les repos dont la branche par defaut est `dev`, `develop`, `trunk`...

    ***235 repos perdus. Dont :***
        🎯 **nkaz001/hftbacktest** — 4 270 etoiles, **NOTRE CIBLE N°1**
           (c'est le repo dont 20 min de lecture ont donne **5 bugs** dans notre simu)
        · backtrader (22 413 etoiles) · zipline (19 967) · alphalens · catalyst
        · une awesome-list entiere · **19 repos a plus de 1 000 etoiles**

    Et l'erreur etait **avalee** : `return ""` -> comptee comme « README vide », pas comme
    « JE N'AI PAS SU LE LIRE ».

        *Une capacite presente, un chemin non emprunte, personne qui se plaint.*
        **7e occurrence du motif -- cette fois dans MON propre outil.**

    ═══════════════════════════════════════════════════════════════════════════════════════════
    LA REPARATION
    ═══════════════════════════════════════════════════════════════════════════════════════════

    `GET /repos/{owner}/{repo}/readme` **resout tout seul** le nom, l'extension et la branche
    par defaut. C'est **exactement** l'endpoint prevu pour ca -- il existait depuis toujours.

    Repli sur `raw.githubusercontent` seulement si l'API echoue. Et **si les deux echouent,
    on le DIT** (l'appelant compte `README_INTROUVABLE`), on ne fait pas semblant.
    """
    # 1) L'API — elle resout nom + extension + branche. **La bonne porte, enfin.**
    entetes = {
        "User-Agent": "hypersmart-research",
        "Accept": "application/vnd.github.raw+json",   # le contenu BRUT, pas du base64
        "X-GitHub-Api-Version": "2022-11-28",
    }
    jeton = os.environ.get("GITHUB_TOKEN", "").strip()
    if jeton:
        entetes["Authorization"] = "Bearer %s" % jeton

    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/%s/readme" % nom, headers=entetes)
        with urllib.request.urlopen(req, timeout=20.0) as r:
            txt = r.read().decode("utf-8", errors="replace")
            if txt.strip():
                return txt
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            time.sleep(10.0)          # quota : on souffle, puis on tente le repli
    except Exception:  # noqa: BLE001
        pass

    # 2) LE REPLI — plusieurs noms x plusieurs branches. *On ne suppose plus une seule forme.*
    for br in BRANCHES:
        for fichier in NOMS_README:
            try:
                req = urllib.request.Request(
                    "https://raw.githubusercontent.com/%s/%s/%s" % (nom, br, fichier),
                    headers={"User-Agent": "hypersmart-research", "Accept": "text/plain"},
                )
                with urllib.request.urlopen(req, timeout=15.0) as r:
                    txt = r.read().decode("utf-8", errors="replace")
                    if txt.strip():
                        return txt
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 429):
                    time.sleep(5.0)
                continue              # 404 : mauvaise combinaison, on continue
            except Exception:  # noqa: BLE001
                continue

    return ""                         # -> l'appelant marque README_INTROUVABLE. **On l'assume.**


def _analyser(nom: str, texte: str) -> tuple[list[str], dict[str, str]]:
    """Quels concepts ce README touche-t-il ? Avec la PREUVE (l'extrait qui a matche)."""
    bas = texte.lower()
    trouves, extraits = [], {}
    for concept, motifs in CONCEPTS.items():
        for motif in motifs:
            m = re.search(motif, bas)
            if m:
                trouves.append(concept)
                # on garde la phrase autour du match : la PREUVE, pas juste un booleen
                d, f = max(0, m.start() - 70), min(len(texte), m.end() + 70)
                extraits[concept] = " ".join(texte[d:f].split())[:150]
                break
    return trouves, extraits


def main() -> int:
    ap = argparse.ArgumentParser(description="Grepper les README des repos moissonnes.")
    ap.add_argument("--min-concepts", type=int, default=3,
                    help="seuil pour meriter une lecture humaine (defaut 3)")
    ap.add_argument("--max-repos", type=int, default=0, help="0 = tous")
    args = ap.parse_args()

    if not ENTREE.exists():
        print("\n  [!] %s introuvable.\n      Lance d'abord MOISSONNER-GITHUB.cmd\n"
              % ENTREE.relative_to(ROOT))
        return 2

    repos = json.loads(ENTREE.read_text(encoding="utf-8"))
    retenus = [r for r in repos if float(r.get("priorite") or 0) > 0]
    if args.max_repos > 0:
        retenus = retenus[: args.max_repos]

    print("\n" + "=" * 88)
    print("  MOISSONNEUR v2 — grep de %d README sur %d concepts MANQUANTS"
          % (len(retenus), len(CONCEPTS)))
    print("  L'oeil n'est pas exhaustif. Le grep l'est.")
    print("  Duree estimee : ~%.0f min. Lecture seule, aucun clone." % (len(retenus) * PAUSE / 60))
    print("=" * 88 + "\n")

    trouvailles: list[Trouvaille] = []
    for i, r in enumerate(retenus, 1):
        nom = r["nom"]
        t = Trouvaille(nom=nom, url=r["url"], etoiles=int(r.get("etoiles") or 0),
                       licence=str(r.get("licence") or ""),
                       statut_licence=str(r.get("statut_licence") or ""))
        txt = _readme(nom)
        if not txt:
            t.erreur = "README_INTROUVABLE"
        else:
            t.concepts, t.extraits = _analyser(nom, txt)
        trouvailles.append(t)

        if i % 25 == 0 or i == len(retenus):
            forts = sum(1 for x in trouvailles if x.score >= args.min_concepts)
            print("  [%3d/%3d] %d repos a >= %d concepts" % (i, len(retenus), forts, args.min_concepts))
        time.sleep(PAUSE)

    trouvailles.sort(key=lambda x: (-x.score, -x.etoiles))
    forts = [x for x in trouvailles if x.score >= args.min_concepts]

    print("\n" + "-" * 88)
    print("  %d repos analyses — %d meritent une LECTURE HUMAINE (>= %d concepts)"
          % (len(trouvailles), len(forts), args.min_concepts))
    print("-" * 88 + "\n")

    print("  %-40s %6s %-14s %2s  %s" % ("repo", "etoil", "licence", "n", "concepts"))
    print("  " + "-" * 100)
    for t in forts[:50]:
        print("  %-40s %6d %-14s %2d  %s"
              % (t.nom[:40], t.etoiles, t.statut_licence[:14], t.score, ",".join(t.concepts)))

    # --- ce que PERSONNE ne couvre : nos trous les plus rares sont les plus interessants
    print("\n  COUVERTURE PAR CONCEPT (combien de repos en parlent) :")
    compte = {c: 0 for c in CONCEPTS}
    for t in trouvailles:
        for c in t.concepts:
            compte[c] += 1
    for c, n in sorted(compte.items(), key=lambda x: x[1]):
        barre = "#" * min(50, n)
        alerte = "  <-- RARE : peu de monde y touche, c'est peut-etre la que ca se joue" if n <= 3 else ""
        print("    %-18s %4d %s%s" % (c, n, barre, alerte))

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps([t.as_dict() for t in trouvailles], indent=2, ensure_ascii=False),
                      encoding="utf-8")
    print("\n  rapport : %s\n" % SORTIE.relative_to(ROOT))

    print("  " + "-" * 84)
    print("  UN REPO QUI TOUCHE 3 CONCEPTS N'EST PAS UNE IDEE QUI MARCHE.")
    print("  C'est un repo dont on peut PROUVER qu'il merite une heure. Les autres, non.")
    print("  Le jugement reste notre travail — et il se fait par la MESURE.")
    print("  " + "-" * 84 + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Interrompu.\n")
        sys.exit(130)
