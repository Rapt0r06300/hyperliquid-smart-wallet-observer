# GitHub Settings Benchmark — réglages PnL extraits vs config actuelle

_2026-07-02. Source = fichiers réellement lus dans `runtime/research/github_repos_v24/`. Objectif : harmoniser les réglages qui pilotent le PnL dans la couche partagée (edge net après coûts), pour copy + arbitrage + funding. Aucune promesse de PnL._

## 1. Réglages extraits (repos, valeurs réelles)
| Repo | Réglage | Valeur | Rôle |
|---|---|---|---|
| gajesh2007/funding-arb | `STRATEGY__MIN_EDGE_BPS` | 20 | edge min (contexte funding-arb pur) |
| gajesh2007/funding-arb | `EXECUTION__SLIPPAGE_BPS` | 5 | slippage estimé |
| gajesh2007/funding-arb | `RISK__DRIFT_THRESHOLD_BPS` | 25 | sortie sur dérive delta-neutral |
| gajesh2007/funding-arb | `FUNDING_HORIZON_HOURS` | 24 | fenêtre rolling funding |
| rustjesty/hl-drift | `max_slippage_bps` | 10 | cap slippage avant fill |
| rustjesty/hl-drift | `min_profit_usd` | 1.0 | **plancher profit absolu (USD)** |
| rustjesty/hl-drift | `hold_time_sec` | 3600 | hold funding |
| rustjesty/hl-drift | coûts | `2×(fee_long+fee_short)` | round-trip 2 jambes |
| jackhuang/hl-arb | `SPREAD_THRESHOLD_PERCENT` | 5 | gate spread (large, spot/CEX) |
| tony-42069/v4 | SL / TP / trailing | 15% / 50% / 5% | exits |
| tony-42069/v4 | `MAX_HOLD_TIME_MINUTES` | 240 | hold max |
| freqtrade | `stoploss` / `trailing_stop_positive` | −10% / 0.5% | exits backtest |
| freqtrade | `max_spread_ratio` | 0.5% | gate spread |
| harrier | TP / SL défaut | 50% / 30% | exits |
| mlmodelpoly | `IMBALANCE_CONFIRM_THRESHOLD` | 0.10 | confirmation OBI |
| mlmodelpoly | `COOLDOWN_SEC` | 2.0 | anti-rafale |

## 2. Notre config actuelle (`hyper_smart_observer/dydx_v4/config.py`)
| Réglage | Valeur | Note |
|---|---|---|
| `min_edge_bps` | 3.0 | **plancher NET après coûts** (pas gross) — volontaire, figé par tests |
| `taker_fee_bps` / `maker_fee_bps` | 5.0 / 2.0 | réaliste Hyperliquid |
| `estimated_spread_bps` | 3.0 | |
| `estimated_slippage_bps` | 1.5 | |
| `total_round_trip_cost_bps` | ≈14.5 + latence + copy_degradation | `fee×2+spread+slip+latency+copy` |
| `max_spread_bps` | 45.0 | gate |
| `funding_edge_horizon_hours` | 1.0 | vs 24h chez gajesh/rustjesty (contexte funding) |
| `max_holding_hours` | 48.0 | vs 4h tony / 1h rustjesty funding |
| `market_side_min_edge_after_loss_bps` | 12.0 | durcissement post-perte (bon) |

## 3. Verdicts (portage)
- **Cost model** : déjà aligné sur le consensus (round-trip complet). `KEEP`. Aucun changement.
- **`min_edge_bps=3` (net)** : `KEEP`. NE PAS monter à 20 (celui de gajesh est un edge de funding-arb dédié, pas un net copy). Monter = risque « 0 trade » déjà vécu.
- **`min_profit_usd` absolu (rustjesty)** : `PORT_BEHAVIOR` recommandé — complément au gate bps pour filtrer les micro-notionnels où 3 bps net = quelques cents (rognés par arrondis/coûts fixes). N'affame PAS le bps. **Vérifier d'abord s'il existe déjà** (`HYPERSMART_SIMULATION_MIN_EXPECTED_EDGE_USDT` côté src).
- **Funding horizon 24h (gajesh/rustjesty)** : `DEFERRED_WITH_PLAN` — pertinent seulement quand l'arb funding live sera branché (STEP 11 PARTIAL). Aujourd'hui 1h suffit au copy.
- **Exits SL/TP/trailing (tony/freqtrade)** : `PORT_BEHAVIOR` prudent — la cause racine des pertes passées = SL/TP synthétiques sur entrées tardives (cf. winrate-root-cause). Le trailing 0.5% de freqtrade est intéressant MAIS à valider en backtest, pas en aveugle.
- **OBI confirm 0.10 (mlmodel)** : `INSPIRE_ONLY` — on a déjà `market_flow_min_imbalance=0.60` (concept différent, plus strict).
- **Spread gate 5% jackhuang** : `SKIP_WITH_REASON` — beaucoup trop large pour du perp Hyperliquid (notre 45 bps est déjà plus sain).

## 4. Conclusion honnête
Il n'existe pas de réglage externe qui rend mécaniquement le PnL positif. La couche coût/edge est déjà saine et harmonisée. Les vrais leviers PnL restent ceux déjà identifiés par le projet : discipline SL/TP sur entrées fraîches, fenêtre de fraîcheur, sizing, et surtout **latence live + 2ᵉ source réelle** (bloc B). Validation obligatoire par backtest/run Windows avant d'acter tout changement de valeur.

## 5. Sélection « meilleures idées » (réponse: choisir pour le bot)
Classées par rapport valeur-PnL / risque, pour intégration en harmonie (couche partagée) :

**RETENU — intégré cette session :**
- rustjesty `min_profit_usd` → **porté** dans `dydx_v4/edge_calculator.calculate_edge` sous `min_expected_edge_usdt` (défaut 0.0 = off ; env `DYDX_MIN_EXPECTED_EDGE_USDT`). Reason-code `EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS` aligné sur le runtime src. Filtre les micro-notionnels sans durcir le gate bps. Tests: `tests/dydx_v4/test_edge_min_expected_usdt.py` (3 passed).

**RETENU — prochaines vagues (PORT_BEHAVIOR, à valider en backtest avant activation) :**
1. freqtrade `trailing_stop_positive=0.5%` — trailing discipliné (protège les gains sans couper trop tôt). Le plus prometteur pour le PnL, MAIS à tester (cause racine passée = SL/TP synthétiques mal placés).
2. freqtrade lookahead/recursive analysis — garde anti-biais backtest (crédibilise le PnL simulé).
3. gajesh funding 24h rolling + spike detection — quand l'arb funding live sera branché (STEP 11).
4. rustjesty partial-fill guard sur jambe de hedge → risk event (réalisme exécution).
5. mlmodel/harrier OBI comme signal de confirmation (déjà partiellement présent).

**ÉCARTÉ (SKIP_WITH_REASON) :**
- jackhuang `SPREAD_THRESHOLD_PERCENT=5` (trop large pour perp HL).
- tony `COPY_TRADE_FEE_PERCENT=10` (frais business du bot source, non pertinent).
- Tout ce qui est Solana/Polymarket-spécifique (venue différente).

**RÈGLE D'OR** : chaque idée retenue passe par le DecisionEngine/RiskEngine et écrit dans le PaperLedger ; aucune ne bypasse l'edge net ni le no-real-trade. Validation PnL = backtest + run Windows, jamais en aveugle.
