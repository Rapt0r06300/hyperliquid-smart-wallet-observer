r"""LA CARTE DES DOMAINES — *tout ce qu'un bot doit savoir, pas seulement comment gagner.*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE FLO A VU, ET QUI EST PLUS GRAVE QU'IL NE LE PENSE
═══════════════════════════════════════════════════════════════════════════════════════════════

    *« 14 sujets, c'est trop peu. »*

Il a raison — mais la vraie faute n'est pas le **nombre**. C'est la **NATURE** :

    ***Mes 14 catégories couvraient le côté ALPHA (comment gagner).
       Elles ne couvraient presque RIEN du côté SURVIE (comment ne pas mourir).***

    **Et c'est la survie qui tue les bots.**

🔴 **LE TROU QUE ÇA M'A FAIT TROUVER DANS NOTRE PROPRE BOT :**

    ***Notre carry a DEUX jambes. Si le spot passe et que le perp ne passe pas — ON EST À NU.***

    C'est le **LEG RISK**. On ne l'a **jamais** cherché, **jamais** mesuré, **jamais** couvert.
    Et un carry à nu, c'est **exactement** le pari directionnel qu'on a mesuré à **−7,97 bps**.

    *Une capacité présente (deux jambes), un chaînon manquant (leur atomicité), personne qui se
    plaint.* **Encore.**

═══════════════════════════════════════════════════════════════════════════════════════════════
LES 5 FAMILLES
═══════════════════════════════════════════════════════════════════════════════════════════════

    🎯 **ALPHA**        comment gagner            (ce qu'on couvrait déjà)
    🛡️ **SURVIE**       comment ne pas mourir     (**presque rien**)
    🔬 **VÉRITÉ**       comment ne pas se mentir  (partiel)
    ⚙️ **MACHINE**      comment ne pas casser     (**rien** — et on a eu des stalls)
    🎲 **ADVERSAIRE**   qui joue contre nous      (**rien**)

PUR : des listes et des motifs. Aucun réseau.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Domaine:
    cle: str
    famille: str
    quoi: str
    pourquoi_nous: str          # 🔑 le trou **CHEZ NOUS**
    sujets: tuple[str, ...]     # topics GitHub
    requetes: tuple[str, ...]   # texte libre / papiers
    motifs: tuple[str, ...]     # pour la laisse et la reconnaissance

    def as_dict(self) -> dict[str, Any]:
        return {"cle": self.cle, "famille": self.famille, "quoi": self.quoi,
                "pourquoi_nous": self.pourquoi_nous, "n_requetes": len(self.requetes)}


ALPHA, SURVIE, VERITE, MACHINE, ADVERSAIRE, MECANIQUE, CODE, QUANT = (
    "🎯 ALPHA", "🛡️ SURVIE", "🔬 VÉRITÉ", "⚙️ MACHINE", "🎲 ADVERSAIRE",
    "🔩 MÉCANIQUE DE L'EXCHANGE", "🧱 NOTRE CODE",
    "🧮 SYSTÈME QUANTITATIF")


DOMAINES: tuple[Domaine, ...] = (
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🛡️ SURVIE — **LA FAMILLE QUI MANQUAIT PRESQUE ENTIÈREMENT.**
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    Domaine(
        "leg_risk", SURVIE,
        "Le **risque de jambe** : une jambe passe, l'autre non → **on est À NU**.",
        "🔴🔴 **LE TROU LE PLUS GRAVE, ET ON NE L'AVAIT JAMAIS CHERCHÉ.** Notre carry a **deux "
        "jambes** (long spot + short perp). Si le spot se remplit et pas le perp, **on détient "
        "du spot À NU** — c'est-à-dire **exactement** le pari directionnel qu'on a mesuré à "
        "**−7,97 bps**. *Et le carnet spot de PUMP ne porte que 473 $ : la jambe qui rate, c'est "
        "précisément celle-là.*",
        ("atomic-swap", "atomic-execution"),
        ('"leg risk" hedge execution', '"legging risk" spread trade',
         '"partial fill" hedge "one leg"', 'atomic execution two legs arbitrage',
         '"execution risk" pairs trade unwind', '"unhedged" exposure "failed leg"',
         '"simultaneous execution" spot perpetual hedge'),
        (r"leg\s*risk", r"legging", r"partial\s*fill", r"atomic\s*execut", r"unhedged",
         r"failed\s*leg", r"one\s*leg"),
    ),
    Domaine(
        "sizing", SURVIE,
        "Le **dimensionnement** : Kelly, Kelly fractionnaire, risk parity, taille optimale.",
        "🔴 **ON N'A JAMAIS TRAITÉ LE SIZING.** On size à **500 $ fixe** (marge 50 × levier 10). "
        "***Le sizing est souvent ce qui décide entre survivre et être ruiné*** — un edge positif "
        "avec un mauvais sizing **ruine quand même**. On n'a **aucune** théorie là-dessus.",
        ("position-sizing", "kelly-criterion", "risk-parity"),
        ('"Kelly criterion" trading position sizing',
         '"fractional Kelly" drawdown optimal',
         '"optimal f" position sizing ruin', '"risk of ruin" trading',
         '"volatility targeting" position size', '"risk parity" allocation',
         'cat:q-fin.PM AND abs:"position sizing"',
         '"bet sizing" machine learning finance'),
        (r"kelly", r"position\s*siz", r"risk\s*of\s*ruin", r"optimal\s*f\b",
         r"volatility\s*target", r"risk\s*parity", r"bet\s*siz"),
    ),
    Domaine(
        "drawdown", SURVIE,
        "Le **contrôle du drawdown** : VaR, CVaR, expected shortfall, stop de portefeuille.",
        "🔴 On a un dossier `risk/` mais **aucune théorie**. Nos garde-fous (`global_stop`, "
        "`stop_per_pair`) sont **posés à la main**. *Et HLP — notre benchmark — affiche un "
        "**drawdown de 70,6 %***. Un APR sans son drawdown est **la moitié d'un chiffre**.",
        ("risk-management", "drawdown", "value-at-risk"),
        ('"maximum drawdown" control strategy', '"expected shortfall" CVaR trading',
         '"drawdown constraint" optimal portfolio', '"stop loss" theory optimal',
         'cat:q-fin.RM AND abs:"drawdown"', '"time under water" recovery'),
        (r"drawdown", r"expected\s*shortfall", r"\bcvar\b", r"value[\s-]at[\s-]risk",
         r"\bvar\b.{0,15}(model|risk)", r"stop[\s-]loss"),
    ),
    Domaine(
        "correlation", SURVIE,
        "La **corrélation de portefeuille** : trois carries **ne sont pas** trois paris "
        "indépendants.",
        "🔴 Le bot ouvre **PURR + HYPE** (et voudrait PUMP). ***Ce sont trois perps sur LA MÊME "
        "venue.*** Si Hyperliquid tousse, **les trois tombent ensemble**. On additionne leurs APR "
        "comme s'ils étaient indépendants. **Ils ne le sont pas.**",
        ("portfolio-optimization", "correlation"),
        ('"correlated positions" portfolio risk crypto',
         '"tail dependence" copula crypto', '"diversification" illusion correlated bets',
         'cat:q-fin.PM AND abs:"correlation"', '"concentration risk" single venue'),
        (r"correlat", r"copula", r"tail\s*depend", r"diversif", r"concentration\s*risk"),
    ),
    Domaine(
        "protocole", SURVIE,
        "Le **risque de protocole** : bug, exploit, pause, gouvernance, oracle manipulé.",
        "🔴 **Notre carry suppose que Hyperliquid FONCTIONNE.** Un exploit, une pause, une "
        "manipulation d'oracle → **les deux jambes sautent en même temps**. *On n'a jamais "
        "chiffré ce risque, ni même listé les précédents.*",
        ("smart-contract-security", "defi-security", "oracle-manipulation"),
        ('perpetual DEX exploit post-mortem', '"oracle manipulation" perpetual liquidation',
         'DeFi protocol hack "post mortem" derivatives',
         '"socialized loss" perpetual exchange', '"auto-deleveraging" ADL risk',
         '"insurance fund" depleted perpetual', 'hyperliquid incident outage'),
        (r"exploit", r"oracle\s*manipulat", r"socializ\w*\s*loss", r"insurance\s*fund",
         r"auto[\s-]deleverag", r"\badl\b", r"post[\s-]?mortem.{0,20}(hack|exploit)"),
    ),
    Domaine(
        "collateral", SURVIE,
        "Le **collatéral** : depeg de stablecoin, haircut, marge croisée vs isolée.",
        "🔴 Notre marge est en **USDC**. *Un depeg de 5 % liquide la jambe perp* — et le carry "
        "« delta-neutre » devient **un pari sur un stablecoin**. Jamais chiffré.",
        ("stablecoin",),
        ('stablecoin depeg risk collateral', '"cross margin" vs "isolated margin" liquidation',
         '"haircut" collateral crypto derivatives', 'USDC depeg March 2023 impact'),
        (r"depeg", r"stablecoin", r"cross\s*margin", r"isolated\s*margin", r"haircut",
         r"collateral"),
    ),
    Domaine(
        "regimes", SURVIE,
        "Les **changements de régime** : ce qui marchait hier peut cesser du jour au lendemain.",
        "🔴 Le funding de PURR est à **+0,29 bps/h**… **dans le régime actuel**. *BERA (−0,83) et "
        "STABLE (−0,99) ont basculé.* ***Un edge mesuré sur 365 jours n'est pas un edge éternel.*** "
        "On n'a **aucune** détection de rupture.",
        ("regime-detection", "hidden-markov-model", "change-point-detection"),
        ('"regime switching" trading strategy',
         '"change point detection" financial time series',
         '"structural break" test time series', '"hidden Markov" market regime',
         '"strategy decay" alpha half-life', '"alpha decay" crowding'),
        (r"regime\s*(switch|change|detect)", r"change[\s-]point", r"structural\s*break",
         r"hidden\s*markov", r"alpha\s*decay", r"strategy\s*decay", r"crowding"),
    ),

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # ⚙️ MACHINE — **RIEN N'ÉTAIT COUVERT. ET ON A EU DES STALLS.**
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    Domaine(
        "flux", MACHINE,
        "La **fiabilité du flux** : WebSocket, reconnexion, gap recovery, heartbeat.",
        "🔴🔴 **ON A EU DES STALLS.** Le flux s'est tu, et le bot a continué à décider sur du "
        "**vieux**. *(`signal_age` était une **tautologie** qui GELAIT quand le flux calait.)* "
        "***Un flux qui se tait est un flux MORT — et un bot qui ne le sait pas est un bot qui "
        "ment.***",
        ("websocket", "market-data", "streaming"),
        ('websocket reconnect "gap recovery" market data',
         '"sequence number" gap detection exchange feed',
         '"heartbeat" stale feed detection trading',
         '"data quality" tick outlier detection', '"clock skew" exchange timestamp',
         '"order book" checksum validation'),
        (r"websocket", r"gap\s*recover", r"heartbeat", r"stale\s*(feed|data|quote)",
         r"sequence\s*number", r"clock\s*(skew|sync|drift)", r"checksum"),
    ),
    Domaine(
        "observabilite", MACHINE,
        "L'**observabilité** : savoir que le bot va mal **AVANT** de perdre.",
        "🔴 On a découvert nos bugs **après coup**, par audit. *Le panneau SÉCURITÉ avait un "
        "voyant vert **SOUDÉ**.* ***Un tableau de bord qui ne peut pas afficher « ça va mal » "
        "est une décoration.***",
        ("observability", "monitoring", "alerting"),
        ('trading system monitoring "kill switch"',
         '"circuit breaker" trading system design',
         '"canary" deployment trading strategy', 'reconciliation "shadow trading"',
         '"pre-trade risk" checks limits'),
        (r"kill\s*switch", r"circuit\s*breaker", r"pre[\s-]trade\s*risk", r"reconcil",
         r"shadow\s*(trad|mode)", r"canary"),
    ),
    Domaine(
        "infra", MACHINE,
        "L'**infrastructure** : latence réseau, RPC, colocation, base de séries temporelles.",
        "On mesure une latence **qu'on ne contrôle pas**. *Et la courbe edge/horizon est **PLATE** "
        "→ la latence n'a jamais été notre problème.* **Mais on ne l'a jamais démontré "
        "proprement** : on l'a supposé.",
        ("low-latency", "timeseries-database"),
        ('"colocation" latency crypto exchange', 'RPC node latency comparison',
         '"time series database" tick storage', 'lock-free ring buffer market data'),
        (r"colocation", r"\brpc\b", r"time\s*series\s*database", r"ring\s*buffer",
         r"lock[\s-]free"),
    ),

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🧮 LE SYSTÈME QUANTITATIF — *la finalité de Flo : un vrai bot QUANTITATIF.*
    #
    #     ***Toutes les familles ci-dessus sont des BRIQUES. Celle-ci est la DISCIPLINE qui les
    #        assemble en un système cohérent — c'est ce qui sépare un « bot de trading » d'un
    #        SYSTÈME QUANTITATIF.***
    #
    #     *Et notre bot est déjà à mi-chemin sans qu'on l'ait nommé : le carry est né d'un
    #      PROCESSUS de falsification (~600 idées → 1). Ce qui manque, c'est le CADRE.*
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    Domaine(
        "recherche_quant", QUANT,
        "🧮 Le **processus de recherche quantitative** : de l'hypothèse au signal, discipliné.",
        "🔑 **C'EST LA FINALITÉ : un vrai bot quantitatif.** *On a testé ~600 idées à la main. "
        "**Un système quant industrialise ça** :* génération d'hypothèses, feature store, "
        "évaluation OOS systématique, journal de recherche. ***Notre carry est né de ce "
        "processus sans qu'on l'ait formalisé — le formaliser, c'est en trouver d'autres.***",
        ("quantitative-finance", "quantitative-trading", "quant", "alpha-research",
         "systematic-trading"),
        ('"systematic trading" research process framework',
         '"alpha research" pipeline feature engineering',
         '"quantitative research" workflow backtest',
         '"feature store" machine learning trading',
         '"research to production" quant trading',
         '"signal research" cross validation alpha',
         'Marcos Lopez de Prado "financial machine learning"',
         '"advances in financial machine learning"',
         '"trading strategy" development lifecycle'),
        (r"systematic\s*trading", r"alpha\s*research", r"quantitative\s*research",
         r"feature\s*store", r"research\s*pipeline", r"signal\s*research",
         r"lopez\s*de\s*prado", r"financial\s*machine\s*learning"),
    ),
    Domaine(
        "combinaison_signaux", QUANT,
        "La **combinaison de signaux** : ensembler plusieurs alphas faibles en un fort.",
        "🔴 On teste chaque idée **isolément** → on jette tout ce qui n'est pas rentable **seul**. "
        "***Mais un système quant COMBINE des signaux faibles** : cinq edges de +2 bps décorrélés "
        "valent mieux qu'un edge de +8 bps.* On n'a **jamais** exploré ça. *(Prudence : "
        "combiner du bruit ne fait que du bruit mieux habillé.)*",
        ("ensemble-learning", "signal-processing"),
        ('"signal combination" alpha blending weights',
         '"ensemble" trading signals meta-labeling',
         '"alpha combination" information coefficient',
         '"meta labeling" Lopez de Prado', '"triple barrier" labeling',
         'weak learners "boosting" financial signals'),
        (r"signal\s*combinat", r"alpha\s*(blend|combin)", r"ensemble.{0,20}(signal|alpha|trad)",
         r"meta[\s-]label", r"triple\s*barrier", r"information\s*coefficient"),
    ),
    Domaine(
        "ml_finance", QUANT,
        "Le **machine learning en finance** — *et ses pièges spécifiques.*",
        "🔴 Le ML en finance **N'EST PAS** le ML normal : *données non-stationnaires, "
        "ratio signal/bruit minuscule, overfit garanti.* On n'a **pas** de ML — **et avant d'en "
        "mettre, il faut savoir POURQUOI 90 % des tentatives échouent.** *Sinon on ajoute une "
        "machine à surajuster à un projet qui a déjà eu 68 % de fuite train/test.*",
        ("machine-learning", "deep-learning", "reinforcement-learning"),
        ('"machine learning" finance overfitting pitfalls',
         '"reinforcement learning" trading "sim to real" gap',
         '"non-stationarity" financial time series ML',
         '"why machine learning" fails trading',
         '"deep learning" limit order book prediction',
         '"feature importance" financial machine learning MDA'),
        (r"machine\s*learning.{0,20}(financ|trad)", r"reinforcement\s*learning.{0,20}trad",
         r"sim[\s-]to[\s-]real", r"non[\s-]stationar", r"feature\s*importance"),
    ),
    Domaine(
        "portfolio_construction", QUANT,
        "La **construction de portefeuille** : de N signaux à M positions, optimisées.",
        "🔴 On ouvre position par position, **sans vue d'ensemble**. *Un système quant construit "
        "un PORTEFEUILLE :* Markowitz, Black-Litterman, HRP, contraintes de risque. **Nos trois "
        "carries sur la même venue devraient être pondérés ENSEMBLE, pas additionnés.**",
        ("portfolio-optimization", "asset-allocation"),
        ('"portfolio construction" mean variance optimization',
         '"hierarchical risk parity" Lopez de Prado',
         '"Black-Litterman" allocation', '"risk budgeting" portfolio',
         '"convex optimization" portfolio constraints cvxpy',
         '"minimum variance" robust portfolio'),
        (r"portfolio\s*(construct|optim)", r"mean[\s-]variance", r"black[\s-]litterman",
         r"hierarchical\s*risk", r"risk\s*budget", r"convex\s*optim"),
    ),
    Domaine(
        "execution_systeme", QUANT,
        "Le **système d'exécution** : OMS, EMS, smart order routing, gestion d'ordres.",
        "🔴 Notre « exécution » est un `PaperIntent`. *Un vrai système quant a un **OMS/EMS** : "
        "cycle de vie des ordres, routage, retries idempotents, réconciliation.* C'est **le "
        "chaînon entre la décision et le marché** — et notre carry a **deux jambes à exécuter "
        "ensemble** (le leg risk !).",
        ("order-management-system",),
        ('"order management system" OMS design trading',
         '"execution management system" EMS architecture',
         '"smart order routing" multi venue',
         '"order lifecycle" state machine trading',
         '"child order" slicing parent execution'),
        (r"order\s*management\s*system", r"\boms\b", r"\bems\b", r"smart\s*order\s*rout",
         r"order\s*lifecycle", r"child\s*order"),
    ),
    Domaine(
        "quant_non_anglophone", QUANT,
        "🌏 Le **quant NON anglophone** — l'énorme angle mort : la communauté chinoise.",
        "🔴 **Tous nos motifs sont en anglais.** *La communauté quant chinoise est immense* "
        "(`vn.py` et son écosystème, `akshare`, `qlib` de Microsoft Research Asia, `hikyuu`) et "
        "**totalement absente de notre corpus**. On a réécrit des choses qu'ils ont bâties et "
        "durcies. ***Un angle mort dont on n'avait même pas conscience.***",
        ("quantitative-finance", "trading-system"),
        ('vnpy quantitative trading framework',
         'qlib microsoft quantitative investment platform',
         'akshare financial data python', 'hikyuu quant framework',
         'wondertrader C++ quantitative', '"高频交易" market making',
         '"量化交易" orderbook strategy', 'chinese crypto quant open source'),
        (r"vnpy", r"\bqlib\b", r"akshare", r"hikyuu", r"wondertrader",
         r"高频|量化|做市"),                       # HFT / quant / market-making en chinois
    ),
    Domaine(
        "plateformes_quant", QUANT,
        "Les **plateformes quant** existantes : les étudier plutôt que réinventer.",
        "🔑 **On a réécrit beaucoup de choses que d'autres ont déjà bâties et durcies.** "
        "*QuantConnect/LEAN, nautilus_trader, vn.py, Freqtrade, Jesse, Hummingbot, backtrader, "
        "zipline…* ***Non pour les copier, mais pour voir ce qu'ils ont prévu et qu'on a "
        "oublié*** — chacun a payé des bugs qu'on n'a pas encore rencontrés.",
        ("algo-trading", "trading-framework", "trading-bot"),
        ('nautilus_trader architecture', 'QuantConnect LEAN engine design',
         'vnpy quantitative framework', 'hummingbot market making connector',
         'freqtrade strategy backtesting', 'jesse trading framework',
         '"open source" quant trading platform comparison',
         'backtrader vs zipline vs backtesting.py'),
        (r"nautilus", r"quantconnect", r"\blean\b.{0,15}engine", r"vnpy", r"hummingbot",
         r"freqtrade", r"\bjesse\b", r"backtrader", r"zipline"),
    ),
    Domaine(
        "gouvernance_quant", QUANT,
        "La **gouvernance** : quand couper une stratégie, comment décider en aveugle.",
        "🔴 On a le carry **maintenant** — *mais quand décide-t-on qu'il est MORT ?* Un système "
        "quant a des **règles de dégommage** (drawdown, décroissance de l'edge), un **comité "
        "de risque** (fût-il une checklist), un **journal de décisions**. *Sinon on tient une "
        "position perdante par attachement — le pire biais du trader.*",
        (),
        ('"strategy retirement" criteria systematic trading',
         '"performance attribution" quant strategy',
         '"kill criteria" trading strategy decay',
         '"paper trading" to "live" promotion gate',
         'trading "research log" journal discipline'),
        (r"strategy\s*retire", r"performance\s*attribut", r"kill\s*criteria",
         r"promotion\s*gate", r"research\s*log"),
    ),

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🧱 NOTRE CODE — *le bot qui exécute la stratégie est lui-même une source de pertes.*
    #
    #     ***On a trouvé 18 fois la même maladie : une capacité présente, un chaînon manquant.***
    #     Ce n'était pas de la malchance : c'était **de l'architecture**.
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    Domaine(
        "architecture", CODE,
        "L'**architecture** : comment on empêche un module d'être **livré et jamais branché**.",
        "🔴🔴 **LA MALADIE DU PROJET, TROUVÉE 18 FOIS** : *une capacité présente, un chaînon "
        "manquant, personne qui se plaint.* **22 modules livrés, 3 branchés.** Le plancher d'edge "
        "à **zéro** dans le chemin live. Les frais par défaut à **0.0**. 7 garde-fous anti-overfit "
        "avec **zéro appelant**. ***Ce n'est pas de la malchance : c'est un défaut d'architecture, "
        "et d'autres l'ont sûrement résolu avant nous.***",
        ("architecture", "software-architecture", "clean-architecture"),
        ('"dead code" detection static analysis python',
         '"unused" function call graph analysis',
         '"hexagonal architecture" trading system',
         '"dependency injection" testability trading',
         '"design by contract" invariants python',
         '"defensive programming" fail fast trading system',
         '"feature flag" dead switch detection'),
        (r"dead\s*code", r"call\s*graph", r"hexagonal\s*architecture",
         r"dependency\s*injection", r"design\s*by\s*contract", r"fail[\s-]fast",
         r"defensive\s*programming"),
    ),
    Domaine(
        "performance", CODE,
        "La **vitesse** : profilage, allocations, hot path, structures de données.",
        "🔴 On n'a **jamais profilé**. *On ne sait même pas où le temps passe.* ***Optimiser sans "
        "profiler, c'est deviner*** — et deviner, c'est exactement ce que ce projet punit. "
        "**Et la latence n'a jamais été notre problème** (la courbe edge/horizon est **PLATE**) — "
        "***donc si on optimise, ce doit être pour une raison MESURÉE, pas par réflexe.***",
        ("performance", "profiling", "optimization"),
        ('python profiling "hot path" trading latency',
         '"zero copy" parsing market data', 'numpy vectorization orderbook',
         '"lock free" queue producer consumer', 'rust vs python trading latency benchmark',
         '"memory allocation" GC pause trading', 'cython numba trading loop',
         '"cache locality" data structure orderbook'),
        (r"profil(ing|er)", r"hot\s*path", r"zero[\s-]copy", r"vectoriz", r"lock[\s-]free",
         r"memory\s*allocation", r"\bgc\s*pause", r"cache\s*localit", r"\bcython\b",
         r"\bnumba\b"),
    ),
    Domaine(
        "qualite_signal", CODE,
        "🔑 **La qualité du SIGNAL lui-même** : fraîcheur, complétude, cohérence, horodatage.",
        "🔴🔴 ***`signal_age` était une TAUTOLOGIE qui GELAIT quand le flux calait*** — le bot "
        "entrait donc sur du **vieux** en croyant que c'était frais. **Le voyant de fraîcheur "
        "était FABRIQUÉ.** *Un signal dont on ne peut pas prouver l'âge n'est pas un signal : "
        "c'est un souvenir.* ***Et un signal parfait vaut plus qu'une stratégie parfaite : une "
        "stratégie juste sur une donnée fausse perd.***",
        ("data-validation",),
        ('"data freshness" staleness detection streaming',
         '"event time" vs "processing time" watermark',
         '"exactly once" deduplication stream processing',
         '"schema validation" market data contract',
         '"clock synchronization" NTP PTP trading timestamp',
         '"out of order" events reordering buffer',
         '"backpressure" stream processing dropped messages'),
        (r"freshness", r"staleness", r"event\s*time", r"processing\s*time", r"watermark",
         r"exactly\s*once", r"backpressure", r"out\s*of\s*order\s*event",
         r"clock\s*sync", r"\bntp\b", r"\bptp\b"),
    ),
    Domaine(
        "tests_qualite", CODE,
        "Les **tests** : mutation testing, property-based, fuzzing, invariants.",
        "🔴 *La couverture dit « **exécuté** », jamais « **vérifié** ».* Notre **mutation testing** "
        "a révélé un score de **62,5 %** — dont un trou sur **le `+` entre deux coûts** de la "
        "formule qui autorise **chaque entrée**. ***Un test qui ne peut pas échouer ne prouve "
        "rien.***",
        ("property-based-testing", "mutation-testing", "fuzzing"),
        ('"mutation testing" python mutmut cosmic-ray',
         '"property based testing" hypothesis financial',
         'fuzzing "order book" state machine',
         '"metamorphic testing" numerical code',
         '"golden master" regression test trading'),
        (r"mutation\s*testing", r"property[\s-]based", r"fuzz", r"metamorphic",
         r"golden\s*master", r"invariant\s*test"),
    ),
    Domaine(
        "numerique", CODE,
        "La **justesse numérique** : flottants, arrondis, unités, précision.",
        "🔴 **LE PIÈGE D'UNITÉ NOUS A COÛTÉ UN FAUX 38 % APR** (8 h vs 1 h). Et *« 150 millions »* "
        "de scénarios en étaient **1 425 000** (facteur **105**). ***Comparer deux nombres qui ne "
        "sont pas dans la même unité FABRIQUE un edge fantôme.*** *(Decimal, lui, a été réfuté : "
        "l'écart valait 2e-15 $.)*",
        (),
        ('"floating point" precision financial calculation',
         '"unit safety" dimensional analysis types',
         '"decimal" vs "float" money representation',
         '"rounding" tick size price precision exchange',
         '"catastrophic cancellation" numerical stability'),
        (r"floating\s*point", r"dimensional\s*analysis", r"unit\s*safety",
         r"catastrophic\s*cancellation", r"rounding\s*error", r"numerical\s*stabilit"),
    ),
    Domaine(
        "etat", CODE,
        "La **gestion d'état** : reprise, idempotence, event sourcing, réconciliation.",
        "🔴 *Le PnL doit venir d'un **ledger d'événements**, pas d'un compteur fragile.* On a eu "
        "des **stalls**, des **orphelins au shutdown**, et un **replay non déterministe** "
        "(*l'invariant le plus fondamental — et on ne l'avait jamais*). ***Un état qu'on ne peut "
        "pas rejouer est un état qu'on ne peut pas auditer.***",
        ("event-sourcing", "state-machine"),
        ('"event sourcing" trading system ledger',
         '"deterministic replay" state machine',
         '"idempotent" order handling exchange',
         '"crash recovery" trading system state',
         '"reconciliation" positions exchange vs local',
         '"write ahead log" durability'),
        (r"event\s*sourcing", r"deterministic\s*replay", r"idempoten", r"crash\s*recover",
         r"reconciliation", r"write[\s-]ahead\s*log", r"\bwal\b"),
    ),
    Domaine(
        "concurrence", CODE,
        "La **concurrence** : async, courses critiques, ordre des événements, deadlocks.",
        "🔴 On a eu un **watchdog qui TUAIT la session** (`os.kill(pid,0)` **EST** un Ctrl-C sous "
        "Windows) et des **orphelins au shutdown**. ***Un bug de concurrence ne se voit pas dans "
        "un test : il se voit à 4 h du matin, à la 8ᵉ heure d'un run.***",
        ("asyncio", "concurrency"),
        ('asyncio pitfalls "race condition" trading',
         '"graceful shutdown" async python signal handling',
         '"happens before" ordering distributed events',
         'deadlock detection async producer consumer',
         '"cancellation" asyncio task leak'),
        (r"race\s*condition", r"deadlock", r"graceful\s*shutdown", r"happens[\s-]before",
         r"task\s*leak", r"cancellation\s*scope"),
    ),

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🔩 LA MÉCANIQUE DE L'EXCHANGE — *les RÈGLES du jeu, pas la stratégie.*
    #
    #     ***On a passé deux jours à découvrir que les FRAIS n'étaient pas ce qu'on croyait,
    #        que le funding était HORAIRE et pas 8-heures, que `BadAloPx` REJETTE au lieu de
    #        passer taker, que le notionnel minimum est de 10 $.***
    #
    #     **CHACUNE de ces découvertes a changé un chiffre qui décidait de chaque trade.**
    #     *Et aucune n'était une « stratégie » : c'était la MÉCANIQUE.*
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    Domaine(
        "mecanique_frais", MECANIQUE,
        "Les **frais**, les **rebates**, les **paliers**, les **remises de staking**.",
        "🔴 **Le nombre qui décide de CHAQUE trade a vécu dans 6 fichiers, avec 4 valeurs "
        "différentes** — dont un **2,5 bps qui n'existe nulle part chez Hyperliquid**. Et le "
        "**spot maker coûte 4,0 bps, pas 1,5** → *T2b avait sa jambe spot chiffrée en PERP : "
        "**−15 % de son edge**.*",
        (),
        ('exchange "fee tier" maker taker rebate comparison',
         '"fee schedule" perpetual dex', '"maker rebate" eligibility volume',
         '"staking discount" trading fees'),
        (r"fee\s*(tier|schedule|rebate)", r"maker\s*rebate", r"staking\s*discount"),
    ),
    Domaine(
        "mecanique_ordres", MECANIQUE,
        "Les **types d'ordres** et leurs **rejets** : post-only, IOC, ALO, reduce-only, TIF.",
        "🔴 **`BadAloPx`** : un post-only qui croiserait est **REJETÉ**, **pas exécuté en taker** — "
        "*on croyait l'inverse, et ça change tout le modèle de coût du maker.* Et le **notionnel "
        "minimum de 10 $** invalidait des tailles qu'on croyait possibles. ***L'exchange a des "
        "RÈGLES ; les ignorer, c'est compter des trades qui n'auraient jamais existé.***",
        (),
        ('"post only" order rejected "would cross"',
         '"time in force" IOC FOK GTC semantics exchange',
         '"reduce only" order semantics perpetual',
         '"minimum notional" order size exchange rules',
         '"tick size" "lot size" rounding rejection',
         '"self trade prevention" STP exchange'),
        (r"post[\s-]only", r"\balo\b", r"\bioc\b", r"\bfok\b", r"reduce[\s-]only",
         r"time\s*in\s*force", r"min\w*\s*notional", r"tick\s*size", r"lot\s*size",
         r"self[\s-]trade\s*prevention"),
    ),
    Domaine(
        "mecanique_marge", MECANIQUE,
        "La **marge** et la **liquidation** : maintenance, prix de liquidation, ADL, "
        "fonds d'assurance.",
        "🔴 **La jambe perp de notre carry est LIQUIDABLE (X-08).** *Et `liquidationPx` était "
        "**REÇU par notre client… puis EFFACÉ** avant d'arriver au moteur.* ***Une capacité "
        "présente, un chaînon manquant.*** Le carry n'est delta-neutre **que tant qu'on tient "
        "les deux jambes**.",
        (),
        ('"maintenance margin" liquidation price formula perpetual',
         '"liquidation price" calculation cross isolated',
         '"auto deleveraging" ADL queue priority',
         '"insurance fund" perpetual exchange mechanics',
         '"partial liquidation" tiered margin'),
        (r"maintenance\s*margin", r"liquidation\s*price", r"auto[\s-]deleverag",
         r"insurance\s*fund", r"partial\s*liquidation", r"margin\s*tier"),
    ),
    Domaine(
        "mecanique_funding", MECANIQUE,
        "Le **mécanisme du funding** : intervalle, plafond, prime d'index, mark vs index.",
        "🔴🔴 **LE PIÈGE D'UNITÉ QUI M'A FAIT ANNONCER UN FAUX 38 % APR.** *Binance/Bybit "
        "publient un taux **8 heures**, Hyperliquid un taux **1 heure**.* J'ai comparé les deux "
        "**sans les normaliser** → un « spread » ×8 **qui n'existait pas**. ***Comparer deux "
        "nombres qui ne sont pas dans la même unité FABRIQUE un edge fantôme.***",
        (),
        ('perpetual "funding rate" mechanism interval cap',
         '"mark price" vs "index price" perpetual',
         '"premium index" funding calculation',
         '"funding interval" 1h 8h normalization', '"impact bid" "impact ask" funding'),
        (r"funding\s*(interval|cap|mechanism)", r"mark\s*price", r"index\s*price",
         r"premium\s*index", r"impact\s*(bid|ask)"),
    ),
    Domaine(
        "mecanique_matching", MECANIQUE,
        "Le **moteur d'appariement** : priorité, batch auctions, séquenceur, ordre des blocs.",
        "🔴 **Hyperliquid est un L1 avec un séquenceur.** *L'ordre dans lequel les transactions "
        "sont exécutées **n'est pas** celui dans lequel on les envoie.* On modélise une file "
        "**prix-temps** classique… **sans avoir vérifié que c'en est une**. ***On suppose les "
        "règles du jeu au lieu de les lire.***",
        ("matching-engine",),
        ('"matching engine" price time priority design',
         '"batch auction" frequent batch trading',
         'sequencer ordering transactions L2 rollup',
         '"pro rata" matching algorithm', 'onchain orderbook consensus ordering'),
        (r"matching\s*engine", r"price[\s-]time\s*priority", r"batch\s*auction",
         r"sequencer", r"pro[\s-]rata"),
    ),
    Domaine(
        "mecanique_api", MECANIQUE,
        "L'**API** : limites de débit, poids des requêtes, WebSocket vs REST, idempotence.",
        "🔴 **On s'est fait couper le flux.** *Et « data-limited » était **AUTO-INFLIGÉ** : "
        "`candleSnapshot(startTime)` était **déjà écrit, déjà autorisé** — on serait passé de "
        "18,9 h à **208 JOURS** de données (×265).* ***On ne lisait pas la doc de notre propre "
        "outil.***",
        (),
        ('exchange API rate limit weight best practices',
         'websocket vs REST market data tradeoff',
         '"idempotency key" order submission', 'exchange API "historical data" endpoints'),
        (r"rate\s*limit", r"request\s*weight", r"idempoten", r"historical\s*data\s*endpoint"),
    ),

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🎲 ADVERSAIRE — **RIEN. Et pourtant on joue contre des gens.**
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    Domaine(
        "adversaire", ADVERSAIRE,
        "**Qui joue contre nous** : les autres bots savent qu'on est là.",
        "🔴 On raisonne comme si le marché était **un décor**. ***Il est peuplé — et par des gens "
        "qui nous voient.*** Notre ordre est **visible** dans le carnet. *Le copy-trading nous a "
        "appris que le leader était **contrarien** : quelqu'un jouait CONTRE lui, et donc contre "
        "nous.*",
        ("game-theory", "adversarial"),
        ('"game theory" market making competition',
         '"predatory trading" front running detection',
         '"order anticipation" HFT strategy', '"quote stuffing" spoofing detection',
         '"latency arbitrage" toxic flow', '"iceberg order" detection',
         'adversarial "market impact" strategic trader'),
        (r"game\s*theor", r"predatory", r"order\s*anticipat", r"spoofing", r"quote\s*stuffing",
         r"iceberg", r"adversarial", r"strategic\s*trader"),
    ),
    Domaine(
        "crowding", ADVERSAIRE,
        "L'**encombrement** : si l'idée est publique, l'edge s'évapore.",
        "🔴 **Le carry HL est une idée PUBLIQUE.** *Si on la trouve sur GitHub, mille autres "
        "l'ont trouvée.* **Le funding de +0,29 bps/h EST le prix que le marché paie pour que "
        "quelqu'un porte ce risque** — et si trop de monde se précipite, **le funding tombe**.",
        (),
        ('"crowded trade" alpha decay', '"capacity" strategy limit AUM',
         '"arbitrage capacity" crypto funding', '"basis compression" crowding'),
        (r"crowd", r"capacity\s*(constraint|limit)", r"basis\s*compression",
         r"alpha\s*decay"),
    ),

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🔬 VÉRITÉ — partiellement couvert, mais il manque **la statistique**.
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    Domaine(
        "statistique", VERITE,
        "La **statistique** : tests multiples, bootstrap, stationnarité, taille d'échantillon.",
        "🔴🔴 **ON A TESTÉ ~600 IDÉES.** *Avec 600 tests à 5 %, on trouve **30 « découvertes » "
        "par pur hasard*.* ***On n'a JAMAIS corrigé pour les tests multiples.*** Notre unique "
        "survivant (le carry) est-il **le vrai** ou **le chanceux** ? **On ne le sait pas.**",
        ("statistics", "hypothesis-testing"),
        ('"multiple testing" correction trading strategies',
         '"family wise error" backtesting', '"false discovery rate" strategy selection',
         '"deflated Sharpe ratio" Bailey', '"probability of backtest overfitting"',
         '"stationarity" test financial time series', 'block bootstrap time series',
         '"minimum track record length"', '"data snooping" White reality check'),
        (r"multiple\s*test", r"family[\s-]wise", r"false\s*discovery", r"deflated\s*sharpe",
         r"data\s*snoop", r"reality\s*check", r"bootstrap", r"stationar",
         r"track\s*record\s*length"),
    ),
    Domaine(
        "donnees", VERITE,
        "La **qualité des données** : trous, ticks aberrants, biais du survivant, ajustements.",
        "🔴 On a mesuré le carry sur **365 j de funding**. *Y a-t-il des trous ? Des coins "
        "**délistés** qu'on ne voit plus ?* **BIAIS DU SURVIVANT : on ne mesure que les coins qui "
        "existent ENCORE.** Ceux qui ont explosé ne sont **pas dans nos données**.",
        ("data-quality",),
        ('"survivorship bias" crypto backtest delisted',
         '"look-ahead bias" data revision', '"point in time" data snapshot',
         'tick data cleaning outlier "bad print"', '"delisted" tokens backtest bias'),
        (r"survivorship", r"delisted", r"point[\s-]in[\s-]time", r"bad\s*print",
         r"outlier.{0,15}(tick|data)", r"data\s*revision"),
    ),

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🎯 ALPHA — ce qu'on couvrait, **plus ce qui sert DIRECTEMENT notre seule piste positive.**
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    Domaine(
        "prediction_funding", ALPHA,
        "🔑 **Prédire le funding** — pas le prix. *Notre seule piste positive en dépend "
        "directement.*",
        "✅ **LE CARRY EST NOTRE UNIQUE SURVIVANT** (PURR +7,09 %). *On le prend en aveugle : on "
        "**LIT** le funding passé.* ***Si on savait quand il monte ou s'inverse, on entrerait "
        "mieux et on sortirait avant BERA/STABLE.*** **C'est le meilleur rapport effort/gain de "
        "toute la liste.**",
        ("funding-rate",),
        ('"funding rate" prediction perpetual model',
         '"basis" mean reversion perpetual futures',
         '"funding rate" term structure', 'perpetual funding "predictable" component',
         '"open interest" funding relationship', 'funding rate seasonality crypto'),
        (r"funding.{0,20}(predict|forecast|model)", r"basis.{0,15}mean\s*revers",
         r"term\s*structure", r"open\s*interest"),
    ),
    Domaine(
        "carnet", ALPHA,
        "Le **carnet**, la **file**, l'**intensité de fill**.",
        "🔴 Notre fill maker est **« 10 % du flux » — UN CHIFFRE INVENTÉ**.",
        ("order-book", "orderbook", "limit-order-book", "matching-engine", "queue-position",
         "market-microstructure"),
        ('"queue position" "order book" fill probability',
         '"probability of fill" kappa exponential intensity',
         'dex perpetual "orderbook reconstruction" L2 deltas',
         'cat:q-fin.TR AND abs:"limit order book"'),
        (r"order\s*book", r"queue", r"fill\s*(prob|intensit)", r"\bkappa\b"),
    ),
    Domaine(
        "market_making", ALPHA,
        "Le **market making** : Avellaneda-Stoikov, GLFT, inventaire.",
        "🔒 **MORT ET MESURÉ** : T1b **0/29** à **100 % de fill**, et **HLP — le MM *payé* par le "
        "protocole — rend −0,01 % APR.** *On ne cherche PAS à le ressusciter : on cherche ce qui "
        "**nous donnerait tort**.*",
        ("market-making", "avellaneda-stoikov"),
        ('cat:q-fin.TR AND abs:"market making"',
         '"market making" profitable retail crypto pnl',
         '"optimal market making" closed form'),
        (r"market\s*mak", r"avellaneda", r"stoikov", r"\bglft\b", r"inventory\s*skew"),
    ),
    Domaine(
        "impact_execution", ALPHA,
        "L'**impact de marché** et l'**exécution optimale**.",
        "🔴 **L'hypothèse qui expliquerait nos −7,97 bps.**",
        ("execution-algorithms", "smart-order-routing", "vwap", "twap", "market-impact"),
        ('"market impact" "square root" execution cost model',
         '"optimal execution" "transaction cost"',
         '"implementation shortfall" algorithm'),
        (r"market\s*impact", r"square[\s-]root\s*law", r"optimal\s*execution", r"almgren"),
    ),
    Domaine(
        "liquidations", ALPHA,
        "🎯 Les **cascades de liquidation** — *le liquidé ne CHOISIT pas de vendre : il est VENDU.*",
        "🎯 **LA DERNIÈRE PISTE NON MESURÉE.** Le seul flux dont le sens est **connu d'avance**.",
        ("liquidation-bot", "liquidations"),
        ('"liquidation cascade" perpetual forced selling',
         '"forced liquidation" price impact crypto',
         '"liquidation" clustering perpetual dex'),
        (r"liquidat", r"cascade", r"forced\s*(sell|liquidat)"),
    ),
    Domaine(
        "mev", ALPHA,
        "Le **MEV** et le **mempool**.",
        "🔒 **MESURÉ ET MORT** : le prix court **CONTRE** le leader **AVANT** son fill (−7,75 bps). "
        "*Voir son ordre plus tôt nous met plus PROFONDÉMENT dans le mouvement adverse.*",
        ("mev", "mempool", "front-running"),
        ('mempool front-run copy trade perp dex', '"order flow auction" MEV',
         '"private mempool" builder'),
        (r"\bmev\b", r"mempool", r"front[\s-]run", r"sandwich"),
    ),
    Domaine(
        "toxicite", ALPHA,
        "La **sélection adverse**, le **VPIN**, le **markout**.",
        "🔴 *Le maker est rempli **quand il a tort**.* Notre VPIN a été branché **hier**, sans "
        "**aucune** validation externe.",
        ("order-flow-imbalance", "orderflow"),
        ('"adverse selection" markout maker post-trade drift',
         '"order flow imbalance" VPIN toxicity microprice',
         '"toxic flow" detection market maker'),
        (r"adverse\s*select", r"\bvpin\b", r"markout", r"toxic"),
    ),
    Domaine(
        "validation", VERITE,
        "Le **lookahead**, l'**overfit**, la **parité backtest/live**.",
        "🔴🔴 **Notre coupe train/test FUYAIT : 68 % de fuite.** *Le test était déjà dans le "
        "train.* Et **7 garde-fous anti-overfit avaient ZÉRO appelant**.",
        ("backtesting", "backtesting-engine", "walk-forward", "overfitting"),
        ('"lookahead bias" backtest detection purged embargo',
         '"walk forward" "deflated sharpe"',
         '"backtest live" divergence parity reconciliation'),
        (r"look[\s-]ahead", r"purged", r"embargo", r"overfit", r"walk[\s-]forward",
         r"parity"),
    ),
    Domaine(
        "carry", ALPHA,
        "Le **carry delta-neutre** et le **basis**.",
        "✅ **NOTRE SEULE PISTE MESURÉE POSITIVE.**",
        ("funding-rate-arbitrage", "basis-trading", "delta-neutral", "cash-and-carry"),
        ('perpetual "funding arbitrage" delta neutral spot',
         'hyperliquid funding rate history basis', '"cash and carry" crypto perpetual'),
        (r"funding\s*(rate|arb)", r"basis\s*trade", r"cash[\s-]and[\s-]carry",
         r"delta[\s-]neutral"),
    ),
    Domaine(
        "venue", ALPHA,
        "**Notre venue** : Hyperliquid, HIP-3, HLP, les perp DEX.",
        "Notre terrain. *HLP — le MM officiel — est **notre benchmark** : il rend **−0,01 % APR**.*",
        ("hyperliquid", "hyperliquid-bot", "perp-dex", "perpetual-futures", "dydx", "gmx"),
        ('hyperliquid market maker', 'hyperliquid node data pipeline',
         'perpetual dex orderbook onchain', 'HIP-3 builder deployed perps'),
        (r"hyperliquid", r"\bhip-?\d\b", r"\bhlp\b", r"perp\w*\s*dex"),
    ),
    Domaine(
        "pedagogie", VERITE,
        "🎓 Les **cours**, les **revues**, les **thèses**.",
        "*Une revue de littérature, c'est **cent papiers déjà digérés** par quelqu'un dont c'est "
        "le métier.* **Le meilleur rapport temps/savoir qui existe.**",
        (),
        ('"lecture notes" "market microstructure"', '"a course in" algorithmic trading',
         '"survey" OR "review" market making', '"PhD thesis" market microstructure',
         '"handbook" of market microstructure', 'cat:q-fin.TR', 'cat:q-fin.CP',
         'cat:q-fin.PM', 'cat:q-fin.RM', 'cat:q-fin.ST'),
        # 🔴 **BUG ATTRAPÉ PAR L'AUDIT.** J'avais mis `tutorial`, `survey`, `review`, `course`
        #    **tout court** → *« React and Redux **tutorial** »* franchissait la laisse.
        #    ***Un motif non ancré n'est pas une laisse : c'est une porte ouverte.***
        #    (Et « review » aurait laissé entrer n'importe quelle *code review*, « course »
        #     n'importe quel *of course*.) -> **tout est ancré dans NOTRE domaine.**
        (r"lecture\s*notes.{0,40}(market|trading|microstructure|finance)",
         r"(survey|review).{0,40}(market\s*mak|microstructure|order\s*book|trading\s*strateg)",
         r"(thesis|dissertation).{0,40}(market|trading|microstructure|finance)",
         r"(handbook|textbook).{0,30}(market|trading|finance|microstructure)",
         r"(course|tutorial).{0,30}(algorithmic\s*trading|market\s*mak|microstructure|quant)"),
    ),
)


def familles() -> dict[str, list[Domaine]]:
    out: dict[str, list[Domaine]] = {}
    for d in DOMAINES:
        out.setdefault(d.famille, []).append(d)
    return out


def tous_les_sujets() -> list[str]:
    v: list[str] = []
    for d in DOMAINES:
        for s in d.sujets:
            if s not in v:
                v.append(s)
    return v


def toutes_les_requetes() -> list[tuple[str, str, str]]:
    """`(requête, domaine, pourquoi NOUS)`. *Une requête sans motif est du bruit.*"""
    return [(q, d.cle, d.pourquoi_nous) for d in DOMAINES for q in d.requetes]


def tous_les_motifs() -> tuple[str, ...]:
    out: list[str] = []
    for d in DOMAINES:
        for m in d.motifs:
            if m not in out:
                out.append(m)
    return tuple(out)


def rapport() -> dict[str, Any]:
    f = familles()
    return {
        "n_domaines": len(DOMAINES),
        "n_requetes": len(toutes_les_requetes()),
        "n_sujets": len(tous_les_sujets()),
        "par_famille": {k: [d.cle for d in v] for k, v in f.items()},
        "le_constat": (
            "🔴 **Les 14 catégories d'avant couvraient le côté ALPHA (comment gagner). Elles ne "
            "couvraient presque RIEN du côté SURVIE (comment ne pas mourir).** "
            "***Et c'est la survie qui tue les bots.***"
        ),
        "le_trou_trouve": (
            "🔴🔴 **En refaisant cette carte, j'ai trouvé un trou dans NOTRE bot : le LEG RISK.** "
            "*Notre carry a **deux jambes**. Si le spot passe et pas le perp — **on est À NU**, "
            "c'est-à-dire exactement le pari directionnel qu'on a mesuré à **−7,97 bps**.* "
            "**Jamais cherché, jamais mesuré, jamais couvert.** Et le carnet spot de PUMP ne porte "
            "que **473 $** : la jambe qui rate, **c'est précisément celle-là**."
        ),
    }


__all__ = ["ADVERSAIRE", "ALPHA", "DOMAINES", "MACHINE", "SURVIE", "VERITE", "Domaine",
           "familles", "rapport", "tous_les_motifs", "tous_les_sujets", "toutes_les_requetes"]
