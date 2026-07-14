# Optimisation honnête — résultats mesurés (2026-07-10)

> ⚠️ **Aucune promesse de PnL.** Mesures sur données passées (23 779 candidats mesurables,
> train 16 645 / test 7 134). 0 ordre réel. Outils : `backtesting/robustness.py` (testé) + le
> moteur d'éval no-lookahead. Tranche étudiée : `edge≥40 + frais≤10s`, sortie #1. Taker OOS = **−$8.72**.

## 1) Maker vs Taker — LA piste la plus concrète

Entrer en **passif** (ordre limite) au lieu de traverser le spread économise ~4 bps (≈ $0.20 par
trade sur $500), MAIS tous les ordres ne se remplissent pas (missed-fill). Résultat OOS :

| Taux de remplissage | Fill aléatoire (optimiste) | Fill adverse (pessimiste) |
|---|---|---|
| 100 % | **+$94** | +$94 |
| 90 % | +$100 | +$42 |
| 70 % | +$91 | **−$23** |
| 50 % | +$79 | **−$87** |

**Lecture honnête :** économiser le spread **peut** faire basculer la tranche de −$9 à **+$40…+$100**
— *si* les remplissages ne sont pas trop « adverses ». Le piège : en maker, les trades qui filent en
ta faveur (les gagnants) ne te remplissent pas, tu ne captures que ceux qui reviennent → sélection
adverse. La vérité est **entre** les deux colonnes, et elle ne se connaît qu'en **mesurant** le vrai
taux de remplissage en paper. C'est un mécanisme réel, pas un espoir en l'air — mais pas une garantie.

## 2) Monte-Carlo — le quasi-breakeven est-il réel ou du bruit ?

Bootstrap 3000× de la séquence de trades :

| Cas | net obs | médiane | p5 | p95 | P(net>0) |
|---|---|---|---|---|---|
| TEST taker | −$8.7 | −$7.8 | −$49.6 | +$32.4 | **0.38** |
| TEST maker fill 0.7 (aléatoire) | +$90.7 | +$91.3 | +$57.4 | +$123.6 | **1.00** |

**Lecture :** le taker à −$9 **chevauche zéro** (38 % de chances d'être positif) = **pas un edge, du
bruit**. Le cas maker est robuste *à l'échantillonnage* (p5 encore +$57) — MAIS seulement **si** le
modèle de remplissage aléatoire tient. Le MC valide la stabilité statistique, pas l'hypothèse de fill.

## 3) La fraîcheur SEULE ne suffit pas (nuance importante)

| Filtre edge≥40 | net (train+test) | PF |
|---|---|---|
| age ≤ 3 s | −$104 | 0.83 |
| age ≤ 5 s | −$118 | 0.82 |
| age ≤ 10 s | −$366 | 0.62 |

Même les signaux **≤3 s** sont négatifs. Pourquoi ? Parce que filtrer par *âge observé* ne réduit pas
la **dégradation de copie** (~13 bps) déjà payée. Le vrai levier n'est pas « jeter les vieux signaux »
mais **réduire le coût réel** (spread via maker, et/ou latence d'exécution).

## Verdict honnête + prochaine étape

Le seul levier **mécanique et concret** qui ressort : **entrées MAKER** (économiser le spread). La
donnée dit qu'il *peut* transformer une perte en petit gain — avec un vrai risque de sélection adverse.
**Zéro promesse.** La bonne démarche : implémenter un **mode maker en paper** avec missed-fill
réaliste, le lancer, et **mesurer le taux de remplissage et la sélection réels**. Si le fill réel est
proche de l'aléatoire → piste sérieuse ; s'il est très adverse → on saura que ça ne marche pas, sans
avoir risqué un centime.
