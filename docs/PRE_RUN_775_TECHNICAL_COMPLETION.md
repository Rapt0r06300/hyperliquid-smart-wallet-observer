# HyperSmart — progression technique canonique vers 775

## Verdict courant

**Progression honnête : 395 / 775.**

Le précédent document annonçait 775/775 en s'appuyant sur une gate dérivée qui considérait, pour de nombreuses exigences, que la présence de deux fichiers génériques de la catégorie suffisait à valider chemin positif, fail-closed, déterminisme et provenance. Cette méthode était trop faible et son verdict est retiré.

La provenance littérale reste inchangée : les formulations historiques originales 321→775 ne sont pas récupérées et ne sont pas inventées.

## Ce qui est réellement verrouillé

- **1→320** : suites exécutables préexistantes conservées.
- **321→395** : bloc Copy-Vault dérivé, désormais contrôlé par `src/hl_observer/ops/pre_run_copy_321_395.py`.
- **396→775** : restent explicitement incomplets jusqu'à ajout de contrôles spécifiques par exigence.

Le bloc Copy-Vault représente 15 exigences préservées × 5 facettes = 75 preuves spécifiques :

1. userFillsByTime / pagination ;
2. lifecycle OPEN/ADD/REDUCE/CLOSE ;
3. dépôts/retraits hors PnL ;
4. identité wallet/vault stable ;
5. copyability / fraîcheur ;
6. latence leader→follower / slippage ;
7. capacité exécutable ;
8. consistency / one-big-win ;
9. drawdown / régimes ;
10. TWAP / métaordres ;
11. conflits entre vaults ;
12. vault réellement jamais vu avant OOS ;
13. OOS / forward ;
14. coûts réels / taille d'échantillon ;
15. PnL net / placebo.

Pour chacune, cinq facettes doivent être vraies : `CONTRACT`, `POSITIVE_PATH`, `NEGATIVE_FAIL_CLOSED`, `DETERMINISM_CAUSALITY`, `EVIDENCE_PROVENANCE`.

## Renforcement Copy-Vault de ce lot

La preuve held-out exécutable est désormais fail-closed :

- un vault est held-out uniquement s'il est absent de toute observation parseable avant la frontière OOS ;
- les lignes strictes doivent être paper-only et causales ;
- gross PnL, frais, spread, slippage et latence doivent se réconcilier ;
- la capacité observée d'entrée et de sortie doit couvrir le notionnel ;
- les identités de trade dupliquées invalident la preuve économique ;
- les lignes strictes incomplètes sont rejetées ;
- les anciennes partitions de vaults ne sont plus éligibles économiquement via l'adaptateur strict.

La preuve expose aussi, sans en faire arbitrairement un gradient de tuning : drawdown held-out, ratio de vaults profitables, concentration du plus gros gain, concentration par vault, dépendance one-big-win, régimes de coût dominants, latence observée, marge de capacité et conflits de directions entre vaults.

## Règle de progression

`src/hl_observer/ops/pre_run_guard_321_775.py` ne déclare plus les catégories futures terminées par simple présence de fichiers. Une catégorie non encore munie d'un évaluateur spécifique reste `CATEGORY_NOT_YET_SPECIFICALLY_VERIFIED`.

La CI peut rester verte pendant la progression : vert signifie que le compteur annoncé est honnête et que les blocs déclarés finis sont réellement prouvés. Cela ne signifie pas 775/775.

## Suite

Le prochain identifiant dérivé à traiter est **396**, début du bloc Lead-Lag. Les blocs seront ensuite poursuivis sans saut jusqu'à 775.

## Sécurité

Toujours : paper/read-only ; mainnet/testnet execution désactivés ; aucune clé privée ou signature ; aucune commande `/exchange` opérationnelle ; aucun test supprimé pour masquer un rouge ; `PREPARER_PC_ALINA.cmd` non lancé ; runner self-hosted non installé tant que `GO_SELF_HOSTED = TRUE` n'est pas explicitement autorisé.
