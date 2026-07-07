# HYPERSMART OBSERVER — ROADMAP FUSION V26 (Hyperliquid, paper-only)
## « 24 repos GitHub → comportements portés, calibrés, câblés en autoritatif »

> **Venue : Hyperliquid uniquement.** Simulation paper locale, read-only, mark-to-market sur prix réels.
> **Successeur de** `HYPERSMART_FUSION_ROADMAP_V12.md` (fusion des 14 premiers repos). Cette V26 couvre les repos **15→39** de `runtime/research/github_repos_v24/`.
> **Zéro promesse de PnL.** Objectif : maximiser la probabilité d'un PnL paper positif réaliste (profit factor), jamais le garantir ni le maquiller.
> **Audit des lectures réelles** : `docs/audit/AUDIT_2026-07-03_GITHUB_REPOS_V26_INSPECTION.md` (aucun fichier non lu n'est cité comme lu).

---

## 0. CONSTAT CENTRAL (ce qui change tout)

L'inspection croisée repos ↔ `src/hl_observer` montre que **la plupart des idées existent déjà en modules… dormants** :
`funding/spike_detector.py`, `risk/atr_trailing_stop.py` (importé par personne), `risk/kelly_sizer.py`, `copying/kelly_sizing.py`, `arbitrage/orderbook_depth_pricer.py`, `copy_mode/cooldown.py`, etc.

**La valeur des 24 repos n'est donc pas « encore plus de modules »** (interdit par CLAUDE.md : pas de doublons, pas de 3ᵉ architecture). Elle est :
1. des **spécifications comportementales précises** (formules, seuils, ordres de vérification) pour calibrer et **promouvoir en autoritatif** les modules dormants ;
2. **4 comportements réellement manquants** : auto-unstuck, halt gradué, protections fenêtrées type freqtrade, barrières ajustées à la volatilité ;
3. des **jeux de tests** copiables (passivbot, hummingbot, djienne).

Rappel contexte : PF paper 0.34 avant fix V25 (gate liquidité inversé + SL 55 bps). Les lots ci-dessous attaquent les causes structurelles restantes : sorties synthétiques rigides, positions coincées, absence de mémoire des marchés perdants, sizing uniforme.

---

## 1. VERDICTS PAR REPO (15→39)

| # | Repo | Verdict | Ce qu'on prend |
|---|---|---|---|
| 15 | ChainInsighter/Solana-Copy-trading-bot | **SKIP_WITH_REASON** | Coquille marketing (5 fichiers TS, cœur absent). Rien d'original vs 17. |
| 16 | Immutal0/Solana-CopyTrading-Bot | **SKIP_WITH_REASON** | Même squelette que 15, quasi identique. |
| 17 | Rezzecup/whale-wallet-mirror-copy-trader | **PORT_BEHAVIOR** | RiskGate fail-fast (ordre : taille>0 → score → cap → solde) ; **slippage budgété par tier de wallet** ; `mirror_scale` proportionnel ; flag paper natif. |
| 18 | Neron888/Polymarket-copy-trading-bot | **UNAVAILABLE** | Repo supprimé/privé (vérifié 2026-07-03). |
| 19 | terauss/Polymarket-Copy-Trading-Bot | **UNAVAILABLE** | Repo supprimé/privé (vérifié 2026-07-03). |
| 20 | warp-id/solana-trading-bot | **INSPIRE_ONLY** | Pattern « filters/ » pré-trade composables (pool-size, burn, mutable…) → conforte notre pile de gates marché ; rien à copier tel quel (Solana-specific). |
| 21 | tony-42069/trader-tony-v4 | **INSPIRE_ONLY** | Sniper Rust Solana ; architecture APIs multiples. Cœur = exécution memecoin, hors venue. |
| 24 | JLowo/gengar_polymarket_bot | **INSPIRE_ONLY** | Concept « oracle lag » : référence rapide (Binance) vs venue lente. Chez nous = WS fills leaders vs REST positions — déjà exploité (V16). Confirme la priorité fraîcheur. |
| 25 | djienne/Polymarket-bot (APEX PREDATOR) | **PORT_BEHAVIOR** ★ | **Kelly fractionné complet** : f*=(p·b−q)/b, fraction 0.25, lookback 50, min 10 trades, edge<2 %→×1.0, Kelly négatif→×0.5, plafond ×2.0, persistance JSON. + **AutoOptimizer par régime de volatilité BTC** (bornes par paramètre). |
| 26 | Jonmaa/btc-polymarket-bot | **SKIP_WITH_REASON** | Arb « UP+DOWN <1 $ » spécifique binaires. Pas de contrepartie perp. |
| 27 | CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot | **INSPIRE_ONLY** | Détection divergence cross-venue même sous-jacent → idée de *feature contexte* (déjà couvert par `arbitrage/cross_source_comparator.py`). |
| 28 | Jackhuang166/hyberliquid-arbitrage-bot | **INSPIRE_ONLY** | Monitoring spread HL↔Bybit + dédup alertes. Trivial ; `hyperliquid_cex_spread_scanner.py` couvre déjà. |
| 29 | Jackhuang166/hyberliquid-arbitrage | **SKIP_WITH_REASON** | Doublon exact du 28 (mêmes fichiers). |
| 30 | rustjesty/hyperliquid-drift-arbitrage-bot | **PORT_BEHAVIOR** ★ | **Walk-the-book** (avg_price par niveaux + slippage bps vs best) ; **coût double-jambe** : 2×(fee_long+fee_short) ; gate `min_profit_usd` ; gate `max_slippage_bps` sur la **pire jambe**. |
| 31 | notlelouch/ArbiBot | **INSPIRE_ONLY** | Go, best bid/ask cross-exchange + net % après frais. Rien de neuf vs 30. |
| 32 | gajesh2007/funding-arb-bot | **PORT_BEHAVIOR** ★★ | **Le meilleur moteur du lot.** Entry : min edge bps → historique suffisant → **veto spike z-score (|edge−μ|/σ > 2 ⇒ refus)** → max positions → max notional → **veto tendance décroissante**. Exit : edge < seuil OU direction flip. Risk : kill-switch (3 échecs consécutifs / 10 par heure / max drawdown USD), distance de liquidation par jambe, détection de désynchronisation (drift) des jambes. |
| 33 | hummingbot/hummingbot | **PORT_BEHAVIOR** ★ | **TripleBarrierConfig** (SL/TP/time_limit/trailing{activation, delta}) + **`new_instance_with_adjusted_volatility(vol_factor)`** : toutes les barrières multipliées par le régime de vol. + `can_create_executor` : max exécuteurs par côté + **cooldown après signal**. |
| 34 | Drakkar-Software/Triangular-Arbitrage | **SKIP_WITH_REASON** | Triangulaire spot ccxt ; `triangular_graph.py` existe déjà chez nous, et hors périmètre copy perp. |
| 35 | enarjord/passivbot | **PORT_BEHAVIOR** ★★ | (1) **Wallet Exposure** WE=taille×prix_entrée/solde et **WEL par position = total/n** ; (2) **Auto-Unstuck** : réalisation partielle contrôlée des pertes, priorité au **moins sous l'eau**, budget de pertes plafonné à x % sous le **pic d'equity** ; (3) **enforcers** de dépassement d'exposition ; (4) **Equity Hard Stop Loss gradué** par côté (modes réduits → panic exit RED) avec **contrats de cooldown** ; (5) **TrailingPriceBundle** 4 valeurs (min_since_open, max_since_min, max_since_open, min_since_max) + tests NaN/Inf ; (6) **Forager** : sélection dynamique des marchés par vol/volume. |
| 36 | pydevtop/interexchange-arbitrage-bot | **SKIP_WITH_REASON** | README seul, zéro code. |
| 37 | ramilexe/crypto-arbitrage-bot | **SKIP_WITH_REASON** | Scanner TS multi-CEX + UI ; rien au-dessus de 30/32 ; protobuf MEXC hors sujet. |
| 38 | chainstacklabs/hyperliquid-trading-bot | **COPY_ADAPTED** | Pattern **RiskRule composable** (1 règle = 1 check, `evaluate()`+`get_status()`) ; distinction **ROE signé vs PnL notionnel** ; exemples HL natifs funding/WS (référence d'API). Grille = SKIP (on ne market-make pas). |
| 39 | RuggedJar/hyperliquid-trader | **UNAVAILABLE** | Repo supprimé/privé (vérifié 2026-07-03). |
| 22 | freqtrade/freqtrade | **PORT_BEHAVIOR** ★★ | **Protections** : StoplossGuard (N stops sous profit_limit dans fenêtre ⇒ halt global/marché), LowProfitPairs (marché cumulativement perdant ⇒ blacklist temporaire), MaxDrawdownProtection fenêtré, CooldownPeriod. **Pairlist filters** : VolatilityFilter, SpreadFilter, RangeStabilityFilter (marchés morts), AgeFilter, PerformanceFilter. (Module `edge/` historique supprimé upstream — ne pas le citer.) |
| 23 | OctoBot | **DEFERRED_WITH_PLAN** | Le clone = orchestrateur + docs ; la logique trading vit dans des packages pip séparés (octobot-trading) non clonés. Si besoin un jour : cloner `Drakkar-Software/OctoBot-Trading`. Rien d'exploitable ici sans mentir. |

★ = source majeure du plan. 3 repos morts, 6 skips justifiés, 0 fichier prétendu lu sans l'être.

---

## 2. LES LOTS V26 (ordre = impact PnL probable / effort)

Chaque lot : petits modules additifs sous `src/hl_observer/`, jamais d'édition de `cli.py`/`routes.py`, tests obligatoires, ledger comme seule vérité, contexts LIVE/BACKTEST/REPLAY/TEST_FIXTURE étanches. Une idée non câblée = `PARTIAL_NOT_WIRED` affiché tel quel.

### V26-L1 — Vetos d'entrée « funding sain + edge stable » (repo 32) — QUICK WIN
**Problème visé :** on entre encore sur des edges instables ou des fundings anormaux.
- Promouvoir `funding/spike_detector.py` + `funding_history_window.py` en **gate autoritatif** : refus si |funding − μ₂₄ₕ| > 2σ (raison `FUNDING_SPIKE`), refus si historique < N échantillons (`FUNDING_HISTORY_WARMUP`).
- Nouveau petit module `edge/edge_trend_veto.py` : sur les 6 dernières mesures d'edge net du signal, si (moy. 2ᵉ moitié − moy. 1ʳᵉ moitié) < −seuil ⇒ `EDGE_TRENDING_DOWN`, NO_TRADE.
- Vérifier que `compute_net_edge` consomme bien le **walk-the-book** (`arbitrage/orderbook_depth_pricer.py`) pour le slippage à la taille du fill, et le coût **double-jambe** si position hedgée (repo 30). Sinon, câbler.
**Tests :** spike refusé, warmup refusé, tendance descendante refusée, walk-book = source slippage, aucun ordre réel.

> **STATUT L1 (2026-07-04) : IMPLÉMENTÉ + TESTÉ (23 tests) — câblage final PARTIAL_NOT_WIRED (2 branchements côté Windows).**
> Livré : `signals/v26_entry_vetos.py` (EdgeTrendRecorder + funding_sanity + apply_v26_entry_vetos), `funding/funding_runtime_cache.py`, extension `signals/copy_decision.py` (checks 9-10), 3 codes taxonomie (`FUNDING_SPIKE`, `FUNDING_HISTORY_WARMUP`, `EDGE_TRENDING_DOWN`), hook opt-in dans `copying/realtime_magic_score.py` (flag `HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE`, défaut OFF), vue shadow dans `signals/shadow_wiring.py`.
> Reste (routes.py interdit d'édition ici, patch exact dans l'audit) : (1) passer `coin=str(row.coin)` au scorer ; (2) alimenter `funding_runtime_cache.push()` depuis la collecte funding.
> **Constat walk-the-book :** le chemin autoritatif utilise des coûts CONSTANTS (`slippage_bps=2.5`, `spread_bps=3.0` dans `RealtimeCopyRiskConfig`) ; `arbitrage/orderbook_depth_pricer.py` n'y est pas branché. Câblage réel → L2 (nécessite le carnet dans le hot path).

### V26-L2 — Barrières ajustées à la volatilité (repo 33 + `risk/atr_trailing_stop.py` dormant)
**Problème visé :** cause racine historique du WR 12,5 % = SL/TP synthétiques fixes sur entrées tardives.
- Nouveau `paper_trading/vol_adjusted_barriers.py` : structure TripleBarrier {SL, TP, time_limit, trailing{activation, delta}} × **facteur de volatilité** (ATR régime vs ATR référence), inspiré `new_instance_with_adjusted_volatility`.
- Câbler `risk/atr_trailing_stop.py` (aujourd'hui importé par personne) dans `sltp_runtime.py` via adaptateur, pas de doublon.
- Plancher de sécurité : SL jamais < k × spread courant (sinon bruit = stop-out).
**Tests :** barrières scalent avec vol_factor, plancher spread respecté, time_limit force la sortie, PnL long/short correct.

> **STATUT L2 (2026-07-04) : IMPLÉMENTÉ + TESTÉ (12 tests) + CÂBLÉ aux 2 sites d'appel.**
> Livré : `paper_trading/vol_adjusted_barriers.py` (MidVolEstimator par coin sur marks réels, `adjust_config` façon hummingbot, wrapper drop-in `apply_sltp_exits_vol_adjusted`), câblé par alias d'import dans `ui/status_routes.py` (chemin FAST_STATUS actif) et `ui/routes.py` (backups dans `runtime/backups/`). Flag `HYPERSMART_V26_VOL_BARRIERS` (défaut OFF = passthrough exact, testé). Plancher SL `HYPERSMART_V26_SL_FLOOR_BPS` (12 bps) au lieu de k×spread tant que le spread live n'est pas dans ce chemin.
> Écarts vs plan : time_limit non ajouté (le min_hold/catastrophic existant couvre déjà le time-based ; ajout ultérieur si le replay le justifie) ; `atr_trailing_stop` reste dormant (l'estimateur travaille sur les mids réels disponibles dans ce chemin, les chandelles n'y sont pas plumbées).
> **Walk-the-book (scorer d'entrée) : DEFERRED_WITH_PLAN** — l2Book est déjà fetché (`collection/collector.py`, `copying/simulation_pipeline.py`) et le côté exécution paper l'utilise ; il reste à router un snapshot de carnet dans la boucle de scan de routes.py puis `orderbook_depth_pricer` → `spread_bps`/`slippage_bps` dynamiques par candidat. Lot dédié (plomberie de données + tests).

### V26-L3 — Auto-Unstuck (repo 35) — comportement réellement manquant
**Problème visé :** positions coincées qui pourrissent l'equity et bloquent l'exposition.
- Nouveau `paper_trading/auto_unstuck.py` : (1) détecte les positions « stuck » (sous l'eau > seuil, âge > seuil, WEL atteint) ; (2) clôt **partiellement** à perte la position **la moins sous l'eau** d'abord ; (3) budget de pertes réalisées plafonné à `allowance_pct` sous le **pic d'equity** (défaut 1 %) — budget épuisé ⇒ plus d'unstuck tant que les profits n'ont pas reconstitué l'allowance.
- Chaque unstuck = événement ledger explicite (`UNSTUCK_PARTIAL_CLOSE`, avec cause, coûts, frais non doublés).
**Tests :** priorisation moins-sous-l'eau, plafond d'allowance strict, reconstitution par profits, événements ledger cohérents dashboard=audit.

### V26-L4 — Halt gradué GREEN/AMBER/RED + cooldown (repo 35 HSL)
**Problème visé :** le hard halt binaire (V25, 2,50 %) coupe tout ou rien.
- Nouveau `risk/graded_halt.py` en **wrapper additif** du halt existant : AMBER = réduction de taille + entrées interdites sur nouveaux marchés ; RED = sortie forcée (paper) + halt du côté concerné ; **contrats de cooldown** avant retour GREEN (pas de yo-yo).
- Signal = drawdown stratégie (realized+unrealized) du ledger, jamais un compteur parallèle.
**Tests :** transitions d'états, cooldown respecté, RED force exits, aucun bypass du halt V25 existant.

### V26-L5 — Protections fenêtrées par marché et globales (repo 22)
**Problème visé :** on re-trade des marchés qui viennent de nous coûter cher.
- Nouveau `risk/protections.py` (pattern RiskRule composable du repo 38) :
  - `StoplossGuardRule` : ≥ N sorties SL (profit < limite) dans les M dernières minutes ⇒ halt (global ou par marché) durée D ;
  - `LowProfitMarketRule` : profit cumulé d'un marché < seuil sur fenêtre ⇒ blacklist temporaire du marché ;
  - `WindowedMaxDrawdownRule` : DD sur les K derniers trades ⇒ pause ;
  - réutiliser `copy_mode/cooldown.py`/`reentry_cooldown.py` (pas de doublon) pour le cooldown post-trade.
**Tests :** un cas par règle + combinaisons, statuts exposés read-only au dashboard.

### V26-L6 — Kelly fractionné par leader (repo 25, câble l'existant)
**Problème visé :** sizing uniforme quel que soit le leader.
- Promouvoir `risk/kelly_sizer.py`/`copying/kelly_sizing.py` en **multiplicateur autoritatif** de la taille copiée, avec les garde-fous exacts d'APEX : fraction 0.25, lookback 50 trades **par leader**, < 10 trades ⇒ ×1.0, edge < 2 % ⇒ ×1.0, Kelly négatif ⇒ ×0.5, plafond ×2.0.
- Persistance des TradeRecords par leader (SQLite, contexte séparé LIVE vs REPLAY — jamais mélangés).
**Tests :** petits échantillons neutres, bornes, kelly négatif, séparation contexts, PnL source = ledger.

### V26-L7 — Budget de coûts par tier de leader (repo 17) + WE/WEL (repo 35)
- `edge/tier_cost_budget.py` : slippage/latence admissibles fonction du score leader (S/A/B), i.e. un leader S justifie 80 bps de budget, un B 30 bps — refus sinon (`COST_BUDGET_EXCEEDED`).
- Exposition : adopter la définition passivbot **WE = notionnel/solde non-levier** et **WEL par position = total/n_positions** en s'alignant sur le modèle marge×levier existant (`HYPERSMART_SIMULATION_LEVERAGE`), sans casser la compta actuelle.
**Tests :** budget par tier, WEL bloque l'ADD, cohérence avec exposition-marge existante.

### V26-L8 — Forager : sélection dynamique des marchés (repos 35 + 22)
- `signals/market_quality_score.py` : score composite volatilité (bornes min/max), volume, spread, **range stability** (élimine les marchés morts), âge du listing, performance passée du marché chez nous (`PerformanceFilter`).
- Top-K marchés autorisés, le reste = `MARKET_QUALITY_LOW`. Étend `is_exotic_market`, ne le remplace pas.
**Tests :** bornes, hystérésis (pas d'oscillation d'univers), read-only.

### V26-L9 — Harnais A/B REPLAY (validation honnête de tous les lots)
- Rejouer la **même fenêtre** de données réelles enregistrées avec chaque lot ON/OFF (contexte REPLAY, jamais mélangé au LIVE).
- Rapport par lot : PF, WR, DD max, nb trades, coûts totaux — publié dans `docs/audit/`. Un lot qui ne bouge pas le PF en replay est marqué tel quel (pas de storytelling).
**Tests :** étanchéité contexts, reproductibilité (seed), zéro écriture live.

---

## 3. MÉTRIQUES DE SUCCÈS (sans promesse)
- Cible de travail : **PF paper > 1.0 soutenu sur fenêtre glissante ≥ 100 trades**, DD max < halt AMBER, coûts totaux/trade en baisse vs V25.
- Vérité unique = ledger ; dashboard, audit, exports convergent ou le lot n'est pas DONE.
- Moins de trades acceptés qu'avant est un **résultat attendu et souhaité** (L1, L5, L8 réduisent le volume).

## 4. SÉCURITÉ (inchangée, non négociable)
Aucun ordre réel, aucun `/exchange`, aucune clé/signature/wallet, aucun dépôt/retrait. Tous les lots = lecture publique + simulation locale. `PaperIntent`/`PaperTrade` ≠ ordres. Donnée douteuse ⇒ `NO_TRADE`/`INSUFFICIENT_DATA`.

## 5. ORDRE D'EXÉCUTION PROPOSÉ
L1 (1 séance) → L2 (1) → L5 (1) → L3 (1-2) → L9 dès L2 en place, puis en continu → L4 → L6 → L7 → L8.
Chaque lot livré = code + tests + doc + câblage (ou `PARTIAL_NOT_WIRED` explicite) + entrée audit.

---

## 6. STATUT GLOBAL (2026-07-04) — ROADMAP V26 : TOUS LOTS LIVRÉS

| Lot | Statut | Module principal | Flag d'activation |
|---|---|---|---|
| L1 vetos funding/edge | ✅ câblé | `signals/v26_entry_vetos.py` | `HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE` |
| L2 barrières volatilité | ✅ câblé | `paper_trading/vol_adjusted_barriers.py` | `HYPERSMART_V26_VOL_BARRIERS` |
| L3 auto-unstuck | ✅ câblé (pipeline exits) | `paper_trading/auto_unstuck.py` | `HYPERSMART_V26_AUTO_UNSTUCK` |
| L4 halt gradué | ✅ câblé (entrées + exits) | `risk/graded_halt.py` | `HYPERSMART_V26_GRADED_HALT` |
| L5 protections freqtrade | ✅ câblé (ledger→veto) | `risk/protections_v26.py` | `HYPERSMART_V26_PROTECTIONS` |
| L6 Kelly par leader | ✅ câblé (sizing scorer + routes `leader_wallet`) | `risk/kelly_leader_book.py` | `HYPERSMART_V26_KELLY_LEADER` |
| L7 budget tier + WE/WEL | ✅ câblé (veto scorer) | `edge/tier_cost_budget.py` | `HYPERSMART_V26_TIER_COST_BUDGET` |
| L8 qualité marché top-K | ✅ câblé (observation auto + veto) | `signals/market_quality_score.py` | `HYPERSMART_V26_MARKET_QUALITY` |
| L9 harnais A/B replay | ✅ livré (CLI + enregistreurs) | `backtesting/ab_flag_replay.py` | `HYPERSMART_V26_RECORD_CANDIDATES` (collecte) |
| Reliquat walk-the-book | ✅ câblé (poller l2Book + coûts live scorer) | `collection/l2_snapshot_cache.py` | `HYPERSMART_V26_BOOK_POLLER` + `HYPERSMART_V26_LIVE_BOOK_COSTS` |

Architecture de câblage : entrées via le hub `apply_v26_entry_vetos` (appelé par le scorer autoritatif) ;
exits via `apply_sltp_exits_vol_adjusted` → `v26_exit_pipeline` (books L5/L6/L8 nourris du ledger,
halt L4, unstuck L3). Tous flags OFF par défaut = comportement V25 strictement inchangé (testé).
Taxonomie NO_TRADE : 70 codes. Kelly : déviation APEX assumée (edge négatif prouvé ⇒ ×0.5, pas neutre).

**Mode d'emploi L9 (mesure honnête avant activation générale)** :
1. `HYPERSMART_V26_RECORD_CANDIDATES=1` + relancer le launcher → collecte `runtime/replay/*.jsonl` (24-48 h) ;
2. `set PYTHONPATH=src && python -m hl_observer.backtesting.ab_flag_replay --candidates runtime/replay/candidates.jsonl --marks runtime/replay/marks.jsonl --out docs/audit/AB_REPLAY_RESULT.json` ;
3. activer en live uniquement les flags dont le bras B améliore le PF en replay. Aucune promesse de PnL.
