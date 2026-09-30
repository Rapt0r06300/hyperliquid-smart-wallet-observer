# Exploration — Réversion à la moyenne (mécanisme différent) — 2026-07-10

> ⚠️ **Aucune promesse.** Expérience d'apprentissage : on teste un mécanisme **génuinement
> différent** du copy-trading (pas de baleines — une propriété statistique du prix). Rigueur
> identique : no-lookahead, split hors-échantillon, coûts réels. `mean_reversion.py`, testé (4 verts).

## L'idée
Quand le prix s'écarte fortement de sa moyenne mobile (z-score élevé), parier sur le **retour** vers
la moyenne. Entrée si |z| > seuil ; sortie quand le z revient vers 0 (réversion faite), ou stop si le
z s'aggrave (la tendance continue), ou durée max.

## Résultat (15 coins liquides, split 70/30, $500/trade)

| seuil d'entrée | TEST (OOS), **coût réel 6 bps** | TEST (OOS), **coût 0 (théorique)** |
|---|---|---|
| z ≥ 1.5 | **−$159** (582 trades) | +$15 |
| z ≥ 2.0 | **−$138** (511 trades) | +$15 |
| z ≥ 2.5 | **−$123** (457 trades) | +$14 |

## La leçon (chiffrée, et c'est la vraie valeur)

Il **existe** un tout petit signal de réversion : à coût zéro, le net est **positif (+$15)** sur ~500
trades = **~0.6 bps de marge brute par trade**. Mais le coût réel aller-retour est **~12 bps par
trade** — soit **~20× plus gros que l'edge**. Résultat : solidement **négatif après coûts**.

C'est exactement le **même mur** que toutes les autres pistes : *un filet d'edge réel, écrasé par la
friction*. Le mécanisme est différent, la conclusion est identique — et maintenant on sait **pourquoi**,
avec un chiffre : l'edge (0.6 bps) est vingt fois trop petit pour payer le passage (12 bps).

## Bonus (une vraie découverte quant)
Une **rampe de prix linéaire plafonne le z-score à ~1.73** (= √12 / 2). Conséquence pratique : un
détecteur de réversion à `entry_z ≥ 2` ne se déclenche **jamais** sur une tendance pure — il ne réagit
qu'au bruit. Le genre de détail qu'on n'apprend qu'en construisant et testant soi-même.

## Verdict
Expérience **réussie** (résultat négatif *propre* et *compris*), pas un échec. La réversion à la
moyenne n'a pas d'edge net exploitable ici après coûts — comme le copy, le maker, le grid. Le fil
rouge est désormais indiscutable : **sur ce marché, en retail, la friction dépasse les petits edges.**

## Sécurité
✅ 0 ordre réel · 0 argent · 0 clé · 0 signature. Lecture seule, paper-only.
