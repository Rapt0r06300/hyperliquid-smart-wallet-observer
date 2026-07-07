# HyperSmart GitHub Modules / Ledger Audit

Date: 2026-06-30

## Constat

- 34 dossiers de repos externes sont présents dans `runtime/research/github_repos_v24`.
- Le pont officiel reste `src/hl_observer/strategies/external_github_bridge.py`.
- Le bus d'adaptation paper locale reste `src/hl_observer/strategies/external_simulation_bus.py`.
- Les moteurs externes ne doivent pas envoyer d'ordre réel. Ils doivent produire des intentions paper locales et des preuves.
- Le serveur live observé avant relance affichait encore des pics de PnL non reliés à un événement ledger et des positions anciennes sans preuves suffisantes.

## Corrections appliquées

1. Les ordres paper directs issus des profils externes conservent maintenant les preuves dans la position ouverte :
   - `edge_remaining_bps`
   - `signal_age_ms`
   - `leader_wallets_count`
   - `liquidity_score`
   - `copy_degradation_bps`
   - scores de vote et source d'evidence quand disponibles.

2. Les ordres copy-like refusés écrivent maintenant un événement `NO_TRADE` dans le ledger local :
   - `DIRECT_COPY_EDGE_MISSING`
   - `DIRECT_COPY_EDGE_TOO_SMALL`
   - consensus insuffisant
   - signal trop vieux
   - liquidité insuffisante
   - dégradation de copie trop élevée
   - garde-fou de perte de session.

3. Le status live ferme localement les anciennes positions copy GitHub sans preuve mesurable :
   - fermeture uniquement au vrai mark disponible ;
   - événement `CLOSE` explicite dans le ledger ;
   - aucune exécution réelle ;
   - aucune création de PnL artificiel.

4. Le dashboard/status expose les preuves de position pour faciliter l'audit :
   - edge restant ;
   - âge du signal ;
   - nombre de wallets leaders ;
   - liquidité ;
   - dégradation de copie ;
   - indicateur `quality_evidence_missing`.

## Validation

Tests ciblés exécutés :

```text
python -m pytest -q tests\test_fusion_persistent_adapter_external_profiles.py tests\test_ui_simulation_status_fast.py tests\test_v9_sltp_runtime.py tests\test_fusion_strategy_runtime.py tests\test_hypersmart_single_launcher.py tests\test_simulation_v2_normal_pnl_ledger_ui.py
```

Résultat :

```text
58 passed
```

Safety :

```text
python -m hyper_smart_observer.app.main --safety-check
python -m hyper_smart_observer.app.main --audit-safety
```

Résultat :

```text
Safety check: OK
Audit safety: OK
```

## Prochaine vérification obligatoire

Relancer `LANCER_HYPERSMART.cmd`, puis vérifier :

- `/api/simulation/status` contient `quality_guard_runtime`.
- `paper_ledger.spike_links.unexplained_spike_count` descend à 0 ou pointe vers un événement ledger explicite.
- Les positions ouvertes ont toutes des champs de preuve ou sont fermées localement par le garde-fou.
- Le PnL reste la formule normale : `1000 + realized + unrealized`.

## Limite importante

Ces changements ne garantissent pas un PnL positif. Ils rendent la simulation plus stricte, plus explicable et moins vulnérable aux positions héritées sans preuve. Toute performance positive doit venir de signaux réels, frais et mesurables, pas d'un ajustement artificiel du graphe.
