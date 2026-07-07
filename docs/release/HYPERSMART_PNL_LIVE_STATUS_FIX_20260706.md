# HyperSmart - Correctif PnL live/status du 2026-07-06

## Objectif

Stabiliser la chaine visible par l'utilisateur:

decision -> position paper locale -> ledger -> PnL -> dashboard -> logs a envoyer.

Le but n'est pas de forcer un PnL positif. Le but est que chaque gain, perte,
refus ou position ouverte soit explicable et relie a un evenement de ledger.

## Constats sur la session live analysee

- Le serveur `127.0.0.1:8794` repondait.
- `/api/simulation/status` indiquait environ `24` positions ouvertes.
- L'exposition ouverte etait autour de `959 USDT`, alors que le launcher promet
  des garde-fous plus prudents (`12` positions / `400 USDT`).
- Le snapshot `logs/logs a envoyer/simulation_snapshot_latest.json` existait.
- Le fichier compact `logs/logs a envoyer/simulation_pnl_ledger_latest.jsonl`
  etait absent sur la session live en cours.
- Le serveur en cours devra etre redemarre pour charger les correctifs Python.

## Correctifs livres

1. `/api/simulation/status` exporte maintenant les diagnostics PnL live dans
   `logs/logs a envoyer`, avec throttling disque.
2. `simulation_pnl_ledger_latest.jsonl` garde maintenant `delta_key`, afin de
   relier un pic du metagraphe a un evenement precis.
3. L'adapter fusion ne sort plus trop tot quand `paper_engine.decisions`
   contient une decision acceptee mais que `runtime.paper_orders` est vide.
4. Les entrees PaperEngine acceptees passent maintenant par un garde-fou global:
   - `HYPERSMART_MAX_OPEN_POSITIONS`, defaut `12`;
   - `HYPERSMART_MAX_TOTAL_EXPOSURE_USDT`, defaut `400`.
5. Les refus portefeuille sont ecrits en ledger `NO_TRADE`, au lieu de disparaitre.
6. Les positions `EXTERNAL_GITHUB_FUSION_PAPER` sans preuve edge/age/liquidite
   sont signalees comme preuve manquante dans le status dashboard.
7. Les defaults du chemin `fusion_paper_engine_adapter` sont alignes sur le
   launcher: `12` positions / `400 USDT`.

## Tests ajoutes ou renforces

- Export du ledger PnL compact depuis `/api/simulation/status`.
- Refus d'une entree PaperEngine si le nombre global de positions est atteint.
- Refus d'une entree PaperEngine si l'exposition globale est atteinte.
- Signalement d'une position fusion sans evidence mesurable.

## Tests passes

```text
python -m pytest -q tests/test_fusion_paper_engine_adapter.py tests/test_fusion_persistent_adapter_external_profiles.py tests/test_ui_simulation_status_fast.py
53 passed

python -m pytest -q tests/test_fusion_persistent_adapter_external_profiles.py tests/test_ui_simulation_status_fast.py tests/test_closed_ledger_replay.py tests/test_ledger_pnl_calibration.py
56 passed
```

## Prochaine verification runtime

1. Redemarrer `LANCER_HYPERSMART.cmd`.
2. Attendre quelques ticks live.
3. Verifier que `logs/logs a envoyer/simulation_pnl_ledger_latest.jsonl` existe.
4. Verifier que les nouvelles entrees au-dela des caps sont `NO_TRADE` avec:
   - `PORTFOLIO_MAX_OPEN_POSITIONS`, ou
   - `PORTFOLIO_MAX_TOTAL_EXPOSURE`.
5. Relire `simulation_snapshot_latest.json` et confirmer que l'exposition reste
   coherente avec les garde-fous.

## Securite

Ce correctif reste local/read-only:

- aucun ordre reel;
- aucune cle privee;
- aucune signature;
- aucun `/exchange`;
- aucun mainnet executor;
- paper local uniquement.
