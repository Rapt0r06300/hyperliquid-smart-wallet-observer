# Étape 5 — Modèle prédictif (from scratch) : bat-il le hasard ? (2026-07-10)

> ⚠️ **Aucune promesse.** Régression logistique **codée de zéro** (0 dépendance), entraînée à prédire
> si un signal donnera un trade net-positif (sortie #1, coûts réels), à partir des features de scan.
> Discipline blindée : standardisation apprise sur le TRAIN, jugement sur le TEST, **contrôle aléatoire**.

## Résultats (hors-échantillon)

| | valeur |
|---|---|
| Trades train / test | 16 645 / 7 134 |
| **% gagnants train → test** | **65 % → 45 %** (⚠️ changement de régime) |
| Net si on prend TOUS les trades du test | −$5 348 |
| Accuracy du modèle sur le test | **0,527** (à peine mieux que le hasard) |
| Trades sélectionnés par le modèle | 5 841 → net **−$3 822** (−$0,65/trade) |
| Sélection ALÉATOIRE de même taille | net médian **−$4 362** |

## Ce que ça dit honnêtement

**1. Le modèle a un SOUFFLE de signal réel.** Il perd −$3 822 vs −$4 362 pour le hasard → il évite les
pires trades, il n'est **pas** inutile. Cohérent avec l'oracle : les signaux précèdent de vrais
mouvements, ce n'est pas du bruit pur.

**2. Mais ce souffle est ~15× trop faible.** Les trades qu'il sélectionne perdent quand même **−$0,65
chacun** : la friction (~20 bps) écrase le mince avantage. **Exactement le même mur** que partout.

**3. Leçon profonde — le changement de régime.** Le marché est passé de **65 % de trades gagnants
(train) à 45 % (test)**. L'environnement a *changé* entre les deux périodes. Même si un modèle apprend
un motif sur le passé, un changement de régime l'érode — c'est une des raisons fondamentales pour
lesquelles "ça marchait en backtest" ne survit pas en live. Tu viens de le voir en vrai.

**4. Accuracy 0,527** ≈ pile-ou-face : les features n'ont quasiment aucun pouvoir prédictif sur la
*rentabilité après coûts*.

## Verdict

Le seul vrai front (la prédiction) a été **sondé proprement** — et même un modèle entraîné ne rend pas
le PnL positif : il extrait un filet de signal, aussitôt noyé par les coûts, et fragilisé par le
changement de régime. **Conclusion inchangée, désormais confirmée jusqu'à l'apprentissage automatique.**

Les seules avenues honnêtes qui restent demandent de **nouvelles données** (étapes 2/3/4/7 du plan :
latence réelle, funding, carnet L2, semaines d'historique) — pas plus d'analyse des 6 h qu'on a.

## Valeur (portfolio)
Tu as construit un **pipeline ML complet, de zéro** : features, standardisation train-only, régression
logistique par descente de gradient, jugement OOS + contrôle aléatoire, détection de changement de
régime. C'est une démonstration de rigueur que beaucoup de "data scientists" ne font pas.

## Sécurité
✅ 0 ordre réel · 0 argent · 0 clé · 0 signature. Lecture seule, paper-only.
