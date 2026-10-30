# Politique de rétention Copy-Vault

Version : `copy-vault-retention/v1`. Politique lecture seule : aucune suppression automatique.

| Classe | Consommateur | Reproductibilité | Conservation | Compaction |
|---|---|---|---|---|
| `immutable_proof` | replay/backtest/OOS/forward reports, scoreboard and audit readers | `required_exact_bytes` | `permanent` | `forbidden_without_exact_manifest_and_restore` |
| `active_resumable` | control plane and resumable campaigns | `required_until_terminal_receipt_and_restore` | `until_terminal_plus_verified_restore` | `allowed_only_with_hash_count_receipt_parity` |
| `frozen_candidate` | Copy-Vault lab, comparison history and promotion gates | `required_exact_config_data_engine` | `permanent_for_all_frozen_variants` | `forbidden_if_any_variant_or_failure_disappears` |
| `safe_shard` | AlinaSync, SAFE admission, replay and backtest | `required_size_sha256_native_identity` | `permanent_until_explicit_user_archival` | `never_mutate; packed copies require bitwise restore proof` |
| `cache_regenerable` | local acceleration only | `regenerable_from_immutable_inputs` | `discardable_after_rebuild_receipt` | `allowed_only_after_rebuild_check` |

## Règle de compaction

Une compaction est refusée si elle est justifiée par la taille seule, si un hash/count/receipt manque, si un candidat ou échec gelé disparaît, ou si la restauration bit à bit n'est pas vérifiée. Les shards SAFE et les données AlinaSync restent hors de toute mutation automatique.

Les fichiers non classés sont `quarantine_unknown` et nécessitent une décision explicite ; ils ne sont jamais supprimés par ressemblance de nom ou pression disque.
