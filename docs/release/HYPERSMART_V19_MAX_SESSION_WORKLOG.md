# HYPERSMART V19 MAX SESSION WORKLOG

Date: 2026-06-27

## Objectif

Refonte anti-PnL negatif orientee logs reels de simulation, sans creer de
nouvelle simulation parallele et sans action externe reelle.

## Git initial

- `git status --short`: worktree tres charge, nombreuses modifications et
  nouveaux modules issus des sprints Claude/Codex. Aucune remise a zero.
- `git diff --stat`: diff index courant limite a `docs/llms.txt`,
  `runtime/ml/explanations_latest.json` et
  `runtime/models/trade_model_v13.json.history.jsonl`.

## Fichiers lus

- `AGENTS.md`
- `docs/HYPERSMART_FUSION_ROADMAP_V12.md`
- prompt V19 colle en attachment Codex
- `src/hl_observer/cli.py`
- `src/hl_observer/simulation/log_metrics.py`
- `src/hl_observer/simulation/loss_attribution.py`
- `src/hl_observer/simulation/decision_replay_analyzer.py`
- `src/hl_observer/optimization/profit_optimizer.py`
- `src/hl_observer/risk/loss_halts.py`

## Decision architecture

Le runtime actif du launcher/simulation est `src/hl_observer`. Les nouveaux
modules V19 sont donc ajoutes dans cette couche, sous forme de petits modules
importables, pour eviter un deuxieme logiciel parallele.

## Modules crees pendant ce run

- `src/hl_observer/analysis/negative_pnl_auditor.py`
- `src/hl_observer/analysis/v19_repo_matrix.py`
- `src/hl_observer/risk/risk_engine_v3.py`
- `src/hl_observer/risk/session_pnl_guard.py`
- `tools/github_fusion_intake.py`

## Modules branches / renforces

- `src/hl_observer/connectors/base.py`: ajout d'un `ConnectorSnapshot`
  read-only et d'un contrat `ReadOnlyConnector.snapshot_from_payload`.
- `src/hl_observer/connectors/hyperliquid_readonly.py`: connecteur
  Hyperliquid rattache au contrat read-only.
- `src/hl_observer/paper_trading/paper_connector.py`: nouveau connecteur
  paper local qui accepte seulement un `ApprovedPaperIntent`, simule un fill
  via le modele de couts et trace l'evidence sans aucune action externe.
- `src/hl_observer/paper_trading/exec_model.py`: ajout d'un simulateur de
  profondeur multi-niveaux avec prix moyen, partial fill et missed fill.
- `src/hl_observer/signals/depth_guard.py`: ajout de `depth_fill_guard`, qui
  refuse les entrées paper si le carnet ne peut pas remplir proprement.
- `src/hl_observer/ui/routes.py`: ajout du guard de PnL session juste avant
  l'entree paper. Si la session est deja perdante, le bot exige plus d'edge,
  plus de consensus et plus de liquidite avant de rejouer.
- `hyper_smart_observer/app/main.py`: pont CLI vers `src/hl_observer` pour
  exposer `v19-pnl-audit`, `v19-repo-matrix` et `v19-github-intake` depuis la
  commande historique.
- `src/hl_observer/analysis/negative_pnl_auditor.py`: lecture du snapshot
  portefeuille comme source PnL effective, et detection de divergence si les
  logs decisionnels ne contiennent pas le trade ferme.
- `tools/github_fusion_intake.py`: verification reseau GitHub des licences,
  generation du rapport de code intake et d'une file de fusion P0/P1.

## Rapports generes

- `data/reports/hypersmart_v19_negative_pnl_audit.json`
- `data/reports/HYPERSMART_V19_NEGATIVE_PNL_AUDIT.md`
- `docs/research/HYPERSMART_V19_GITHUB_FUSION_MATRIX.md`
- `docs/research/hypersmart_v19_github_code_intake.json`
- `docs/research/HYPERSMART_V19_GITHUB_CODE_INTAKE.md`
- `docs/research/HYPERSMART_V19_GITHUB_FUSION_QUEUE.md`

## Resultat concret PnL session observe

- Equity snapshot: `999.674049 USDT`.
- PnL net paper effectif: `-0.325951 USDC`.
- Trades fermes snapshot: `1`.
- Positions ouvertes snapshot: `0`.
- Frais detectes: `0.115326 USDC`.
- Fee drag ratio: `0.353814`.
- Top causes: `LIQUIDITY_TOO_LOW`, `EDGE_REMAINING_TOO_LOW`,
  `SINGLE_WALLET_EDGE_TOO_LOW`, `PRICE_DEVIATION_TOO_HIGH`,
  `COPY_DEGRADATION_TOO_HIGH`.

Conclusion: le probleme n'est pas seulement "pas assez de trades". Le moteur
voit beaucoup de candidats, mais la majorite est trop faible apres couts,
liquidite et degradation. La correction V19 ajoute donc un guard anti-redoublement
de perte au lieu d'ouvrir plus agressivement apres une session negative.

## Fusion GitHub V19

- 36 repos couverts dans `HYPERSMART_V19_GITHUB_FUSION_MATRIX.md`.
- 16 repos P0/P1 transformes en file de fusion dans
  `HYPERSMART_V19_GITHUB_FUSION_QUEUE.md`.
- Licences verifiees via API GitHub quand possible.
- Repos permissifs detectes et priorises pour adaptation testee:
  `hummingbot`, `rustjesty hyperliquid-drift-arbitrage-bot`, `CloddsBot`,
  `HarrierOnChain`, `MrFadiAi`, `txbabaxyz polyrec`, `Polymarket/agents`,
  `tradingview/lightweight-charts`, etc.
- Repos non disponibles, 404, GPL/AGPL ou non asserts: patterns reimplementes
  sans copie brute.

## Slices codees apres generation de la file

### Slice 1 - Hummingbot-style connector split

- `ReadOnlyConnector` observe seulement.
- `PaperSimConnector` simule localement seulement.
- `PaperIntent` doit passer par `approve_with_risk`.
- Evidence locale produite pour chaque fill/refus.

### Slice 2 - Hyperliquid/Drift depth-average + partial guard

- `simulate_depth_execution` consomme des niveaux `(price, size)`.
- Refuse `MISSED_FILL` si le carnet ne peut pas remplir assez.
- Signale `PARTIAL_FILL` si la copie ne peut pas être complete.
- Calcule un prix moyen de fill au lieu de prendre un mid idealise.

### Slice 3 - Harrier-style depth gate

- `depth_fill_guard` transforme la profondeur explicite en decision:
  `MISSED_FILL`, `PARTIAL_FILL_BELOW_FULL_COPY_STANDARD`,
  `DEPTH_SLIPPAGE_TOO_HIGH` ou acceptation.

## Bugs / risques trouves

- Beaucoup de refus sont deja diagnostiques par les logs, mais il manquait une
  vue unique qui consolide PnL, couts, timing, edge, wallets, coins et tournoi
  de strategies.
- La V19 demande de ne pas bannir les mots, mais de bannir les actions reelles.
  Les nouveaux modules gardent donc les concepts paper/mock, et ne declenchent
  aucune action externe.

## Actions de reprise

- Continuer la file `docs/research/HYPERSMART_V19_GITHUB_FUSION_QUEUE.md` dans
  l'ordre, repo par repo.
- Premier bloc suivant recommande: reprendre l'architecture connecteur/strategie
  Hummingbot en version `ReadOnlyConnector + PaperExecutionConnector`, puis
  verifier `tests/test_v12_strategy_registry.py`.
- Deuxieme bloc: reprendre le pattern Hyperliquid/Drift `depth average price`,
  `partial fill guard`, `reconciliation` dans `paper_trading/exec_model.py`.
- Troisieme bloc: renforcer `features/orderbook_imbalance.py` et
  `risk/depth_guard.py` avec les idees Harrier/CloddsBot.

## Tests lances

- `PYTHONPATH=src python -m pytest -q tests\test_hypersmart_v19_github_intake.py`
  -> `3 passed`.
- `PYTHONPATH=src python -m pytest -q tests\test_hypersmart_v19_negative_pnl_audit.py tests\test_hypersmart_v19_risk_engine_v3.py tests\test_hypersmart_v19_repo_coverage.py tests\test_hypersmart_v19_no_real_trade.py tests\test_hypersmart_v19_session_pnl_guard.py tests\test_hypersmart_v19_github_intake.py`
  -> `17 passed`.
- `PYTHONPATH=src python -m pytest -q tests\test_v12_connectors_research.py tests\test_v12_strategy_registry.py tests\test_paper_engine_realized_unrealized_pnl_equity.py`
  -> `20 passed`.
- `PYTHONPATH=src python -m pytest -q tests\test_v13_costs_features_optim.py tests\test_v12_connectors_research.py`
  -> `23 passed`.
- `python -m hyper_smart_observer.app.main v19-github-intake --network-read --output-dir docs\research`
  -> rapports GitHub et file de fusion regeneres.
- `python -m hyper_smart_observer.app.main --safety-check` -> OK.
- `python -m hyper_smart_observer.app.main --audit-safety` -> OK.
