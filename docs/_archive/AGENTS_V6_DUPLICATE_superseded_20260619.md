# NOTE AGENTS V6 — Version renforcée pour Codex

Cette version conserve toutes les règles précédentes et ajoute un supplément V6 en fin de fichier. Les règles les plus strictes priment.

---

# AGENTS.md — Règles strictes pour Codex / agents IA

> Ce fichier est obligatoire pour tout agent travaillant sur `hyperliquid-smart-wallet-observer`.  
> Il complète `README.md` et définit les règles de sécurité, d’architecture, de développement et de livraison.

---

## 0. Priorité des règles

Ordre de priorité :

```text
1. Sécurité utilisateur / secrets / pas de mainnet
2. AGENTS.md
3. README.md
4. Tests existants
5. Demande ponctuelle utilisateur
```

Si une demande ponctuelle contredit la sécurité, refuser la partie dangereuse et proposer une alternative safe.

---

## 1. Mission du projet

Construire un logiciel local qui :

- observe des wallets/adresses Hyperliquid ;
- collecte positions, fills, ordres ouverts, carnets et prix ;
- reconstruit les deltas de position ;
- score wallets et signaux ;
- refuse par défaut les signaux risqués ;
- simule en paper trading ;
- prépare un testnet executor verrouillé ;
- interdit toute exécution mainnet dans le MVP.

Le projet est un **outil R&D**, pas un service financier, pas un bot magique, un protocole de validation orienté performance.

---

## 2. Interdictions absolues

Un agent ne doit jamais :

```text
- demander une seed phrase ;
- demander une clé privée mainnet ;
- écrire une clé privée dans un fichier ;
- stocker un secret en base ;
- logger un secret ;
- coder une fonctionnalité de retrait ;
- activer l’exécution mainnet ;
- appeler /exchange mainnet ;
- contourner le risk engine ;
- désactiver le kill switch ;
- supprimer les tests de sécurité ;
- ajouter du levier par défaut ;
- placer un ordre réel ;
- promettre un gain visé avec preuves ;
- présenter le bot viral comme prouvé ;
- mettre Claude/MCP/LLM dans le hot path trading.
```

---

## 3. Capital Protection & Profitability Protocol

Le protocole du projet est :

```text
0 euro réel exposé dans le MVP.
0 ordre mainnet.
0 secret mainnet.
0 trade si une seule condition de sécurité échoue.
```

Chaque signal doit passer toutes les portes :

```text
wallet_score_ok
signal_score_ok
freshness_ok
spread_ok
liquidity_ok
slippage_ok
latency_ok
market_regime_ok
exposure_ok
daily_loss_ok
weekly_loss_ok
drawdown_ok
ws_stable_ok
api_stable_ok
reconciliation_ok
duplicate_order_ok
kill_switch_ok
```

Si une porte échoue : `REJECT_*` obligatoire et stockage dans `rejected_signals`.

---

## 4. Variables d’environnement obligatoires

Valeurs par défaut :

```env
HL_ENV=paper
HL_ENABLE_MAINNET_EXECUTION=false
HL_ENABLE_TESTNET_EXECUTION=false
HL_TESTNET_PRIVATE_KEY=
```

Règles :

- `read_only` et `paper` ne nécessitent aucune clé privée ;
- `testnet` peut nécessiter une clé testnet, jamais une clé mainnet ;
- si `HL_ENABLE_MAINNET_EXECUTION=true`, le MVP doit refuser de démarrer ;
- si `HL_ENV=mainnet` et qu’une commande d’exécution est appelée, refuser ;
- tout secret absent ou vide doit produire une erreur claire uniquement dans les modes qui en ont besoin.

---

## 5. Politique mainnet

```text
Mainnet read-only : autorisé.
Mainnet exchange/execution : interdit dans le MVP.
Mainnet private key : interdite.
Mainnet withdrawal : interdit pour toujours.
```

Aucun chemin de code ne doit permettre une exécution mainnet accidentelle.

Créer un module explicite :

```text
live_executor_disabled.py
```

Ce module doit refuser toute tentative.

---

## 6. Politique testnet

Le testnet est verrouillé par défaut.

Conditions minimales pour un ordre testnet :

```text
HL_ENV=testnet
HL_ENABLE_TESTNET_EXECUTION=true
clé testnet présente
risk_engine_ok
kill_switch_inactive
reconciliation_ok
taille sous limite
logs activés
commande explicitement testnet
```

Si une condition manque : refuser.

---

## 7. Rôle autorisé de l’IA

L’agent IA peut :

- lire README/AGENTS ;
- écrire du code ;
- créer tests ;
- résumer docs ;
- proposer architecture ;
- analyser logs ;
- améliorer backtest ;
- générer rapports ;
- maintenir la documentation.

L’agent IA ne peut pas :

- décider un trade live ;
- gérer secrets ;
- changer les limites de risque sans trace ;
- supprimer des garde-fous ;
- utiliser MCP pour exécuter une action sensible sans sandbox/allowlist ;
- transformer un signal incertain en ordre.

---

## 8. Sécurité MCP / outils connectés

MCP et outils externes doivent être traités comme dangereux par défaut.

Règles :

```text
- MCP hors hot path.
- Outils lecture seule par défaut.
- Pas de secrets dans le contexte.
- Pas de clé privée dans MCP.
- Pas d’accès exécution trading.
- Allowlist stricte des commandes.
- Sandbox pour tout outil shell/code.
- Logs complets des appels outils.
- Entrées/sorties validées.
- Pas de dépendance non auditée.
```

Menaces à prendre en compte : prompt injection, tool poisoning, rug pull de tool descriptor, exfiltration, sur-permissions, commande shell cachée, dépendance malveillante.

---

## 9. Architecture obligatoire

Respecter la structure du README.

Interdit : tout mettre dans `main.py`.

Modules attendus :

```text
config/
hyperliquid/
collectors/
discovery/
storage/
wallets/
scoring/
signals/
strategies/
execution/
risk/
backtest/
metrics/
reports/
dashboard/
alerts/
security/
llm/
utils/
```

---

## 10. Style de code

- Python 3.11+ ;
- type hints autant que possible ;
- Pydantic pour config ;
- Typer pour CLI ;
- SQLAlchemy pour DB ;
- logs structurés ;
- exceptions explicites ;
- aucun `print` métier ;
- pas de dépendance inutile ;
- pas de code mort ;
- pas de magie silencieuse ;
- pas de global mutable dangereux ;
- fonctions petites et testables.

---

## 11. Gestion API / WebSocket

Le code doit gérer :

```text
timeout
retry with backoff
rate limit
payload inattendu
reconnect
heartbeat
messages dupliqués
trous de données
ordre d’événements incohérent
pagination userFills/userFillsByTime
order status rejected/canceled/filled/open
stale data après reconnect
```

En cas d’incertitude : lecture seule / refus.

---

## 12. Données à stocker

Stocker raw JSON + données normalisées.

Tables importantes :

```text
wallets
wallet_sources
wallet_snapshots
wallet_metrics
wallet_scores
wallet_clusters
fills
positions
position_deltas
open_orders
historical_orders
market_snapshots
orderbook_snapshots
trades_public
funding_snapshots
signals
signal_scores
rejected_signals
paper_orders
paper_fills
paper_trades
testnet_orders
testnet_fills
risk_events
kill_switch_events
api_health
websocket_events
reconciliation_events
strategy_runs
backtest_runs
daily_reports
source_references
x_research_claims
copy_degradation_metrics
edge_remaining_metrics
exit_quality_metrics
mfe_mae_metrics
no_trade_decisions
```

---

## 13. Décisions de signal obligatoires

Utiliser des constantes/enums explicites :

```text
IGNORE
OBSERVE
PAPER_TRADE
TESTNET_ALLOWED
REJECT_TOO_LATE
REJECT_TOO_ILLIQUID
REJECT_SPREAD_TOO_WIDE
REJECT_SLIPPAGE_TOO_HIGH
REJECT_WALLET_TOXIC
REJECT_MARKET_REGIME_BAD
REJECT_RISK_ENGINE
REJECT_API_UNSTABLE
REJECT_WS_RECENTLY_RECONNECTED
REJECT_DUPLICATE_ORDER_RISK
REJECT_RECONCILIATION_UNCERTAIN
```

Jamais de décision implicite.

---

## 14. Stratégies autorisées dans le MVP

Autorisé :

```text
wallet-following filtré
delta de position
paper trading
partial take profit simulé
trailing stop simulé
exit on leader reduce/close
spread/slippage/liquidity guards
no-trade analytics
```

À explorer mais désactivé par défaut :

```text
whale clusters
order book imbalance
funding/open interest filters
liquidation zones externes
market making limité
```

Interdit :

```text
martingale
levier élevé
copy aveugle
ordre mainnet
LLM décisionnaire live
stratégie basée uniquement sur X
```

---

## 15. Correction conceptuelle obligatoire

Ne jamais confondre :

```text
Polymarket = YES/NO, merge, negative risk, prediction markets.
Hyperliquid = perps/spot order book, fills, positions, funding, open orders.
MEXC = CEX, copy trade natif, pas de scan public de wallets tiers.
```

Si un agent écrit “acheter Yes/No sur Hyperliquid”, corriger immédiatement.

---

## 16. Métriques obligatoires

Implémenter ou prévoir :

```text
copy_degradation
edge_remaining
exit_quality
MFE
MAE
capital_velocity
no_trade_precision
profit_factor
expectancy
max_drawdown
consecutive_losses
wallet_toxicity_score
signal_freshness_score
```

---

## 17. Tests obligatoires

Créer au minimum :

```text
test_no_mainnet_execution_by_default
test_mainnet_exchange_endpoint_forbidden
test_private_key_not_required_for_read_only
test_private_key_not_required_for_paper
test_testnet_execution_disabled_by_default
test_kill_switch_blocks_orders
test_signal_rejected_if_spread_too_high
test_signal_rejected_if_wallet_score_too_low
test_signal_rejected_if_daily_loss_reached
test_signal_rejected_if_too_old
test_signal_rejected_after_ws_reconnect
test_duplicate_order_guard
test_reconciliation_guard
test_no_secret_in_logs
test_user_fills_pagination
test_order_status_rejections_are_handled
test_edge_remaining_negative_rejected
test_copy_degradation_calculated
test_no_trade_precision_calculated
test_polymarket_strategies_are_not_marked_hyperliquid
test_llm_never_required_for_risk_decision
```

Aucun PR ou run Codex n’est acceptable sans tests de sécurité.

---

## 18. Commandes CLI attendues

```bash
python -m hl_observer doctor
python -m hl_observer init-db
python -m hl_observer collect-once
python -m hl_observer collect-loop
python -m hl_observer discover-wallets
python -m hl_observer score-wallets
python -m hl_observer detect-signals
python -m hl_observer paper-run
python -m hl_observer paper-report
python -m hl_observer backtest-run
python -m hl_observer dashboard
python -m hl_observer testnet-check
python -m hl_observer testnet-run --dry-run
python -m hl_observer safety-audit
```

---

## 19. `doctor` obligatoire

`doctor` doit vérifier :

```text
Python version
imports
config
.env safety
mainnet execution disabled
testnet disabled by default
DB path
logs path
API read-only reachable
WebSocket reachable if configured
no secrets in repo
no .env committed
```

---

## 20. `safety-audit` obligatoire

`safety-audit` doit vérifier :

```text
aucun secret en clair
aucun appel exchange mainnet
aucun retrait
mainnet disabled
tests sécurité présents
risk limits chargés
kill switch activable
live_executor_disabled présent
```

---

## 21. Livraison Codex attendue

À chaque livraison, Codex doit répondre avec :

```text
Résumé en français
Fichiers créés/modifiés
Commandes exécutées
Résultat des tests
Risques restants
Ce qui est hors scope
Confirmation mainnet execution impossible
```

---

## 22. Sources et documentation

Un agent doit privilégier :

```text
1. Documentation officielle Hyperliquid.
2. Documentation officielle Polymarket pour le casebook.
3. Repos officiels SDK.
4. Rapports de recherche fournis.
5. Repos open source audités.
6. Threads X uniquement comme hypothèses, jamais comme preuves.
```

---

## 23. Règle finale

Le meilleur code est celui qui refuse une mauvaise action.

```text
Safe by default.
Read-only by default.
Paper first.
Testnet second.
Mainnet never in MVP.
```


---

# SUPPLÉMENT AGENTS V5 — Règles Codex Ultra Strictes, Hyperliquid Mock USDC Only

> Cette section renforce toutes les règles précédentes. Elle ne les remplace pas.  
> En cas de conflit, appliquer la règle la plus sûre.

## A5.0 Périmètre final pour tout agent

```text
Plateforme codée : Hyperliquid uniquement.
Exécution autorisée : testnet mock USDC uniquement, et désactivée par défaut.
Mainnet : lecture seule uniquement.
Polymarket : recherche/casebook, jamais module d'exécution.
MEXC : exclu du code.
Objectif : maximiser l'edge mesurable sans jamais promettre de profit garanti.
```

## A5.1 Langage interdit et langage autorisé

Interdit :

```text
gain visé avec preuves
perte réelle neutralisée dans le MVP
bot miracle
revenu assuré
imparable
100% gagnant
```

Autorisé :

```text
edge_remaining positif
profit_factor_net
réduction des pertes évitables
refus par défaut
validation paper/testnet
stratégie hypothétique à tester
```

## A5.2 Règle “ne supprime rien”

Un agent ne doit pas supprimer une information de README.md ou AGENTS.md sans :

```text
1. expliquer pourquoi elle est obsolète ;
2. la déplacer en archive si elle peut encore servir ;
3. conserver la décision ou l'historique utile ;
4. ne jamais effacer une règle de sécurité.
```

## A5.3 Priorité absolue : sécurité > performance

Si un choix augmente potentiellement le profit mais réduit la sécurité : refuser ou le laisser en recherche.

```text
Safety first.
No trade is better than unsafe trade.
Mock USDC only.
Mainnet never in MVP.
```

## A5.4 Obligation de modèles typés

Codex doit créer des modèles explicites pour :

```text
WalletCandidate
WalletSnapshot
PositionState
PositionDelta
MarketContext
Signal
SignalScore
EdgeEstimate
RiskDecision
PaperTrade
TestnetOrderIntent
TestnetExecutionResult
RejectedSignal
KillSwitchEvent
```

Pas de propagation de `dict` non typés dans les modules métiers.

## A5.5 Obligation de décisions énumérées

Toute décision doit être un enum, jamais une string magique dispersée.

Minimum :

```text
IGNORE
OBSERVE
PAPER_TRADE
TESTNET_CANDIDATE
TESTNET_ALLOWED
REJECT_TOO_LATE
REJECT_TOO_ILLIQUID
REJECT_SPREAD_TOO_WIDE
REJECT_SLIPPAGE_TOO_HIGH
REJECT_WALLET_TOXIC
REJECT_EDGE_NEGATIVE
REJECT_CROWDING_RISK
REJECT_MARKET_REGIME_BAD
REJECT_RISK_ENGINE
REJECT_API_UNSTABLE
REJECT_WS_RECENTLY_RECONNECTED
REJECT_RECONCILIATION_UNCERTAIN
REJECT_DUPLICATE_ORDER_RISK
```

## A5.6 Testnet executor — conditions obligatoires

Aucun ordre testnet ne peut être construit si ces conditions ne sont pas toutes vraies :

```text
HL_ENV == testnet
HL_ENABLE_TESTNET_EXECUTION == true
HL_ENABLE_MAINNET_EXECUTION == false
--confirm-testnet-only fourni
kill_switch == ARMED
risk_decision == ACCEPT_TESTNET
reconciliation_state == OK
edge_remaining > min_edge_remaining
cloid généré
logs activés
```

Si une seule condition échoue : lever une exception safe et créer un `risk_event`.

## A5.7 Mainnet execution doit être impossible

Même si l’utilisateur met :

```env
HL_ENABLE_MAINNET_EXECUTION=true
```

le MVP doit refuser de démarrer toute commande d’exécution.

Créer un test :

```text
test_mainnet_execution_impossible_even_if_env_true
```

## A5.8 CLoid, idempotence et duplicate guard

Tout ordre testnet doit avoir un `cloid` déterministe.

```text
cloid = hash(run_id + signal_id + coin + side + action + attempt_index)
```

Codex doit empêcher :

```text
même signal envoyé deux fois
même cloid réutilisé accidentellement
ordre de sortie sans position correspondante
ordre d'entrée si ordre actif déjà présent
```

Tests :

```text
test_duplicate_signal_cannot_place_two_orders
test_cloid_is_deterministic
test_exit_without_position_rejected
```

## A5.9 scheduleCancel obligatoire pour testnet actif

Si Codex implémente une exécution testnet active, il doit prévoir :

```text
schedule_cancel_arm
schedule_cancel_refresh
schedule_cancel_clear
```

Interdiction : laisser des ordres testnet ouverts sans watchdog.

## A5.10 Risk gates obligatoires V5

Chaque signal doit passer :

```text
wallet_score_gate
wallet_toxicity_gate
sample_confidence_gate
freshness_gate
spread_gate
slippage_gate
liquidity_gate
orderbook_age_gate
edge_remaining_gate
crowding_gate
position_exposure_gate
daily_loss_gate
drawdown_gate
ws_stability_gate
api_health_gate
reconciliation_gate
duplicate_order_gate
kill_switch_gate
```

L'absence de données n’est pas neutre :

```text
missing data = reject
```

## A5.11 No-trade analytics obligatoire

Chaque rejet doit être stocké et, si possible, rejoué en shadow.

Objectif : savoir si le bot refuse intelligemment.

Codex doit créer :

```text
no_trade_decisions table/model
no_trade_precision metric
shadow_outcome evaluator
```

## A5.12 Exit engine obligatoire avant testnet actif

Il est interdit d’envoyer des entrées testnet si les sorties ne sont pas définies.

Minimum :

```text
exit_on_leader_reduce
exit_on_leader_close
partial_take_profit
trailing_stop
time_stop
max_mae_stop
kill_switch_exit
```

## A5.13 Backtest réaliste obligatoire avant toute promotion testnet

Le code doit permettre de simuler :

```text
fees
spread
slippage
latency
partial fill
non-fill
stale signal
missed signal
ws reconnect gap
rate limit delay
```

## A5.14 Hiérarchie de sources

Codex doit respecter :

```text
1. Hyperliquid API/WS local data
2. Hyperliquid official docs
3. Hyperliquid SDK official examples
4. README/AGENTS
5. Rapports de recherche fournis
6. Trackers externes
7. Threads X uniquement comme hypothèses
```

Jamais de code critique basé uniquement sur X/Twitter.

## A5.15 Dépendances et supply-chain

Avant d’ajouter une dépendance, Codex doit justifier :

```text
nom
usage
source officielle
alternative standard library possible ?
risque sécurité
```

Interdictions :

```text
dépendance inconnue pour gérer secrets
dépendance de trading obscure
copier-coller d'un bot GitHub sans audit
```

## A5.16 Rapport final obligatoire de Codex

Chaque run Codex doit terminer par :

```text
Résumé français
Fichiers modifiés
Nouvelles commandes CLI
Tests ajoutés
Tests exécutés
Résultat sécurité
Preuve mainnet impossible
Preuve testnet désactivé par défaut
Risques restants
Prochaine phase recommandée
```

## A5.17 Tests supplémentaires V5

Codex doit ajouter ou prévoir :

```text
test_missing_market_context_rejects_signal
test_missing_orderbook_rejects_signal
test_edge_remaining_negative_rejects_signal
test_crowding_risk_can_reject_signal
test_sample_confidence_penalizes_small_sample_wallet
test_martingale_pattern_penalized
test_pnl_concentration_penalized
test_no_trade_decision_is_stored
test_rejected_signal_shadow_outcome_can_be_computed
test_exit_engine_required_before_testnet_active
test_schedule_cancel_required_for_testnet_active
test_cloid_required_for_testnet_order
test_mainnet_execution_impossible_even_if_env_true
test_polymarket_merge_not_available_on_hyperliquid
test_mexc_modules_absent_from_runtime
```

## A5.18 Règle finale

```text
Le but n'est pas de trader plus.
Le but est de refuser mieux,
de mesurer mieux,
et de ne tester que les rares signaux dont l'edge net reste positif.
```


---

# SUPPLÉMENT AGENTS V6 — Règles Codex Ultra pour maximiser l’edge sans promettre de gain visé avec preuves

Ce supplément est cumulatif. Il ne remplace aucune règle précédente. Les règles les plus strictes priment.

## A6.1 Périmètre dur

```text
Code cible : Hyperliquid uniquement.
Exécution autorisée : paper trading + testnet mock USDC uniquement.
Mainnet : lecture seule uniquement.
Polymarket/MEXC/X : recherche/casebook uniquement, jamais code d’exécution.
```

## A6.2 Interdiction de promesse de profit

Codex doit optimiser l’espérance testable, pas promettre un résultat.

Formulation autorisée :

```text
maximiser edge_remaining
réduire copy_degradation
améliorer exit_quality
augmenter no_trade_precision
réduire drawdown simulé
```

Formulation interdite :

```text
gain visé avec preuves
zéro perte garanti
bot miracle
profit assuré
revenu journalier sûr
```

## A6.3 Architecture de décision obligatoire

Aucun ordre testnet ne peut exister sans :

```text
SignalCandidate
SignalScore
RiskDecision
ExecutionPlan
IdempotencyKey / cloid
KillSwitchState
ReconciliationState
AuditLogEvent
```

Si un seul objet manque, refuser.

## A6.4 Tout signal doit avoir une raison explicite

Un signal doit finir dans un de ces états :

```text
REJECTED_WITH_REASON
OBSERVE_ONLY
PAPER_SIMULATED
TESTNET_BLOCKED_BY_DEFAULT
TESTNET_ALLOWED_AFTER_MANUAL_CONFIRMATION
```

Jamais de passage implicite.

## A6.5 Edge remaining obligatoire

Codex doit coder `edge_remaining` avant toute simulation d’ordre avancée.

```text
Si edge_remaining <= 0 : rejet obligatoire.
Si un coût est inconnu : ajouter uncertainty_penalty.
Si uncertainty_penalty trop élevée : rejet obligatoire.
```

## A6.6 Paper trading pessimiste obligatoire

Le paper executor doit être défavorable par défaut :

```text
ajouter spread
ajouter slippage
ajouter latency penalty
simuler partial fill
simuler non-fill
simuler sortie moins favorable
soustraire les fees
journaliser chaque hypothèse
```

Interdit : paper trading “parfait” qui remplit toujours au mid.

## A6.7 Wallet scoring : caps de sécurité

Même si un wallet a un excellent PnL :

```text
FLAG_MARTINGALE_LIKE -> score max 60
FLAG_SINGLE_BIG_WIN -> score max 65
FLAG_LOW_SAMPLE_SIZE -> score max 55
FLAG_ILLIQUID_MARKETS -> score max 60
FLAG_STYLE_DRIFT -> statut OBSERVE_ONLY
```

## A6.8 Exit engine obligatoire

Codex ne doit jamais créer une entrée sans plan de sortie.

Un `ExecutionPlan` doit contenir :

```text
entry_rule
partial_take_profit_rule
stop_loss_rule
trailing_rule
time_stop_rule
leader_reduce_exit_rule
leader_close_exit_rule
emergency_exit_rule
```

## A6.9 Testnet verrouillé

Un ordre testnet requiert :

```text
HL_ENV=testnet
HL_ENABLE_TESTNET_EXECUTION=true
--confirm-testnet-only
cloid présent
scheduleCancel actif si configuré
risk_decision.approved == true
kill_switch.active == false
reconciliation_state.clean == true
mainnet URL absente du client d’exécution
```

## A6.10 `cloid` et idempotence

Tout ordre testnet doit avoir un `cloid` déterministe :

```text
cloid = hash(run_id + signal_id + side + coin + intended_size + intended_price + attempt_number)
```

Si le même `cloid` existe déjà, ne pas recréer d’ordre.

## A6.11 Schedule cancel / dead man’s switch

Si `schedule_cancel_enabled_testnet=true`, Codex doit :

```text
programmer scheduleCancel avant ou immédiatement autour de toute session testnet
renouveler proprement si session longue
annuler la session si scheduleCancel échoue
journaliser le trigger count si disponible
```

## A6.12 Interdiction de confusions plateforme

Si Codex écrit l’une des phrases suivantes, la livraison est invalide :

```text
acheter Yes/No sur Hyperliquid
negative risk Hyperliquid
merge Hyperliquid
Polymarket testnet Hyperliquid
MEXC wallet public scanning
```

## A6.13 Lots de développement imposés

Codex doit avancer par lots et ne pas mélanger exécution testnet avec collecte/scoring.

Ordre imposé :

```text
1. Scaffolding + sécurité
2. REST read-only
3. DB + raw JSON
4. Wallet deltas
5. Wallet scoring
6. Signal scoring
7. Risk engine
8. Paper executor
9. Exit engine
10. Reports
11. WS market
12. WS shortlist
13. Testnet locked
```

## A6.14 Tests V6 obligatoires

Codex doit ajouter les tests V6 du README, notamment :

```text
test_signal_rejected_if_edge_remaining_negative
test_partial_fill_pessimistic_model
test_non_fill_recorded_not_ignored
test_wallet_martingale_caps_score
test_testnet_order_requires_confirm_testnet_only
test_cloid_required_for_testnet_order
test_idempotency_prevents_duplicate_testnet_order
```

## A6.15 Règle finale Codex

```text
Le meilleur bot n’est pas celui qui trade souvent.
Le meilleur bot est celui qui refuse correctement presque tout,
mesure honnêtement l’edge restant,
et ne teste en mock USDC que les rares signaux qui survivent à tous les garde-fous.
```



---

# SUPPLÉMENT AGENTS V7 — Règles Codex pour maximiser l’edge testnet sans danger

> Ce supplément ne remplace aucune règle précédente. Il ajoute les règles V7 pour que Codex travaille comme un ingénieur trading-system prudent : objectif de performance **en mock USDC/testnet**, jamais promesse de gain réel.

## V7.0 — Périmètre absolu

```text
Plateforme codée : Hyperliquid uniquement.
Mode d’exécution : testnet/mock USDC uniquement.
Mainnet : lecture seule uniquement.
Polymarket : casebook documentaire uniquement.
MEXC : hors code.
Claude/LLM : hors hot path.
```

Un agent ne doit pas créer de module Polymarket/MEXC exécutable dans le MVP, sauf simulateur documentaire explicitement désactivé.

## V7.1 — Règle “max gains” acceptable

Interpréter “max de gains” comme :

```text
maximiser edge_remaining en simulation/testnet
+ réduire les pertes évitables
+ améliorer la qualité des sorties
+ augmenter la précision des refus
+ ne jamais relâcher les garde-fous
```

Il est interdit d’interpréter “max gains” comme :

```text
augmenter le levier ;
baisser les seuils de sécurité ;
ignorer le slippage ;
ignorer la latence ;
trader plus souvent sans edge ;
coder du mainnet ;
promettre un profit garanti.
```

## V7.2 — Edge Gate obligatoire

Aucun signal ne peut devenir `PAPER_TRADE` ou `TESTNET_ALLOWED` sans calcul de :

```text
edge_remaining_bps
copy_degradation_bps
estimated_slippage_bps
spread_bps
latency_decay_bps
exit_cost_bps
uncertainty_penalty_bps
```

Si `edge_remaining_bps <= min_required_edge_bps`, décision obligatoire :

```text
REJECT_EDGE_TOO_WEAK
```

## V7.3 — Skill vs luck obligatoire

Un agent doit pénaliser un wallet si :

```text
sample_size_too_small
one_big_win_dependency
pnl_hhi_too_high
recent_expectancy_negative
martingale_pattern_detected
copy_degradation_high
exit_quality_bad
```

Ajouter les décisions :

```text
REJECT_SAMPLE_TOO_SMALL
REJECT_ONE_BIG_WIN_WALLET
REJECT_MARTINGALE_PATTERN
REJECT_WALLET_DEGRADED
```

## V7.4 — Interdiction de copie naïve

Codex ne doit pas implémenter un simple :

```text
if wallet buys then buy
```

Il doit implémenter :

```text
if wallet_signal
   and wallet_score_ok
   and signal_fresh
   and price_not_chased
   and liquidity_ok
   and edge_remaining_ok
   and risk_engine_ok:
       allow paper/testnet candidate
else:
       reject with reason
```

## V7.5 — Pullback mode plutôt que chase

Si le prix a déjà bougé trop loin depuis l’entrée du leader, Codex doit préférer :

```text
WAIT_FOR_PULLBACK
```

ou :

```text
REJECT_PRICE_ALREADY_MOVED
```

Jamais “acheter quand même pour ne pas rater”.

## V7.6 — Sorties obligatoires

Le code doit prévoir au minimum en paper/testnet :

```text
EXIT_LEADER_REDUCE
EXIT_LEADER_CLOSE
EXIT_PARTIAL_TP_1
EXIT_TRAILING_STOP
EXIT_MAX_HOLD_TIME
EXIT_EDGE_DECAY
EXIT_STOP_LOSS
EXIT_KILL_SWITCH
```

Toute position simulée/testnet doit avoir un plan de sortie avant entrée.

## V7.7 — Testnet order safety

Un ordre testnet doit exiger :

```text
HL_ENV=testnet
HL_ENABLE_TESTNET_EXECUTION=true
--confirm-testnet-only
risk_engine_allowed=true
kill_switch=false
cloid présent
idempotency_key présent
max_size respectée
scheduleCancel prévu si ordres ouverts
```

Sans cela : refus.

## V7.8 — Nouvelles décisions de signal obligatoires

Ajouter aux enums :

```text
REJECT_EDGE_TOO_WEAK
REJECT_PRICE_ALREADY_MOVED
REJECT_COPY_DEGRADATION_TOO_HIGH
REJECT_EXIT_NOT_CLEAR
REJECT_CROWDING_RISK
REJECT_WALLET_DEGRADED
REJECT_SAMPLE_TOO_SMALL
REJECT_ONE_BIG_WIN_WALLET
REJECT_MARTINGALE_PATTERN
REJECT_UNKNOWN_POSITION_STATE
REJECT_ORDERBOOK_STALE
WAIT_FOR_PULLBACK
WAIT_FOR_CONFIRMATION
EXPIRED
```

## V7.9 — Nouvelles commandes CLI à prévoir

```bash
python -m hl_observer wallet-backfill --address 0x...
python -m hl_observer wallet-state --address 0x...
python -m hl_observer wallet-promote --address 0x... --dry-run
python -m hl_observer signal-watch
python -m hl_observer pullback-watch
python -m hl_observer compare-exits
python -m hl_observer no-trade-report
python -m hl_observer edge-report
python -m hl_observer promote-testnet-candidates --dry-run
python -m hl_observer codex-audit
```

## V7.10 — Tests V7 obligatoires

```text
test_wallet_not_promoted_with_small_sample
test_wallet_penalized_for_one_big_win
test_wallet_penalized_for_martingale_pattern
test_wallet_degraded_after_recent_negative_expectancy
test_signal_rejected_when_edge_remaining_below_threshold
test_signal_rejected_when_price_already_moved
test_signal_waits_for_pullback_when_chase_too_high
test_signal_expires_when_pullback_ttl_exceeded
test_cluster_signal_penalized_by_crowding
test_copy_size_capped_by_orderbook_depth
test_exit_on_leader_reduce
test_exit_quality_vs_mfe_calculated
test_paper_executor_uses_pessimistic_fill_model
test_testnet_order_requires_confirm_testnet_only
test_testnet_order_uses_cloid_idempotency
test_schedule_cancel_requested_when_testnet_orders_open
test_reject_if_orderbook_snapshot_stale
test_reject_if_agent_wallet_used_as_account_address
```

## V7.11 — Règle de livraison par lots

Codex doit livrer en lots courts, jamais tout en vrac :

```text
Batch 1 sécurité/config/CLI
Batch 2 REST read-only + DB raw
Batch 3 wallet backfill + deltas
Batch 4 scoring skill-vs-luck
Batch 5 signal engine + edge_remaining
Batch 6 paper trading pessimiste
Batch 7 dashboard/reports
Batch 8 testnet locked
Batch 9 replay/backtest
```

Chaque batch doit finir par :

```text
pytest
safety-audit
résumé français
liste fichiers modifiés
confirmation mainnet impossible
risques restants
```

## V7.12 — Règle finale

Le meilleur agent n’est pas celui qui code le plus de trades.

```text
Le meilleur agent est celui qui empêche les mauvais trades,
mesure l’edge réel,
prouve les résultats en mock USDC,
et refuse toute action dangereuse.
```
---

# SUPPLÉMENT AGENTS V8 — Règles Profitability-Max pour Codex

## A8.1 Objectif de l’agent

Codex doit optimiser le projet pour :

```text
- meilleurs wallets ;
- meilleurs signaux ;
- meilleurs prix d’entrée ;
- meilleures sorties ;
- meilleur edge_remaining ;
- meilleur refus des mauvais signaux ;
- meilleurs résultats paper/testnet ;
- sécurité stricte ;
- mock USDC uniquement pour l’exécution.
```

Codex ne doit pas coder un simple copy bot. Il doit coder un système de décision mesurable.

## A8.2 Mots d’ordre

```text
Measure first.
Reject by default.
Edge remaining rules.
Exit quality matters.
Paper must be pessimistic.
Testnet must be locked.
Mainnet execution is out of MVP.
```

## A8.3 Contrat de signal obligatoire

Chaque signal doit contenir :

```python
SignalCandidate(
    id: str,
    source_wallet: str,
    coin: str,
    side: Literal["long", "short"],
    signal_type: Literal["open", "add", "reduce", "close", "flip"],
    leader_entry_price: Decimal | None,
    observed_price: Decimal,
    timestamp_ms: int,
    signal_age_ms: int,
    wallet_score_v8: float,
    signal_score_v8: float,
    edge_remaining_bps: float,
    estimated_fee_bps: float,
    estimated_spread_bps: float,
    estimated_slippage_bps: float,
    estimated_latency_decay_bps: float,
    orderbook_depth_usdc: float,
    crowding_score: float,
    exit_plan_id: str,
    decision: SignalDecision,
    reject_reason: str | None,
)
```

Sans ces champs, pas de décision.

## A8.4 Gates Profitability-Max

Avant `PAPER_TRADE` :

```text
wallet_score_v8 >= config.min_wallet_score
signal_score_v8 >= config.min_signal_score
edge_remaining_bps > config.min_edge_remaining_bps
signal_age_ms <= config.max_signal_age_ms
copy_degradation_recent <= config.max_copy_degradation_bps
wallet_degradation_score <= config.max_wallet_degradation_score
exit_plan_quality >= config.min_exit_quality_score
orderbook_depth_usdc >= config.min_orderbook_depth_usdc
spread_bps <= config.max_spread_bps
slippage_bps <= config.max_slippage_bps
```

Avant `TESTNET_ALLOWED`, ajouter :

```text
paper_normal_positive
paper_high_slippage_acceptable
paper_high_latency_acceptable
paper_thin_book_acceptable
reconciliation_ok
kill_switch_ok
schedule_cancel_ok
cloid_ok
reduce_only_exit_ok
```

## A8.5 Interdiction du copy aveugle

Interdit :

```text
if leader_trade_detected:
    place_order()
```

Obligatoire :

```text
leader_trade_detected
→ build_signal
→ score_wallet
→ score_signal
→ compute_edge_remaining
→ build_exit_plan
→ risk_engine
→ paper/testnet only
```

## A8.6 Edge remaining gouverne l’entrée

Codex doit faire de `edge_remaining_bps` la métrique économique centrale.

Si `edge_remaining_bps <= min_edge_required_bps`, décision :

```text
REJECT_EDGE_TOO_SMALL
```

Si `edge_remaining_bps <= 0`, décision :

```text
REJECT_EDGE_NEGATIVE
```

## A8.7 Paper trading pessimiste obligatoire

Le paper executor doit toujours supporter :

```text
normal
high_slippage
high_latency
thin_book
fast_reversal
partial_fill
non_fill
api_reject
ws_reconnect
```

Un paper trade affiché comme gagnant sans coûts pessimistes est incomplet.

## A8.8 Sortie obligatoire

Aucun signal `PAPER_TRADE` ou `TESTNET_ALLOWED` sans `exit_plan`.

Exit plan minimum :

```text
hard_stop
partial_take_profit
trailing_stop_after_tp1
leader_reduce_exit
time_stop
edge_decay_exit
kill_switch_exit
```

## A8.9 No-trade analytics obligatoire

Chaque refus doit être analysable après coup.

Créer :

```text
no_trade_decisions
no_trade_outcome_checks
missed_gain_bps
avoided_loss_bps
```

Objectif : réduire les faux refus et augmenter les pertes évitées.

## A8.10 Tests V8 obligatoires

Ajouter :

```text
test_edge_remaining_negative_rejected
test_edge_remaining_too_small_rejected
test_signal_decay_reduces_edge
test_late_signal_rejected
test_delayed_copy_expires
test_delayed_copy_cancels_if_price_runs
test_cluster_boost_requires_low_crowding
test_crowded_signal_penalized
test_one_big_win_wallet_penalized
test_martingale_wallet_penalized
test_wallet_degradation_blocks_testnet
test_exit_plan_required
test_partial_take_profit_plan_created
test_pessimistic_paper_worse_than_ideal
test_no_trade_decision_stored
test_no_trade_outcome_check_calculated
test_testnet_order_requires_cloid
test_testnet_order_requires_schedule_cancel
test_testnet_exit_reduce_only
test_mainnet_exchange_unreachable_from_any_executor
```

## A8.11 Règle d’écriture Codex

Codex doit livrer par lots. Après chaque lot :

```text
- fichiers modifiés ;
- tests ajoutés ;
- commandes exécutées ;
- risques restants ;
- prochaine étape.
```

Aucun lot ne doit contourner AGENTS.md.

## A8.12 Style de code attendu

```text
typed Python
Pydantic models
enums explicites
pas de décision implicite
logs structurés JSON
tests pytest
config YAML
SQLite MVP
pas de secrets en dur
pas de mainnet executor
```

## A8.13 Configuration minimale à créer

```yaml
profitability_max:
  min_wallet_score: 75
  min_signal_score: 80
  min_edge_required_bps: 8
  max_copy_degradation_bps: 7
  min_exit_quality_score: 65

risk:
  mode: paper
  mainnet_execution_enabled: false
  testnet_execution_enabled: false
  max_testnet_trade_size_usdc: 5
  max_signal_age_ms: 3500
  max_spread_bps: 6
  max_slippage_bps: 10
  min_orderbook_depth_usdc: 5000
  require_reduce_only_exits: true
  require_cloid: true
  require_schedule_cancel: true
```

## A8.14 Validation de livraison

Une livraison Codex est acceptable seulement si :

```text
pytest passes
doctor passes
safety-audit passes
no mainnet execution path exists
no secret committed
edge_remaining is implemented
paper pessimistic scenarios exist
testnet executor remains locked by default
README and AGENTS remain aligned
```
---

# SUPPLÉMENT AGENTS V9 — Instructions Codex Profit Engine

## A9.1 Objectif Codex V9

Codex doit travailler comme si l’objectif était de construire le meilleur système testnet possible :

```text
maximum edge mesuré
maximum qualité de wallet
maximum qualité d’entrée
maximum qualité de sortie
maximum qualité de refus
maximum qualité de simulation
minimum exposition opérationnelle
mock USDC uniquement
```

## A9.2 Interdiction du “simple copier-coller”

Codex ne doit jamais coder :

```python
if leader_trade:
    order()
```

Codex doit coder :

```python
signal = build_signal(leader_event)
wallet_score = score_wallet(signal.wallet)
lead_lag = compute_lead_lag(signal.wallet)
replicable = compute_replicable_pnl(signal.wallet)
edge = compute_edge_remaining(signal)
entry_plan = build_entry_plan(signal, edge)
exit_plan = build_exit_plan(signal)
decision = risk_engine.evaluate(signal, wallet_score, edge, entry_plan, exit_plan)

if decision == TESTNET_ALLOWED:
    testnet_executor.place_order_with_cloid_and_safety_gates(...)
```

## A9.3 Objets obligatoires

Créer ou prévoir ces objets :

```text
WalletProfile
WalletStyle
WalletScoreV9
LeadLagMetric
CopyHalfLifeMetric
ReplicablePnlMetric
SignalCandidateV9
EdgeEstimate
GainAssuranceScore
EntryPlan
ExitPlan
RiskDecision
PaperScenarioResult
TestnetExecutionPlan
PromotionLevel
```

## A9.4 Règles V9 de promotion

```text
DISCOVERED → BACKFILLED → SCORED → WATCHLIST → PREMIUM_WS → PAPER → TESTNET_SMALL → TESTNET_STRONG
```

Aucune promotion ne doit être implicite. Chaque promotion doit créer un `promotion_level_event`.

## A9.5 Gain Assurance Score obligatoire

Avant testnet :

```text
gain_assurance_score >= config.min_gain_assurance_score
edge_remaining_bps >= config.min_edge_remaining_bps
replicability_ratio >= config.min_replicability_ratio
exit_plan_score >= config.min_exit_plan_score
paper_pessimistic_ok == true
```

## A9.6 Lead-lag obligatoire

Un wallet ne peut pas être premium si ses entrées ne montrent pas un avantage temporel mesurable.

Stocker :

```text
forward_return_10s_bps
forward_return_30s_bps
forward_return_1m_bps
forward_return_5m_bps
post_entry_mae_bps
post_entry_mfe_bps
```

## A9.7 Style wallet obligatoire

Chaque wallet doit avoir un style :

```text
SCALPER_FAST
SWING_TRADER
BREAKOUT_TRADER
MEAN_REVERSION_TRADER
MOMENTUM_CHASER
LIQUIDITY_ABSORBER
HEDGER
MARTINGALE_AVERAGER
ONE_BIG_WIN
MARKET_MAKER_LIKE
EVENT_REACTIVE
UNKNOWN
```

Le style impacte le score de copiabilité.

## A9.8 Entry plan obligatoire

Décisions d’entrée :

```text
ENTRY_IMMEDIATE_IOC_SIM
ENTRY_LIMIT_JOIN_BID_ASK
ENTRY_DELAYED_PULLBACK
ENTRY_CONFIRM_BREAKOUT
ENTRY_SKIP_IF_CHASE
ENTRY_SCALE_IN_TESTNET_SMALL
```

Aucun signal ne passe en paper/testnet sans EntryPlan.

## A9.9 Exit plan obligatoire

Aucun signal ne passe en paper/testnet sans ExitPlan.

ExitPlan minimal :

```text
hard_stop
partial_tp
trailing_after_tp
leader_reduce_exit
edge_decay_exit
time_stop
kill_switch_exit
```

## A9.10 Strategy tournament

Codex doit prévoir un système de comparaison de variantes :

```text
immediate copy
delayed pullback
strict edge only
partial TP fast
cluster confirmation
```

Classement par :

```text
net_pnl_after_costs
profit_factor
max_drawdown
edge_remaining_avg
exit_quality
copy_degradation
no_trade_precision
```

## A9.11 Tests V9 obligatoires

Ajouter ces tests :

```text
test_gain_assurance_score_blocks_weak_signal
test_replicability_ratio_blocks_bad_wallet
test_lead_lag_required_for_premium_ws
test_wallet_style_affects_copyability
test_entry_plan_required_for_paper
test_exit_plan_required_for_paper
test_chase_detector_blocks_late_entry
test_profit_locking_prevents_full_giveback
test_strategy_tournament_selects_best_after_costs
test_promotion_event_created_on_level_change
test_no_testnet_without_pessimistic_paper_validation
test_testnet_trade_has_cloid_reconciliation_and_exit_plan
```

## A9.12 Livraison attendue

Codex doit finir chaque run par :

```text
Résumé français
Fichiers modifiés
Tests ajoutés
Tests exécutés
Garde-fous vérifiés
Ce qui améliore les gains testnet
Ce qui reste à optimiser
```


---

# SUPPLÉMENT AGENTS V10 — Profit Engine & Wallet Replication Lab

## A10.1 Mission Codex V10

Codex doit construire un système qui optimise les gains mesurables en mock USDC par la qualité de décision, pas par la prise de risque.

Objectif de codage :

```text
maximiser edge_remaining
maximiser replicable_pnl
maximiser exit_capture_ratio
maximiser no_trade_precision
minimiser copy_degradation
minimiser drawdown
minimiser crowding
minimiser trades tardifs
```

## A10.2 Interdiction du copy bot naïf

Interdit :

```python
if leader_trade:
    copy_trade()
```

Obligatoire :

```text
leader_trade
→ normalize event
→ classify wallet style
→ compute lead_lag
→ compute copy_half_life
→ compute replicable_pnl
→ compute gain_assurance_score
→ compute edge_remaining
→ choose entry plan
→ choose exit plan
→ risk gates
→ paper/testnet only
```

## A10.3 Contrat GainAssuranceSignal

Codex doit créer un modèle typé :

```python
class GainAssuranceSignal(BaseModel):
    signal_id: str
    wallet: str
    coin: str
    side: Literal["long", "short"]
    signal_type: str
    wallet_style: str
    wallet_score: float
    gain_assurance_score: float
    lead_lag_score: float
    copy_half_life_ms: int
    edge_remaining_bps: float
    replicable_pnl_estimate_bps: float
    entry_copy_degradation_bps: float | None
    expected_exit_capture_ratio: float
    market_regime: str
    entry_plan: str
    exit_plan: str
    decision: str
    reject_reason: str | None
```

## A10.4 Gates V10

Avant `PAPER_TRADE` :

```text
gain_assurance_score >= min_gain_assurance_score
edge_remaining_bps >= min_edge_remaining_bps
lead_lag_score > 0
copy_half_life_ms >= min_copy_half_life_ms
replication_ratio >= min_replication_ratio
entry_copy_degradation_bps <= max_entry_copy_degradation_bps
exit_plan exists
market_regime aligned
```

Avant `TESTNET_PRIORITY_SIGNAL` :

```text
paper normal positive
paper stress positive enough
strategy tournament rank acceptable
wallet not degraded
no reconciliation issue
no WS/API instability
cloid required
scheduleCancel required
reduceOnly exit required
```

## A10.5 Event sourcing obligatoire

Tout événement brut doit être stocké dans `raw_events` avant normalisation.

Codex doit préserver :

```text
source
exchange_ts
local_received_ts
payload_json
payload_hash
```

Les états doivent être reconstructibles depuis `raw_events`.

## A10.6 Truth hierarchy

Codex doit respecter :

```text
1. Hyperliquid raw API/WS
2. Normalized local state
3. Calculated metrics
4. External discovery sources
5. Viral/social claims
```

Un signal testnet ne doit jamais venir uniquement des niveaux 4 ou 5.

## A10.7 Tests V10 obligatoires

Ajouter :

```text
test_gain_assurance_score_orders_candidates
test_lead_lag_positive_required
test_copy_half_life_too_short_blocks_testnet
test_replicable_pnl_low_blocks_promotion
test_entry_copy_degradation_calculated_long
test_entry_copy_degradation_calculated_short
test_exit_capture_ratio_calculated
test_market_regime_mismatch_rejected
test_raw_events_append_only
test_replay_reconstructs_state_from_raw_events
test_external_sources_never_trigger_testnet_alone
test_strategy_tournament_ranks_by_stability_adjusted_pnl
test_mainnet_execution_still_impossible
```

## A10.8 Livraison Codex V10

Chaque livraison doit confirmer :

```text
mainnet execution impossible
testnet locked by default
mock USDC only
no secrets committed
raw events stored
edge_remaining implemented
gain_assurance_score implemented
exit plan required
pytest passed
safety-audit passed
```
