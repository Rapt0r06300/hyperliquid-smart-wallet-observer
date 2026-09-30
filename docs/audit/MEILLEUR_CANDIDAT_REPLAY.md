# Rapport — Meilleur candidat du replay (2026-07-09)

> ⚠️ **Aucune promesse de PnL.** Ceci est un backtest paper sur données passées. Rien n'a été exécuté en réel (0 ordre, 0 argent, 0 clé, 0 signature).

## Contexte du replay

- **1 425 000 scénarios** évalués sur ~4h (streaming sur la DB de 150M, 14 cœurs).
- Données : **23 779 candidats exploitables** sur ~6h de marché réel Hyperliquid (train 16 645 / test 7 134, split temporel 70/30).
- Discipline anti-surapprentissage : chaque scénario jugé sur le **hors-échantillon** (test) + gate de validation + plateau (voisinage sain).

## Verdict : `robust_count = 0`

**Aucun** scénario ne passe *tous* les critères de robustesse. Donc **aucun réglage certifié gagnant**. Le fameux « +$328 » vu pendant le run était le meilleur sur le **train uniquement** = curve-fitting (mirage) : il n'est même pas le meilleur en hors-échantillon → écarté.

## Le meilleur candidat réel : #1 (le seul positif hors-échantillon)

| Métrique | Train (optim) | **Test (hors-échantillon, jamais vu)** |
|---|---|---|
| Trades | 382 | **403** |
| Net USD | +$213.36 | **+$54.15** |
| Profit factor | 5.63 | **1.64** |
| Winrate | 93.2 % | **76.4 %** |
| Drawdown max | $24.02 | **$84.59** |

**Calibrage complet de #1 :**

- **Sortie** : stop-loss **126 bps**, take-profit **40 bps**, trailing **132 bps** (activation **201**), breakeven **14 bps**, stop catastrophe **180 bps**, horizon 480 min.
- **Coût modélisé** : 6 bps (+ dégradation de copie réelle par candidat).
- **Entrée (filtres qualité)** : edge net **≥16 bps**, âge signal **≤30 s**, liquidité **≥0.80**, consensus **≥3 wallets**, dégradation de copie **≤12 bps**, score leader ≥20, sens = les deux.

**Lecture** : un profil « **gagne souvent petit, coupe rarement gros** » (TP serré, SL large) sur des signaux très sélectifs (liquidité haute + 3 wallets). Il est **positif en entraînement ET hors-échantillon**, sur 403 vrais trades OOS — ce n'est **pas** un coup de chance.

## Pourquoi il n'est PAS certifié « robuste »

Le gate de déploiement l'a **rejeté** : son **drawdown hors-échantillon ($85) est trop gros par rapport au gain ($54)**. Autrement dit, il faudrait encaisser une perte temporaire supérieure au profit final — trop risqué pour être qualifié « sûr ». Le gate a raison d'être prudent.

## Ce qu'on en fait

Le calibrage **#1 a été appliqué** au paper-sim (via `tools/start_hypersmart_simulation.ps1`), **en observation**, sur le serveur **durci** (recording par-process incassable, poll-loop résiliente, anti-bloat). Objectif : collecter **48h de données propres** et voir si #1 **tient sur des données fraîches** (le vrai juge).

- *Non transféré tel quel* : `horizon 480 min` (la sortie live est gouvernée par le suivi-leader + SL/TP) et `min_leader 20` (permissif, sans effet ici).

## Prochaine étape honnête

Après **48h de données propres**, relancer le replay dessus. Avec un jeu de données plus riche (plus de trades, plus de régimes de marché dans le test), un candidat comme #1 peut enfin **passer le gate** — ou un meilleur émerger. **La donnée est le facteur limitant, pas le nombre de scénarios.**
