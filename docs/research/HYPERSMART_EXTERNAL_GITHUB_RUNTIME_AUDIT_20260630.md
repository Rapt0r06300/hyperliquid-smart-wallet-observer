# HyperSmart - audit runtime GitHub externe 2026-06-30

## Resume

Objectif verifie: les moteurs issus des repos GitHub externes doivent rester
independants, ne pas modifier leur code upstream clone, mais pouvoir ecrire
dans la simulation locale HyperSmart quand ils produisent une decision paper
compatible.

Etat observe apres correction:

- profils demandes dans le bridge: 37;
- profils disponibles/installes localement: 34;
- profils indisponibles depuis cette machine: 3, avec erreur GitHub 404;
- profils disponibles executes par le bus de simulation: 34/34;
- positions paper visibles dans `/api/simulation/status` apres redemarrage: 2;
- execution reelle: interdite;
- `/exchange`: absent;
- signature/private key/wallet connect: absents.

## Correction effectuee

Probleme: le bus executait bien les profils installes, mais l'adaptateur
persistant bloquait certains ordres directs issus des profils de copy-follow
quand le `PaperEngine` principal refusait le meme signal. Dans Chrome, cela
pouvait donner une simulation vide meme si un profil externe avait produit un
ordre paper local valide.

Solution:

1. `PaperEngine` reste prioritaire quand il accepte une decision.
2. Si `PaperEngine` refuse, un profil externe `ext_*` ou `copy_*` peut
   materialiser une position paper locale s'il fournit:
   - `accepted=True`;
   - `paper_only=True`;
   - `real_execution=False`;
   - `reference_price > 0`;
   - `notional_usdt > 0`;
   - `side` dans `LONG` ou `SHORT`.
3. Les ordres directs de copy-follow ne doublonnent pas les positions acceptees
   par le `PaperEngine`.
4. Tous les profils installes ecrivent une trace locale `ENGINE_EVALUATION`
   pour prouver qu'ils ont tourne independamment.
5. Le code upstream sous `runtime/research/github_repos_v24` reste intact.

## Fichiers touches

- `src/hl_observer/ui/fusion_persistent_adapter.py`
- `tests/test_fusion_persistent_adapter_external_profiles.py`
- `docs/research/HYPERSMART_EXTERNAL_GITHUB_RUNTIME_AUDIT_20260630.md`

## Preuves locales

Commandes executees:

```powershell
python -m pytest -q tests\test_fusion_persistent_adapter_external_profiles.py tests\test_ui_simulation_status_fast.py tests\test_fusion_strategy_runtime.py tests\test_external_github_strategy_bridge.py
python -m hyper_smart_observer.app.main --safety-check
python -m hyper_smart_observer.app.main --audit-safety
```

Resultats:

- tests cibles: `37 passed`;
- safety-check: `OK`;
- audit-safety: `OK`;
- audit confirme:
  - aucun `/exchange`;
  - aucune signature;
  - aucun ordre operationnel;
  - aucune cle privee;
  - dashboard read-only;
  - mainnet interdit;
  - execution disabled by default;
  - testnet disabled by default.

Controle API local apres redemarrage:

```json
{
  "running": true,
  "engine_running": true,
  "open_positions": 2,
  "equity_usdt": 1000.012702,
  "net_pnl_usdt": 0.012702,
  "fusion_persistent_adapter": {
    "paper_only": true,
    "real_execution": false,
    "external_action": false,
    "external_profiles_executed": 34
  }
}
```

## Interpretation

La simulation n'est plus vide cote runtime: les profils externes executes
peuvent maintenant ecrire dans l'etat paper local si leur ordre est valide.

Le PnL reste calcule depuis les prix reels et les couts paper locaux. Il ne doit
jamais etre force artificiellement. Une perte ou un gain affiche est donc une
donnee de simulation a auditer, pas une valeur a maquiller.

## Limites restantes

- 3 depots demandes restent indisponibles: impossible de les executer sans URL
  corrigee ou droits GitHub valides.
- Les moteurs upstream ne sont pas lances en mode natif argent-reel; ils sont
  adaptes en profils paper locaux, pour garder HyperSmart read-only.
- Les profils externes doivent encore etre analyses trade par trade pour
  identifier ceux qui degradent le PnL et ceux qui ameliorent la selection.

## Prochaine priorite

Analyser les logs `logs/logs a envoyer` par profil externe:

1. PnL par `strategy_id`;
2. win rate par profil;
3. age moyen des signaux acceptes;
4. couts spread/slippage/frais par profil;
5. exits leader vs exits SL/TP;
6. profils a reduire, mettre en quarantaine ou renforcer.

Cette prochaine passe doit ajuster les adapters et les risk gates HyperSmart,
pas modifier le code upstream clone.
