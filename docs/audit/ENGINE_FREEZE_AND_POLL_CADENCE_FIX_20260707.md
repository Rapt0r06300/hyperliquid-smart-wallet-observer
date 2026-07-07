# Audit incident — « le moteur ne tourne plus / ne scanne plus rien » (2026-07-07 soir)

## Symptôme rapporté
Session relancée à 21:03. UI figée, aucune activité visible. Impression de moteur mort.

## Constat factuel (logs + engine status, aucune donnée inventée)
- Le poller n'était PAS mort : `runtime/data/hypersmart_engine_status.json` avançait
  (poll 2 à 21:10, poll 3 à 21:11, poll 4 à 21:13) pendant que les logs `.log` semblaient
  figés à 21:03:34 (buffering de la redirection PowerShell + cache mount).
- Cadence réelle mesurée : **~200 s par poll au lieu de 15 s** (~14 démarrages Python
  à froid séquentiels par poll, dont diagnostics lourds à CHAQUE poll : readiness sur le
  dossier `logs à envoyer` de 5,3 Go, warehouse-report ~32 s).
- Le **stream temps réel V16 était gelé depuis 21:03:27** : entré dans son segment de
  300 s, jamais sorti (ni ligne de reconnexion à 21:08:27, ni stats de sortie, 0 fill
  temps réel stocké). Chemin rapide mort en silence → plus aucune entrée fraîche.

## Causes racines
1. `wallets/user_fills_live.py` — `stream_user_fills_ws` :
   - `websockets.connect()` ouvert **sans timeout** : un connect DNS/TCP qui pend
     (déjà observé sur cette machine : getaddrinfo) gèle la coroutine pour toujours ;
     le `stop_event` (deadline 300 s) n'est jamais consulté pendant un connect bloquant.
   - `except TimeoutError` ne catche PAS `asyncio.TimeoutError` en Python 3.10
     (unifiés seulement en 3.11) : chaque période calme de 30 s forçait une
     reconnexion complète au lieu d'un idle.
2. `tools/stream_loop.ps1` faisait une confiance aveugle à la sortie du python
   (pas de watchdog) : un python gelé = stream mort jusqu'au prochain restart manuel.
3. `tools/hypersmart_simulation_poll_loop.ps1` payait à CHAQUE poll des étapes de
   plan/diagnostic (throughput-plan, fresh-scan-plan, fresh-data-plan,
   simulation-readiness, warehouse-report) alors que le cœur du poll est
   scan → copy-run → opportunity → fusion.

## Corrections livrées (100 % read-only, rien de supprimé)
1. `src/hl_observer/wallets/user_fills_live.py` :
   - timeout dur d'ouverture (`connect_timeout_s`, défaut 15 s) via
     `asyncio.wait_for(cm.__aenter__(), …)` ; fermeture bornée à 5 s ;
   - `except (TimeoutError, asyncio.TimeoutError)` pour l'idle recv (compat 3.10) ;
   - `recv_timeout_s` paramétrable (défaut 30 s, inchangé).
2. `tools/stream_loop.ps1` : watchdog — segment lancé via `Start-Process`, budget
   `duration + 120 s` (env `HYPERSMART_STREAM_WATCHDOG_GRACE_SECONDS`) ; dépassé →
   kill + relance loguée ; `python -u` + capture stdout/stderr par fichier segment
   (fini les logs muets) ; réaction au stop ≤ 5 s.
3. `tools/hypersmart_simulation_poll_loop.ps1` :
   - mini-T43 (Annexe B roadmap) : durée par étape loguée
     (`poll N durations: total=…ms step=…ms`) et exposée dans l'engine status
     (metrics `step_ms_*`, `poll_total_ms`) — on mesure avant d'optimiser ;
   - plans exécutés 1 poll sur 5 (`-PlansEveryPolls`, poll 1 inclus, gap-recovery
     conservé), diagnostics readiness/warehouse 1 poll sur 5
     (`-DiagnosticsEveryPolls`) ; tout reste exécuté régulièrement, rien de supprimé.

## Tests
- `tests/test_ws_stream.py` : 2 régressions ajoutées —
  `test_hanging_connect_never_freezes_stream` (connect qui pend → sortie propre bornée,
  échouait avant le fix) et `test_idle_recv_timeout_keeps_socket_alive_py310`
  (idle ≠ reconnexion sous 3.10). Résultat : 5/5 verts (sandbox, Python 3.10).
- Sous-ensemble sécurité ciblé relancé (voir rapport de session).

## Ce qui reste vrai / honnête
- La cadence attendue après correctif est ~60–90 s par poll (encore > 15 s visés) :
  le vrai chemin rapide est le stream persistant réparé ; la refonte T44
  (une seule boucle Python persistante au lieu de ~14 spawns) reste la cible.
- Le PnL et les décisions ne sont pas modifiés par ce correctif : uniquement transport,
  orchestration et observabilité. Aucun ordre réel, aucune clé, aucune signature.

## Action requise
Redémarrer `LANCER_HYPERSMART.cmd` pour charger le nouveau code (l'ancien stream
gelé sera tué par l'arrêt de session ; le watchdog protège les prochains segments).
