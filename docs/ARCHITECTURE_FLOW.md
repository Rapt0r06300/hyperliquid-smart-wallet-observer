# HyperSmart — Carte de flux end-to-end (H1)

_Généré 2026-07-01. Read-only / paper-only. Décrit le flux réellement câblé du runtime `src/hl_observer`._

## Chaîne principale (data → dashboard)
```
[1] Collecte HL read-only
    hyperliquid/rest_info_client.py (REST /info)  +  realtime_monitor/ws_supervisor.py (WS)
    → sources/collection_recorder.py (provenance + source_health)
        │  source=live|snapshot ; timestamp ; freshness_ms
        ▼
[2] Normalisation + reconstruction de position
    normalization/reconcile.py, normalization/fill_inference.py
    → DeltaDetector / PositionLifecycle (OPEN/ADD/REDUCE/CLOSE/flip, size, entry price)
        ▼
[3] Features / microstructure
    features/orderbook_imbalance.py, features/basis.py, features/funding.py,
    features/microstructure.py, features/scan_features_schema.py, edge/fair_value.py
        ▼
[4] Signaux + scoring leaders
    scoring/wallet_score_v2.py, scoring/smart_money_filter.py, wallets/leader_hotness.py
    signals/entry_quality_gate.py, signals/source_reconcile.py, signals/eligibility.py
        ▼
[5] Gate de décision + risque (NoTrade-first)
    signals/ (gate unifié) + risk/microstructure_guard.py + risk/gates.py
    + risk/var_cvar.py + risk/adaptive_sizing.py + risk/correlated_exposure.py + risk/loss_halts.py
    edge/edge_calculator.py (edge net après frais/slippage/latence/dégradation copie)
        │  sinon → NoTradeDecision (raison codée) / INSUFFICIENT_DATA
        ▼
[6] Sizing paper (marge × levier) → PaperIntent
    paper_trading/ (paper_engine, sltp_runtime)
        ▼
[7] Exécution paper simulée → PaperFill / PaperPosition
    exec/slippage/fees ; partial fills / missed fills ; funding carry
        ▼
[8] Ledger = source unique de vérité (PaperLedgerEvent)
    paper_trading/ ledger + pnl_reconciliation + evidence/decision_ledger.py
        │  cash, positions, realized, unrealized, equity, drawdown, fees, funding
        ▼
[9] Audit + Dashboard + Exports (lisent LE MÊME ledger)
    audit/simulation_realism_audit.py, security/fake_data_scanner.py
    ui/routes.py (/api/v12/panels, /metrics, SSE), ui/sse_events.py
```

## Invariants de câblage
- **Provenance obligatoire** à chaque étage : `source`, `timestamp`, `freshness_ms`,
  `evidence_refs` ; donnée manquante/vieille → `INSUFFICIENT_DATA` / `NO_TRADE`.
- **Une seule vérité PnL** : dashboard, audit et exports convergent sur le ledger (étape 8).
- **Séparation stricte** LIVE / BACKTEST / REPLAY / TEST_FIXTURE (pas de mélange de PnL).
- **Deny-by-default** : aucun ordre réel, `real_execution=False` partout.

## Preuves E2E (tests qui traversent le flux)
- `tests/test_copy_run_fake_rest_broad_scan_end_to_end.py` — pipeline complet (REST fake → décisions).
- `tests/test_refactor_fusion_wallet_copy_e2e.py` — copy wallet bout-en-bout.
- `tests/test_refactor_fusion_arbitrage_e2e.py` / `_funding_e2e.py` — arbitrage/funding (fixtures labellisées).
- `tests/test_refactor_fusion_backtest_e2e.py` — replay sans lookahead.
- `tests/test_refactor_fusion_dashboard_e2e.py` — payload dashboard sans fake.
- `tests/test_refactor_fusion_no_real_trade_e2e.py` — preuve 0 ordre réel.

## Statut H1
- Flux **câblé et couvert** par des tests E2E existants → **DONE** (documentation).
- Reste (suivi ailleurs) : prouver la **parité live↔replay↔backtest** sur un flux enregistré
  (STEP 12, tâche I/parité) et resserrer la fenêtre de fraîcheur (bloc B).

## Réserve honnête
Cette carte décrit le câblage d'imports/flux ; certains modules restent en **shadow**
(non autoritatifs) — leur promotion est suivie en H3. « Câblé » ≠ « autoritaire sur le hot-path ».
