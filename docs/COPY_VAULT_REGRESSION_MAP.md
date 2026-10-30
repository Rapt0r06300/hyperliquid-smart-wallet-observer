# Copy-Vault — carte des régressions locales

Cette carte relie les modules de production Copy-Vault aux consommateurs aval et aux suites déjà présentes. Elle n’ajoute aucun moteur économique ni registre de résultats.

## Liens vérifiables dans le code

| Producteur/module | Consommateur aval établi | Preuve locale reproductible | Commande d’acceptation |
| --- | --- | --- | --- |
| `tools/collect_cloud_copy_vault.py` | `PartitionedTickDatasetWriter` est importé et créé par le collecteur ; celui-ci écrit les événements observés dans les partitions instrument/canal. | Recherche des imports/appels `PartitionedTickDatasetWriter` dans le collecteur et les tests collector/writer. | `python tools/run_copy_vault_regressions.py --path tools/collect_cloud_copy_vault.py` |
| `PartitionedTickDatasetWriter` | `TickDatasetWriter` scelle les partitions utilisées par le writer partitionné. | Import/instanciation dans `src/hl_observer/collection/partitioned_tick_dataset.py`; contrats de partition et de writer. | `python tools/run_copy_vault_regressions.py --path src/hl_observer/collection/partitioned_tick_dataset.py` |
| `TickDatasetWriter` | Writer partitionné et collecte Copy-Vault consomment son format d’enveloppe scellé. | `TickEnvelope`/`TickDatasetWriter` et suites dataset/collector. | `python tools/run_copy_vault_regressions.py --path src/hl_observer/collection/tick_dataset.py` |
| Adaptateurs marché et coordinateurs de collecte | Les adaptateurs publient dans le tape natif/coordinateur, consommé par la collecte et les contrats transport. | Import/calls vérifiés dans chaque adaptateur ; les suites propres à la plateforme et le tape natif sont sélectionnés. | `python tools/run_copy_vault_regressions.py --changed` |
| `tools/restore_alina.py` / `tools/copy_vault_safe_bridge.py` | Le labo consomme le workspace SAFE matérialisé et son manifeste ; les outils de restauration et bridge sont couverts avec les tests d’admission SAFE. Le lien est un contrat de stockage/intégrité, pas un appel direct entre modules. | Contrats de manifeste/catalogue, restoration, bridge et workspace SAFE dans leurs suites respectives. | `python tools/run_copy_vault_regressions.py --path tools/restore_alina.py` |
| `copy_vault_book_loader.load_observed_books` | `copy_vault_executable` charge les carnets observés avant le replay exécutable. | Import direct dans `copy_vault_executable.py`; tests loader, exécution et watermark. | `python tools/run_copy_vault_regressions.py --path src/hl_observer/backtesting/copy_vault_book_loader.py` |
| `copy_vault_executable` | `copy_vault_local_lab` utilise l’exécuteur canonique pour les campagnes et replays. | Import du module comme `cv`; tests exécuteur, replay/parité, lab et événements. | `python tools/run_copy_vault_regressions.py --path src/hl_observer/backtesting/copy_vault_executable.py` |
| `copy_vault_local_lab.materialize_safe_workspace` / `run_local_campaign` | `tools/alina_quant_lab_console.py` matérialise les entrées SAFE puis appelle la campagne locale. | Imports et appels dans la console ; tests lab, reprise, verrou de campagne et rapport HTML. | `python tools/run_copy_vault_regressions.py --path src/hl_observer/backtesting/copy_vault_local_lab.py` |
| `ScoreboardProducer` | Il agrège les métriques runtime puis appelle `scoreboard_feeder.lignes_depuis_ledger`. | Imports et appel direct dans `scoreboard_producer.py`; suites producer/runtime/feeder/clôture. | `python tools/run_copy_vault_regressions.py --path src/hl_observer/simulation/scoreboard_producer.py` |
| `scoreboard_feeder` | Il calcule les lignes/métriques et transmet les preuves au gate `scoreboard_promotion`. | Appels du feeder vers métriques et promotion ; tests feeder, métriques et promotion. | `python tools/run_copy_vault_regressions.py --path src/hl_observer/simulation/scoreboard_feeder.py` |
| `scoreboard_promotion` et scoreboard économique | La porte refuse les stratégies hors scope ou insuffisamment prouvées ; les consommateurs de clôture vérifient le statut propagé. | Appel de `require_active_strategy`, verdicts de promotion et suites de clôture. | `python tools/run_copy_vault_regressions.py --path src/hl_observer/simulation/scoreboard_promotion.py` |

Les liens d’appel ci-dessus sont vérifiables avec `rg -n` sur les symboles cités. Les lignes de stockage SAFE sont couvertes comme contrat de fichiers, hashes, manifeste et admission ; elles ne sont pas présentées comme des appels directs. Une relation qui n’est pas confirmée dans le code reste explicitement limitée à son contrat testé.

## Propagation et garde-fous

- `tools/run_copy_vault_regressions.py --changed` sélectionne les suites aval depuis le diff Git local et les nouveaux fichiers source non suivis sous `src/hl_observer/` et `tools/`.
- Les modules critiques ont un mapping explicite vers les suites existantes. Un nouveau module sous les espaces critiques sans mapping produit `COPY_VAULT_REGRESSION_NO_GO`; il ne peut pas être déclaré validé par absence de tests.
- Les chemins non critiques, tels que la documentation, ne déclenchent pas ces suites.
- L’exécution locale impose un Job Object à 50 % CPU avant pytest. Si cette limite n’est pas confirmée, aucune suite n’est lancée.
- L’outil ne lit ni n’écrit les shards, n’effectue aucun accès réseau, ne lance pas CI GitHub et ne certifie pas la rentabilité.
- L’acceptation pour un module modifié est : toutes les suites sélectionnées passent. Le rapport économique TRAIN, VALIDATION, OOS et FORWARD reste indépendant des tests techniques.

## Commandes ciblées

```powershell
python tools/run_copy_vault_regressions.py --path src/hl_observer/simulation/scoreboard_producer.py
python tools/run_copy_vault_regressions.py --changed --list-only
```

Pour exécuter les régressions de tous les modules critiques modifiés dans le checkout :

```powershell
python tools/run_copy_vault_regressions.py --changed
```
