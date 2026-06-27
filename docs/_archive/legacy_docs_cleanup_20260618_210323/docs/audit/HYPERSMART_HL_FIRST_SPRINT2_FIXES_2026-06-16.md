# Sprint 2 — Durcissement Hyperliquid-first (corrections) — 2026-06-16

SIMULATION ONLY. Read-only, paper/mock USDC, deny-by-default. Aucun ordre reel.

## M1 — `--audit-safety` borne (ne scanne plus 23 Go)

Cause racine : `archive_readiness()` et `scan_runtime_files()` utilisaient
`Path.rglob("*")`, qui DESCEND dans `data/` (23 Go), `runtime/` (7 Go) et
`logs/` (3 Go) avant tout filtrage -> l'audit ne terminait jamais.

Correctif :
- nouveau module `hyper_smart_observer/audit/bounded_walk.py` :
  - elague (prune) AU MOMENT de la descente : `.git, data, runtime, outputs,
    node_modules, __pycache__, .pytest_cache, .pytest_tmp*, .mypy_cache, ...` ;
  - limites defensives : `max_files` (200k), `max_bytes` (5 Go),
    `max_seconds` (deadline) ;
  - `stopped_reason` explicite : `"" | "max_files" | "max_bytes" | "deadline"`.
- `archive_readiness()` et `scan_runtime_files()` utilisent ce parcours borne
  (`stat_sizes=False`, deadline 6 s) ; `logs/` n'est plus traverse :
  detection "DB sous logs/" via un glob TOP-LEVEL uniquement.
- `RuntimeFileReport.stopped_reason` ajoute + expose dans `format_runtime_report`
  et dans le message `audit_databases`.

Resultat (sandbox, FUSE) :
- `--audit-safety` : timeout infini -> **6 s, exit 0**, 14/14 findings OK.
- `bounded_walk` racine : 906 fichiers, 0.23 s, 78 dossiers elagues.
- `archive_readiness` 0.15 s ; `scan_runtime_files` 0.14 s.
- Detection "DB sous logs/" preservee (test runtime_check vert).

## M2 — Garde-fou de fraicheur restaure dans LANCER_HYPERSMART.cmd

`HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=6000` restaure (le WIP dYdX l'avait
passe a 120000). Edition byte-level : CRLF + encodage UTF-8 preserves.
Commentaire corrige : cette variable EST lue par la stack hl_observer
(`signal_detector.py`, `ui/routes.py`) que ce launcher demarre — ce n'est pas
un no-op. `DYDX_MAX_SIGNAL_AGE_MS=120000` (moteur dYdX) laisse INTACT.

Test cible `test_single_hypersmart_launcher_exists_and_forces_simulation_mode` :
PASS.

A NOTER (suivi recommande, hors perimetre) :
- `tools/start_hypersmart_simulation.ps1` (ligne ~63) re-fixe
  `HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS = "30000"` au runtime : pour que le
  garde-fou 6 s soit EFFECTIF au lancement, aligner aussi le PS1. Non modifie
  ici (le PS1 fait partie du WIP dYdX).
- `test_start_script_initializes_everything_without_execution` echoue de facon
  PRE-EXISTANTE (drift du PS1 par le WIP dYdX : `MIN_EDGE_BPS="35"` absent).

## M3 — Harmonisation des reason codes (Option A)

`hyper_smart_observer/copy_mode/copy_models.py` :
- `OPEN_ORDERS_ONLY_NOT_EVIDENCE = NoTradeReason.OPEN_ORDERS_CONTEXT_ONLY`
- `REASON_CODE_ALIASES = {"OPEN_ORDERS_ONLY_NOT_EVIDENCE": ...}`
Le code existant `OPEN_ORDERS_CONTEXT_ONLY` est conserve ; le nom du brief est
un alias documente vers la MEME valeur canonique. Invariant inchange : un
openOrder seul ne produit JAMAIS de PaperIntent.

## M4 — Preuves ciblees

Nouveau `tests/test_audit_bounded_scan.py` :
- `test_bounded_walk_prunes_big_runtime_dirs` : data/logs/runtime/.git/__pycache__
  jamais enumeres ;
- `test_bounded_walk_stops_on_max_files` : stopped_reason="max_files" ;
- `test_bounded_walk_deadline_is_explicit` : stopped_reason="deadline" ;
- `test_scan_runtime_files_never_traverses_data` : DB sous data/ ignoree, DB sous
  logs/ (top-level) detectee.

Deja couverts par la suite existante : MarketMid fallback data_quality,
userFillsByTime truncation/window, WS isSnapshot dedupe, RiskEngine
deny-by-default, no /exchange, no Exchange SDK, dashboard read-only.

## M5 — Resultats des tests (sandbox, Python 3.10)

- Cible (bounded_scan + openOrders + audit_safety + dashboard_readonly +
  collector_readonly + risk_gates + no_exchange x2) : **21 passed**.
- Regression (runtime_check, archive_hygiene, audit_safety, database,
  dashboard_truth_audit, copy_mode, copy_preflight, single_launcher) :
  **37 passed, 1 failed** (le 1 = drift PS1 pre-existant, hors perimetre).

Note sandbox : le montage bindfs ne propage pas les mtimes de facon fiable ;
Python peut charger des .pyc obsoletes. Tests lances avec
`PYTHONPYCACHEPREFIX=/tmp/pyc` pour forcer une compilation fraiche. Sur la
machine Windows native (Py3.11), ce contournement est inutile.

## Securite (inchangee)

no /exchange operationnel, no private key, no signature, no order, no live
toggle, no fake dashboard data, no profit promise, no LLM hot path.
