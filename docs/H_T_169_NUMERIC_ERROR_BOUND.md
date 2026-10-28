# H‑T‑169 — Borne numérique Copy‑Vault

**État : borne analytique implémentée et vérifiée pour le score LCB TRAIN et ses décisions de rang ; les résultats économiques restent non prouvés.** Ce rapport porte sur l’erreur numérique, pas sur la rentabilité ni sur les hypothèses statistiques du modèle.

## Périmètre et provenance

Travail effectué directement dans `C:\Users\flo\Desktop\Projet invest`, branche `main`, HEAD `755441d3b442c9c981d2876d07bf71f9459e1ad5`. Les changements sont du WIP local ; aucun commit/push et aucun shard modifié.

Les champs `*_exact_decimal` restent l’autorité des sommes, rapprochements, seuils et classements. Les tolérances de rapprochement détectent une divergence ; elles ne sont jamais ajoutées au PnL. Les conversions affichées comparent désormais le **float binaire exact** (`Decimal.from_float`) au Decimal source : PnL arrondi vers le bas, coûts/risques vers le haut. Le texte court de `str(float)` ne sert plus de preuve d’arrondi.

## Borne analytique du LCB

Pour `n ≥ 3` journées TRAIN et valeurs journalières Decimal finies `xᵢ`, le code construit les rationnels exacts `P = Σxᵢ` et `R = n/(n−1) × Σ(xᵢ−P/n)²`. Le score total avant arrondi est `P − z√R`.

### Valeur critique conservatrice

La valeur `z` n’est plus estimée par une quantile de bibliothèque avec une erreur observée sur une grille. Le code cherche un `z` Decimal et n’accepte son extrémité supérieure qu’après vérification d’une borne de queue normale dirigée vers le haut :

```text
Φ(−z) < exp(−z²/2) / (√(2π) z)
       < 0.41 × exp(−z²/2) / z
```

La première inégalité est Mills : dans l’intégrale de queue, `t/z ≥ 1` pour `t ≥ z`. Pour la seconde, `π > 3`, donc `1/√(2π) < 1/√6 < 0.41` (`0.41²×6 > 1`). Le carré de `z`, l’exposant, `Decimal.exp`, la multiplication et la division sont élargis/arrondis vers une borne supérieure. La bisection n’est qu’un moyen de trouver le seuil ; chaque résultat final est revalidé par l’inégalité. Ainsi, pour l’alpha ajusté exact du float binaire, la queue normale réelle est au plus cet alpha. Cette valeur peut être plus conservatrice que la quantile exacte ; elle ne peut pas rendre le LCB plus favorable.

### Intervalle d’arrondi du score

Les valeurs Decimal journalières sont converties en `Fraction`, ce qui rend les sommes, la moyenne et la variance exactes et indépendantes du contexte Decimal global. La conversion rationnelle→Decimal est faite une fois vers `ROUND_FLOOR` et une fois vers `ROUND_CEILING`. `Decimal.sqrt`, correctement arrondi, est élargi d’un ulp de chaque côté ; le produit et la soustraction sont aussi arrondis dans le sens extérieur. Le code obtient donc `[L, U]` qui contient le score exact défini avec le `z` certifié.

```text
LCB publié = L
borne d’erreur numérique = U − L ≥ 0
```

Conséquences vérifiables :

- Un gate positif fondé sur `L` ne peut pas être créé par l’arrondi ; `L` est une borne inférieure du score exact. Les gates PnL et les seuils restent comparés sur leurs champs Decimal exacts.
- Le classement champion/challenger n’est déclaré résolu que si l’écart des bornes basses excède la somme des largeurs des deux intervalles. Sinon le sélecteur refuse la sélection comme `NUMERIC_LCB_RANK_UNRESOLVED`.
- Les sorties float de présentation ne peuvent relever un PnL ni sous-estimer un coût par erreur de conversion binaire ; les données exactes alimentent les gates.
- Débordement ou résultat non représentable reste refusé ; il ne devient pas un PnL ou une métrique nulle.

Le schéma des statistiques est `hypersmart.train_selection_statistics.v3` ; le résultat conserve les bornes basse/haute exactes et l’intervalle numérique utilisé pour le classement.

## Vérifications

- **Oracle indépendant** : SciPy `ndtri` et calcul Decimal 240 chiffres comparent le quantile normal et le LCB à 30 jeux de données déterministes, incluant annulations, nombres jusqu’à `1e308` et sous-normaux `5e-324`. Les bornes publiées encadrent le score avec le `z` certifié et restent sous le LCB de référence.
- **Queue certifiée** : 65 niveaux d’alpha sur `[1e−12, 0.499999]`, vérification de `z ≥ −ndtri(alpha)` et vérification directe de la borne de Mills arrondie vers le haut.
- **Rang/gates** : tests de rang sous précision d’affichage, rangs non séparables, petits PnL positifs/négatifs, seuils juste en dessous, données invalides et conversions conservatrices. Les tâches antérieures couvrent aussi les chemins canoniques fill/notional/frais/PnL/equity/drawdown par oracle.
- **Validation finale** : 485 tests Copy‑Vault/statistiques/comptabilité/ledger passent en 51,16 s, incluant les cas extrêmes `1e308` et `5e-324`. Ruff, `py_compile` et `git diff --check` passent.
- Deux exécutions réelles après cette révision (`20261028T075551828170Z` et `20261028T080138250355Z`) ont la même empreinte de sélection SAFE `7114ad06d5ce20b065f6d41767bb7dda4958a1ff78eb6763f3888891b97477d6`, de catalogue `97e52c152c51b9db788fbd561e66a65e67d41e1b07e894567f97270d5798086a`, de résultat économique `9c09c8f0ae6766a73b53a59d4cd60fb2832230541c9c1850b2e7058f23b9d142` et de replay sans la liste volumineuse des essais `ac894c7fd37ba9ae2e0c387c63ef71226b734d2d5ebbf34f93aee7bff01b3b2f`.

## Vérification réelle du laboratoire

Rapport final : `runtime/reports/copy_vault_quant_lab/20261028T080138250355Z/RAPPORT.md` (JSON et HTML dans le même dossier). Le lanceur a vérifié 15 256 fichiers SAFE ; le catalogue référence 15 456 shards, dont 200 fichiers `copy_vault_positions`/`copy_vault_selection` absents mais non utilisés pour le PnL de cette campagne. Aucun fill live causal n’est disponible ; 14 285 fills sont des snapshots historiques. Le run est `MORE_DATA`, avec zéro candidat testé.

Le replay historique reste exploratoire : 73 728 scénarios, 8 trades sur 4 jours ; baseline et meilleur résultat `+1.887900406929213423… USD/jour`, amélioration exactement nulle. Aucune rentabilité n’est prouvée.

## Limites restantes

Cette preuve borne l’arrondi des champs numériques et de la statistique LCB décrits ici. Elle ne démontre pas que les observations source sont vraies, causales, complètes ou exécutables, ni que les hypothèses statistiques modélisent les rendements réels. Le corpus actuel n’a aucun fill live causal et ne permet aucun candidat OOS/forward ; aucun champion ni PnL économique ne peut être certifié. L’état de la recherche demeure `MORE_DATA`.
