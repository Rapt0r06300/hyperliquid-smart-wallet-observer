# Analyse replay — le vrai levier d'un PnL positif (2026-07-09)

> ⚠️ **Aucune promesse de PnL.** Backtest paper sur données passées (6h réelles Hyperliquid).
> 0 ordre réel, 0 argent, 0 clé, 0 signature. Lecture seule — le serveur n'a pas été touché.

## Ce que tu demandais
« Tous les réglages nécessaires pour un PnL ultra positif. » J'ai extrait **le maximum** du replay,
avec **deux analyses indépendantes** sur les 23 779 candidats mesurables (train 16 645 / test 7 134,
split temporel). Voici la vérité, chiffrée.

## Verdict 1 — aucun calibrage SL/TP ne rend ces données gagnantes (hors-échantillon)
18 tranches d'entrée × 4 profils de sortie = 0 configuration positive sur le **test** (OOS).
La moins mauvaise :

| Sortie | Entrée | TEST (OOS) net | trades | winrate | PF |
|---|---|---|---|---|---|
| #1 (live) | edge≥40 + frais≤10s | **−$8.7** | 516 | 81 % | 0.96 |
| #1 (live) | edge≥40 | −$30 | 550 | 77 % | 0.87 |
| #1 (live) | edge≥50 + frais≤10s + cons≥3 | −$12 | 361 | 83 % | 0.92 |

**Et #1 est de loin la MEILLEURE sortie.** Les autres (anciens défauts, tight, tp-wide) s'effondrent
à **winrate 2–20 %, PF 0.03–0.15** sur ces signaux (70 % de shorts). Donc : #1 n'est pas le problème,
c'est déjà le moins mauvais. Le calibrage a été poussé à fond → mur. `robust_count = 0` **confirmé**
par une 2ᵉ méthode.

## Verdict 2 — la cause racine, isolée et chiffrée : la DÉGRADATION DE COPIE
Pourquoi ça perd malgré 81 % de winrate ? Les **coûts**. Le compte est simple sous la sortie #1
(TP 40 / SL 126) : `0.81×40 − 0.19×126 = +8.5 bps` de marge brute par trade. Les coûts sont
`~6 bps (frais/spread) + ~13 bps de dégradation de copie = ~19 bps` → **net ≈ −10 bps**. Négatif.

La dégradation de copie médiane est de **~13 bps** parce que les signaux sont **vieux** :
âge médian **57 secondes**. Le leader a bougé le prix ~13 bps avant qu'on « copie ».

## La preuve — sensibilité du NET (OOS) à la fraîcheur (mêmes trades, on ne varie QUE la dégradation)

| Tranche | degr≈13 (actuel, ~57s) | degr≈8 | degr≈4 (frais) | degr≈2 (~temps réel) |
|---|---|---|---|---|
| edge≥40 + frais≤10s | **+$17** | +$212 | +$418 | +$521 |
| edge≥40 | +$6 | +$216 | +$436 | +$546 |
| edge≥50 + frais≤10s + cons≥3 | +$10 | +$146 | +$290 | +$362 |

**Le levier n'est PAS le calibrage. C'est la fraîcheur du signal.** Diviser la dégradation par ~3
(signaux quasi temps réel) transforme une tranche breakeven en **+$300 à +$500 sur 500 trades OOS**.

## Les 2 réglages honnêtes qui en découlent

**A. Maintenant (petit gain, à VALIDER) — « moins de trades, beaucoup plus propres » :**
resserrer l'entrée à **edge≥40 + fraîcheur≤10s + plafond dur de dégradation ≤13 bps**.
Sur ces 6h : passe de −$8.7 à **+$17 OOS** (516 → ~460 trades). Marginal, mais positif et honnête.
⚠️ +$17 sur 6h = razoir. C'est un **candidat à valider sur 48h**, pas une garantie.

**B. Le vrai prix (gain réel) — réduire la latence des signaux :**
le firehose userFills multiplexé (V27, déjà dans le code) vise exactement ça. Si la dégradation
réelle tombe à ~4 bps, la même tranche fait **+$300+ OOS**. **C'est là que vit ton « PnL positif ».**

## Ce que je ne ferai pas
Te promettre « ultra positif », ni te livrer un mirage collé au train (le « +$328 »). La donnée dit :
pas d'edge net dans les signaux **tels qu'observés** (trop tard). L'edge existe **si on les capte frais**.

## Prochaines étapes possibles (ton choix — je n'ai touché à rien)
1. Préparer la config A (edge≥40 / frais≤10s / degr≤13) pour le **prochain redémarrage** (pas maintenant) + valider sur 48h.
2. Attaquer le levier B : auditer/durcir le firehose pour faire **baisser la dégradation réelle** (le vrai gain).
3. Ne rien changer, laisser tourner, ré-évaluer sur 48h de données propres.
