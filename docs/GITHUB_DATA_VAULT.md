# GitHub Data Vault — architecture Alina SmartFlow

Dernière mise à jour : **2026-11-11**.

> **Contrat actuel :** le repository `Rapt0r06300/hyperliquid-smart-wallet-observer`
> est l'unique dépôt actif pour le code, les catalogues, les manifests et les
> preuves. L'ancien dépôt privé `hypersmart-datasets` est retiré de l'architecture
> active et ne doit être ni requis ni interrogé. Les paragraphes historiques
> ci-dessous sont conservés pour provenance ; la synchronisation SAFE actuelle
> passe par `ALINA_SYNC_COMPLETE.cmd` et les GitHub Releases du dépôt unique.

## Objectif historique conservé

GitHub doit conserver le maximum d'information utile à la recherche Alina afin que le code, les récoltes, les replays, les résultats et leur provenance puissent être retrouvés sans dépendre d'un seul PC. Cette section décrit l'ancien modèle de séparation pour audit ; elle n'autorise plus un second dépôt actif.

Le stockage était historiquement séparé en deux dépôts :

- `Rapt0r06300/hyperliquid-smart-wallet-observer` : code et moteur du Vault ;
- `Rapt0r06300/hypersmart-datasets` : dépôt privé de données lourdes, catalogues et Releases.

Le dépôt de code est public. Les données lourdes restent privées.

## Couches de données historiques

L'architecture conserve les couches existantes au lieu de les remplacer :

1. snapshot HOT historique dans le dépôt privé ;
2. snapshot FULL/COLD historique dans la Release privée `371149058` ;
3. snapshots incrémentaux futurs du dossier projet ;
4. snapshots incrémentaux futurs de `ALINA_RESEARCH_HOME`.

Les fichiers déjà archivés puis supprimés localement restent référencés dans l'index cumulatif. Une suppression locale ne devient donc pas une suppression de sauvegarde. Les nouveaux assets SAFE doivent toutefois suivre le contrat courant du dépôt unique et ses manifests/hash vérifiés.

## Moteur incrémental historique

Les outils canoniques sont :

- `tools/data_vault_core.py`
- `tools/build_data_vault_snapshot.py`
- `tools/publish_data_vault_snapshot.py`
- `tools/restore_data_vault_snapshot.py`
- `tools/update_data_vault_pointer.py`

Le constructeur :

- ne copie que les fichiers nouveaux ou modifiés ;
- réutilise les références GitHub des fichiers inchangés ;
- calcule un SHA-256 par fichier ;
- ignore les chemins de secrets connus ;
- scanne les petits fichiers texte pour des secrets évidents ;
- reporte les fichiers qui changent pendant la copie au snapshot suivant ;
- regroupe les petits fichiers ;
- découpe les gros fichiers en morceaux inférieurs à la limite d'un asset Release ;
- écrit les fichiers temporaires hors de la racine observée.

Le publieur refuse un asset sans SHA-256 GitHub et ne publie la Release qu'après vérification.

## Sources

Le Vault supporte un `source_label` afin de ne jamais mélanger plusieurs racines.

### alina-project (ancienne source locale)

Source prévue sur le portable :

`C:\Users\rberm\Desktop\Projet AlinaSmartFlow`

Zones de données principales :

- `runtime/**`
- `data/**`
- `reports/**`
- `logs/**`
- `Rapports en continu/**`

### alina-research-home (ancienne source externe)

Source : variable machine `ALINA_RESEARCH_HOME`.

Zones :

- `datasets/**`
- `jobs/**`
- `results/**`
- `status/**`
- `job_logs/**`
- `checkpoints/**`
- `runtime/**`

## Reconstruction / replays

Le moteur `restore_data_vault_snapshot.py` sait calculer les Releases/assets nécessaires pour une sélection, vérifier les hashes puis reconstruire les fichiers.

Les données FULL/COLD historiques continuent d'utiliser le pont existant `hl_observer.ops.dataset_bridge`. Le plan historique montre notamment une suite `economic-core` d'environ 4,5 Gio à télécharger, bien plus adaptée à un replay ciblé qu'un téléchargement du snapshot complet.

Un workflow GitHub-hosted a été préparé dans le dépôt privé pour planifier ou exécuter les replays économiques en mode PAPER strict. Il force l'exécution réelle à OFF et n'active aucune collecte live.

## État de validation

Le moteur Data Vault est testé sur les runners GitHub-hosted du dépôt principal :

- compilation Python ;
- sauvegarde initiale ;
- détection de secret ;
- snapshot incrémental ;
- conservation de l'historique après suppression locale ;
- découpage des gros fichiers ;
- sélection de restauration ;
- construction de la liste d'assets.

Les workflows qui lisent réellement un PC restent manuels uniquement. Ils ne doivent pas être déclenchés sans autorisation explicite.

## Règle de reproductibilité

À terme, tout replay important doit pouvoir être décrit par :

- SHA exact du code ;
- dépôt/index de données ;
- Release(s) et SHA-256 ;
- sélection de fichiers/suite ;
- paramètres de replay ;
- résultats et rapport.

Le but n'est pas seulement de sauvegarder des octets : il faut pouvoir prouver précisément quelles données ont produit quel résultat.
