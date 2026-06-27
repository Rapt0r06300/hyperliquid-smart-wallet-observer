# Reprise Codex - HyperSmart V9 Scan/Admission

Date: 2026-06-20

## Etat livre

- Simulation officielle conservee: `LANCER_HYPERSMART.cmd` -> `tools/start_hypersmart_simulation.ps1` -> `src/hl_observer/ui/static/simulation_v2.html`.
- Aucune nouvelle simulation, aucun mode demo, aucun PnL fabrique.
- Admission V9 branchee dans `src/hl_observer/ui/routes.py` via `signals/fill_admission.py`.
- Les entrees passent par une porte unique: fraicheur, doublon, exotique, backfill trop vieux, sortie sans position.
- Les sorties leader REDUCE/CLOSE refonctionnent pour les positions paper consensus.
- `edge_remaining_bps=-9999` ne fuit plus dans le runtime simulation; les sorties suivent le leader avec `edge_remaining_bps=0.0` et contexte explicite.
- Diagnostic offre-vs-gates expose dans `/api/simulation/status` et visible dans `simulation_v2.html`.
- Poller renforce: `live-public-scan` a chaque cycle, `collect-all` periodique, `scrape-explorer` + `explorer-candidates` periodiques, `live-user-fills-scan` sur shortlist bornee.

## Points importants

- Plus de donnees fraiches ne garantit pas un PnL positif. Le bot reste deny-by-default et mesure honnêtement les refus.
- Le bottleneck doit maintenant etre lisible: `NO_DATA`, `SUPPLY`, `GATES` ou `OK`.
- L'ancien `logs/hl_observer.sqlite3` est encore detecte comme legacy runtime sous logs, mais il est exclu des archives propres.

## Tests et audits valides

- `python -m pytest -q`: 1334 passed.
- `python -m pytest -q tests/test_hypersmart_*.py` via expansion PowerShell: 264 passed.
- `python -m hyper_smart_observer.app.main --safety-check`: OK.
- `python -m hyper_smart_observer.app.main --audit-safety`: OK.
- `python -m hyper_smart_observer.app.main --archive-audit`: OK.
- `python -m hyper_smart_observer.app.main --runtime-check`: OK avec warning legacy DB dans logs.

## Prochaine priorite

1. Observer une vraie session live de 10 a 30 minutes.
2. Comparer `entry_supply_bottleneck`, `fresh_entry_diagnostics` et `filter_diagnostics`.
3. Si bottleneck `SUPPLY`: augmenter les sources read-only, enrichir coins/leader pool, verifier Explorer/WS.
4. Si bottleneck `GATES`: calibrer edge/liquidite/degradation sans forcer ni inventer de trade.
5. Brancher progressivement le `simulation_pipeline.run_paper_simulation_decision` complet pour remplacer les derniers bouts du scorer historique.

