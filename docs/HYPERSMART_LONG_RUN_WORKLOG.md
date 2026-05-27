# HyperSmart Long Run Worklog

Date: 2026-05-22

## Etat initial

- Depot deja modifie avant ce run; aucun reset, aucun clean, aucun push.
- DB detectees:
  - `data/hypersmart_observer.sqlite3`
  - `logs/hl_observer.sqlite3`
- Probleme observe: WinRAR ne peut pas archiver `logs/hl_observer.sqlite3` parce qu'un processus garde la base ouverte.
- Regle appliquee: une archive source propre ne doit jamais inclure `logs/`, `data/`, SQLite, WAL/SHM, caches, environnements virtuels ou secrets.

## Objectifs

- Corriger durablement l'hygiene runtime: DB HyperSmart dans `data/`, logs texte uniquement.
- Ajouter diagnostic runtime et scripts d'archive propres Windows.
- Etendre la chaine read-only: `/info`, explorer observer experimental, WebSocket monitor read-only.
- Ajouter discovery, lifecycle, ranking V2, patterns, backtesting local, dashboard read-only et audit securite.

## Garde-fous confirmes

- Aucun ordre reel.
- Aucun mainnet.
- Aucun testnet executor.
- Aucun endpoint trading operationnel.
- Aucun score converti en signal.
- Paper trading local seulement.

## Fichiers runtime detectes

Les fichiers runtime sont exclus des archives propres. `logs/hl_observer.sqlite3` est traite comme legacy runtime a sortir de `logs/` apres fermeture du processus qui le verrouille.

## Resultats du run

Le code ajoute un diagnostic `--runtime-check`, un rapport `--runtime-clean-report`, un audit `--audit-safety`, un export dashboard read-only et des scripts `tools/create_clean_archive.*`.

## 2026-05-25 copy-mode implementation run

Scope couvert depuis `HYPERSMART_MAGIC_BOT_RESEARCH_README.md`:

- Batch 1: `hyper_smart_observer/copy_mode` avec leaderboard shortlist,
  delta detector, edge remaining, SignalCandidate et no-trade report.
- Batch 2: `leaderboard_shortlist.json` runtime plus tables SQLite pour
  shortlist, leader snapshots, open-order snapshots, fill dedupe,
  copy_signal_candidates, no_trade_decisions et source_health.
- Batch 3: `copy-run --ws --duration-seconds N --dry-run` reste read-only et
  borne; le WebSocket manager existant conserve les limites shortlist.
- Batch 4: replay/backtesting local conserve dans `hyper_smart_observer/backtesting`.
- Batch 5: dashboard export avec copy status, top wallets followed,
  leaderboard shortlist, leader activity, latest deltas, signal candidates,
  no-trade report, edge remaining, copy degradation et safety audit.
- Batch 6: `promote-testnet-candidates --dry-run` est verrouille, promeut 0
  candidat et n'active aucun executor.

Validation:

- Tests cibles archive/runtime/copy/dashboard/audit: 20 passed.
- Tests HyperSmart cibles: 136 passed.
- Suite complete: 347 passed.
- Runtime check: une DB legacy reste dans `logs/hl_observer.sqlite3`, mais les
  archives propres l'excluent sans la supprimer.
- Safety audit: no exchange path, no signature calls, mainnet disabled,
  execution disabled, testnet disabled, copy mode sans LLM hot path.

## 2026-05-25 final archive/copy network-read hardening

Corrections ajoutees:

- `CREER_ARCHIVE_PROPRE.cmd` cree une archive propre sur le Bureau via
  `tools/create_clean_archive.ps1`.
- `tools/create_clean_archive.ps1` et `tools/create_clean_archive.py`
  refusent une sortie dans le projet, utilisent un staging temporaire et
  excluent `logs/`, `data/`, `.git/`, SQLite, WAL/SHM, `.env`, caches et
  archives imbriquees.
- `--archive-audit` pointe vers la derniere archive Desktop et verifie que
  son contenu ne contient aucun runtime.
- `copy-run --network-read` est branche sur le chemin `/info` read-only
  testable: shortlist -> allMids -> clearinghouseState -> userFillsByTime
  borne -> userFills -> openOrders/frontendOpenOrders -> snapshots -> deltas
  -> SignalCandidate -> edge_remaining_bps -> no_trade/PaperIntent local.
- Les deltas issus des fills et des positions sont stockes en `leader_deltas`.
- Le dashboard lit les vraies tables `leader_deltas`, `source_health` et
  `api_health`.

Validation finale:

- Tests HyperSmart: 142 passed.
- Suite complete: 353 passed.
- `--runtime-check`: root archives = 0, DB HyperSmart dans `data/`, warning
  legacy pour `logs/hl_observer.sqlite3`.
- `--audit-safety`: OK, aucun `/exchange`, aucune signature, execution et
  testnet disabled by default.
- Archive Desktop creee: `C:\Users\flo\Desktop\Projet_invest_clean_20260525_150837.zip`.
- Verification ZIP: 486 entrees, 0 entree interdite.

## 2026-05-26 shortlist perfection pass

Ajout de la passerelle locale `--build-shortlist-file`:

- importe des candidats depuis CSV/JSON/TXT;
- refuse les adresses tronquees;
- n'invente pas les metriques manquantes;
- ecrit `data/leaderboard_shortlist.json` ou un chemin choisi;
- persiste les entrees dans SQLite;
- reste sans reseau, sans ordre, sans testnet.

Fichier exemple: `config/leaderboard_candidates.example.csv`.

## 2026-05-26 copy preflight / bounded leaders

Ajouts:

- commande `copy-preflight --network-read`, sans appel reseau;
- rapport `data/reports/copy_preflight_report.{json,md}`;
- commande `--write-shortlist-template` pour produire un CSV local;
- limite `HYPERSMART_COPY_MAX_LEADERS_PER_RUN=3`;
- `copy-run --network-read` applique cette limite et journalise
  `RATE_LIMIT_GUARD` si la shortlist est plus large.

Validation:

- tests preflight/import/network-read: 8 passed.
