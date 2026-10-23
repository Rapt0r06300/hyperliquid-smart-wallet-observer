# Certification L2 locale des shards SAFE (23 octobre 2026)

Après \`git pull --ff-only\`, **ne retélécharge pas** les shards déjà présents.

Depuis la racine du clone Windows, lance \`VERIFIER_REPARER_L2_LOCAL.cmd\`.
Le lanceur exécute un audit **offline** des shards SAFE déjà récupérés par
\`ALINA_SYNC_COMPLETE.cmd\` dans \`runtime/recovery/full/usable/shards/\`.

Pour un test rapide : \`VERIFIER_REPARER_L2_LOCAL.cmd --limit 10\`.
Par défaut, la vérification complète utilise jusqu'à 8 threads. Réglage :
\`VERIFIER_REPARER_L2_LOCAL.cmd --workers 4\`.
Aucune suppression, téléchargement, exécution d'ordre, transaction, clé privée
ou modification du catalogue GitHub.

## Fichiers de sortie

* \`runtime/recovery/full/LOCAL_L2_CERTIFICATION.json\` : rapport détaillé par
  shard, statut, anomalies, séquences, intervalles valides (lignes inclusives).
* \`runtime/recovery/full/usable/local_l2_repaired/\` : nouvelles copies gzip
  **uniquement** des intervalles prouvés par un vrai snapshot et une suite
  continue de deltas; receipts \`.proof.json\` SHA-256 réutilisables.
* Les originaux \`.jsonl.gz\` ne changent jamais. Les shards manquants ne sont
  ni générés ni téléchargés.

Statuts: \`CONTINUOUS_L2\` = continuité locale vérifiée entre un snapshot
et les deltas présents; \`RECOVERABLE_ANCHORED_SPANS\` = segments re-ancrés
conservés séparément; \`SNAPSHOT_OBSERVATIONS_ONLY\` = snapshots pris
individuellement, sans affirmation de continuité entre eux; \`BLOCKED\` =
pas de preuve suffisante ou objet absent/corrompu.

**Limites importantes :** un historique de snapshots ne reconstitue pas les
transactions intervenues entre les snapshots. Une continuité *à l'intérieur
d'un shard* ne prouve pas une continuité *entre shards*. Le rapport n'est pas
un certificat de disponibilité/latence L2 inférieur à 1 seconde, de
synchronisation multivenue, de profitabilité ou d'absence de look-ahead.
Les versions venues non reconnues sont refusées, pas devinées. Les shards
réparés ne doivent pas être automatiquement promus dans le catalogue canonique
ou chargés dans un backtest L2 global avant vérification inter-shards.
Ne lance pas deux audits/réparations simultanés vers la même destination.

Code de sortie : 0 = aucun BLOCKED, 1 = au moins un BLOCKED (rapport écrit),
2 = erreur d'infrastructure (catalogue, accès disque ou arguments).

Tests déterministes: \`python -m pytest -q tests/test_certify_local_l2.py\`.

## Performance et reprise

Chaque scan strict parcourt les octets gzip et vérifie SHA-256, CRC, JSONL, séquences et structure de carnet **sans tout décompresser sur disque**. Les shards sont traités en parallèle (1 à 16 threads), dans une mémoire bornée par flux de carnet. Les reçus sous `LOCAL_L2_RECEIPTS/` sont sauvegardés individuellement, pour reprendre après interruption avec `--resume` (ex. `VERIFIER_REPARER_L2_LOCAL.cmd --resume --workers 8`). **Attention :** `--resume` fait confiance à la taille et au mtime d'un fichier précédemment haché ; ce mode n'est pas une nouvelle vérification cryptographique. Pour un audit de preuve final, relancer sans `--resume`.

Les checksums natifs optionnels de carnet et les frontières **inter-shards** ne sont pas encore vérifiés de bout en bout. `CONTINUOUS_L2` désigne uniquement la chaîne structurelle validée **dans le shard**. Les fichiers produits par la réparation ne sont pas automatiquement branchés aux backtests.
