# Fusion #12 — ent0n29/polybot (+ AWARE)

**Repo:** https://github.com/ent0n29/polybot — "reverse-engineer every polymarket strategy and trade fast"
**Stack:** Java 21 microservices (Spring Boot), ClickHouse + Redpanda (Kafka), Grafana/Prometheus/Alertmanager, Python research toolkit. 609★.
**Venue d'origine:** Polymarket. **Notre cible:** dYdX v4 (paper), Hyperliquid conservé en comparatif.

## Architecture observée (6 services)
- `executor-service` (8080): order execution, **paper sim**, settlement. Mode défaut `hft.mode: PAPER`.
- `strategy-service` (8081): runtime de stratégie + status.
- `analytics-service` (8082): APIs analytiques sur données ClickHouse.
- `ingestor-service` (8083): pipelines d'ingestion market/user-trade.
- `infrastructure-orchestrator-service` (8084): cycle de vie des stacks analytics + monitoring.
- `research/`: snapshot extraction, replication & similarity scoring, backtesting & calibration, execution-quality analysis.

## KEEP (idées d'architecture transférables, venue-agnostic)
1. **Séparation nette ingestion / strategy / analytics / execution(paper) / orchestration.** Mappe directement sur notre `dydx_v4/`: `indexer_rest` + `indexer_ws` (= ingestor), `scoring`+`signals` (= strategy), `backtest`+`dashboard` (= analytics), `paper_trading` (= executor PAPER), un superviseur relançable (= orchestrator).
2. **`hft.mode: PAPER` comme mode par défaut explicite et nommé.** On a déjà le deny-by-default; ajouter un enum de mode runtime nommé (`PAPER` seul autorisé; `LIVE` = stub qui lève) rend l'intention lisible. → cf. notre distinction LIVE/BACKTEST/REPLAY/TEST_FIXTURE.
3. **Endpoints `/actuator/health` par service + `SELECT 1` DB-ping.** Healthchecks granulaires par sous-système. → on a `/healthz`; ajouter un check par source (REST Indexer / WS Indexer / SQLite).
4. **ClickHouse comme magasin analytique colonne pour les trades ingérés.** *Idée* à NOTER: pour le backtest massif, un store colonne accélère les agrégations. → DEFER (SQLite suffit à notre échelle; garder l'idée si volume explose).
5. **`research/` = replication & similarity scoring + execution-quality analysis.** Exactement notre besoin: scorer à quel point notre copie *réplique* le wallet cible (tracking error de copie) et mesurer la *qualité d'exécution* simulée (slippage/latence/dégradation). → ALIMENTE notre `EdgeCalculator` + un futur `copy_fidelity_score`.

## ADAPT_TO_DYDX
- "complete-set arbitrage strategy for Up/Down binaries" (`docs/EXAMPLE_STRATEGY_SPEC.md`): spécifique aux binaires Polymarket → **non applicable** aux perp dYdX. On garde seulement le *patron de spec de stratégie* (un MD par stratégie: hypothèse, signal, filtres, edge attendu, invalidations).
- `POLYMARKET_TARGET_USER` (recherche par wallet cible): mappe sur notre `account/subaccount` cible dYdX (normalisation accounts/subaccounts).

## BAN (jamais dans le runtime)
- `executor-service` mode **LIVE** + `POLYMARKET_PRIVATE_KEY` / `POLYMARKET_API_KEY/SECRET/PASSPHRASE` → clés privées + ordres réels. **Interdit absolu.**
- Market-making runtime (poser des ordres). On peut *modéliser* le maker rebate/queue en paper, jamais poster.
- Toute connexion `/exchange`-équivalent dYdX (signature, dépôt/retrait, wallet connect).

## DEFER (lourd, valeur incertaine à notre échelle)
- Le stack microservices Java + Kafka/Redpanda + ClickHouse + Grafana/Prometheus/Alertmanager. **On ne réécrit pas en Java.** On garde les *concepts* (séparation, healthchecks, métriques) en Python/SQLite. Grafana/Prometheus = DEFER (notre dashboard read-only suffit).

## OR OUBLIÉ (pépites à intégrer en V9)
- **"replication & similarity scoring"**: un score formel mesurant l'écart entre nos paper-trades et les trades réels du wallet copié (decalage temporel, taille relative, prix d'entrée). C'est le chaînon manquant entre "signal détecté" et "edge net": si la copie réplique mal (latence/spread), l'edge s'évapore. → nouveau module `copy_fidelity`.
- **"execution-quality analysis"** comme sous-système de recherche dédié (pas juste un champ): rapports sur slippage réalisé vs attendu, fill ratio, queue position estimée. → alimente la calibration shadow→primary.
- **Orchestrator service** = un superviseur qui gère le *cycle de vie* des autres (start/stop/health). → notre indexer doit être relançable proprement (gap recovery au redémarrage), idée déjà au plan mais le pattern "orchestrator" la formalise.
