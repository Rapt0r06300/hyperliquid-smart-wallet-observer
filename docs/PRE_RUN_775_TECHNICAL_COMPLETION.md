# HyperSmart — progression technique canonique vers 775

## Verdict courant

**Progression honnête : 465 / 775.**

La provenance littérale reste inchangée : les formulations historiques originales
321→775 ne sont pas récupérées et ne sont pas inventées.

Le précédent faux verdict 775/775 reste retiré : une présence de fichiers ne vaut
pas une preuve technique spécifique.

## Ce qui est réellement verrouillé

- **1→320** : suites exécutables préexistantes conservées ;
- **321→395** : Copy-Vault, 15 exigences × 5 facettes = 75 preuves ;
- **396→465** : Lead-Lag, 14 exigences × 5 facettes = 70 preuves ;
- **466→775** : explicitement incomplets tant que leur évaluateur spécifique
  n'existe pas et ne passe pas.

Les cinq facettes obligatoires restent :

1. `CONTRACT` ;
2. `POSITIVE_PATH` ;
3. `NEGATIVE_FAIL_CLOSED` ;
4. `DETERMINISM_CAUSALITY` ;
5. `EVIDENCE_PROVENANCE`.

## Lead-Lag 396→465

Le bloc spécifique est dans
`src/hl_observer/ops/pre_run_lead_lag_396_465.py`.

Il couvre :

1. timestamps certifiables ;
2. causalité et lag réel ;
3. multi-horizon ;
4. régimes ;
5. frontière seconde / minute ;
6. horizons 5 min / 15 min ;
7. OFI / microprice ;
8. queue depletion ;
9. ADD/CANCEL ;
10. profondeur ;
11. latence ;
12. univers test / contrôle ;
13. stress de coûts ;
14. placebos.

### Renforcement de causalité

Le chemin économique certifié n'utilise plus de monkeypatch global de
`lead_lag_shadow._event_time_ns`.

`src/hl_observer/backtesting/lead_lag_certified_backtest.py` charge une vue
certifiée séparée :

- `ts_wall_ms` ou `recv_wall_ts_ms` obligatoire ;
- une ligne avec seulement `recu_ns` est classée
  `uncertifiable_clock_rows` et exclue de la preuve économique ;
- les sources brutes restent intactes ;
- les doublons sont rejetés de façon déterministe ;
- les métriques économiques utilisent seulement les épisodes fermés avec
  référence fraîche et capacité top-of-book mesurée ;
- l'univers test et les coins de contrôle restent séparés ;
- les placebos sont reproductibles.

`lead_lag_certified_clock.py` reste l'entrée publique utilisée par la campagne
économique, mais délègue désormais au loader/backtest certifié sans mutation
globale temporaire.

### Multi-échelle

Les horizons minute, 5 minutes et 15 minutes sont ici des **preuves techniques
de chronologie/observabilité**. Ils ne sont pas ajoutés silencieusement au
protocole économique sub-seconde gelé et ne constituent pas une nouvelle
optimisation sur le holdout.

## Règle de progression

`src/hl_observer/ops/pre_run_guard_321_775.py` ne compte que les catégories avec
un évaluateur spécifique réellement vert. Les catégories futures restent
`CATEGORY_NOT_YET_SPECIFICALLY_VERIFIED`.

Le prochain identifiant est **466**, début du bloc **Cross-Venue**.

## Sécurité

Toujours : paper/read-only ; mainnet/testnet execution désactivés ; aucune clé
privée ou signature ; aucun test supprimé pour masquer un rouge ;
`PREPARER_PC_ALINA.cmd` non lancé ; runner self-hosted non installé tant que
`GO_SELF_HOSTED = TRUE` n'est pas explicitement autorisé.
