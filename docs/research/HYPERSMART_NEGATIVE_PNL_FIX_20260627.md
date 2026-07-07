# HyperSmart - Correctif PnL negatif et reprise Claude - 2026-06-27

## Contexte

La simulation Hyperliquid locale affichait un PnL regulierement negatif malgre un scanner actif. Les logs recents indiquaient que le moteur acceptait quelques entrees, mais que les pertes nettes etaient amplifiees par :

- des signaux souvent limites par les frais et la degradation de copie ;
- des refus massifs `EDGE_REMAINING_TOO_LOW`, `LIQUIDITY_TOO_LOW`, `COPY_DEGRADATION_TOO_HIGH`, `PRICE_DEVIATION_TOO_HIGH` ;
- des sorties/reductions leader rejouees en perte ;
- une taille de position qui ne se reduisait pas assez apres une sequence de pertes ;
- une IA locale entrainee sur des echantillons defavorables mais non promue, donc mal visible dans l'UI ;
- un rapport d'audit securite bloque par une archive `logs.zip` posee a la racine.

Le correctif reste strictement local et paper-only : aucune cle, aucune signature, aucun ordre reel, aucun `/exchange`.

## Corrections code

### 1. Sizing adaptatif paper

Nouveau module :

- `src/hl_observer/simulation/adaptive_paper_sizing.py`

Fonction :

- lit les sorties paper `LOCAL_REPLAY` deja realisees ;
- calcule la serie de pertes/gains consecutive ;
- combine edge restant, liquidite, consensus wallets et equity courante ;
- reduit la marge virtuelle apres pertes ou session negative ;
- refuse proprement si la taille devient inferieure au minimum paper.

Objectif : ne pas continuer a rejouer des entrees pleine taille apres plusieurs pertes.

### 2. Branchement dans la simulation existante

Fichier modifie :

- `src/hl_observer/ui/routes.py`

Le sizing adaptatif est appele juste apres acceptation du signal et juste avant l'ouverture de position virtuelle. Il ne change pas le template de simulation et ne cree aucune simulation parallele.

Champs ajoutes dans les evenements :

- `adaptive_sizing`
- `adaptive_size_reason`
- `requested_margin_usdt`
- `final_margin_usdt`
- `cap_margin_usdt`
- `consecutive_losses`
- `consecutive_wins`
- `confidence`
- `size_pct`
- `session_pnl_usdt`

### 3. Logs enrichis pour analyse externe

Fichier modifie :

- `src/hl_observer/ui/simulation_log_export.py`

Les logs `logs/logs a envoyer` exportent maintenant les champs de sizing adaptatif avec les decisions. Cela permet d'expliquer pourquoi une entree a ete reduite ou refusee.

### 4. Lanceur unique synchronise

Fichiers modifies :

- `LANCER_HYPERSMART.cmd`
- `tools/start_hypersmart_simulation.ps1`
- `tools/hypersmart_simulation_poll_loop.ps1`

Activation par defaut :

- `HYPERSMART_ADAPTIVE_PAPER_SIZING=1`

Le poller expose aussi `adaptive_paper_sizing` dans les metriques runtime pour que les snapshots montrent la configuration effective.

### 5. Panneau IA corrige

Fichier modifie :

- `src/hl_observer/ml/model_panel.py`

Correction :

- le panneau IA peut maintenant afficher un rapport d'entrainement non promu quand un chemin de rapport est fourni ;
- il n'affiche plus par erreur un rapport global quand un test ou un appel demande explicitement un etat vide ;
- l'IA reste lecture seule et non autoritaire tant qu'elle ne bat pas la baseline.

### 6. Hygiene archive

Action non destructive :

- `logs.zip` a ete deplace depuis la racine vers `logs/logs a envoyer/attachments_archives/logs.zip`.

Raison :

- l'audit securite echouait sur `archive_hygiene` parce qu'un ZIP etait a la racine ;
- aucun fichier n'a ete supprime.

## Tests lances

Commande :

```powershell
$env:PYTHONPATH='src'; python -m pytest -q tests\test_pnl_loss_fixes.py tests\test_v9_sl_tp.py tests\test_v9_sltp_runtime.py tests\test_hypersmart_single_launcher.py tests\test_hypersmart_simulation_diagnostic_logs.py tests\test_runtime_session_logs.py tests\test_v13_recorder_extract.py
```

Resultat :

- `39 passed`

Commande :

```powershell
$env:PYTHONPATH='src'; python -m pytest -q tests\test_realtime_magic_score.py tests\test_exit_expectancy.py tests\test_v15_exit_sizing.py tests\test_v15_entry_quality.py
```

Resultat :

- `42 passed`

Commande :

```powershell
$env:PYTHONPATH='src'; python -m pytest -q tests\test_no_exchange_sdk_imports_or_actions.py tests\test_no_fake_chart_or_fake_position_data.py tests\test_dashboard_no_fake_paper_positions.py tests\test_paper_engine_realized_unrealized_pnl_equity.py
```

Resultat :

- `6 passed`

Securite :

```powershell
$env:PYTHONPATH='src'; python -m hyper_smart_observer.app.main --safety-check
$env:PYTHONPATH='src'; python -m hyper_smart_observer.app.main --audit-safety
```

Resultats :

- `Safety check: OK`
- `audit-safety: OK`

## Ce que ce correctif ne garantit pas

Ce correctif ne force pas un PnL positif et ne fabrique pas de fausses bougies. Il rend le moteur plus prudent apres pertes, plus explicable et plus stable, mais le PnL depend toujours des donnees Hyperliquid reelles, de la fraicheur des signaux, de la liquidite et des mouvements de marche.

## Prochaine priorite exacte

1. Lancer une nouvelle session propre avec `LANCER_HYPERSMART.cmd`.
2. Laisser tourner au moins 30 a 60 minutes.
3. Envoyer `logs/logs a envoyer/simulation_decisions_latest.jsonl` et `simulation_resume_pour_chatgpt.md`.
4. Comparer :
   - taille demandee vs `final_margin_usdt` ;
   - `adaptive_size_reason` ;
   - PnL par coin ;
   - pertes apres `LOSS_STREAK_SIZE_REDUCED` ;
   - refus `EDGE_REMAINING_TOO_LOW` et `LIQUIDITY_TOO_LOW`.
5. Prochain bloc code recommande : optimiser les seuils par coin/regime a partir du ledger recent, pas globalement.

## Garde-fous confirmes

- Hyperliquid par defaut.
- Simulation locale uniquement.
- Aucun ordre reel.
- Aucun `/exchange` operationnel.
- Aucune signature.
- Aucune cle privee.
- Aucun wallet connect.
- Aucun faux PnL.
- Aucun faux chart.
- L'IA locale reste observation/rapport tant qu'elle n'est pas promue par tests.
