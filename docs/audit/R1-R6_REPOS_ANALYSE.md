# R1–R6 — Analyse & classification des repos externes (18/07)

Règle de portage du projet : classer chaque idée `COPY_DIRECT | COPY_ADAPTED | PORT_BEHAVIOR |
INSPIRE_ONLY | SKIP_WITH_REASON | DEFERRED_WITH_PLAN`. **Aucun repo ne bypasse le noyau, le
ledger, ou le no-real-trade.** On ne prétend pas avoir lu un fichier non lu : ci-dessous = verdict
sur la base des READMEs/descriptions (recherche web 18/07) + connaissance des frameworks. Le
deep-read fichier-par-fichier reste à faire sur le repo réel (Windows/clone).

## R1 — stephenpeters/delta_neutral_strategies  → **PORT_BEHAVIOR (benchmark direct)**
Même venue (Hyperliquid), même stratégie (funding delta-neutre spot+perp) + framework de backtest.
C'est **le comparatif direct de NOTRE carry**. À extraire : (a) leur modèle de coûts d'entrée/sortie
(le comparer à notre `COUT_MAKER_2_JAMBES_BPS=11` + base VWAP) ; (b) gèrent-ils le **risque de
liquidation de la jambe perp** (notre A3/M4) et la **finesse du spot** (notre #B) — la plupart des
repos publics les IGNORENT ; (c) leur break-even vs le nôtre (A1 persistance + A5 base). **Garde-fou :
s'ils annoncent un APR sans coûts de 4 jambes ni liquidation, c'est optimiste → ne pas copier le
chiffre, copier seulement ce qui est plus rigoureux que nous.**

## R2 — Jesse  → **INSPIRE_ONLY (moteur de backtest)**
Backtester réputé « zero look-ahead bias », coûts/slippage/**délais d'exécution** réalistes. À
étudier pour durcir **O1 (simulation de latence)** et **F26/J1 (anti-lookahead)**. Ne PAS remplacer
notre backtester (on a déjà `orderbook_execution_simulator`, `execution_delay_model`, `purged_split`,
`feature_store` point-in-time) : s'inspirer de leur design d'exécution, c'est tout.

## R3 — Freqtrade + FreqAI  → **INSPIRE_ONLY (workflow), SKIP l'optim naïve**
`IStrategy`, hyperopt, FreqAI (ML), connecteur HL via CCXT. Inspire nos clusters **F (mesure)** et
**K (modèle)**. ⚠️ Leur hyperopt peut **sur-ajuster** — on garde notre discipline **F27 (deflated
Sharpe / PBO)** + **H1 (porte de survie)** par-dessus toute optimisation. Utile aussi comme
**connecteur de secours** (CCXT→HL) si besoin, mais lecture seule.

## R4 — Hummingbot  → **INSPIRE_ONLY (primitives d'exécution), SKIP la stratégie MM**
Framework de market making (HL sponsor). Miner les **primitives d'exécution** (types d'ordres,
maker/taker, gestion d'inventaire) pour le cluster **L**. **SKIP la stratégie MM elle-même** : notre
MM est mort (0/29, le prix bouge 5-30× le spread — venue non bornée). On prend l'exécution, pas
l'alpha.

## R5 — funding-arb publics (50shadesofgwei, ynhy513, guides « 8-20% APY »)  → **SKIP_WITH_REASON (audit)**
Servent de **repoussoir**, pas de source. Ils **ignorent** ce qu'on a mesuré qui tue le rendement :
spot HL mince (notre #B), risque de liquidation (A3/M4), frais **spot maker** 4 bps (≠ perp 1,5).
Verdict : notre carry est **déjà plus honnête**. Les lire uniquement pour confirmer nos garde-fous,
jamais pour reprendre leurs chiffres.

## R6 — awesome-quant / awesome-systematic-trading  → **DEFERRED_WITH_PLAN (méta-mine ciblée)**
Listes curées. On a **déjà 5617 repos moissonnés** → NE PAS re-moissonner en aveugle. Plan : y
piocher des **libs précises** manquantes pour I-Q (ex. une lib de microstructure ou de backtest
event-driven mieux testée que la nôtre), au coup par coup, avec le même filtre différentiel.

---
**Synthèse honnête** : la vraie valeur externe pour nous = **R1** (benchmarker notre carry) et **R2**
(design de backtest sans lookahead/latence). Le reste confirme surtout des choses qu'on a déjà
tranchées (MM mort, funding-arb optimiste). Aucun repo ne remplace notre noyau ; tout ce qu'on
retient repasse par DecisionEngine → PaperIntent ou NO_TRADE → PaperLedger.
