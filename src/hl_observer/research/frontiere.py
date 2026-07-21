r"""LA FRONTIÈRE — *le moissonneur ne doit jamais être à court de choses à chercher.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LES DEUX INQUIÉTUDES DE FLO, ET LEUR CAUSE COMMUNE
═══════════════════════════════════════════════════════════════════════════════════════════════

  🔴 *« au bout de 10 h il ne saura plus quoi chercher »*
  🔴 *« il y avait plein de termes de recherche avec 0 résultat »*

    ***C'est le MÊME défaut, vu par ses deux bouts.***

Le moissonneur avait une **LISTE** de requêtes. Une liste est **finie** (elle s'épuise) et elle
est **devinée** (mes mots-clés, pas ceux du terrain). D'où les deux symptômes :

    au bout de N heures  -> **plus rien à chercher**
    dès la 1ʳᵉ heure     -> **des requêtes stériles**, parce que je les avais inventées

═══════════════════════════════════════════════════════════════════════════════════════════════
LA RÉPONSE : UNE **FRONTIÈRE**, PAS UNE LISTE
═══════════════════════════════════════════════════════════════════════════════════════════════

    ***Le bon objet n'est pas un scanner avec une liste. C'est un CRAWLER avec une FRONTIÈRE
    qui se nourrit de ce qu'il trouve.***

  un README cite **« Almgren-Chriss »**        -> nouvelle requête
  un papier en **cite un autre**               -> nouvelle requête
  une dépendance s'appelle **`hftbacktest`**   -> nouvelle requête
  une issue mentionne **« GLFT »**             -> nouvelle requête
  un commit dit **« fix kappa estimation »**   -> nouvelle requête

    ***Le corpus génère ses propres requêtes. Il ne peut alors JAMAIS être à court.***

Et les requêtes ne sont plus **devinées** : elles sont **extraites du terrain**. C'est ce qui
tue les « 0 résultat » — *un terme qu'on a lu quelque part existe forcément quelque part.*

═══════════════════════════════════════════════════════════════════════════════════════════════
🚩 CE QUE LA FRONTIÈRE NE FERA PAS
═══════════════════════════════════════════════════════════════════════════════════════════════

Elle ne **dérivera pas** hors sujet. Un crawler sans laisse finit sur des recettes de cuisine.
Chaque terme extrait doit **toucher notre domaine** (`PERTINENCE`) et chaque requête garde
**la trace de sa parentée** (*qui l'a engendrée, et depuis quoi*).

    *Une requête dont on ne peut pas dire d'où elle vient est une requête qu'on ne peut pas juger.*

PUR : aucun réseau. Aucun ordre réel.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LA LAISSE — *un crawler sans laisse finit sur des recettes de cuisine.*
#
# Un terme extrait n'entre dans la frontière QUE s'il touche notre domaine.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔴 **BUG ATTRAPÉ PAR MON PROPRE TEST.** La 1ʳᵉ version contenait `r"impact"` **tout court** —
#    qui matche **« environmental impact »**. Le crawler serait parti sur des recettes de cuisine.
#    Idem pour `margin` (marge commerciale), `cascade`, `execution`, `inventory` (stock d'entrepôt),
#    `intensit` (physique)… ***Un motif trop lâche est une laisse coupée.***
#    -> les termes ambigus sont **ancrés** dans leur contexte métier.
PERTINENCE: tuple[str, ...] = (
    # le carnet
    r"order\s*book", r"orderbook", r"limit\s*order", r"\blob\b", r"micro[\s-]*price",
    r"order\s*flow\s*imbalance", r"book\s*imbalance", r"\bofi\b", r"depth\s*of\s*(the\s*)?book",
    r"level[\s-]*[23]\b", r"tick\s*data", r"market\s*by\s*order",
    # la cotation
    r"market\s*mak", r"\bmaker\b", r"\btaker\b", r"bid[\s-]*ask", r"\bhalf[\s-]*spread\b",
    r"\bquot(e|es|ing)\b", r"reservation\s*price",
    # le fill
    r"queue\s*(posit|model|prior)", r"fill\s*(rate|prob|model|ratio)", r"\bqty[_\s]?ahead\b",
    r"(arrival|fill|order)\s*intensit", r"\bkappa\b",
    # la toxicité
    r"adverse\s*select", r"toxic(ity)?\s*(flow|of)?", r"\bvpin\b", r"markout", r"informed\s*trad",
    # l'impact — 🔴 **ANCRÉ** : `impact` seul matchait « environmental impact »
    r"market\s*impact", r"price\s*impact", r"impact\s*(model|function|cost)",
    r"(temporary|permanent)\s*impact", r"square[\s-]*root\s*law", r"propagator",
    r"slippage", r"(optimal|order)\s*execution", r"execution\s*cost", r"transaction\s*cost",
    r"almgren", r"\bkyle\b.{0,20}(model|lambda)",
    # la théorie
    r"avellaneda", r"stoikov", r"gueant|guéant", r"lehalle", r"\bglft\b",
    r"inventory\s*(risk|skew|penalt|control|constraint)",
    r"stochastic\s*control", r"hamilton[\s-]*jacobi", r"\bhjb\b", r"bellman",
    # le carry
    r"funding\s*(rate|arb|payment)", r"basis\s*(trade|spread|risk)", r"cash[\s-]*and[\s-]*carry",
    r"carry\s*trade", r"contango", r"backwardation", r"perpetual", r"\bperp\b",
    # les liquidations
    r"liquidat", r"liquidation\s*cascade", r"forced\s*(selling|liquidat|close)",
    r"auto[\s-]*deleverag", r"(maintenance|initial)\s*margin", r"margin\s*call",
    # la validation
    r"backtest", r"look[\s-]*ahead", r"overfit", r"walk[\s-]*forward", r"purged",
    r"\bembargo\b.{0,30}(sample|fold|cross)", r"cross[\s-]*valid", r"deflated\s*sharpe",
    r"out[\s-]*of[\s-]*sample",
    # les chiffres
    r"sharpe\s*ratio", r"\bpnl\b", r"\bp&l\b", r"\bbps\b", r"basis\s*points?",
    r"(maker|taker|trading)\s*fee", r"fee\s*(tier|schedule|rebate)",
    # notre terrain
    r"hyperliquid", r"\bdydx\b", r"perp\w*\s*dex", r"\bhft\b", r"high[\s-]*frequency\s*trad",
    r"microstructure", r"algorithmic\s*trad", r"quantitative\s*(finance|trad)",
    r"mempool", r"\bmev\b", r"front[\s-]*run", r"sandwich\s*attack",
)

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔑 ON ÉLARGIT LA LAISSE AVEC **TOUS LES DOMAINES** — survie, mécanique, machine, adversaire.
#
# *Sans ça, la frontière serait aveugle à tout ce qui ne parle pas d'alpha : le **leg risk**,
#  le **sizing**, le **drawdown**, les **régimes**, les **rejets d'ordre**, les **stalls**…*
#
# ***Et c'est la survie qui tue les bots, pas l'absence d'alpha.***
# ═══════════════════════════════════════════════════════════════════════════════════════════════
from hl_observer.research.domaines import tous_les_motifs as _motifs_domaines  # noqa: E402

PERTINENCE = PERTINENCE + tuple(
    m for m in _motifs_domaines() if m not in PERTINENCE
)

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# CE QU'ON EXTRAIT — *des ENTITÉS, pas des mots.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

# Les noms propres du métier : deux majuscules liées par un tiret ou "and".
_AUTEURS = re.compile(
    r"\b([A-Z][a-z]{3,15})[\s-]+(?:and\s+|&\s+|et\s+al\.?\s*)?([A-Z][a-z]{3,15})\b"
)
# Un terme technique en `code` ou **gras** dans un markdown.
_TERME_CODE = re.compile(r"`([A-Za-z][\w .+-]{3,40})`")
# Les acronymes de 3 à 6 lettres (GLFT, VPIN, OFI, HJB, PBO...)
_ACRONYME = re.compile(r"\b([A-Z]{3,6})\b")
# Les identifiants de papiers
_ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I)
_DOI = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", re.I)
# owner/repo
_REPO = re.compile(r"github\.com/([\w.-]{1,39})/([\w.-]{1,100})", re.I)

# Les acronymes qu'on refuse (bruit courant des README)
_ACRO_BRUIT = frozenset("""
API SDK CLI GPU CPU RAM URL HTTP JSON YAML TOML CSV PDF PNG JPG SVG MIT BSD GPL LGPL
AWS GCP TLS SSL SSH FAQ TODO WIP LGTM RFC ISO UTC USD EUR BTC ETH USDT USDC NFT DAO
README LICENSE MAKEFILE DOCKER LINUX MACOS WINDOWS PYTHON RUST NODE NPM PIP
""".split())

# Les mots trop génériques pour faire une requête utile
_MOT_BRUIT = frozenset("""
data model code test main src lib utils config setup install python rust java script
trading trade bot crypto exchange market price order buy sell open close high low
paper authors results method approach section figure table appendix abstract
""".split())

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔴 LES CONCEPTS EN PROSE — *le trou que l'audit a trouvé.*
#
# Un rapport OpenReview écrit : *« the market impact model is unrealistic ; a square root law
# would be more appropriate ; the queue position assumption is not defensible »*.
#     ***Aucun lien. Aucun acronyme. Aucun backtick. -> ZÉRO piste engendrée.***
#
# Il faut donc extraire **les concepts du métier tels qu'ils s'écrivent en prose**.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
_CONCEPTS_PROSE: tuple[str, ...] = (
    r"square[\s-]root\s+law", r"market\s+impact\s+model", r"price\s+impact\s+function",
    r"queue\s+position", r"queue\s+model", r"fill\s+probability", r"fill\s+intensity",
    r"order\s+arrival\s+(rate|intensity|process)", r"adverse\s+selection",
    r"transaction\s+costs?", r"implementation\s+shortfall", r"optimal\s+execution",
    r"limit\s+order\s+book", r"order\s+flow\s+imbalance", r"micro[\s-]?price",
    r"reservation\s+price", r"inventory\s+(risk|penalty|constraint)",
    r"optimal\s+market\s+making", r"stochastic\s+control", r"closed[\s-]form\s+solution",
    r"walk[\s-]forward\s+(validation|analysis)", r"purged\s+cross[\s-]validation",
    r"lookahead\s+bias", r"data\s+leakage", r"in[\s-]sample\s+(bias|result)",
    r"out[\s-]of[\s-]sample\s+(test|result|edge)", r"backtest\s+overfitting",
    r"deflated\s+sharpe", r"funding\s+rate\s+arbitrage", r"basis\s+trade",
    r"cash[\s-]and[\s-]carry", r"delta[\s-]neutral", r"liquidation\s+cascade",
    r"forced\s+liquidation", r"maker[\s-]taker\s+(fee|model|spread)",
    r"toxic\s+(flow|order\s+flow)", r"informed\s+trading", r"realized\s+spread",
    r"effective\s+spread", r"markout", r"tick[\s-]by[\s-]tick", r"volume\s+clock",
    r"latency\s+(model|arbitrage|distribution)", r"matching\s+engine",
    r"queue\s+priority", r"price[\s-]time\s+priority", r"partial\s+fill",
    r"order\s+rejection", r"self[\s-]financing", r"transaction\s+cost\s+analysis",
)
_CONCEPT = re.compile("|".join(_CONCEPTS_PROSE), re.IGNORECASE)

# Un terme technique **candidat** : un mot composé ou capitalisé, pas dans notre vocabulaire.
# *On ne le retient que s'il est ENTOURÉ d'au moins deux concepts qu'on connaît.*
_CANDIDAT_NEUF = re.compile(r"\b[A-Za-z][a-z]{2,}(?:[\s-][A-Za-z][a-z]{2,}){0,2}\b")

# Ce qu'on connaît déjà — inutile de le « découvrir ».
_VOCABULAIRE_CONNU = frozenset("""
market making order book queue position adverse selection transaction cost impact
funding rate basis trade carry delta neutral liquidation cascade lookahead bias
backtest overfitting walk forward cross validation sharpe ratio limit order
microstructure high frequency latency spread maker taker fee slippage execution
the and for with from that this are was were have has been will can not but their
authors paper propose show study using based approach method model results
""".split())


@dataclass(frozen=True, slots=True)
class Piste:
    """Une nouvelle piste. **Elle porte sa PARENTÉ.**

    *Une requête dont on ne peut pas dire d'où elle vient est une requête qu'on ne peut pas juger
    — et c'est exactement comme ça qu'on se retrouve avec des « 0 résultat » inexplicables.*
    """
    requete: str
    genre: str            # "repo" | "code" | "papier" | "biblio"
    venu_de: str          # ce qui l'a engendrée
    parent: str           # QUI l'a engendrée
    poids: float = 1.0

    def cle(self) -> str:
        return "%s|%s" % (self.genre, self.requete.lower())

    def as_dict(self) -> dict[str, Any]:
        return {"requete": self.requete, "genre": self.genre,
                "venu_de": self.venu_de, "parent": self.parent, "poids": self.poids}


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔒 LA PORTE DE DOMAINE — **le garde-fou que l'audit m'a forcé à écrire.**
#
# 🔴 L'audit durci (20 textes hors sujet) a trouvé **9 fuites** :
#
#       « **Race condition** in a video game... **Deadlock** in the render thread »   -> 4 pistes
#       « **Insurance fund** for natural disasters... **collateral** damage »         -> 4 pistes
#       « A survey of image compression... **Rate limiting** on the CDN »             -> 1 piste
#
#    Ces motifs sont **légitimes chez nous** (`deadlock`, `rate limit`, `insurance fund`,
#    `collateral`) — mais ils existent **aussi** dans les jeux vidéo, les CDN et les
#    catastrophes naturelles.
#
#        ***Un terme d'ingénierie ne devient NOTRE terme que s'il est assis dans un contexte
#           de MARCHÉ.***
#
# -> **Aucune extraction si le texte ne parle pas de marchés du tout.** C'est la laisse la plus
#    courte, et la plus fiable : *on ne raffine pas un filtre, on ferme d'abord la porte.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
NOYAU_DOMAINE: tuple[str, ...] = (
    r"\btrading\b", r"\btrader\b", r"\bmarket\b", r"\bexchange\b", r"\border\b", r"\borders\b",
    r"\bprice\b", r"\bprices\b", r"\bpricing\b", r"\bportfolio\b", r"\basset\b", r"\bassets\b",
    r"\bfinanc", r"\bequit(y|ies)\b", r"\bfutures?\b", r"\bperpetual\b", r"\bperp\b",
    r"\bderivative", r"\bhedg", r"\barbitrage\b", r"\balpha\b", r"\bpnl\b", r"\bp&l\b",
    r"\bbps\b", r"\bsharpe\b", r"\bvolatilit", r"\bliquidity\b", r"\bspread\b",
    r"\bbacktest", r"\bstrateg(y|ies)\b.{0,30}\b(trad|market|invest)",
    r"\bcrypto\b", r"\bbitcoin\b", r"\bethereum\b", r"\bdefi\b", r"\bdex\b", r"\bcex\b",
    r"\bhyperliquid\b", r"\bbinance\b", r"\bbybit\b", r"\bdydx\b",
    r"\bfunding\s*rate\b", r"\bbasis\b.{0,20}\b(trade|risk|spread)",
    r"\bmicrostructure\b", r"\bquant(itative)?\b.{0,20}\b(financ|trad)",
    r"\bhft\b", r"\bhigh[\s-]frequency\b", r"\bmaker\b", r"\btaker\b",
)


def dans_notre_domaine(t: str) -> bool:
    """🔒 **La porte.** *Un texte qui ne parle pas de marchés n'a RIEN à nous dire.*

    ***On ne raffine pas un filtre : on ferme d'abord la porte.***
    """
    return any(re.search(m, t or "", re.IGNORECASE) for m in NOYAU_DOMAINE)


def _pertinent(t: str) -> bool:
    return any(re.search(m, t, re.IGNORECASE) for m in PERTINENCE)


def extraire(texte: str, *, parent: str, contexte: int = 90) -> list[Piste]:
    """🔑 **Le corpus génère ses propres requêtes.**

    On n'extrait un terme que si **son voisinage** touche notre domaine.
    *Le mot seul ne suffit pas : « impact » dans une phrase sur l'impact écologique n'est pas
    notre impact.* -> on regarde **autour**.
    """
    t = texte or ""

    # 🔒 LA PORTE DE DOMAINE, EN PREMIER. *Si le texte ne parle pas de marchés, on ne lit rien.*
    #    C'est le garde-fou que l'audit m'a **forcé** à écrire : `deadlock`, `insurance fund` et
    #    `rate limit` sont nos termes — **mais pas dans un jeu vidéo, une catastrophe ou un CDN.**
    if not dans_notre_domaine(t):
        return []

    out: list[Piste] = []
    vus: set[str] = set()

    def _ajouter(p: Piste) -> None:
        if p.cle() not in vus:
            vus.add(p.cle())
            out.append(p)

    def _autour(deb: int, fin: int) -> str:
        return t[max(0, deb - contexte): min(len(t), fin + contexte)]

    # 1) LES PAPIERS CITÉS. *Le code est une implémentation ; le papier est le RAISONNEMENT.*
    for m in _ARXIV.finditer(t):
        _ajouter(Piste("arxiv:%s" % m.group(1), "papier",
                       "cité dans le texte de `%s`" % parent, parent, 2.0))
    for m in _DOI.finditer(t):
        _ajouter(Piste("doi:%s" % m.group(1), "papier",
                       "DOI cité par `%s`" % parent, parent, 1.8))

    # 2) LES REPOS CITÉS. *Une source déjà validée par quelqu'un qui a fait le travail.*
    for m in _REPO.finditer(t):
        nom = "%s/%s" % (m.group(1), re.sub(r"\.git$", "", m.group(2)).split("#")[0])
        _ajouter(Piste(nom, "repo", "cité par `%s`" % parent, parent, 1.5))

    # 3) LES NOMS PROPRES DU MÉTIER. *« Almgren-Chriss » -> une littérature entière.*
    for m in _AUTEURS.finditer(t):
        a, b = m.group(1), m.group(2)
        if a.lower() in _MOT_BRUIT or b.lower() in _MOT_BRUIT:
            continue
        if not _pertinent(_autour(m.start(), m.end())):
            continue
        _ajouter(Piste('"%s %s" market microstructure' % (a, b), "papier",
                       "nom propre lu dans `%s`" % parent, parent, 1.6))

    # 4) LES ACRONYMES. *GLFT, VPIN, OFI, HJB, PBO — chacun ouvre un pan du métier.*
    for m in _ACRONYME.finditer(t):
        a = m.group(1)
        if a in _ACRO_BRUIT:
            continue
        if not _pertinent(_autour(m.start(), m.end())):
            continue
        _ajouter(Piste('"%s" trading microstructure' % a, "papier",
                       "acronyme lu dans `%s`" % parent, parent, 1.2))

    # 5) LES TERMES EN `code`. *Un symbole cité entre backticks est un symbole qui compte.*
    for m in _TERME_CODE.finditer(t):
        s = m.group(1).strip()
        if len(s) < 4 or s.lower() in _MOT_BRUIT or " " in s and len(s.split()) > 3:
            continue
        if not (_pertinent(s) or _pertinent(_autour(m.start(), m.end()))):
            continue
        _ajouter(Piste('"%s"' % s, "code", "symbole lu dans `%s`" % parent, parent, 1.4))

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 6) 🔴🔴 LA PROSE PURE — **LE TROU QUE L'AUDIT A TROUVÉ.**
    #
    #    Les points 1 à 5 cherchent des **liens**, des **noms propres**, des **acronymes** et des
    #    **backticks**. Or un **rapport de relecture OpenReview** — *notre MEILLEURE source
    #    (×1,45)* — est de la **PROSE PURE**. Il n'a rien de tout ça.
    #
    #        ***Résultat mesuré par l'audit : OpenReview et StackExchange engendraient ZÉRO piste.***
    #        **Le texte le plus riche du corpus était INVISIBLE pour la frontière.**
    #
    #    -> on extrait maintenant **les CONCEPTS eux-mêmes** (des n-grammes du métier), et
    #       surtout **le VOISINAGE** : *un mot que je ne connais pas, assis à côté de cinq mots
    #       que je connais, est un mot qu'il faut apprendre.*
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    for m in _CONCEPT.finditer(t):
        s = " ".join(m.group(0).split()).lower()
        if s in _MOT_BRUIT:
            continue
        _ajouter(Piste('"%s"' % s, "papier",
                       "concept lu dans la prose de `%s`" % parent, parent, 1.3))

    # 🔑 LE VOISINAGE — *comment on apprend un mot qu'on ne connaît pas.*
    for m in _CANDIDAT_NEUF.finditer(t):
        s = m.group(0).strip()
        bas = s.lower()
        if len(s) < 6 or bas in _MOT_BRUIT or bas in _VOCABULAIRE_CONNU:
            continue
        autour = _autour(m.start(), m.end())
        # il faut **au moins DEUX** ancres de notre domaine autour : *une seule serait un hasard.*
        ancres = sum(1 for x in PERTINENCE if re.search(x, autour, re.IGNORECASE))
        if ancres >= 2:
            _ajouter(Piste('"%s" trading microstructure' % s, "papier",
                           "🔑 **terme INCONNU** entouré de %d concepts qu'on connaît, dans `%s` "
                           "— *un mot qu'on ne connaît pas, assis à côté de cinq qu'on connaît, "
                           "est un mot qu'il faut apprendre*" % (ancres, parent),
                           parent, 1.5))

    return out


def depuis_dependances(deps: Iterable[str], *, parent: str) -> list[Piste]:
    """*Le `requirements.txt` d'un bon repo est une liste de courses validée par un expert.*"""
    return [
        Piste(d, "biblio", "dépendance de `%s`" % parent, parent, 1.7)
        for d in deps if len(d) > 2
    ]


def depuis_commits(messages: Iterable[str], *, parent: str) -> list[Piste]:
    """Un commit `fix kappa estimation` **nomme** un problème que quelqu'un a **résolu**."""
    out: list[Piste] = []
    for m in messages:
        for x in re.finditer(r"fix\w*[:\s]+([a-z][\w\s-]{6,45})", str(m or ""), re.I):
            s = " ".join(x.group(1).split())
            if _pertinent(s):
                out.append(Piste('"%s"' % s, "code",
                                 "un commit de `%s` corrige ça" % parent, parent, 1.9))
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LA FRONTIÈRE — *elle ne se vide jamais.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
@dataclass
class Frontiere:
    """La file des choses à explorer. **Elle grandit en même temps qu'on la vide.**

    🔒 **Anti-dérive** : une piste ne peut pas engendrer une piste qui engendre une piste…
    à l'infini. `PROFONDEUR_MAX` borne la descendance. *Un crawler sans laisse dérive.*
    """
    PROFONDEUR_MAX: int = 3

    a_faire: list[Piste] = field(default_factory=list)
    vues: set[str] = field(default_factory=set)
    profondeur: dict[str, int] = field(default_factory=dict)
    steriles: dict[str, int] = field(default_factory=dict)     # requête -> nb de fois sans résultat
    fecondes: dict[str, int] = field(default_factory=dict)

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🔑 CE QUI NOUS MANQUE — *le principe DIFFÉRENTIEL, appliqué à la frontière elle-même.*
    #
    # 🔴 **L'AUDIT A CHANGÉ LA QUESTION.** Avec b = 31,5, la frontière est **effectivement
    #    infinie** : en 12 h on explorera ~27 000 pistes sur ~280 000 engendrées.
    #
    #        ***Le problème n'est donc plus « va-t-il être à court ? ».
    #           C'est « explorera-t-il les BONNES ? ».***
    #
    # -> **L'ORDRE devient tout.** Une piste qui touche un concept **qu'on N'A PAS** doit passer
    #    devant une piste qui redit ce qu'on sait déjà.
    #    *Un repo qui a 12 concepts dont on en a 11 vaut UNE idée. Le même principe, ici.*
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    nous_manque: tuple[str, ...] = ()
    BONUS_MANQUE: float = 2.5

    def priorite(self, p: Piste) -> float:
        """*Ce qu'on n'a pas passe devant ce qu'on a déjà.*"""
        s = float(p.poids)
        if self.nous_manque:
            q = p.requete.lower()
            if any(m.replace("_", " ") in q or m in q for m in self.nous_manque):
                s *= self.BONUS_MANQUE
        # les pistes **peu profondes** d'abord : *plus on s'éloigne de la source, plus on dérive.*
        s /= (1.0 + 0.35 * self.profondeur.get(p.cle(), 0))
        return s

    def semer(self, pistes: Sequence[Piste], *, profondeur: int = 0) -> int:
        """Ajoute ce qui est **neuf**. Renvoie combien. *Ce qui est déjà vu ne se re-cherche pas.*"""
        n = 0
        for p in pistes:
            if profondeur > self.PROFONDEUR_MAX:
                continue
            c = p.cle()
            if c in self.vues:
                continue
            self.vues.add(c)
            self.profondeur[c] = profondeur
            self.a_faire.append(p)
            n += 1
        # 🔑 le tri se fait sur la **PRIORITÉ**, pas sur le poids brut :
        #    *ce qui nous MANQUE passe devant ce qu'on a déjà.*
        self.a_faire.sort(key=lambda x: -self.priorite(x))
        return n

    def prochaine(self) -> Piste | None:
        """`None` **seulement** si la frontière est vraiment vide. *Et elle l'est rarement.*"""
        return self.a_faire.pop(0) if self.a_faire else None

    def noter(self, p: Piste, n_trouves: int) -> None:
        """🔑 **On COMPTE les stériles.** *Flo : « plein de termes avec 0 résultat ».*

        On ne les cache pas : on les **publie**, pour savoir **lesquels** de mes mots-clés
        devinés étaient du vent — *et ne plus les deviner.*
        """
        if n_trouves > 0:
            self.fecondes[p.requete] = self.fecondes.get(p.requete, 0) + n_trouves
        else:
            self.steriles[p.requete] = self.steriles.get(p.requete, 0) + 1

    def profondeur_de(self, p: Piste) -> int:
        return self.profondeur.get(p.cle(), 0)

    def reste(self) -> int:
        return len(self.a_faire)

    def as_dict(self) -> dict[str, Any]:
        st = sorted(self.steriles.items(), key=lambda x: -x[1])
        fe = sorted(self.fecondes.items(), key=lambda x: -x[1])
        return {
            "reste_a_explorer": len(self.a_faire),
            "deja_explorees": len(self.vues) - len(self.a_faire),
            "requetes_FECONDES": [{"requete": q, "trouves": n} for q, n in fe[:25]],
            "requetes_STERILES": [{"requete": q, "essais": n} for q, n in st[:40]],
            "n_steriles": len(self.steriles),
            "pourquoi_les_steriles": (
                "🔴 **Ces requêtes n'ont RIEN rendu — et je les publie au lieu de les cacher.** "
                "*Ce sont, pour la plupart, des mots-clés que **j'avais devinés**.* "
                "C'est exactement la raison d'être de la frontière : **les requêtes ne doivent "
                "plus être devinées, elles doivent être EXTRAITES du terrain.** "
                "*Un terme qu'on a lu quelque part existe forcément quelque part.*"
            ),
            "pourquoi_ca_ne_se_vide_pas": (
                "🔑 **Le corpus génère ses propres requêtes** : un README cite Almgren-Chriss, "
                "un papier en cite un autre, une dépendance s'appelle `hftbacktest`… "
                "***Un crawler avec une frontière ne peut pas être à court.*** "
                "(Borne : profondeur %d — *un crawler sans laisse dérive.*)" % self.PROFONDEUR_MAX
            ),
        }


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🎓 LE FOND DE ROULEMENT — *il ne doit JAMAIS rester sans rien faire.*
#
# Si (et seulement si) la frontière se vide **vraiment**, on retombe là-dessus : la littérature
# de fond, celle qu'on devrait avoir lue et qu'on n'a pas lue.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
FOND_DE_ROULEMENT: tuple[tuple[str, str, str], ...] = (
    ("papier", "cat:q-fin.TR", "toute la littérature « Trading & Market Microstructure » d'arXiv"),
    ("papier", "cat:q-fin.CP", "« Computational Finance » — les méthodes numériques"),
    ("papier", "cat:q-fin.PM", "« Portfolio Management » — le dimensionnement, qu'on n'a jamais traité"),
    ("papier", "cat:q-fin.RM", "« Risk Management » — nos garde-fous n'ont aucune base théorique"),
    ("papier", '"optimal market making"', "le cadre dont le grinder était une intuition floue"),
    ("papier", '"optimal execution" "transaction cost"', "l'edge net après coûts — notre seul juge"),
    ("papier", '"limit order book" "queue"', "le fill qu'on n'a jamais modélisé"),
    ("papier", '"perpetual futures" funding', "le carry — notre seule piste positive"),
    ("papier", '"crypto market microstructure"', "notre terrain, vu par des chercheurs"),
    ("papier", '"lecture notes" "market microstructure"',
     "🎓 **les cours** — *Flo : « des cours avancés sur les bots »*"),
    ("papier", '"a course in" "algorithmic trading"', "🎓 idem"),
    ("papier", '"survey" OR "review" market making', "🎓 une revue = 100 papiers digérés"),
    ("papier", '"stochastic control" "high frequency"', "le cadre d'optimisation qu'on n'a pas"),
    ("papier", '"adverse selection" "limit order"', "le maker est rempli quand il a TORT"),
    ("papier", '"market impact" "square root law"', "l'hypothèse qui expliquerait nos −7,97 bps"),
    ("papier", '"backtest overfitting"', "nos 1 425 000 scénarios : combien d'overfit ?"),
    ("biblio", "hftbacktest", "**LE** repo qui nous a donné 5 bugs — ses dépendants ?"),
    ("biblio", "nautilus_trader", "un moteur d'exécution sérieux"),
    ("biblio", "ccxt", "l'accès multi-venue"),
    ("code", '"order_book" "imbalance"', "l'OFI, qu'on vient de brancher sans validation"),
)


def fond_de_roulement() -> list[Piste]:
    """🎓 *Il ne doit jamais rester sans chercher.* **La littérature qu'on aurait dû lire.**

    Ce n'est **pas** du remplissage : ce sont les **catégories entières** d'arXiv qui couvrent
    notre métier. *Un moissonneur qui a fini son plan et qui n'a pas lu q-fin.TR n'a rien fini.*
    """
    return [Piste(q, g, "fond de roulement — %s" % p, "FOND", 0.5)
            for g, q, p in FOND_DE_ROULEMENT]


__all__ = [
    "FOND_DE_ROULEMENT", "PERTINENCE",
    "Frontiere", "Piste",
    "depuis_commits", "depuis_dependances", "extraire", "fond_de_roulement",
]
