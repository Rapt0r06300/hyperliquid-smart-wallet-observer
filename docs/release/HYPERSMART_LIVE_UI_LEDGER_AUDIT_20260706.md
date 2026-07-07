# HyperSmart Live UI / Ledger Audit - 2026-07-06

## Contexte

Audit effectue pendant que le serveur local `127.0.0.1:8794` tournait depuis environ 30 minutes.

Objectif: expliquer pourquoi l'UI de simulation affichait des donnees incoherentes, des compteurs `0 / 0`, des logs vides et un PnL negatif mal explique, sans inventer de PnL et sans modifier l'historique.

## Constats live

- `GET /api/simulation/status` repond et contient la verite runtime vivante:
  - serveur actif;
  - moteur actif;
  - positions paper ouvertes;
  - ledger paper;
  - trades fermes;
  - win/loss stats;
  - source `UI_STATE_LEDGER_PROJECTION`.
- `GET /api/simulation/overview?limit=20` repondait avec un snapshot minimal et stale:
  - `overview_fast_snapshot=true`;
  - message `Nouvelle session; aucun evenement paper exporte pour le moment`;
  - aucun `bot_simulation`;
  - aucun `paper_ledger`;
  - aucun compteur closed/win/loss.
- Les fichiers dans `logs/logs a envoyer` etaient incoherents avec le runtime:
  - `simulation_snapshot_latest.json` faisait seulement 273 octets;
  - il ne contenait pas `bot_simulation`;
  - il ne contenait pas `paper_ledger`;
  - `simulation_decisions_latest.jsonl` et `simulation_decisions_append_only.jsonl` etaient vides.

## Cause racine 1 - snapshot stale prioritaire

Quand la base runtime SQLite devient tres grosse, `/api/simulation/overview` bascule en mode rapide pour eviter de bloquer le navigateur. Ce chemin lisait `logs/logs a envoyer/simulation_snapshot_latest.json` sans verifier suffisamment:

- age reel du snapshot;
- presence d'un `bot_simulation`;
- presence d'un `paper_ledger`;
- coherence avec `/api/simulation/status`.

Resultat: l'UI pouvait afficher un etat quasi vide alors que le moteur continuait de travailler.

## Correction 1 - fallback live state

Le routeur UI refuse maintenant un snapshot rapide si:

- il est plus vieux que `HYPERSMART_OVERVIEW_FAST_SNAPSHOT_MAX_AGE_MS` (60 s par defaut);
- il ne contient ni `bot_simulation` ni `paper_ledger`.

Si le snapshot est absent, vide ou perime, `/api/simulation/overview` construit une vue compacte depuis le `UiState` vivant:

- equity;
- realized PnL;
- unrealized PnL;
- open positions;
- ledger events;
- closed trade stats;
- paper ledger projection;
- export diagnostic vers `logs/logs a envoyer`.

Fichier principal:

- `src/hl_observer/ui/routes.py`

## Cause racine 2 - compteurs de trades non fusionnes cote JS

Le graphe utilise `/api/simulation/status` comme source rapide, mais le merge frontend ne copiait pas tous les compteurs:

- `closed_trades`;
- `winning_trades`;
- `losing_trades`;
- `flat_trades`;
- `winrate_pct`.

Resultat: l'UI pouvait afficher `0 / 0` alors que le ledger connaissait deja des trades fermes.

## Correction 2 - merge frontend complet

`mergeStatusWithFreshTick()` copie maintenant ces champs depuis le tick status et merge aussi `lastTick.bot_simulation` dans `merged.bot_simulation`.

Fichier principal:

- `src/hl_observer/ui/static/simulation_v2.html`

## Cause racine 3 - quality guard cristallisait des pertes nettes de frais

Le ledger live montrait de nombreuses sorties `QUALITY_GUARD_LEGACY_UNEVIDENCED` avec:

- gross PnL parfois tres proche de zero ou legerement positif;
- fee cost autour de 0.03 USDC;
- net PnL negatif apres frais.

Le quality guard fermait localement des positions legacy non confirmees, ce qui pouvait transformer une position encore vivante en perte realisee juste a cause des frais.

## Correction 3 - ne plus realiser les fee-drag losses par defaut

Le quality guard legacy:

- continue de fermer les positions quand le resultat net apres frais est positif;
- garde la position ouverte si la fermeture locale ferait une perte nette de frais;
- journalise `QUALITY_GUARD_HOLD_TO_AVOID_FEE_DRAG`;
- peut etre force en mode audit via `HYPERSMART_LEGACY_POSITION_QUALITY_GUARD_REALIZE_NEGATIVE=1`.

Nouveaux flags de lanceur:

- `HYPERSMART_LEGACY_POSITION_QUALITY_GUARD_REALIZE_NEGATIVE=0`
- `HYPERSMART_LEGACY_POSITION_QUALITY_GUARD_MIN_NET_PNL_USDC=0`

Fichiers principaux:

- `src/hl_observer/ui/status_routes.py`
- `tools/start_hypersmart_simulation.ps1`

## Activation UI

Le cache-buster du dashboard est passe de:

- `ui-graph-stable-20260630a`

a:

- `ui-ledger-live-20260706a`

Cela force Chrome a charger le JavaScript corrige au prochain lancement.

## Tests lances

Commandes ciblees:

```powershell
python -m pytest -q tests/test_ui_simulation_status_fast.py tests/test_ui_simulation_v9_filters.py tests/test_ui_overview_paper_ledger.py tests/test_hypersmart_v19_negative_pnl_audit.py
python -m pytest -q tests/test_hypersmart_single_launcher.py tests/test_launcher_guards_match_runtime.py tests/test_start_script_min_edge_bps_guard.py tests/test_start_script_preserves_6s_freshness_guard.py
python -m hl_observer audit-safety
python -m hl_observer safety-audit
```

Resultats:

- 55 tests UI/ledger/PNL cibles passent;
- 12 tests lanceur/guards passent;
- `audit-safety` OK;
- `safety-audit` OK.

## Limite importante

Le serveur qui tournait pendant l'audit avait deja charge l'ancien code en memoire. Les corrections ci-dessus seront actives apres redemarrage propre via:

```powershell
LANCER_HYPERSMART.cmd
```

L'historique PnL existant n'est pas efface ni maquille. Le but est de corriger les causes futures:

- overview stale;
- logs vides;
- compteurs faux;
- fermetures quality guard a perte nette de frais.

## Garde-fous confirmes

- Simulation locale uniquement;
- aucun ordre reel;
- aucune cle privee;
- aucune signature;
- aucun endpoint `/exchange` operationnel;
- aucun PnL invente;
- aucun graphe fake.
