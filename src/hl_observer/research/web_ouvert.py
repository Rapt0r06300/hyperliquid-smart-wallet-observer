r"""LE WEB OUVERT — *chercher partout, avec ce qui est VRAIMENT accessible et gratuit.*

═══════════════════════════════════════════════════════════════════════════════════════════════
🚩 CE QUE JE DOIS DIRE AVANT TOUT
═══════════════════════════════════════════════════════════════════════════════════════════════

Flo demande **« libre accès à internet et aux recherches »**.

    🔴 ***Il n'existe AUCUN moteur de recherche web gratuit et sans clé.***
       Google et Bing exigent une clé **payante**. Et Flo a dit : *« je ne veux rien de payant. »*

    ***Je ne vais donc pas faire semblant d'avoir un accès web générique.***

Mais pour **notre métier**, il existe mieux qu'un moteur de recherche — et c'est **gratuit,
sans clé, et sans limite déraisonnable** :

  **OpenAlex**          250 M+ travaux académiques, **le graphe de citations complet**, sans clé.
                        🔑 *Il répond à « qui cite ce papier ? » — c'est-à-dire :
                        **quelle idée a survécu au jugement de ses pairs.***
  **Semantic Scholar**  résumés, citations, **et les papiers « influents »** — sans clé.
  **arXiv**             le texte intégral des prépublications. **La source des formules.**
  **Crossref**          les DOI et leurs métadonnées.
  **PyPI / crates.io**  *quelles bibliothèques des gens sérieux ont-ils choisi d'importer ?*
  **Hacker News**       *quelqu'un vient toujours dire pourquoi ça ne marche pas.*
  **StackExchange**     *les réponses y sont **notées et contestées**.*
  **GitHub**            le code.

🎓 **Et les « cours avancés » que Flo veut ?** Ils sont **là** : `"lecture notes" market
microstructure`, `"a course in" algorithmic trading`, et surtout les **revues de littérature**
(*une revue = cent papiers déjà digérés par quelqu'un dont c'est le métier*).

    ***Un moteur de recherche web nous donnerait des blogs. OpenAlex nous donne ce que le
    métier a RETENU.*** C'est mieux, et c'est gratuit.

PUR : ce module **décrit** les sources et **fabrique** les URL. Il n'appelle rien.
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔒 LA POLITESSE — *se faire bannir = MOINS de données, pas plus.*
#    Chaque source a son rythme. On le respecte, et on le documente.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
RYTHMES: dict[str, float] = {
    "openalex": 0.15,          # 100 000/jour avec un e-mail dans l'UA — très généreux
    "semanticscholar": 3.5,    # ~100/5 min sans clé : on est PRUDENT
    "arxiv": 3.2,              # leur doc demande 3 s entre deux appels. On obéit.
    "crossref": 0.3,
    "pypi": 0.5,
    "cratesio": 1.2,
    "hackernews": 1.0,
    "stackexchange": 1.5,
    "github": 2.1,
    "github_code": 6.5,
}

# 🔑 OpenAlex demande **un e-mail dans le User-Agent** pour vous mettre dans le « pool poli »
#    (plus rapide, plus fiable). *On donne ce qu'ils demandent : c'est le prix de la politesse.*
UA = "hypersmart-research (mailto:bermond.florent06@gmail.com)"


@dataclass(frozen=True, slots=True)
class SourceWeb:
    nom: str
    genre: str
    sans_cle: bool
    pourquoi: str
    fiabilite: float

    def as_dict(self) -> dict[str, Any]:
        return {"nom": self.nom, "genre": self.genre, "sans_cle": self.sans_cle,
                "fiabilite": self.fiabilite, "pourquoi": self.pourquoi}


LE_WEB: tuple[SourceWeb, ...] = (
    SourceWeb(
        "openalex", "papier", True,
        "🔑 **250 M+ travaux + LE GRAPHE DE CITATIONS**, sans clé. *Il répond à « qui cite ce "
        "papier ? » — c'est-à-dire : **quelle idée a survécu au jugement de ses pairs**.*",
        1.35),
    SourceWeb(
        "semanticscholar", "papier", True,
        "Résumés + citations + les papiers **influents**. Sans clé (rythme prudent).",
        1.25),
    SourceWeb(
        "arxiv", "papier", True,
        "🔑 **La source des FORMULES.** Le texte intégral. q-fin.TR / q-fin.CP.",
        1.30),
    SourceWeb(
        "crossref", "papier", True,
        "Les DOI et leurs métadonnées — pour résoudre ce que les README citent.",
        1.10),
    SourceWeb(
        "pypi", "biblio", True,
        "*Quelles bibliothèques des gens sérieux ont-ils choisi d'importer ?* "
        "**Une recommandation d'expert, gratuite.**",
        1.00),
    SourceWeb(
        "cratesio", "biblio", True,
        "Idem, côté Rust — *là où vit le vrai HFT.*",
        1.05),
    SourceWeb(
        "hackernews", "forum", True,
        "*Quelqu'un vient **toujours** dire pourquoi ça ne marche pas.*",
        0.90),
    SourceWeb(
        "stackexchange", "forum", True,
        "quant.stackexchange — *les réponses y sont **notées et contestées**. "
        "Un corpus qui se contredit lui-même est un corpus qui se corrige.*",
        1.00),
    SourceWeb(
        "github", "code", True,
        "Le code. *Le README est la page de vente ; le code est la vérité.*",
        1.20),
)

# 🔴 CE QU'ON N'A **PAS** — et on le dit.
INACCESSIBLES: tuple[tuple[str, str], ...] = (
    ("google / bing", "🔴 **Clé PAYANTE obligatoire.** Flo : « je ne veux rien de payant. » "
                      "*Je ne fais pas semblant d'avoir un accès web générique.*"),
    ("X / Twitter", "🔴 **API payante.** Et *le grinder et le sniper sont MORTS et mesurés* — "
                    "X est la source la plus dense au monde en promesses sur ces deux-là."),
    ("YouTube", "🔴 Clé requise. *Et une vidéo ne pose pas de formule qu'on puisse grepper.*"),
    ("Reddit", "⚠️ Bloque désormais les lecteurs anonymes. *On tente, et s'il refuse, "
               "**on le COMPTE au lieu de faire semblant**.*"),
)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LES URL — *fabriquées ici, appelées ailleurs.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
def url_openalex(q: str, *, par_page: int = 50) -> str:
    """Recherche plein texte + résumé. **Trié par nombre de citations** : *ce que le métier a retenu.*"""
    return ("https://api.openalex.org/works?search=%s&per-page=%d"
            "&sort=cited_by_count:desc&mailto=bermond.florent06@gmail.com"
            % (urllib.parse.quote(q), par_page))


def url_openalex_cite_par(id_openalex: str, *, par_page: int = 40) -> str:
    """🔑 **QUI CITE ce papier ?** *Une citation est un choix de chercheur ; une étoile est un clic.*

    C'est le **#10 (citations inverses)** appliqué à la littérature — et là, c'est **gratuit et
    complet**, alors que sur GitHub il faut le reconstruire à la main.
    """
    court = id_openalex.rsplit("/", 1)[-1]
    return ("https://api.openalex.org/works?filter=cites:%s&per-page=%d"
            "&sort=cited_by_count:desc&mailto=bermond.florent06@gmail.com"
            % (urllib.parse.quote(court), par_page))


def url_semanticscholar(q: str, *, limite: int = 40) -> str:
    return ("https://api.semanticscholar.org/graph/v1/paper/search?query=%s&limit=%d"
            "&fields=title,abstract,year,citationCount,externalIds,openAccessPdf"
            % (urllib.parse.quote(q), limite))


def url_arxiv(q: str, *, n: int = 50) -> str:
    return ("http://export.arxiv.org/api/query?search_query=%s&max_results=%d"
            "&sortBy=relevance&sortOrder=descending" % (urllib.parse.quote(q), n))


def url_crossref(q: str, *, n: int = 30) -> str:
    return ("https://api.crossref.org/works?query=%s&rows=%d&mailto=bermond.florent06@gmail.com"
            % (urllib.parse.quote(q), n))


def url_pypi(nom: str) -> str:
    return "https://pypi.org/pypi/%s/json" % urllib.parse.quote(nom)


def url_cratesio(q: str, *, n: int = 30) -> str:
    return "https://crates.io/api/v1/crates?q=%s&per_page=%d" % (urllib.parse.quote(q), n)


def url_hn(q: str, *, n: int = 50) -> str:
    return "https://hn.algolia.com/api/v1/search?query=%s&hitsPerPage=%d" % (
        urllib.parse.quote(q), n)


def url_stackexchange(q: str, *, n: int = 30) -> str:
    return ("https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=votes"
            "&q=%s&site=quant&filter=withbody&pagesize=%d" % (urllib.parse.quote(q), n))


def rapport() -> dict[str, Any]:
    return {
        "sources": [s.as_dict() for s in LE_WEB],
        "inaccessibles": {n: p for n, p in INACCESSIBLES},
        "rythmes_respectes": RYTHMES,
        "franchise": (
            "🔴 **Il n'existe aucun moteur de recherche web gratuit et sans clé.** Google et Bing "
            "sont payants. **Je ne fais pas semblant d'avoir un accès web générique.** "
            "Mais pour notre métier, **OpenAlex** (le graphe de citations complet) donne mieux "
            "qu'un moteur : *un moteur nous donnerait des blogs ; OpenAlex nous donne **ce que le "
            "métier a RETENU**.* Et c'est gratuit."
        ),
        "les_cours_que_flo_veut": (
            "🎓 Ils sont **là** : `\"lecture notes\" market microstructure`, "
            "`\"a course in\" algorithmic trading`, et surtout les **revues de littérature** — "
            "*une revue, c'est cent papiers déjà digérés par quelqu'un dont c'est le métier.*"
        ),
    }


__all__ = [
    "INACCESSIBLES", "LE_WEB", "RYTHMES", "UA", "SourceWeb",
    "rapport", "url_arxiv", "url_cratesio", "url_crossref", "url_hn",
    "url_openalex", "url_openalex_cite_par", "url_pypi", "url_semanticscholar",
    "url_stackexchange",
]
