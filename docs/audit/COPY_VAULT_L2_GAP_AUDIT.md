# Copy-Vault — audit des trous L2 silencieux

## Périmètre

Le garde canonique `hl_observer.realtime.feed_quality.FeedQualityGate` sépare
maintenant quatre preuves qui ne doivent plus être confondues :

- socket ouvert et heartbeat reçu ;
- dernière observation L2 encore fraîche ;
- carnet exploitable avec deux côtés valides ;
- continuité de séquence effectivement démontrée pour l'époque de connexion.

Chaque `FeedQualitySnapshot` conserve aussi `connection_id`, `feed_epoch`,
`continuity_status`, `sequence_continuity_proven` et `book_usable`.

## Règles fail-closed

- Un heartbeat ne rafraîchit jamais `last_received_ts_ms` et ne rend donc pas
  un carnet ancien exploitable.
- Une fermeture/reconnexion ouvre une nouvelle époque et exige une nouvelle
  synchronisation.
- Un saut ou une régression de séquence rend le carnet non exploitable ; une
  simple trame arrivée après le saut ne suffit pas. Il faut `mark_resync()` puis
  un nouveau snapshot source.
- Quand la source ne fournit pas de séquence exploitable (cas Hyperliquid
  `l2Book` public), le reçu porte explicitement
  `SEQUENCE_CONTINUITY_NOT_DEMONSTRATED`. Aucun enchaînement causal n'est
  inventé.
- Les trames restent observables et mesurées ; seules les preuves invalides
  sont bloquées pour les fills/replays.

## Vérification locale

Commande exécutée dans le dépôt local :

```text
python -m pytest -q tests/test_l2_gap_detection.py tests/test_feed_quality_gate.py tests/test_coverage_closure_feed_quality_deep.py
```

Résultat : **17 tests passés**.

Ruff ciblé :

```text
python -m ruff check src/hl_observer/realtime/feed_quality.py tests/test_l2_gap_detection.py
```

Résultat : **All checks passed**.

Cette correction ne collecte aucune donnée, ne déclenche aucun ordre et ne
modifie pas la CI GitHub.
