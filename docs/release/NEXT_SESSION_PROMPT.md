# HyperSmart — Prompt de reprise (prochaine session)

_2026-07-01._

## État
Runtime `src/hl_observer` mature. Blocs F→K (30-70) + finisseurs (71-80) traités par
vérification statique + 3 bugs réels corrigés. Suite Windows = 2080 passed.
Docs clés : `CLAUDE_CODE_STEP_PROGRESS.md`, `GITHUB_COVERAGE.md`, `ARCHITECTURE_FLOW.md`,
`CONFIG_FLAGS.md`, `DATA_CONTRACTS.md`, `FINAL_CLAUDE_CODE_REPORT.md`.

## Garde-fous (non négociables)
Read-only, paper-only, deny-by-default. Aucun ordre réel/clé/signature/wallet connect/dépôt.
Donnée manquante/vieille ⇒ INSUFFICIENT_DATA / NO_TRADE. Ne jamais inventer de PnL. Ne rien
supprimer brutalement. Terminer chaque réponse par la ligne sécurité.

## Priorités restantes (le vrai levier PnL)
1. **Bloc B** : prouver la latence sub-seconde du stream WS en run réel (`LANCER_HYPERSMART.cmd`
   + `live-user-fills-stream`), puis resserrer la fenêtre fraîche à ~4 s ; brancher
   arbitrage/funding live ou état vide honnête.
2. **Bloc C** : recalibrage walk-forward des seuils, IA entraînée sur trades à issues mixtes.
3. **Finir côté Windows** : H3 (shadow par module), K1 (revue complète), K3 (run prolongé),
   mini-run réaliste, tests round-trip des contrats.

## Rappel outillage
Le mount sandbox tronque les gros fichiers (`routes.py`, `log_metrics.py`,
`microstructure_guard.py`, `rest_info_client.py`) → faux positifs. Vérifier ces fichiers et
lancer `pytest -q` **sur Windows**. Ne pas lancer `ruff --fix` dans le sandbox.

## Commandes utiles (Windows)
- Lancer : `LANCER_HYPERSMART.cmd` (UI :8794 + poller + IA + stream).
- Tests : `python -m pytest -q`.
- Sécurité : `python -m hl_observer.cli safety-audit` / `audit-safety` / `doctor`.
- PnL : `python -m hl_observer.cli pnl-audit`.

---
## Prochaine session (mise à jour 2026-07-02)
Priorités restantes réelles (le reste est DONE/vert) :
1. **Bloc B — live > fixtures** : brancher 2ᵉ source arbitrage (CEX read-only) et historique funding live ; sinon état vide honnête (jamais de fake).
2. **Latence WS live** : prouver en run Windows (~1-2 s) puis resserrer la fenêtre fraîche.
3. **Convergence comptable** : migrer progressivement la compta de `dydx_v4/live_observer` vers le PaperLedger `src/hl_observer` (garder la réconciliation comme garde-fou).
4. **Suite complète** : `set PYTHONPATH=src && python -m pytest -q` sur Windows (sandbox tronque les gros fichiers).
Ne rien supprimer brutalement. Simulation/paper/read-only only.
