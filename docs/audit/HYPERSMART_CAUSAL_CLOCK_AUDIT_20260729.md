# Audit du contrat d'horodatage causal - 2026-07-29

## Verdict

Le runtime utilise maintenant quatre horloges distinctes et explicites :

- `exchange_ts_ms` : horodatage fourni par la source, facultatif ;
- `recv_wall_ts_ms` : réception locale durable, obligatoire pour la fraîcheur ;
- `recv_mono_ns` : ordre local dans une connexion, jamais réutilisé après redémarrage ;
- `write_wall_ts_ms` : instant d'écriture durable et borne causale du replay.

Chaque tick conserve aussi `event_id`, `connection_id` et `sequence`. Les
anciens alias (`received_ts_ms`, `local_monotonic_ns`, `written_ts_ms`) restent
lisibles, mais les adaptateurs ne traitent plus un âge persisté comme un âge
actuel.

## Causes racines corrigées

1. Le cross-venue relisait `age_hl_ms` et `age_bin_ms` sans tenir compte du
   temps écoulé depuis l'écriture.
2. Le lead-lag transformait `recu_ns`, issu de `time.monotonic_ns()`, en
   timestamp Unix. Après redémarrage, la fraîcheur était mathématiquement
   invalide.
3. Une collecte absente pouvait être remplacée par `now`, ce qui fabriquait
   une fraîcheur.
4. Le lead-lag utilisait la dernière quote du fichier, même si elle avait été
   reçue après le trade étudié.

## Preuves

- 59 tests ciblés passent.
- Un snapshot reçu à `now-120 ms` produit un signal à l'appel runtime.
- Le même snapshot, relu deux secondes plus tard malgré `age_ms=1`, est refusé
  avec `SNAPSHOT_PERIME_1S` et un âge recalculé de 2120 ms.
- Les données runtime historiques sans horloge murale par jambe sont refusées
  avec `TS_ABSENT` au lieu d'être maquillées en données fraîches.
- Un enregistrement lead-lag qui ne possède que `recu_ns` est refusé.
- Une quote reçue après le trade ne peut pas être utilisée pour calculer le
  signal.
- Une comparaison monotone entre deux `connection_id` lève une erreur.

Commande de test :

```text
python -m pytest -q tests/test_causal_timestamp_contract_v2.py
  tests/test_collecter_bbo.py tests/test_tick_dataset.py
  tests/test_canonical_market_events.py
  tests/test_lot14_corrections_integration.py
  tests/test_cross_venue_side_contract_v2.py tests/test_experimental_paper.py
```

Résultat : `59 passed`.

## Déploiement runtime

Le collecteur actif avant ce commit écrit encore l'ancien schéma en mémoire.
Le prochain redémarrage normal du lanceur chargera le nouveau code et produira
les champs canoniques. Aucun ancien fichier n'est réinterprété comme frais :
les lignes legacy incomplètes restent explicitement refusées.

Commit code : `4589481`.
