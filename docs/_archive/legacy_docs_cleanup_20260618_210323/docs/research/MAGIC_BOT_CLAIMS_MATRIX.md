# Magic Bot Claims Matrix

Date: 2026-06-02

| Claim public | Source | Verifiable ? | Pertinent Hyperliquid ? | Fonction logicielle a creer | Risque | Statut |
|---|---|---|---|---|---|---|
| Scan de milliers de wallets | HyperTracker, public trades, copy bot articles | Partiel | Oui | Public trade discovery + priority queue | Rate limits, bruit | Implemented/strengthen |
| Classement top wallets | LearnWithMeAI, HyperTracker | Oui avec donnees | Oui | leaderboard selector + intelligence score | Survivorship bias | Implemented/strengthen |
| Detection wallets PnL eleve | Hyperliquid fills/closedPnl | Oui si historique disponible | Oui | closedPnl scoring | one-big-win | Implemented |
| Detection ouvertures/fermetures | Hyperliquid `userFills`, positions | Oui | Oui | delta detector + lifecycle | Contradictions fill/snapshot | Implemented/strengthen |
| Copy avec delai | Polymarket articles, HL repos | Oui en simulation | Oui | delay-aware SignalCandidate | Edge decay | Implemented |
| Profits eleves | Marketing pages | Non | Non comme promesse | Research report only | Misleading | Rejected |
| Pas de pertes | Marketing pages | Non | Non | Safety disclaimer | Dangerous | Rejected |
| Edge apres couts | Risk articles, internal design | Oui | Oui | `edge_remaining_bps` | Bad assumptions | Implemented/strengthen |
| Wallet cohorts | Analytics products | Partiel | Oui | consensus/cohort detector | Crowding | Implemented/strengthen |
| Leaderboards | Hyperliquid ecosystem | Oui | Oui | importer/selector | Incomplete public data | Implemented |
| Alerts temps reel | WS docs | Oui | Oui read-only | hot scanner | User-specific limits | Implemented/strengthen |
| Backtest | Public tooling | Oui localement | Oui | replay from deltas | Overfit | Implemented/strengthen |
| Paper portfolio | LearnWithMeAI | Oui | Oui | 1000 USDT local portfolio | Fake optimism | Implemented |
| No-trade filtering | Risk-control patterns | Oui | Oui | no-trade report | Too strict / too lax | Implemented/strengthen |
| One-big-win detection | Quant risk best practice | Oui | Oui | anti-luck filters | False negatives | Planned/partial |
| Drawdown/consistency | Quant risk best practice | Oui | Oui | wallet intelligence | Sample size | Planned/partial |
| Scraping explorer aggressively | User desire / marketing | Non safe | No | Import/manual observer only | ToS/rate abuse | Rejected |
| LLM in hot path | Claude stories | Technically possible | No | LLM-free hot path tests | Non-determinism | Rejected |
