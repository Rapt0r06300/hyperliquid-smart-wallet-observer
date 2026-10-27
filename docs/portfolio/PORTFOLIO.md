# Alina Smart Flow — recherche et simulation Copy-Vault

> Projet de collecte read-only, replay et simulation paper. Le dépôt ne revendique pas de rentabilité démontrée par la simple présence d'un backtest positif.

## Mission actuelle

La seule famille économique active est **Copy-Vault**. Le travail consiste à collecter des événements publics de leaders/vaults et les conditions de marché associées, à reconstruire les événements causaux, puis à chercher et évaluer des politiques de copie avec des coûts réalistes. Les autres familles, dont arbitrage, Lead-Lag, Cross-Venue, Carry, market-making et 3x4, sont hors scope actif.

L'objectif terminal de recherche est **au moins +5 USD nets/jour sur 200 USD paper**, à évaluer après les réparations, contrôles de qualité, replay/backtest, OOS et forward paper. C'est une cible, pas une prévision ni une garantie.

## Parcours opérateur

- `LANCER_COLLECTEURS_COPY_VAULT.cmd` : lance les collecteurs Copy-Vault.
- AlinaSync, via `ALINA_SYNC_COMPLETE.cmd` : récupère/restaure les shards SAFE publiés, avec validation de taille, SHA-256 et reçus.
- `LANCER_LAB_QUANT_COPY_VAULT.cmd` : exploite les shards SAFE pour les backtests et replays et conserve chaque essai/candidat, même si son résultat est provisoire ou moins bon.
- Les lanceurs de support sont rangés dans `tools/launchers/`; seuls les quatre lanceurs principaux et AlinaSync restent à la racine.
- `LANCER_HYPERSMART.cmd` : lance le moteur avec affichage de simulation paper ; il doit respecter le scope Copy-Vault.
- `POUSSER-GITHUB-FORCE.cmd` : réconcilie et publie le code Git sans force. Il ne transfère pas les shards.

Ces fichiers décrivent les rôles opérateur attendus ; leur nom ne vaut pas certification de leur branchement réel. Le code au HEAD et les receipts font foi.

## Méthode et critères de preuve

Les candidats sont comparés sur des fenêtres et capitaux cohérents, avec paramètres, identité/hash des données, seed, coûts et résultats conservés. Chaque amélioration reste consultable quand une autre lui succède. Les coûts, fills, timestamps et PnL ne sont jamais inventés ; toute donnée manquante ou incertaine reste inconnue et peut rendre un résultat `UNMEASURABLE`.

La chaîne canonique est `IDLE → COLLECT → ANALYZE`, puis `DRAIN → QUALITY → REPLAY → BACKTEST → OOS → FORWARD_PAPER → PNL_PROOF → SCOREBOARD → DONE`. Seuls des résultats causaux, reproductibles et validés par les gates correspondants peuvent être qualifiés de `PROVEN`. Les autres verdicts honnêtes sont `PROMISING`, `MORE_DATA`, `UNMEASURABLE` et `REJECTED`.

## Sécurité

**PAPER / READ-ONLY / FAIL-CLOSED** : aucun ordre mainnet ou testnet, aucune signature, clé privée, seed, dépôt, retrait ou transfert. Une simulation n'est pas une exécution.

## Notes de recherche historiques

Les anciens rapports et synthèses peuvent contenir des résultats sur copy-trading général, arbitrage, grille, market-making ou d'autres familles. Ils sont conservés comme historique ; ils ne décrivent ni le scope actif, ni le statut actuel, ni une preuve économique Copy-Vault actuelle. Vérifier leurs artefacts source avant toute citation ou comparaison.


### Valeurs recopiées de l'ancienne synthèse — historique non revalidé

Les chiffres ci-dessous sont conservés comme traces de l'ancien document de présentation. Ils ne décrivent pas la stratégie active actuelle et doivent être rapprochés de leurs artefacts sources avant toute réutilisation.

| Étude ancienne | Résultat annoncé dans l'ancienne synthèse |
|---|---|
| Copy-trading général | Dégradation de copie d'environ 13 bps ; edge médian annoncé négatif. |
| Calibrage SL/TP | Environ 1,4 M de scénarios ; aucun réglage robuste annoncé en OOS. |
| Entrée maker | Taux de fill annoncé à 16 %, avec sélection adverse. |
| Grille / market-making | Breakeven annoncé en marché calme, pertes importantes en tendance. |
| Réversion à la moyenne | Edge brut annoncé à environ 0,6 bps, inférieur aux coûts. |
| Contrôle aléatoire | 0 stratégie positive sur 50 essais aléatoires selon l'ancienne synthèse. |
| Sortie oracle | Plafond théorique annoncé à +50 k$, explicitement irréalisable. |
| Modèle prédictif | Signal annoncé comme environ 15 fois trop faible et soumis au changement de régime. |
