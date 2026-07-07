# Rapport final PnL — jugé au profit factor (jamais promis)

_2026-07-02. HyperSmart Observer — Hyperliquid, simulation paper locale, read-only._

## 1. Sécurité (non négociable) — VERT
`doctor` + `safety-audit` : mainnet_execution_disabled, testnet_disabled_by_default, info_endpoint_read_only, no_forbidden_mainnet_order_method, no_exchange_endpoint_in_runtime_source, live_executor_disabled_exists, security_tests_present — **tous ok**. **0 ordre réel, 0 clé, 0 signature, 0 dépôt/retrait.**

## 2. Baseline honnête mesurée (juge sur le vrai ledger)
`simulation_decisions_append_only.jsonl` (145 trades clos) : **profit factor 0,22 · PnL −4,09 USDC · winrate 20%**.
Lecture de trader : le système perd encore — winrate bas, pertes > gains. Ce n'est PAS un bug de comptabilité (convergence OK), c'est la **stratégie d'entrées/exits** — exactement ce que les phases A→D outillent pour corriger, et ce que seul un run avec flags activés + A/B peut améliorer.

## 3. Ce qui a été construit (codé + testé, deny-by-default OFF)
- Juge PnL (profit factor/drawdown/expectancy) sur logs réels + A/B — `backtest/`.
- Pipeline câblé au chokepoint unique : gate d'entrée → risk gate → sizing → exits composés → ledger — `strategies/models`, `mirror_paper_executor`, adaptateurs `*_runtime`.
- Machinerie de réglage : optimiseur profit-factor + sweeps + gardes OOS/anti-overfit + best_config — `optimization/`.
- Sélectivité : profil de gate strict + rapport sélectivité — `signals/gate_profile`, `backtest/selectivity_report`.
- Gardes live : liveness source, 2e source, mini-run, fenêtre fraîche, training readiness — D1-D5.
- Robustesse : scan read-only tolérant à la coupure réseau (état vide honnête).
Tests dédiés cette campagne : **68 passed** (+ suites moteur/backtest existantes).

## 4. Statut par phase
A (câblage) : DONE. B (réglage machinery) : DONE. C (sélectivité) : DONE. D (tooling live) : DONE ; **preuve live = run Windows**. E (finition) : DONE. F→M : planifiées, détaillées.

## 5. La vérité, sans promesse
Aucun logiciel ne garantit un PnL positif — le trading garde une incertitude irréductible. Le PnL actuel est négatif (PF 0,22). Le chemin réaliste pour le redresser : **activer les flags un par un, lancer baseline vs variante sur Windows, et ne garder que ce qui monte le profit factor en A/B** (out-of-sample, anti-overfit). Les gains les plus probables : exits propres (A/B sur trailing/BE/TP) + sélectivité (gate strict → moins de trades, PF plus haut). Le frein le plus dur : la latence live (D1).

## 6. Prochaine commande exacte (Windows)
```
set PYTHONPATH=src
set HYPERSMART_EXIT_POLICY_ENABLED=1
LANCER_HYPERSMART.cmd          REM produit un log "variante"
python -m hl_observer.backtest.pnl_from_logs baseline.jsonl variante.jsonl   REM verdict au profit factor
```
Ne garder le flag que si le verdict = KEEP_VARIANT.
