# HYPERSMART V19 - NEXT CODEX OBJECTIVE

Date: 2026-06-27

## Objectif exact

Continuer la fusion GitHub V19 dans HyperSmart sans creer une deuxieme
simulation. La simulation officielle reste celle du launcher local Hyperliquid,
avec vrais prix marche, PaperEngine local et aucun ordre externe.

## Etat actuel verifie

- `tests` V19 cibles: 16 passed.
- `safety-check`: OK.
- `audit-safety`: OK.
- PnL session observe par snapshot: `-0.325951 USDC`.
- Equity session: `999.674049 USDT`.
- Cause principale: couts/frais trop importants vs edge, liquidite trop faible,
  signaux mono-wallet trop faibles, edge model non fiable.
- `RiskEngineV19` bloque les nouvelles entrees via:
  - `FEE_DRAG_TOO_HIGH`
  - `EDGE_MODEL_UNRELIABLE`
- `session_pnl_guard` est branche dans `src/hl_observer/ui/routes.py`.

## Derniere passe Codex - Ollama local / IA shadow

Statut: DONE pour le portage local safe, PARTIAL pour le branchement decisionnel
avancé.

Livré:

- Ollama installe localement et modele `llama3.2:latest` disponible.
- `src/hl_observer/research/ollama_client.py` centralise les endpoints natif
  `/api/generate` et compatible OpenAI `/v1/chat/completions`.
- `src/hl_observer/research/ollama_preflight.py` valide que l'IA reste
  `paper_only=True`, `hot_path=False`, `can_create_trade=False`.
- `src/hl_observer/research/ollama_signal_rater.py` note les candidats en
  shadow et peut recommander un veto conservateur, sans jamais creer d'entree.
- `src/hl_observer/research/local_llm_explainer.py` filtre les hallucinations:
  mauvais actif, profit garanti, conseil financier, phrase non ancree sur le
  symbole observe => fallback regles deterministes.
- `logs/logs a envoyer/hypersmart_ia_explanations.json` regenere depuis le
  dernier snapshot session.

Tests:

- `tests/test_v14_ollama_integration.py`
- `tests/test_v13_calibration_explainer.py`
- bloc elargi V12/V13/V14: 50 passed.
- `safety-check`: OK.
- `audit-safety`: OK, `copy_mode_no_llm_hot_path`.

Important:

- L'IA locale ne doit pas devenir createur de position.
- Prochaine evolution autorisee: brancher son score en `shadow evidence` et
  veto conservateur observable dans le dashboard/logs, jamais comme signal
  unique d'entree.

## Rapports a lire avant de continuer

1. `docs/research/HYPERSMART_V19_GITHUB_FUSION_QUEUE.md`
2. `docs/research/HYPERSMART_V19_GITHUB_CODE_INTAKE.md`
3. `docs/research/HYPERSMART_V19_GITHUB_FUSION_MATRIX.md`
4. `data/reports/HYPERSMART_V19_NEGATIVE_PNL_AUDIT.md`
5. `docs/release/HYPERSMART_V19_MAX_SESSION_WORKLOG.md`

## Slices deja livrees dans cette session

### Slice 1 - Hummingbot-style connector architecture

Statut: DONE.

Livré:

- `ConnectorSnapshot` et `ReadOnlyConnector.snapshot_from_payload`.
- `HyperliquidReadonlyConnector` rattache au contrat read-only.
- `PaperSimConnector` local qui accepte seulement `ApprovedPaperIntent`.
- Evidence locale sur acceptation/refus paper.
- Tests:
  - `tests/test_v12_connectors_research.py`
  - `tests/test_v12_strategy_registry.py`
  - `tests/test_paper_engine_realized_unrealized_pnl_equity.py`

### Slice 2 - Hyperliquid/Drift depth average + partial fill guard

Statut: DONE/PARTIAL.

Livré:

- `simulate_depth_execution`.
- Detection `FILLED`, `PARTIAL_FILL`, `MISSED_FILL`.
- Refus des fills paper trop incomplets dans `PaperSimConnector`.
- Tests:
  - `tests/test_v12_connectors_research.py`

### Slice 3 - Harrier/CloddsBot depth gate

Statut: DONE/PARTIAL.

Livré:

- `depth_fill_guard` avec raisons `MISSED_FILL`,
  `PARTIAL_FILL_BELOW_FULL_COPY_STANDARD`, `DEPTH_SLIPPAGE_TOO_HIGH`.
- Tests:
  - `tests/test_v13_costs_features_optim.py`

## Prochaine vertical slice obligatoire

### Slice 4 - Brancher depth_fill_guard dans la decision runtime

Objectif:

- Quand `ui/routes.py` ou le pipeline runtime a des niveaux de carnet l2Book,
  appeler `depth_fill_guard` avant tout PaperIntent/PaperTrade.
- Ajouter `MISSED_FILL` / `DEPTH_SLIPPAGE_TOO_HIGH` dans les logs a envoyer.
- Verifier que le dashboard affiche la raison au lieu d'ouvrir un trade faible.

Modules cibles:

- `src/hl_observer/ui/routes.py`
- `src/hl_observer/copying/simulation_pipeline.py`
- `src/hl_observer/evidence/decision_ledger.py`

Tests minimum:

- `tests/test_ui_simulation_persistence.py`
- `tests/test_v9_simulation_pipeline_src.py`
- nouveau test ciblé si nécessaire.

### Mise a jour Codex - Slice 4 livree

Statut: DONE.

Livre:

- `OrderbookSnapshot` est lu dans `/api/simulation/overview`.
- Les derniers niveaux `l2Book` par coin sont parses en tuples `(price, size)`.
- Avant ouverture paper, la simulation calcule le notional reel controle par
  levier puis appelle `depth_fill_guard`.
- Si le carnet reel prouve un fill rate trop faible ou un slippage excessif,
  l'evenement reste `NO_TRADE` et logge `MISSED_FILL`,
  `PARTIAL_FILL_BELOW_FULL_COPY_STANDARD` ou `DEPTH_SLIPPAGE_TOO_HIGH`.
- Les evenements contiennent `depth_fill_ratio`, `depth_slippage_bps`,
  `depth_levels_consumed`, `depth_snapshot_id`.
- Si aucun carnet reel n'existe pour le coin, la simulation n'invente pas de
  profondeur et logge `NO_RECENT_L2BOOK_FOR_COIN`.
- Cycle d'import corrige: `paper_trading.__init__` ne charge plus
  `mirror_paper_executor` au simple import.

Modules touches:

- `src/hl_observer/ui/routes.py`
- `src/hl_observer/paper_trading/__init__.py`
- `tests/test_ui_simulation_persistence.py`

Validation:

- `tests/test_ui_simulation_persistence.py` + `tests/test_v13_costs_features_optim.py`
  => 47 passed.
- Bundle cible V12/V13/V14/UI => 83 passed.
- Famille HyperSmart => 281 passed.
- Suite complete locale => 1920 passed.
- `safety-check`: OK.
- `audit-safety`: OK.

### Slice 5 - Harrier/CloddsBot risk + microstructure

Sources:

- `https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits`
- `https://github.com/alsk1992/CloddsBot`

Transformer en HyperSmart local:

- OBI/depth guard plus strict;
- confidence calibration;
- VaR/CVaR paper;
- shadow promotion avant de desserrer les seuils.

Modules cibles:

- `src/hl_observer/features/orderbook_imbalance.py`
- `src/hl_observer/risk/depth_guard.py`
- `src/hl_observer/calibration/confidence_buckets.py`
- `src/hl_observer/risk/var_cvar.py`

## Commandes de verification

```powershell
$env:PYTHONPATH='src'
python -m pytest -q tests\test_hypersmart_v19_*.py
python -m hl_observer.cli v19-pnl-audit --output-dir data\reports
python tools\github_fusion_intake.py --network-read --output-dir docs\research
python -m hyper_smart_observer.app.main --safety-check
python -m hyper_smart_observer.app.main --audit-safety
```

## Garde-fous

- Simulation locale uniquement.
- Hyperliquid runtime par defaut.
- dYdX legacy/dormant/mockable.
- Aucune action externe argent-reel.
- Pas de fausse donnee.
- Pas de faux PnL.
- Pas de promesse de profit futur.
