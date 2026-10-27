ALINA SMART FLOW — CLONE PORTABLE
=================================

« Portable » signifie ici qu'un clone fonctionne depuis son propre chemin local.
Aucune archive portable séparée n'est nécessaire pour ce parcours.

LANCEURS À LA RACINE
--------------------
- LANCER_COLLECTEURS_COPY_VAULT.cmd : collecte Copy-Vault.
- LANCER_LAB_QUANT_COPY_VAULT.cmd : laboratoire de backtests et replays.
- LANCER_HYPERSMART.cmd : moteur avec simulation PAPER visible.
- POUSSER-GITHUB-FORCE.cmd : synchronisation prudente du code, sans push forcé.
- ALINA_SYNC_COMPLETE.cmd / ALINA_SYNC_COMPLETE.sh : synchronisation du code et des shards SAFE.

UTILITAIRES DE SUPPORT
---------------------
Les autres commandes sont rangées dans tools\launchers\. Elles sont appelées par les
workflows, les validations et les opérations de restauration. Leurs chemins sont
résolus à partir du dossier du clone.

NOUVEAU CLONE
-------------
1. Cloner le dépôt principal dans le dossier souhaité.
2. Installer ou préparer Python selon README.md.
3. Exécuter ALINA_SYNC_COMPLETE.cmd (Windows) ou ALINA_SYNC_COMPLETE.sh (Linux/macOS)
   pour importer les shards SAFE publiés.
4. Lancer LANCER_COLLECTEURS_COPY_VAULT.cmd, LANCER_LAB_QUANT_COPY_VAULT.cmd ou
   LANCER_HYPERSMART.cmd selon le besoin.

Les shards restent gérés par AlinaSync, hors de l'historique Git ordinaire. Les résultats
économiques restent PAPER/read-only et ne constituent pas une preuve sans les contrôles
OOS/forward et la réconciliation comptable canonique.