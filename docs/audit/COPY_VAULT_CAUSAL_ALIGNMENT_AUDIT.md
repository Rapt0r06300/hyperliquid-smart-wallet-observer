# Copy-Vault — jointure causale leader / L2-BBO

## Objet

Le replay Copy-Vault ne peut utiliser un état de carnet que si sa disponibilité
avant la décision est démontrée. Une proximité entre deux horodatages ne suffit
pas : l'ordre causal doit être vérifiable.

## Contrat appliqué

Pour chaque carnet candidat, le moteur vérifie, dans cet ordre :

1. `exchange_ts_ms <= received_at_ms <= available_at_ms` ;
2. la provenance SAFE : dataset, trois SHA-256, manifeste vérifié et
   compatibilité replay ;
3. `available_at_ms < cutoff_ms` ; une égalité est refusée sauf preuve
   explicite de checkpoint ou de séquence native ;
4. une fraîcheur mesurable, dérivée de l'historique causal disponible avant le
   cutoff : `min(cap_ms, p95_interarrival_ms + p95_event_to_receive_ms)` ;
5. l'unicité de la disponibilité : deux carnets au même instant ne peuvent pas
   être départagés par leur ordre de lecture.

Le plafond protocolaire reste celui du moteur, mais il ne remplace pas la
mesure de cadence et de latence. En l'absence d'historique suffisant, le statut
est `UNMEASURABLE` et l'épisode est exclu. Aucun fill, zéro, timestamp ou PnL
n'est inventé.

## Intégration

- `copy_vault_causal_alignment.py` est l'autorité déterministe de sélection et
  d'audit.
- `copy_vault_executable.py` l'utilise pour les décisions live/forward et
  conserve les refus explicites dans les diagnostics.
- `copy_vault_book_loader.py` produit, par fenêtre et par signal, le schéma
  `hypersmart.copy_vault_causal_alignment.v1`, la politique de fraîcheur, les
  rejets par cause et les états train/forward séparés.
- `copy_vault_local_lab.py` expose la même preuve dans le rapport du labo ; ses
  alignements sont SAFE-only et consultatifs.
- Le gate de couverture refuse toute ancienne ou incomplète couverture qui ne
  porte pas cette preuve causale.

## États de diagnostic

Les causes importantes sont conservées séparément : horloge invalide, carnet
futur, égalité non prouvée, fraîcheur non mesurable, référence trop ancienne,
disponibilités ambiguës, gap/reconnexion et provenance SAFE incomplète. Les
compteurs sont ventilés par fenêtre, coin et signal afin de distinguer une
absence de marché d'une absence de collecte.

## Vérification locale

La couverture de cette évolution est vérifiée par les tests d'alignement,
loader, labo et replay Copy-Vault. Le périmètre validé localement comprend les
cas futur, égalité prouvée/non prouvée, doublon de disponibilité, cadence
insuffisante, gap, non-causalité et refus d'exécution.

Cette note ne constitue pas une preuve économique : elle décrit uniquement le
contrat de données nécessaire avant toute mesure économique.
