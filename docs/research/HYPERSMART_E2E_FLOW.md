# E1 — Carte de flux end-to-end (gate → risk → sizing → ledger)

_2026-07-02. Venue = Hyperliquid, paper local, read-only. Tout le chemin de décision est câblé ; chaque étage est deny-by-default (flag OFF = comportement inchangé)._

## Chaîne de décision (chokepoints réels)
```
Collecte HL read-only            hyperliquid/ (/info) + realtime/ (WS) + collection/
  └─ garde liveness  ............ collection/source_liveness.py        (D2: LIVE/FIXTURE/STALE/EMPTY → NO_TRADE si pas live)
Normalisation / features ........ normalization/, features/ (OBI, microstructure, basis)
Scoring wallets ................. scoring/ (leader_quality, smart_money_filter, whale gate)
Edge net après coûts ............ edge/ (compute_net_edge 30bps + plancher USD) + backtest/cost_model (slippage depth-aware, latence)
GATE D'ENTRÉE (unifié) .......... signals/entry_gate_v2 + entry_gate_runtime  (A2/A3)
  profil strict optionnel ....... signals/gate_profile.py               (C1-C5: fraîcheur/OBI/consensus/calibration/régime)
  2e source (arb/funding) ....... signals/second_source_guard.py        (D3: >=2 sources sinon NO_TRADE)
       │  accepté ?  ── non ──►  NO_TRADE (raisons tracées)
       ▼ oui
RISK ENGINE (chokepoint) ........ strategies/models.approve_with_risk_and_gate  (A3)
  risk gate portefeuille ........ risk/risk_gate_runtime  (A5: halts jour/mois, drawdown kill, loss-streak, VaR)
  sizing ........................ risk/sizing_v2 (edge×confiance + cap corrélé) ; cap Kelly (F8)
       │  approuvé ?  ── non ──►  NO_TRADE (RISK_NOT_APPROVED + raisons)
       ▼ oui
PaperIntent → ApprovedPaperIntent → PaperSimConnector.apply_intent   (mirror_paper_executor.py)
  exits .......................... exits/exit_policy_runtime (A4: SL→BE→TP→TRAILING→TIME_STOP+ATR), scale_out grille (B5)
  re-entry cooldown .............. copy_mode/reentry_cooldown (B6)
PaperLedger (source de vérité) .. paper_trading/ + ledger/   (A6: accept/NO_TRADE + sizing tracés dans evidence)
Audit / convergence ............. audit/pnl_convergence (R15) + audit/mini_run_check (D4)
Dashboard read-only ............. ui/ (lit le même ledger)
Juge PnL ........................ backtest/pnl_from_logs + ab_report (profit factor)
```

## Invariants (prouvés par tests)
- Un `PaperIntent` n'est actionnable **que** via `approve_with_risk_and_gate` (chokepoint unique) — `is_actionable()` l'exige. Un refus (gate OU risk) = NO_TRADE, jamais un ordre.
- Tous les étages ajoutés sont **deny-by-default OFF** : sans flag, le pipeline est identique à l'existant.
- Ancrages E2E : `tests/test_entry_gate_wiring.py`, `test_exit_risk_runtime_wiring.py`, `test_refactor_fusion_*_e2e.py`.

## Flags d'activation (à valider en A/B avant de garder)
HYPERSMART_ENTRY_GATE_ENABLED · HYPERSMART_EXIT_POLICY_ENABLED · HYPERSMART_RISK_GATE_ENABLED · HYPERSMART_GATE_STRICT_PROFILE (+ seuils exits/risk).
