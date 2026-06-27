# HyperSmart Observer

HyperSmart Observer est un logiciel local de surveillance, d'analyse et de
simulation paper autour de Hyperliquid.

Objectif actuel: reproduire la partie mesurable du "smart wallet observer" en
mode safe:

- observer les donnees publiques Hyperliquid;
- decouvrir des wallets et clusters interessants;
- detecter ouvertures, additions, reductions et fermetures;
- calculer edge, fraicheur, couts et risque;
- refuser ce qui est vieux, incomplet ou non mesurable;
- simuler localement un portefeuille fictif de 1000 USDT;
- expliquer chaque decision dans des logs exportables;
- ne jamais executer d'ordre reel.

Le runtime officiel est **Hyperliquid-first**. Les modules dYdX historiques sont
conserves comme legacy/mockable, mais ils ne doivent pas etre lances par le
launcher principal ni montes dans l'UI Hyperliquid.

---

## Doctrine

```text
OBSERVE FIRST
SCORE SECOND
SIMULATE LOCALLY THIRD
READ ONLY
PAPER ONLY
SIMULATION ONLY
DENY BY DEFAULT
SCORE IS NOT SIGNAL
PAPER TRADE IS NOT ORDER
HISTORICAL PNL IS NOT FUTURE PROFIT
NO GUARANTEED PROFIT
```

HyperSmart peut ouvrir et fermer des **positions virtuelles** en simulation, mais
il ne place jamais d'ordre reel, ne signe rien et ne demande aucune cle.

---

## Regles de securite

Interdit:

- mainnet execution;
- `/exchange` operationnel;
- signature;
- private key, seed phrase, wallet connect;
- bouton buy/sell/trade/execute/copy trade;
- testnet executor actif;
- LLM dans le hot path decisionnel;
- faux PnL ou graphe synthetique presente comme reel;
- promesse de gain.

Autorise:

- scraping public + pool de proxies/rotation (datacenter/residentiel/mobile) pour la collecte a grande echelle (cf. AGENTS.md et V9 §8);
- REST Hyperliquid `/info` read-only;
- WebSocket Hyperliquid read-only;
- imports CSV/JSON/TXT;
- SQLite local runtime;
- paper simulation;
- backtesting/replay;
- dashboard local read-only;
- logs detailles dans `logs/logs a envoyer`.

---

## Architecture 3 jobs

### Job A - Discovery / Leaderboard

- importer ou decouvrir des wallets publics;
- valider uniquement les adresses completes;
- refuser les adresses tronquees;
- scorer historique, consistency, drawdown, one-big-win, pnl concentration,
  copyability, activite recente et qualite d'execution;
- produire une shortlist locale.

### Job B - Copy loop read-only / simulation

- lire la shortlist;
- collecter `allMids`, `l2Book`, `clearinghouseState`, `userFills`,
  `userFillsByTime`, `openOrders`, `frontendOpenOrders`;
- dedupliquer les fills;
- comparer les snapshots precedents et courants;
- produire `LeaderDelta` et `SignalCandidate`;
- calculer `edge_remaining_bps`;
- creer une decision `NO_TRADE` ou une intention paper locale;
- ne jamais appeler `/exchange`.

### Job C - Reports / Dashboard

- afficher le solde fictif, positions virtuelles, decisions recentes, etat scan,
  logs et raisons de refus;
- exporter JSON/CSV/Markdown/HTML quand disponible;
- montrer uniquement des donnees reelles collectees ou un etat vide explicite.

---

## Lanceur principal

Le point d'entree utilisateur est:

```text
LANCER_HYPERSMART.cmd
```

Il lance le serveur local et le poller de simulation en mode visible. Fermer
proprement avec la commande affichee dans la fenetre du lanceur.

URL locale par defaut:

```text
http://127.0.0.1:8794/static/simulation_v2.html
```

La session repart a 1000 USDT fictifs au lancement. Pendant la session, le solde
doit suivre les gains/pertes paper realises et latents issus des positions
virtuelles.

---

## Modules principaux

```text
src/hl_observer/                      # CLI/UI runtime local
hyper_smart_observer/hyperliquid_client/
hyper_smart_observer/copy_mode/
hyper_smart_observer/realtime_monitor/
hyper_smart_observer/market_signals/
hyper_smart_observer/paper_trading/
hyper_smart_observer/backtesting/
hyper_smart_observer/dashboard/
hyper_smart_observer/audit/
```

Legacy preserve:

```text
hyper_smart_observer/dydx_v4/
```

Le legacy dYdX ne doit pas etre importe par le runtime Hyperliquid par defaut.

---

## Fusion des idees GitHub

Les repos externes sont utilises comme sources d'idees, pas comme code a copier.

Classification:

- KEEP: dashboard, logs, health, backtest, scoring, microstructure, exports.
- ADAPT_TO_HYPERLIQUID: WS-first, REST reconcile, adapter/risk layer, wallet
  scoring, source health, feature rows.
- DEFER: microservices lourds, RAG, orchestration multi-venue.
- BAN: ordre reel, CLOB runtime, private key, signature, wallet connect, live
  toggle, executor service, faux PnL, promesse de profit.

Voir:

```text
docs/research/HYPERSMART_GITHUB_FUSION_MASTER.md
docs/research/HYPERSMART_REPO_IDEA_MATRIX_FUSION.md
docs/research/HYPERSMART_GITHUB_RESCAN_CODEX.md
```

---

## Logs a envoyer

Les logs de diagnostic partageables doivent aller ici:

```text
logs/logs a envoyer/
```

Ils doivent expliquer:

- quelle opportunite a ete observee;
- pourquoi le bot a refuse ou accepte en paper;
- quelle donnee etait absente ou trop vieille;
- quel edge et quels couts ont ete calcules;
- comment le PnL paper a evolue.

Ces logs servent a ameliorer le moteur sans inventer de gains.

---

## Commandes utiles

Tests runtime Hyperliquid-only:

```powershell
python -m pytest -q tests/test_hyperliquid_runtime_does_not_import_dydx_by_default.py
python -m pytest -q tests/test_dydx_is_secondary_mockable_not_runtime.py
```

Tests ciblés HyperSmart:

```powershell
python -m pytest -q tests/test_hypersmart_*.py
```

Suite complete:

```powershell
python -m pytest -q
```

CLI locale:

```powershell
python -m hl_observer --help
python -m hl_observer ui
```

---

## Limite importante

Un PnL positif ne peut pas etre garanti. HyperSmart doit chercher a reduire les
mauvaises decisions, mieux filtrer les signaux et expliquer les pertes, mais ne
doit jamais tricher sur le graphe, le solde ou les logs.

Si une donnee manque, le logiciel doit l'afficher comme absente.
Si une action est ambigue, elle doit rester `UNKNOWN`.
Si l'edge est absent ou negatif, la decision doit etre `NO_TRADE`.
