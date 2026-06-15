# CODEX OBJECTIVE — HyperSmart Observer dYdX v4 : Upgrade Complet

## CONTEXTE DU PROJET

Tu travailles sur **HyperSmart Observer**, un bot de paper trading (simulation) sur dYdX v4. Le code est dans `hyper_smart_observer/dydx_v4/`. Le but : observer des wallets performants en temps réel, détecter des signaux d'order-flow, et simuler des paper trades avec le PnL le plus réaliste et positif possible.

**Le problème actuel** : le bot a un PnL négatif. L'edge calculator vient d'être recalibré (session précédente), mais il reste de nombreuses lacunes architecturales et algorithmiques qui empêchent le bot de capturer les bonnes opportunités et de filtrer les mauvaises.

## RÈGLE DE SÉCURITÉ ABSOLUE — LIRE EN PREMIER

```
SIMULATION PAPER UNIQUEMENT. Aucun ordre réel, aucun argent réel, aucune clé
privée, aucun seed, aucune mnemonic, aucune signature, aucun dépôt/retrait,
aucun wallet connect, aucun appel d'API privée pour trader.
READ-ONLY, PAPER-ONLY, TESTNET-FIRST, DENY-BY-DEFAULT.
Un signal n'est jamais un ordre. Un paper trade n'est jamais un ordre.
Si une donnée est incertaine, trop vieille ou incomplète : NO_TRADE.
```

**Avant chaque modification**, vérifie que tu n'introduis AUCUNE méthode de trading réel, AUCUN import de signing/broadcasting, AUCUNE clé privée. Tous les tests de sécurité dans `tests/dydx_v4/test_dydx_safety_and_config.py` doivent rester verts.

## ARCHITECTURE ACTUELLE — CE QUI EXISTE

```
hyper_smart_observer/dydx_v4/
├── config.py              # DydxV4Config — tous les seuils
├── engine.py              # DydxEngine singleton, démarre l'observer
├── live_observer.py       # Boucle principale: poll → detect → evaluate → paper trade
│                            Méthodes clés: run(), _poll_shortlist(), _evaluate_cluster(),
│                            _process_stream_consensus(), _check_exits(), _honest_entry_price()
├── edge_calculator.py     # Calcul de l'edge net (freshness exp, consensus, leader quality, coûts)
├── adaptive_exits.py      # ExitPlan: ATR stop/TP/trailing + time-stop + funding awareness
├── risk_policy.py         # CircuitBreaker, anti-churn, anti-scalper, ATR exits
├── cluster_detector.py    # Détection de clusters multi-wallets (consensus)
├── consensus.py           # ConsensusTracker: buffer glissant des ouvertures récentes
├── stream_consensus.py    # Consensus temps réel via WS fills
├── market_flow.py         # v4_trades WS: momentum d'order-flow (buy/sell imbalance)
├── fast_scanner.py        # FastScanner: WS subaccount fills, HotWalletSet, ThroughputMeter
├── fast_scan_integration.py  # Orchestre harvester + scanner
├── wallet_discovery.py    # Découverte et scoring de wallets (Cosmos LCD + REST)
├── wallet_harvester.py    # Multi-sources: leaderboard, tape, cosmos, statique
├── leaderboard.py         # DydxLeaderboardBuilder: évaluation et classement des comptes
├── leader_quality.py      # qualifies_as_leader(), has_track_record()
├── selection.py           # SelectionTier, classify_account(), composite_score()
├── scoring.py             # compute_account_score()
├── paper.py / paper_fill.py / fill_simulator.py  # Simulation de fills honnêtes (VWAP, orderbook)
├── rest_client.py         # DydxIndexerRestClient (read-only)
├── ws_client.py           # DydxIndexerWsClient (WebSocket public)
├── cosmos_client.py       # DydxCosmosLcdClient (on-chain subaccounts)
├── safety.py              # Gates de sécurité: assert_paper_only, check_url_safety, gate_signal_for_live
├── no_trade.py            # Journalisation des refus
├── storage.py             # SQLite: fills, paper trades, no_trade, signals, health
├── models.py              # Dataclasses normalisées (NormalizedFill, PaperTrade, etc.)
├── backtest.py            # DydxBacktester (squelettique: run_on_fills seulement)
├── signals.py             # DydxSignalEngine: evaluate_delta → signal ou no_trade
├── lifecycle.py           # OPEN/ADD/REDUCE/CLOSE
├── normalizer.py          # Normalisation des données Indexer
├── metrics.py             # Métriques internes
├── dashboard_adapter.py   # Adaptateur pour l'UI
└── cli.py                 # CLI
```

**Valeurs actuelles des seuils critiques** (config.py) :
- `min_edge_bps = 3.0` — seuil minimum d'edge net pour entrer
- `edge_safety_multiplier = 1.2` — edge doit être > 1.2× les coûts
- `max_signal_age_ms = 20000` — signal max 20s
- `max_open_paper_trades = 3`
- `consensus_min_wallets = 2` (REST), `flow_consensus_min_wallets = 1` (flow)
- `atr_stop_mult = 1.0`, `atr_take_profit_mult = 3.0`, `atr_trail_mult = 0.8`
- `PAPER_NOTIONAL_USDT = 50.0` (fixe, dans live_observer.py)
- `poll_interval_s = 5.0` (REST poll)
- `market_flow_min_volume_usdc = 10000`, `market_flow_min_imbalance = 0.65`
- `flow_min_trades = 5`
- `reopen_cooldown_seconds = 90.0`
- `DISCOVERY_REFRESH_S = 6 * 3600` (6 heures)
- `STALE_POSITION_TIMEOUT_S = 600` (10 min)
- `max_holding_hours = 48.0`

**Edge calculator** (edge_calculator.py) :
- Freshness decay exponentiel, half-life 8s
- DEFAULT_LEADER_EDGE_BPS = 25.0
- EVAL_FEE_BPS = 7.0 (entry + marge)
- Consensus factor : 1 wallet → 0.75, 2 → 1.0, 3+ → bonus
- Unknown leader consistency → 0.7

## LES 20 PROBLÈMES À RÉSOUDRE — PAR PRIORITÉ

### BLOC A — Signaux manqués et latence (le bot rate des opportunités)

**A1. Pas de confirmation multi-timeframe (CRITIQUE)**
Fichier : `live_observer.py` → `_evaluate_cluster()`
Problème : Le bot évalue un signal sans vérifier s'il est aligné avec la tendance du marché. Un LONG pendant un downtrend 15min = perte quasi-certaine.
Solution : Avant d'entrer, fetcher les candles 5min et 1h via `rest_client.get_candles()`. Calculer un trend score simple : si les 3 dernières candles 5min ET la candle 1h courante vont dans le même sens que le signal → bonus. Si opposition → gate refus "TREND_OPPOSITION". Ajouter un champ `trend_alignment_score` dans `EdgeComponents` (edge_calculator.py). Pondérer l'edge : `edge *= trend_score` (0.5 si neutre, 1.2 si aligné, 0.0 si opposé).
Impact attendu : -30-40% de trades perdants (les reversals sont la cause #1 de pertes en copy-trading).

**A2. Pas de détection d'anomalie de volume (CRITIQUE)**
Fichier : `market_flow.py` → `detect_flow_signals()`
Problème : L'imbalance de 65% est vérifiée, mais pas si le volume est anormalement élevé. Un imbalance de 70% sur un volume 3× la moyenne est BEAUCOUP plus significatif que le même sur un volume normal.
Solution : Ajouter un `VolumeProfiler` dans `market_flow.py` qui maintient une EMA du volume par marché sur les 1h/4h/24h (via les candles REST, rafraîchies toutes les 5min). Calculer un `volume_z_score = (current_volume - ema) / std`. Si `z_score > 2.0` + imbalance ≥ 0.65 → signal "VOLUME_SPIKE". Ajouter un bonus multiplicateur dans le flow signal : `signal_strength *= min(2.0, 1.0 + z_score * 0.3)`.

**A3. Discovery trop lente (IMPORTANT)**
Fichier : `live_observer.py` constante `DISCOVERY_REFRESH_S = 6 * 3600`
Problème : Le refresh de la shortlist se fait toutes les 6 heures. Un wallet qui devient très actif et performant ne sera découvert qu'après 6h.
Solution : Réduire à 1h (`DISCOVERY_REFRESH_S = 3600`). Ajouter un "fast refresh" conditionnel : si le nombre de signaux acceptés dans les 30 dernières minutes est 0, trigger un refresh immédiat (le scan actuel n'attrape rien → changer d'angle). Ajouter un compteur `_signals_last_30min` dans `ObserverStats`.

**A4. Scanner ne croise pas les sources de signaux (IMPORTANT)**
Fichiers : `live_observer.py` → `_evaluate_cluster()` et `_process_stream_consensus()`
Problème : Les signaux REST (copy-wallet) et les signaux Flow (momentum) sont évalués indépendamment. Quand les DEUX détectent le même marché dans la même direction, c'est un signal beaucoup plus fort, mais le bot ne le sait pas.
Solution : Ajouter un `SignalConfluenceTracker` (nouveau fichier `signal_confluence.py`). Quand un signal REST arrive, vérifier si un signal Flow récent (< 30s) existe sur le même marché+side. Si oui → `confluence_bonus = 1.5` appliqué à l'edge. Inversement, un signal Flow confirmé par un consensus REST → bonus. Le tracker maintient un buffer circulaire de (market, side, origin, timestamp_ms).

### BLOC B — Gestion du risque et des exits (le bot perd trop par trade)

**B1. Pas de position sizing dynamique (CRITIQUE)**
Fichier : `live_observer.py` constante `PAPER_NOTIONAL_USDT = 50.0`
Problème : Chaque trade a la même taille ($50), quelle que soit la conviction ou la volatilité. Un signal fort sur un marché calme devrait avoir une taille plus grosse qu'un signal faible sur un marché volatil.
Solution : Remplacer la constante par une fonction `compute_position_size()` dans un nouveau fichier `position_sizing.py`. Formule : `base_size = 50.0`, `conviction_mult = edge_remaining_bps / 10.0` (plafonné à 2.0), `vol_mult = 1.0 / max(0.5, atr_pct)` (plafonné à 2.0), `size = base_size * min(conviction_mult, vol_mult)`, borné entre 20.0 et 100.0. Plus de conviction + moins de volatilité = plus gros. Le circuit breaker (risk_policy.py) réduit automatiquement : `size *= 0.5` si 2 pertes consécutives.

**B2. Pas de partial take-profit (IMPORTANT)**
Fichier : `adaptive_exits.py` et `live_observer.py` → `_check_exits()`
Problème : Le TP est tout-ou-rien. Quand le prix touche le TP, on ferme 100%. Mais souvent le prix continue — on rate le mouvement étendu.
Solution : Ajouter 2 niveaux de TP dans `ExitPlan` : `tp1_price` (2× ATR, ferme 50% de la position) et `tp2_price` (4× ATR, ferme les 50% restants). Le trailing stop s'arme après TP1. Modifier `PaperPositionState` pour supporter `remaining_pct` (commence à 1.0, passe à 0.5 après TP1). `_close_paper_position()` doit gérer les fermetures partielles (proportionnel au `remaining_pct`).

**B3. Pas de détection de régime de marché (IMPORTANT)**
Fichier : nouveau `regime_detector.py` + intégration dans `live_observer.py`
Problème : Le bot trade de la même façon que le marché soit en tendance forte, en range, ou en chute libre. En range choppy, le copy-trading est destructeur (les wallets leaders sont stop-outtés aussi).
Solution : Créer `RegimeDetector` avec 3 régimes : TRENDING, RANGING, VOLATILE_CHOPPY. Basé sur : (1) ADX sur candles 1h (>25 = trending), (2) ratio ATR/prix sur 24h, (3) direction des 3 dernières candles 4h. En régime RANGING → réduire `max_open_paper_trades` à 1, augmenter `min_edge_bps` à 5.0. En régime TRENDING → normal. En régime CHOPPY → circuit breaker automatique, attendre. Stocker le régime dans `ObserverStats` pour le dashboard.

**B4. Pas de corrélation inter-positions (IMPORTANT)**
Fichier : `live_observer.py` → `_evaluate_cluster()` gate 4/5
Problème : Le bot peut ouvrir BTC-LONG + ETH-LONG + SOL-LONG = 3 positions ultra-corrélées. Un crash crypto = 3 pertes simultanées.
Solution : Ajouter une gate "CORRELATION_LIMIT" dans `_evaluate_cluster()`. Mapper les marchés par groupe de corrélation : `GROUP_A = {"BTC-USD", "ETH-USD"}`, `GROUP_B = {"SOL-USD", "SUI-USD", "AVAX-USD", "NEAR-USD", "APT-USD"}`, `GROUP_C = {"ARB-USD", "OP-USD"}`, etc. Règle : max 1 position par groupe de corrélation dans le même sens. Si déjà BTC-LONG ouvert et signal ETH-LONG → refuser avec raison "CORRELATED_EXPOSURE".

### BLOC C — Qualité des leaders et scoring (le bot suit les mauvais wallets)

**C1. Leader scoring ne distingue pas les spécialités (CRITIQUE)**
Fichier : `scoring.py` → `compute_account_score()` et `wallet_discovery.py`
Problème : Un wallet avec 80% winrate sur ETH mais 30% sur SOL a un score moyen. Le bot le copie sur SOL = perte.
Solution : Ajouter un scoring PAR MARCHÉ dans `compute_account_score()`. Enrichir `WalletScore` avec un dict `per_market_winrate: dict[str, float]`. Dans `_evaluate_cluster()`, au lieu de `avg_wr` global, utiliser le winrate du leader SUR LE MARCHÉ DU SIGNAL. Si le leader n'a pas de track record sur ce marché → pénaliser (consistency_factor × 0.5). Stocker dans SQLite (storage.py, nouvelle table `leader_market_stats`).

**C2. Pas de scoring temporel des leaders (IMPORTANT)**
Fichier : `leader_quality.py` et `selection.py`
Problème : Un wallet historiquement bon mais en drawdown récent est toujours suivi. Son edge récent est peut-être négatif.
Solution : Ajouter un `recent_performance_score` basé sur les 20 derniers trades du wallet. Si les 5 derniers sont des pertes → `recent_score = 0.3` → quasi-exclusion. Si le wallet est en drawdown >10% sur 7 jours → `recent_score = 0.5`. Pondérer : `final_score = historical_score * 0.4 + recent_score * 0.6`. Les wallets en drawdown récent sont naturellement écartés.

**C3. Pas de "leader exit follow" fiable (IMPORTANT)**
Fichier : `live_observer.py` → `_handle_leader_close()` (ligne 1164)
Problème : Quand le leader ferme sa position, le bot devrait fermer aussi (le leader sait quelque chose). Mais `_handle_leader_close()` ne fonctionne que si le bot détecte le delta CLOSE du leader via le polling REST (toutes les 5s). Pendant 5s, le prix peut bouger énormément.
Solution : Utiliser le WebSocket subaccount pour les leaders shortlistés (via `fast_scanner.py`). Quand un fill "SELL" est détecté en WS pour un leader qui est LONG sur un marché où le bot est aussi LONG → fermer immédiatement. Ajouter un mapping `_leader_positions: dict[str, set[str]]` dans `live_observer.py` qui track market+side par leader. Le fast scanner signale les closes en < 1s au lieu de 5s.

### BLOC D — Backtest et auto-calibration (le bot ne sait pas si ses paramètres sont bons)

**D1. Backtest quasi-inexistant (CRITIQUE)**
Fichier : `backtest.py`
Problème : `DydxBacktester.run_on_fills()` existe mais c'est squelettique. Aucun walk-forward, aucune analyse de sensibilité, aucun rapport de performance détaillé.
Solution : Réécrire `backtest.py` avec :
- `run_backtest(fills, config)` → simule la stratégie exacte du live observer sur des fills historiques
- `walk_forward(fills, train_pct=0.7)` → optimise sur train, valide sur test, retourne les métriques out-of-sample
- `parameter_sensitivity(fills, param_name, values)` → teste une plage de valeurs pour un paramètre et retourne une courbe PnL
- `BacktestReport` dataclass avec : total_pnl, winrate, max_drawdown, sharpe_ratio, profit_factor, avg_trade_pnl, max_consecutive_losses
- Utiliser les fills historiques depuis SQLite (`storage.get_fills()`) ou en fetchant via REST (`rest_client.paginate_fills()`)
Le backtest doit reproduire EXACTEMENT la logique de `_evaluate_cluster()` + exits. Si le backtest dit -$X, le live confirmera.

**D2. Pas d'auto-calibration des seuils (IMPORTANT)**
Fichier : nouveau `auto_calibrator.py`
Problème : Les seuils (min_edge, flow_min_trades, atr_stop_mult, etc.) sont fixés manuellement. Ils pourraient être optimisés automatiquement sur les données récentes.
Solution : Créer `AutoCalibrator` qui tourne périodiquement (toutes les 24h ou sur commande CLI) :
1. Collecte les 7 derniers jours de paper trades (SQLite)
2. Pour chaque paramètre clé, teste ±20% de la valeur actuelle
3. Évalue le PnL simulé de chaque variante
4. Propose (mais n'applique PAS automatiquement) les meilleures valeurs
5. Log les recommandations dans `logs/calibration/`
Ne JAMAIS appliquer automatiquement (le humain valide). Ajouter une commande CLI `python -m hyper_smart_observer.dydx_v4.cli calibrate`.

### BLOC E — Dashboard et observabilité (le bot ne communique pas assez)

**E1. Dashboard ne montre pas les opportunités manquées (IMPORTANT)**
Fichier : `src/hl_observer/ui/static/simulation_v2.html` et `src/hl_observer/ui/dydx_routes.py`
Problème : Le dashboard montre les trades ouverts/fermés mais pas les signaux refusés et pourquoi. L'utilisateur ne sait pas si le bot est actif ou mort.
Solution : Ajouter un endpoint `/api/dydx/refused` qui retourne les 50 derniers refus depuis `NoTradeEngine.recent(50)`. Dans le HTML, ajouter une section "Signaux récents" avec une liste : `[timestamp] [market] [side] [raison] [edge estimé]`. Couleur : vert = accepté, rouge = refusé, orange = refusé mais edge proche du seuil (aurait presque passé). Ajouter aussi le régime de marché actuel et le statut du circuit breaker.

**E2. Pas de logs structurés exploitables (IMPORTANT)**
Fichier : `live_observer.py` et tous les modules
Problème : Les logs sont textuels, difficiles à parser pour analyse post-session.
Solution : Ajouter un logger JSON séparé (`logs/structured/decisions.jsonl`). Chaque ligne = un JSON avec : `{"ts": ..., "type": "SIGNAL_ACCEPTED"|"SIGNAL_REFUSED"|"POSITION_CLOSED", "market": ..., "side": ..., "edge_bps": ..., "reason": ..., "mark_price": ..., "regime": ..., "confluence": ...}`. Utiliser `json.dumps()` sur un dictionnaire, une ligne par événement. Ce fichier permet d'analyser les patterns de performance offline.

### BLOC F — Micro-optimisations du moteur de décision

**F1. Edge calculator ne pondère pas par marché (IMPORTANT)**
Fichier : `edge_calculator.py`
Problème : `DEFAULT_LEADER_EDGE_BPS = 25.0` est le même pour tous les marchés. Mais ETH a plus de copieurs (edge dilué) et les altcoins ont des spreads plus larges mais un edge brut plus élevé.
Solution : Ajouter un `MARKET_EDGE_MULTIPLIER` dict : `{"BTC-USD": 1.0, "ETH-USD": 0.9, "SOL-USD": 1.1, "DOGE-USD": 1.3, ...}`. L'edge brut du leader est multiplié par ce facteur. Les altcoins volatils ont un edge brut plus élevé (whale impact plus fort) mais aussi des coûts plus élevés (spread, slippage). Les majors ont un edge plus stable mais plus dilué.

**F2. Consensus window trop large (IMPORTANT)**
Fichier : `config.py` → `consensus_window_ms = 10 * 60 * 1000`
Problème : 10 minutes de fenêtre de consensus. Deux wallets qui tradent le même marché à 9 minutes d'écart ne sont PAS coordonnés. Bruit pur.
Solution : Réduire à 3 minutes (`consensus_window_ms = 180_000`). Ajouter un "recency bonus" dans le consensus : les wallets qui sont entrés dans les 30 dernières secondes comptent double. Modifier `ConsensusTracker.check()` pour pondérer par recency.

**F3. Funding rate non utilisé dans l'edge (IMPORTANT)**
Fichier : `edge_calculator.py` → `calculate_edge()`
Problème : Le funding rate est utilisé dans `adaptive_exits.py` pour raccourcir la durée de holding, mais il n'est PAS inclus dans le calcul de l'edge. Un LONG quand le funding est +0.05%/h = le carry ronge l'edge de 1.2bps/h minimum.
Solution : Ajouter `funding_cost_bps` dans `EdgeComponents`. Si la position moyenne dure 2h et le funding adverse = 0.03%/h → `funding_cost_bps = 0.03 * 2 * 100 = 6bps`. Soustraire du net edge. Le funding rate est fetchable via `rest_client.get_market(market)` → champ `nextFundingRate`.

**F4. Pas de filtre "heure de la journée" (NICE-TO-HAVE)**
Fichier : `live_observer.py` → `_evaluate_cluster()`
Problème : Le crypto trade 24/7 mais la liquidité et le comportement des whales changent drastiquement entre les sessions (Asie 00-08 UTC, Europe 08-16, US 16-00). Les signaux pendant les heures creuses (faible liquidité) ont plus de slippage et de faux signaux.
Solution : Ajouter un `session_quality_factor` : heures 14-22 UTC (overlap EU/US) = 1.0, heures 08-14 et 22-02 = 0.8, heures 02-08 = 0.6. Appliquer comme multiplicateur dans l'edge : `edge *= session_factor`. Configurable via `config.py`.

## MÉTHODE DE TRAVAIL

Pour CHAQUE modification :

1. **Lire** le fichier cible complètement avant de modifier
2. **Comprendre** l'architecture existante (imports, dépendances, flow)
3. **Coder** proprement (docstrings, types, logging)
4. **Tester** : ajouter des tests unitaires dans `tests/dydx_v4/` pour chaque nouvelle fonctionnalité
5. **Vérifier la sécurité** : `grep -rn "place_order\|private_key\|mnemonic\|sign_transaction\|broadcast" hyper_smart_observer/` ne doit rien retourner de dangereux
6. **Lancer les 241 tests existants** : `PYTHONDONTWRITEBYTECODE=1 python -B -m pytest tests/dydx_v4/ -x -q -p no:cacheprovider` — tous doivent rester verts

**Ordre de priorité d'implémentation** (faire dans cet ordre) :
1. A1 (trend filter) → impact immédiat sur le winrate
2. B1 (position sizing) → réduit les pertes par trade
3. B3 (régime detector) → évite de trader en conditions défavorables
4. A2 (volume anomaly) → améliore la qualité des signaux flow
5. B4 (corrélation) → réduit le risque portfolio
6. A4 (confluence) → booste les signaux confirmés
7. C1 (leader scoring par marché) → suit les bons leaders sur les bons marchés
8. D1 (backtest) → valide que les changements améliorent réellement le PnL
9. F2 (consensus window) → réduit le bruit
10. F3 (funding dans edge) → edge plus réaliste
11. B2 (partial TP) → capture plus de profit sur les gagnants
12. A3 (discovery rapide) → attrape les opportunités plus vite
13. C2 (scoring temporel leaders) → écarte les leaders en drawdown
14. C3 (leader exit via WS) → réaction plus rapide aux fermetures
15. E1 (dashboard refusés) → observabilité
16. E2 (logs structurés) → analyse post-session
17. F1 (edge par marché) → calibration fine
18. F4 (session hours) → évite les heures creuses
19. D2 (auto-calibration) → recommandations automatiques
20. B2 (partial TP finition) → les 50% restants

## CONTRAINTES TECHNIQUES

- **Python 3.10+**, pas de dépendances externes lourdes (numpy/pandas interdits dans le runtime — OK dans les tests/backtest)
- **Aucun async** dans le moteur principal (threading seulement, l'observer est synchrone)
- **SQLite** pour la persistance (pas de PostgreSQL/Redis)
- **Tous les nouveaux fichiers** doivent avoir le header `"""...\nPAPER-ONLY. Aucun ordre réel. Aucune clé privée.\n"""`
- **Pas de modification** de `safety.py` sauf pour AJOUTER des gates (jamais en retirer)
- **Chaque nouveau paramètre** doit être ajouté dans `DydxV4Config` avec un default safe et un env var `DYDX_*`
- Les fichiers de tests sont dans `tests/dydx_v4/` et commencent par `test_`
- Le sandbox Linux tronque parfois les fichiers via Edit → utiliser bash heredoc pour les fichiers > 200 lignes

## CRITÈRE DE SUCCÈS

Un backtest sur 7 jours de données historiques dYdX v4 doit montrer :
- Winrate ≥ 55% (actuellement ~42%)
- Profit factor ≥ 1.3 (actuellement <1.0)
- Max drawdown < 5% du capital paper
- ≥ 10 trades sur la période (pas de sur-filtrage)
- 0 faux positifs de sécurité (tous les tests passent)

## RAPPEL FINAL

Ne jamais promettre un PnL positif garanti. L'objectif est de **maximiser la probabilité** d'un PnL paper positif réaliste en filtrant les mauvais trades, en ne gardant que les signaux frais, cohérents, liquides, avec edge net positif après tous les coûts. Chaque refus NO_TRADE est une BONNE décision s'il aurait été un trade perdant.
