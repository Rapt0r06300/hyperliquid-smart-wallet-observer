# T44 — Runner de poll persistant (2026-07-08)

## Pourquoi
Mesures mini-T43 (session 2026-07-08 ~01h30, `poll N durations`) : poll stable à
**60-63 s** (pics 91 s quand plans + diagnostics tombent ensemble) pour ~15 s visées.
Décomposition mesurée : opportunity_report 15-16 s À CHAQUE poll, live_user_fills_scan
13-14 s (10 s d'écoute + spawn), live_public_scan 10,4 s (8 s + spawn), fusion 7-9 s,
scan_markets 6,5 s, copy_run 4-6 s. La taxe de démarrage Python à froid (~8 spawns ×
2-4 s) représente ~25 s/poll ; les deux écoutes WS (18 s incompressibles) étaient
séquentielles.

## Ce qui est livré
`src/hl_observer/runtime/persistent_poll_runner.py` — un SEUL process Python chaud :
- mêmes commandes CLI, mêmes argv, mêmes gardes (assert_mainnet_execution_disabled
  s'exécute à chaque invocation in-process) via typer CliRunner ;
- écoutes WS (public + userFills) en sous-processus PARALLÈLES au bloc local
  (plans/discover/scan-markets), jointes AVANT copy-run (dépendance fills → décision
  préservée) ; budget + kill si dépassement ;
- même engine status JSON (schéma identique, fusion_runtime_* préservés) = heartbeat ;
- même log live + mêmes métriques key=value + step_ms_* / poll_total_ms ;
- échec d'étape absorbé (log + metric step_failed_*), la boucle ne meurt jamais ;
- stop-file honoré ; self-restart tous les N polls (défaut 400) = garde-fou mémoire,
  exit code 3 → relance immédiate par le .ps1.

`tools/hypersmart_simulation_poll_loop.ps1` :
- mode persistant par DÉFAUT ; `HYPERSMART_PERSISTENT_LOOP=0` → boucle legacy
  intégralement conservée (rien de supprimé) ;
- watchdog externe : heartbeat engine status plus vieux que 600 s
  (`HYPERSMART_PERSISTENT_WATCHDOG_STALE_SECONDS`) → kill + relance.

## Attendu (à vérifier au prochain run, pas de promesse)
Suppression de la taxe de spawn (~25 s) + parallélisation WS (~10-14 s masquées) →
poll attendu ~25-35 s. La vérité sera le log `poll N durations` du prochain run ;
si opportunity-report reste >10 s à chaud, c'est SON contenu (lecture deltas 5000 +
consensus) qu'il faudra profiler (T45), pas l'orchestration.

## Tests (sandbox 3.10, fakes, zéro réseau)
`tests/test_persistent_poll_runner.py` : séquence + gating (plans/diag 1/5, collect
1/20), overlap WS joint avant copy-run, stop-file, étape en échec absorbée, schéma
engine status + préservation fusion, self-restart exit 3. 6/6 verts ; batterie élargie
23/23 (ws_stream, ws_first_plan, no_real_trade, paper_ledger, pnl_reconciliation).

## Sécurité
Aucun appel nouveau : orchestration de commandes read-only existantes. 0 ordre réel,
0 clé, 0 signature, 0 dépôt/retrait. Redémarrage `LANCER_HYPERSMART.cmd` requis.
