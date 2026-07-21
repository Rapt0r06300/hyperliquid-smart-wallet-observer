r"""CHERCHER **PARTOUT** — *la recherche par topic ne voit qu'un tiers du monde.*

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI LA RECHERCHE ACTUELLE EST AVEUGLE
═══════════════════════════════════════════════════════════════════════════════════════════════

Le moissonneur cherche par **topic** et par **texte libre**. Il rate structurellement :

  🔴 **LES AWESOME-LISTS.** Un seul repo `awesome-quant` contient **200 liens** vers des projets
     dont beaucoup n'ont **aucun topic**. La moisson en a trouvé une… **et n'a jamais suivi ses
     liens.** *On avait la carte au trésor et on l'a classée.*

  🔴 **LES DÉPENDANCES.** Le `requirements.txt` d'un bon repo cite les bibliothèques que ses
     auteurs ont jugées dignes de confiance. ***C'est une recommandation d'expert, gratuite.***

  🔴 **LES PAPIERS.** Un README qui cite `arxiv.org/abs/xxxx` pointe vers la SOURCE de la
     formule. *Le code est une implémentation ; le papier est le raisonnement.*

  🔴 **LES REPOS CITÉS DANS LE TEXTE.** « inspired by X », « port of Y », « based on Z ».
     ***Un auteur qui cite sa source nous donne une source déjà validée par quelqu'un.***

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE CE MODULE FAIT
═══════════════════════════════════════════════════════════════════════════════════════════════

Il transforme **un texte** (README, manifeste) en **nouvelles pistes**. Le moissonneur peut alors
**se propager** : moisson -> lecture -> nouvelles cibles -> re-lecture.

    ***C'est ça, chercher partout : ne pas interroger un index, mais SUIVRE LE FIL.***

PUR : aucun réseau. Aucun code exécuté. Lecture seule.
"""
from __future__ import annotations

import json
import re
from typing import Any
from hl_observer.ops.echec_silencieux import noter as _noter_echec

# `owner/repo` dans une URL GitHub. On refuse les pages qui ne sont pas des repos.
_LIEN_REPO = re.compile(
    r"github\.com/([A-Za-z0-9][\w.-]{0,38})/([\w.-]{1,100})",
    re.IGNORECASE,
)

# Les chemins GitHub qui ne sont PAS des repos. *Deny-by-default : dans le doute, on écarte.*
_PAS_UN_REPO = {
    "features", "topics", "collections", "sponsors", "orgs", "users", "settings",
    "marketplace", "explore", "pricing", "enterprise", "about", "site", "login",
    "apps", "readme", "security", "notifications", "codespaces", "issues", "pulls",
}

_ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.IGNORECASE)
_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)

# *« inspired by », « port of », « based on » : l'auteur nous donne une source qu'il a validée.*
_CITATION = re.compile(
    r"(?:inspired\s+by|port\s+of|based\s+on|fork\s+of|thanks\s+to|credits?\s+to|"
    r"adapted\s+from|reference\s+implementation\s+of)\s*[:\-]?\s*",
    re.IGNORECASE,
)


def liens_de_repos(texte: str, *, exclure: set[str] | None = None) -> list[str]:
    """Tous les `owner/repo` cités dans un texte. **La mine d'or des awesome-lists.**

    *Un `awesome-quant` contient 200 liens vers des projets sans aucun topic.
    Les chercher par topic, c'est les rater — et on les a ratés.*
    """
    vus: list[str] = []
    ex = exclure or set()
    for m in _LIEN_REPO.finditer(texte or ""):
        owner, repo = m.group(1), m.group(2)
        if owner.lower() in _PAS_UN_REPO:
            continue
        repo = re.sub(r"\.git$", "", repo)
        repo = repo.split("#")[0].split("?")[0].rstrip(".,);:'\"")
        if not repo or repo.lower() in _PAS_UN_REPO:
            continue
        nom = "%s/%s" % (owner, repo)
        if nom not in vus and nom not in ex:
            vus.append(nom)
    return vus


def est_une_liste(nom: str, texte: str, *, seuil: int = 25) -> bool:
    """Ce repo est-il une **awesome-list** ? *Alors c'est une carte, pas un territoire.*

    Un repo qui cite 25+ autres repos n'est pas un projet : c'est un **index**.
    Et un index vaut mille recherches par topic.
    """
    if "awesome" in nom.lower() or "awesome" in (texte or "")[:400].lower():
        return True
    return len(liens_de_repos(texte or "")) >= seuil


def papiers(texte: str) -> list[str]:
    """Les papiers cités. *Le code est une implémentation ; le papier est le RAISONNEMENT.*"""
    out: list[str] = []
    for m in _ARXIV.finditer(texte or ""):
        u = "https://arxiv.org/abs/%s" % m.group(1)
        if u not in out:
            out.append(u)
    for m in _DOI.finditer(texte or ""):
        u = "https://doi.org/%s" % m.group(0)
        if u not in out:
            out.append(u)
    return out


def citations(texte: str) -> list[str]:
    """Les repos que l'auteur **cite comme sa source**. *Une source déjà validée par quelqu'un.*"""
    out: list[str] = []
    for m in _CITATION.finditer(texte or ""):
        fin = min(len(texte), m.end() + 160)
        for r in liens_de_repos(texte[m.end():fin]):
            if r not in out:
                out.append(r)
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LES DÉPENDANCES — *une recommandation d'expert, gratuite.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

# Ce qu'on connaît déjà : inutile de le « découvrir ».
_BANALES = {
    "numpy", "pandas", "scipy", "requests", "aiohttp", "websockets", "pytest", "setuptools",
    "wheel", "pip", "typing-extensions", "python-dateutil", "pyyaml", "click", "tqdm",
    "matplotlib", "urllib3", "six", "attrs", "packaging", "certifi", "charset-normalizer",
    "idna", "pydantic", "python-dotenv", "black", "ruff", "mypy", "flake8", "isort",
    "serde", "serde_json", "tokio", "anyhow", "thiserror", "clap", "log", "rand",
}

_PY_DEP = re.compile(r"^\s*([A-Za-z0-9][\w.\-]{1,60})\s*(?:[=<>!~\[]|$)")
_TOML_DEP = re.compile(r'^\s*["\']?([A-Za-z0-9][\w.\-]{1,60})["\']?\s*=', re.MULTILINE)


def dependances(nom_fichier: str, contenu: str) -> list[str]:
    """Les bibliothèques **non banales**. *Ce que des gens sérieux ont choisi d'importer.*

    ***Le `requirements.txt` d'un bon repo est une liste de courses validée par quelqu'un
    qui a fait le travail.***
    """
    f = (nom_fichier or "").lower()
    txt = contenu or ""
    out: list[str] = []

    def _ajouter(x: str) -> None:
        n = x.strip().lower()
        if n and n not in _BANALES and n not in out and not n.startswith(("#", "-", ".")):
            out.append(n)

    if f.endswith(("requirements.txt", "requirements-dev.txt", "constraints.txt")):
        for ligne in txt.splitlines():
            l = ligne.strip()
            if not l or l.startswith(("#", "-r", "--")):
                continue
            m = _PY_DEP.match(l)
            if m:
                _ajouter(m.group(1))

    elif f.endswith("package.json"):
        try:
            d = json.loads(txt)
            for cle in ("dependencies", "devDependencies"):
                for k in (d.get(cle) or {}):
                    _ajouter(str(k))
        except Exception:  # noqa: BLE001
            _noter_echec("hl_observer/research/github_graph.py:169")

    elif f.endswith(("pyproject.toml", "cargo.toml")):
        # on ne lit QUE le bloc [dependencies] / [project.dependencies] -> pas de faux positifs
        bloc = re.split(r"^\[(?:tool\.poetry\.)?dependencies\]|^\[project\]",
                        txt, flags=re.MULTILINE)
        cible = bloc[1] if len(bloc) > 1 else ""
        for m in _TOML_DEP.finditer(cible):
            _ajouter(m.group(1))
        for m in re.finditer(r'"([A-Za-z0-9][\w.\-]{1,60})\s*[><=~]', cible):
            _ajouter(m.group(1))

    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🎯 LES REQUÊTES DÉRIVÉES DE **NOTRE** ARCHITECTURE
#
# Flo : *« le cmd doit connaître l'architecture de notre bot afin de chercher mieux »*.
#
# On ne cherche pas « trading bot ». On cherche **ce qui manque À NOTRE BOT**, nommément.
# Chaque requête vient d'un trou MESURÉ — pas d'un mot à la mode.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
REQUETES_DE_NOS_TROUS: tuple[tuple[str, str], ...] = (
    # (la requête, le trou de NOTRE bot qu'elle vise)
    ('"queue position" "order book" fill probability',
     "notre fill maker est un chiffre INVENTÉ (« 10 % du flux »)"),
    ('"probability of fill" kappa exponential intensity',
     "κ n'a JAMAIS été mesuré chez nous"),
    ('hyperliquid funding rate history basis',
     "le carry est notre SEULE stratégie mesurée positive (PURR +7,09 %)"),
    ('perpetual "funding arbitrage" delta neutral spot',
     "idem — et il faut la jambe SPOT, que le noyau vérifie enfin"),
    ('"market impact" "square root" execution cost model',
     "l'hypothèse qui expliquerait nos −7,97 bps"),
    ('"liquidation cascade" perpetual forced selling',
     "🎯 LA DERNIÈRE PISTE NON MESURÉE — le liquidé ne CHOISIT pas de vendre"),
    ('"lookahead bias" backtest detection purged embargo',
     "notre coupe train/test FUYAIT — 68 % de fuite"),
    ('"walk forward" "deflated sharpe" "probability of backtest overfitting"',
     "7 garde-fous anti-overfit avaient ZÉRO appelant"),
    ('"backtest live" divergence parity reconciliation',
     "le replay ne reproduisait PAS le live — l'un des deux ment"),
    ('"order flow imbalance" VPIN toxicity microprice',
     "notre VPIN a été branché hier, sans AUCUNE validation externe"),
    ('"adverse selection" markout maker post-trade drift',
     "le maker est rempli QUAND IL A TORT — jamais modélisé"),
    ('dex perpetual "orderbook reconstruction" L2 deltas',
     "on lit des snapshots, on ne REJOUE rien"),
    ('awesome quantitative finance list',
     "🔴 une awesome-list = 200 repos SANS TOPIC. On en avait trouvé une… et jamais suivie."),
    ('awesome market making algorithmic trading resources',
     "idem — la carte au trésor, qu'on avait classée"),
    ('"paper trading" ledger reconciliation pnl attribution',
     "notre PnL doit converger dashboard ↔ audit ↔ ledger"),
    ('"fee tier" maker taker rebate exchange comparison',
     "le nombre qui décide de CHAQUE trade vivait dans 6 fichiers, 4 valeurs"),
)


def requetes_ciblees() -> list[dict[str, str]]:
    """Les requêtes **dérivées de nos trous mesurés**. *On ne cherche pas au hasard.*"""
    return [{"requete": q, "pourquoi": p} for q, p in REQUETES_DE_NOS_TROUS]


def nouvelles_pistes(texte: str, *, deja_vus: set[str] | None = None,
                     nom: str = "") -> dict[str, Any]:
    """**Tout ce qu'un texte peut nous ouvrir.** *Ne pas interroger un index : suivre le fil.*"""
    vus = deja_vus or set()
    liens = liens_de_repos(texte, exclure=vus)
    return {
        "est_une_liste": est_une_liste(nom, texte),
        "repos_cites": liens,
        "sources_citees": citations(texte),
        "papiers": papiers(texte),
        "n_nouvelles_pistes": len(liens),
    }


__all__ = [
    "REQUETES_DE_NOS_TROUS",
    "citations", "dependances", "est_une_liste", "liens_de_repos", "nouvelles_pistes",
    "papiers", "requetes_ciblees",
]
