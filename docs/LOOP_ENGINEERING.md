# HyperSmart Loop Engineering

Ce module applique la logique "observer -> comprendre -> decider -> tester -> apprendre" en version HyperSmart.

## Doctrine

- Mainnet Hyperliquid: lecture seule.
- DecisionEngine: local, explicable, auditable.
- Testnet: verrouille par defaut.
- Fake adapter: tests unitaires et preuve de chaine uniquement.
- Hyperliquid testnet adapter: prepare, mais `READY_BUT_LOCKED_SIGNATURE_REQUIRED` tant que le sprint signature testnet n'est pas explicitement valide.
- Aucun PnL fake, aucun ordre mainnet, aucune cle privee, aucune signature dans le repo.

## Flux

```text
MainnetReadOnlyObserver
  -> CandidateFactory (userFills + position_deltas frais -> SignalCandidate)
  -> ResearchThesis
  -> LocalDecisionEngine
  -> TestnetSafetyGuard
  -> TestnetExecutor
  -> TestnetDecisionJournal
  -> LoopMemoryStore
  -> LoopDecisionTrace
  -> LearningSummary
  -> /api/loop/dashboard
```

## Fichiers

- `src/hl_observer/loops/models.py`: theses, feedback, learning summaries.
- `src/hl_observer/loops/engine.py`: orchestration de boucle.
- `src/hl_observer/loops/candidate_factory.py`: transforme des fills Hyperliquid lus en read-only et des `position_deltas` locaux frais en `SignalCandidate` mesurables.
- `src/hl_observer/loops/decision_trace.py`: relie candidat, decision, requete testnet preparee et statut pour audit/dashboard.
- `src/hl_observer/loops/input_diagnostics.py`: explique pourquoi la boucle a ou non recu des candidats exploitables.
- `src/hl_observer/loops/dashboard_payload.py`: payload JSON lisible par dashboard/agent.
- `src/hl_observer/loops/memory.py`: journal local `runtime/learning`.
- `src/hl_observer/testnet/*`: adapters, guard, executor, journal.

## Commandes

Lire le dernier rapport local:

```powershell
python -m hl_observer loop-learning-report
```

Lire le payload dashboard/agent de la derniere boucle:

```powershell
python -m hl_observer loop-dashboard-payload
```

Executer une boucle sur un fichier de `SignalCandidate` explicite, sans reseau:

```powershell
python -m hl_observer testnet-loop-dry-run --candidate-json .\runtime\candidate_examples.json
```

Prouver la chaine fake testnet en local:

```powershell
python -m hl_observer testnet-loop-dry-run `
  --candidate-json .\runtime\candidate_examples.json `
  --execute-fake-testnet `
  --dry-confirmed `
  --confirm-testnet
```

Observer Hyperliquid en lecture seule et construire des candidats depuis des `userFills` reels:

```powershell
python -m hl_observer testnet-loop-observe `
  --network-read `
  --wallets AUTO `
  --max-wallets 3 `
  --coins BTC,ETH,SOL,HYPE `
  --max-candidates 10 `
  --include-recent-deltas `
  --recent-delta-window-seconds 300
```

`AUTO` lit la shortlist locale des leaders selectionnes, bornee par `--max-wallets` (maximum CLI 10). Cette commande ne cree aucun ordre reel. Elle lit `/info`, cree des candidats locaux uniquement si des fills exploitables existent, complete avec des `position_deltas` locaux recents si disponibles, puis passe par `LocalDecisionEngine`. L'execution fake testnet reste separee et exige `--execute-fake-testnet --dry-confirmed --confirm-testnet`.

Lire le payload expose au dashboard local:

```powershell
python -m hl_observer loop-dashboard-payload
```

La route UI `/api/loop/dashboard` lit la meme source et la page `simulation_v2.html` affiche la boucle dans la carte "Boucle decision/testnet".

## Sorties

- `runtime/learning/loop_events.jsonl`
- `runtime/learning/latest_loop_result.json`
- `runtime/learning/latest_decision_trace.json`
- `runtime/learning/latest_loop_input_diagnostics.json`
- `runtime/learning/latest_loop_report.md`
- `logs/logs a envoyer/latest_loop_result.json`
- `logs/logs a envoyer/latest_decision_trace.json`
- `logs/logs a envoyer/latest_loop_input_diagnostics.json`
- `logs/logs a envoyer/latest_loop_report.md`
- `logs/logs a envoyer/testnet_decisions_latest.jsonl` selon l'encodage du dossier existant.

## Limites volontaires

- Le module ne cree de candidat que depuis des fills read-only, des `position_deltas` locaux frais ou depuis un JSON explicite.
- Les `position_deltas` trop vieux restent historises mais ne deviennent pas candidats par defaut.
- Si l'observation ne produit aucun fill exploitable, la boucle ecrit un etat vide honnete.
- Si aucun candidat n'est produit, `latest_loop_input_diagnostics.json` indique la cause observable (`NO_RECENT_POSITION_DELTAS`, `NO_WALLET_FILLS`, `READONLY_SOURCE_ERRORS`, etc.).
- Le vrai adapter Hyperliquid testnet ne signe pas encore et refuse les ordres: c'est voulu.
- Le module n'est pas une promesse de PnL positif; il sert a rendre les decisions mesurables et corrigibles.
