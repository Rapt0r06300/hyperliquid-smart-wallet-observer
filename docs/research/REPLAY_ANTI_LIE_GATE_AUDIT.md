# LABORATOIRE REPLAY — AUDIT DES PORTES ANTI-MENSONGE (2026-07-21)

> **Résultat : les portes annoncées existent toutes et refusent réellement.**
> 23 tests neufs (`tests/test_replay_portes_anti_mensonge.py`), tous verts au premier essai.
> Le trou n'était pas dans les portes — il était dans le fait que **rien n'interdisait de les
> retirer**.

## 1. Chaque promesse du README, vérifiée

| porte annoncée | constante / fonction | vérifiée | valeur |
|---|---|---|---|
| deux moitiés temporelles disjointes | `_moitie_vivante` × 2 dans `porte_robuste` | ✅ | — |
| embargo entre les moitiés | `EMBARGO_FACTEUR` | ✅ | ≥ 1,0 horizon |
| coûts stressés ×1,5 | `STRESS_COUTS` | ✅ | 1,5 |
| ≥ 30 trades par moitié | `MIN_TRADES_PAR_MOITIE` | ✅ | 30 |
| profit factor minimal | `MIN_PF_PAR_MOITIE` | ✅ | 1,1 |
| plateau des voisins | dans la porte du `/goal` | ✅ | rejet `REJETE_INSTABLE` |
| folds purgés CPCV | `folds_purges` | ✅ | — |
| rang OR = net > 0 sur ≥ 3/4 folds | `rang_pepite` | ✅ | `vivants >= 3` |

## 2. La porte refuse-t-elle vraiment ? (11 cas, un par un)

`porte_robuste` a été confrontée à chaque manière de tricher :

29 trades sur la 1re moitié · 29 sur la 2e · net négatif d'un côté · net négatif de l'autre ·
net **exactement nul** (zéro n'est pas positif) · profit factor 1,05 · net négatif sous
stress · stress **exactement nul** · moitié manquante · stress manquant · rapport vide.

**Les 11 sont refusés.** Un contrôle positif (scénario parfait accepté) garantit que la porte
n'est pas simplement bloquée sur « non ».

Cas limites traités : un profit factor **infini** (aucune perte) est **accepté** — c'est un
résultat légitime. Un profit factor **illisible** (`None`, texte, `NaN`) est **refusé** :
deny-by-default, une métrique qu'on ne sait pas lire ne vaut pas un feu vert.

## 3. Ce que l'invariant ajoute

Avant : les portes étaient des **conventions**. Un `MIN_TRADES_PAR_MOITIE = 5` « juste pour
voir » aurait fait promouvoir du bruit **sans qu'aucun test ne casse**.

Maintenant, un test échoue si :
- l'un des quatre seuils est affaibli ;
- `STRESS_COUTS` cesse d'être un multiplicateur > 1 ;
- `STRESS_COUTS` n'est plus multiplié à un coût quelque part (une constante décorative) ;
- les deux moitiés et le stress cessent d'être **trois évaluations distinctes** ;
- l'embargo ou les folds purgés disparaissent ;
- le rang OR n'exige plus 3 folds sur 4 ;
- **le README promet une porte que le code n'applique pas** (test de cohérence croisée).

## 4. Ce qui reste non vérifié

- **déterminisme** : deux exécutions sur les mêmes données donnent-elles le même résultat ?
  Non testé ici (le backtest carry, lui, a son test de déterminisme).
- **absence de lookahead dans `run_ab_replay`** : les folds purgés et l'embargo le rendent
  structurellement improbable, mais aucun test ne l'attaque directement.
- **reprise après Ctrl-C** : le mécanisme existe (essais sauvegardés en continu), non testé.

Ces trois points restent ouverts en **P0-3 bis**.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
