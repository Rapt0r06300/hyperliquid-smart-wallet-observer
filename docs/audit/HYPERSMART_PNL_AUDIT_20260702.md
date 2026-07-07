# Audit HyperSmart — sécurité, santé, et étapes vers un PnL positif réaliste

_2026-07-02. Venue = Hyperliquid, paper local, read-only. Runtime = `src/hl_observer`._

> **Cadre d'honnêteté** : aucun système ne peut garantir un PnL « sûr et certain positif » — le trading a une incertitude irréductible. Cet audit vise à **maximiser la probabilité d'un PnL paper positif réaliste** et à supprimer ce qui le sabote. Jamais de promesse, jamais de chiffres maquillés.

## 1. Sécurité (no-real-trade) — VERT
`python -m hl_observer doctor` : mainnet_execution_disabled=ok, testnet_execution_disabled_by_default=ok, info_endpoint_read_only=ok, safety_audit_ok=ok. (Seul FAIL: `python_3_11_plus` = artefact sandbox 3.10 ; Windows OK.)
`python -m hl_observer safety-audit` : no_secret_patterns, env_not_committed, no_forbidden_mainnet_order_method, no_exchange_endpoint_in_runtime_source, live_executor_disabled_exists, security_tests_present = **tous ok**.
→ **0 ordre réel, 0 clé, 0 signature, 0 endpoint d'exécution.**

## 2. Santé du code (tests, cette session)
- Fondations/core + no-real-trade : 10 ✅ · Ledger/PnL/audit : 9 ✅ · Moteur (suite dydx legacy) : 348 ✅ · Arb/funding/backtest : 25 ✅ · Dashboard/safety/CLI : 38 ✅ · Nouveaux modules PnL : 71 ✅.
- Bugs réels corrigés : compat Python 3.10 (`datetime.UTC` non gardé ×3, docstring escape), + venue clarifiée (Hyperliquid vs dYdX legacy).

## 3. Ce qui est DÉJÀ solide (ne rapporte pas plus à retoucher)
Couche coût/edge (`edge/edge_net_v12`, plancher net 30 bps + plancher USD), fraîcheur (`freshness/signal_decay`, STALE_SIGNAL), SL/TP runtime (`paper_trading/sltp_runtime` 329 l.), microstructure (`features/microstructure` 192 l.), VaR/halts (`risk/var_cvar`, `risk/loss_halts`), calibration (`calibration/*`), no-lookahead (`backtest/no_lookahead_guard`).

## 4. Ce qui MANQUE pour maximiser la probabilité d'un PnL positif
| # | Manque | Impact PnL | Statut |
|---|---|---|---|
| A | Exits profonds : trailing discipliné + score qualité | **ÉLEVÉ** (cause racine des pertes passées) | **FAIT cette session** (`edge/exit_quality.py`) — reste à **câbler dans `sltp_runtime`** |
| H | Juge backtest : profit factor / drawdown / expectancy | **ÉLEVÉ** (sans mesure, on avance à l'aveugle) | **FAIT** (`backtest/experiment_runner.summarize_*`) — reste à brancher sur les logs réels |
| C | Gate d'entrée unique tracé (freshness×edge×liquidité×calibration) | Moyen-élevé | `signals/entry_quality_gate` mince (31 l.) → approfondir |
| E | Slippage dérivé de la profondeur réelle du carnet (pas constant) | Moyen | à implémenter (`features/basis`+orderbook) |
| I | Latence live ~1-2 s prouvée + fenêtre fraîche resserrée | **ÉLEVÉ (frein n°1 live)** | nécessite run Windows |
| G | Funding/arb live (2e source réelle) | Moyen (décorrélé) | fixtures seulement ; DEFERRED |

## 5. Étapes concrètes (ordre = rendement/risque)
1. **[FAIT] H** — juge backtest (profit factor). *Fait : `summarize_pnl` / `summarize_decisions` + 7 tests.*
2. **[FAIT] A** — trailing + score d'exit. *Fait : `TrailingState`, `should_exit_trailing`, `exit_quality_score` + tests.*
3. **Câbler A dans `sltp_runtime`** (drapeau env, défaut off) puis **A/B backtest** trailing on/off sur logs réels → garder si profit factor monte. *(PARTIAL_NOT_WIRED aujourd'hui.)*
4. **C** — approfondir `entry_quality_gate` en un verdict unique tracé.
5. **F** — ne promouvoir que les buckets de confiance calibrés (Brier bas).
6. **E** — slippage depth-aware + pénalité latence sur l'edge.
7. **I** — run Windows : prouver latence, resserrer fenêtre fraîche (le vrai frein live).
8. **Mini-run réaliste** : vérifier ledger = audit = dashboard sur données fraîches (convergence PnL).

## 6. Verdict honnête
Le logiciel est **sain et sûr** (0 ordre réel), la comptabilité est fiable, et les leviers PnL sont identifiés. Le chemin réaliste vers un PnL positif = exits propres (A, fait) mesurés par le juge backtest (H, fait), puis câblage + A/B + latence live. Aucune de ces étapes ne « garantit » le profit ; ensemble elles maximisent sa probabilité.
