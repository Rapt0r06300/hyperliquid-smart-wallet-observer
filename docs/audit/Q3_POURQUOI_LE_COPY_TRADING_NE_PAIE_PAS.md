# Q3 — Pourquoi le fill public d'un leader ne paie pas. La cause, mesurée.

> Mesuré le 2026-07-13. **38 388 signaux, panel strict** (les mêmes signaux aux 12 horizons).
> Outil : `Q3-AVANT-APRES.cmd`. Code : `src/hl_observer/signals/signal_taxonomy.py`.
> Tests : `tests/test_signal_taxonomy.py` (8 verts).

## Ce qu'on savait, et ce qu'on ne savait pas

Trois preuves indépendantes disaient déjà que le copy-trading ne paie pas :

1. **OOS du 11/07** — 24 133 signaux : **−7,97 bps même à coût ZÉRO**.
2. **Courbe edge/horizon plate** — de 500 ms à 5 min. La latence n'a jamais été le problème.
3. **Table d'edge mesurée (Q1, 13/07)** — 23 358 markouts : **0 cellule** ne survit hors
   échantillon avec un edge net positif.

Aucune ne disait **pourquoi**. Et sans le pourquoi, on continue d'espérer qu'un réglage sauve la
mise.

## L'expérience

On mesure le markout **des deux côtés** du signal :

```
mid(T−300s) ... mid(T−60s) ... mid(T) ... mid(T+60s) ... mid(T+300s)
<------ AVANT le fill ------>|<------ APRÈS le fill ------>
```

Deux hypothèses possibles, **qui n'impliquent pas les mêmes suites** :

- **« On arrive trop tard »** — le prix a déjà couru avant qu'on voie le fill. → chercher le flux
  *avant* exécution (mempool, dépôts).
- **« Il n'y avait rien »** — le prix ne bouge pas du tout autour de ses trades. → le leader n'est
  pas informé ; chercher un flux **forcé**, pas un flux qu'on espère malin.

## 🚩 Mon premier passage était faussé — et je l'ai vu avant de conclure

J'avais mis une tolérance **proportionnelle** à l'horizon (`max(15, |h|/2)`). Les horizons
lointains acceptaient donc bien plus de signaux : **48 000 à ±300 s contre 23 000 à ±5 s**.

Comparer la courbe entre horizons revenait à comparer des **populations différentes** — et toute
« forme » pouvait n'être qu'un effet de composition. Refait en **panel strict** : tolérance
uniforme (30 s), et un signal n'est gardé que si les **douze** horizons se résolvent. Les mêmes
signaux partout.

## Le résultat

| horizon | markout moyen | borne basse | net (−12 bps) |
|---|---|---|---|
| **−300 s** | **−7,75 bps** | −8,03 | |
| −120 s | −3,54 | −3,77 | |
| −60 s | −1,12 | −1,26 | |
| −30 s | +0,14 | +0,08 | |
| −5 s | +0,00 | −0,07 | |
| | | | |
| +5 s | −0,13 | −0,20 | **−12,13** |
| +30 s | +0,22 | +0,12 | **−11,78** |
| +60 s | +0,08 | −0,04 | **−11,92** |
| +300 s | +0,62 | +0,45 | **−11,38** |

## Le verdict : **c'est la seconde hypothèse**

**Le fill du leader ne porte aucune information.**

Après le fill : **+0,08 bps à 60 s.** Le meilleur, +0,62 bps à 5 minutes, est statistiquement
réel (borne basse +0,45) — et **20× sous les 12 bps de coût aller-retour**.

Et avant ? Le prix bouge **contre** le trade : **−7,75 bps sur 5 minutes**.

> **Ces wallets achètent la baisse et vendent la hausse.**

Ce ne sont pas des informés qui devancent le marché. Ce sont des contrariens. Et le marché ne les
récompense pas assez : le retour à la moyenne existe (+0,62 bps à 5 min) mais il est **écrasé par
les coûts**.

## Ce que ça ferme définitivement

**Ce n'est pas un problème de vitesse. C'est un problème de contenu.**

On ne peut pas être « plus rapide » à capturer un mouvement de +0,08 bps qui n'existe pas. Aucune
latence, aucun scoring de wallet, aucun filtre de fraîcheur, aucun modèle IA ne fabriquera de
l'information là où il n'y en a pas.

C'est aussi le **verdict de Z1** : *ne pas optimiser la latence pour améliorer le PnL.* Il est
maintenant figé dans un test (`test_Z1_la_courbe_MESUREE_interdit_d_esperer_de_la_latence`), pas
seulement dans un document.

## Ce que ça ouvre

La taxonomie est dans le code, avec ses preuves, et le refus est **estampillé au point de
décision** (`edge_source._zone_morte`) — donc dans le journal, le dashboard et l'audit :

| famille | verdict | mécanisme |
|---|---|---|
| **DISCRETIONNAIRE_PUBLIC** | **MORT_PROUVÉ** | le fill déjà exécuté d'un humain. L'info est consommée — ou n'a jamais existé. |
| PRE_EXECUTION | NON_MESURÉ | l'ordre **avant** qu'il touche le carnet (mempool, dépôts entrants). L'info n'est pas encore dans le prix. |
| FLUX_FORCÉ | NON_MESURÉ | un flux qui **n'a pas le choix** : liquidation, ADL, prélèvement de funding, oracle qui suit les CEX. La contrepartie ne cherche pas à nous battre — elle **subit**. |
| CARRY_STRUCTUREL | **VALIDÉ (partiel)** | pas une prédiction : un **paiement** pour détenir une position. T2 : HYPE, +33,6 bps nets dans son pire mois. ⚠️ jambe short liquidable (T2b). |

La différence n'est pas de degré, elle est de **nature** :

- suivre un discrétionnaire = **parier qu'il sait quelque chose**. Mesuré : il ne sait rien.
- suivre un flux forcé = **savoir ce qui va se passer parce que la mécanique l'impose**.

## Limite honnête

Sur 273 459 signaux lus, **200 515 sont écartés** (panel incomplet : pas assez de marks autour du
signal). On ne garde donc que les coins densément suivis. Un biais de sélection est possible —
mais il jouerait *en faveur* du copy-trading (les coins les mieux suivis sont les plus liquides,
donc les plus favorables), et le résultat reste nul. Le biais ne sauve pas la thèse.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
