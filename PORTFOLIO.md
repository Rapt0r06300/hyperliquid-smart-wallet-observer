# HyperSmart Observer — Système de recherche quantitative (paper-trading)

> Un moteur d'observation et de backtesting **read-only** pour Hyperliquid, conçu pour **tester
> rigoureusement des stratégies de trading et rejeter honnêtement celles qui n'ont pas d'edge réel**
> après coûts. Zéro exécution réelle, zéro argent risqué — la rigueur avant le résultat.

## En une phrase
J'ai construit de zéro un système qui collecte des données de marché réelles, reconstruit les positions
des « smart-money wallets », et évalue des stratégies avec une discipline anti-surapprentissage de
niveau professionnel — puis conclut *honnêtement* sur ce qui marche et ce qui ne marche pas.

## Ce qui rend ce projet remarquable
La plupart des projets de trading affichent un backtest flatteur et promettent des profits. Celui-ci
fait l'inverse : **il est construit pour ne pas se mentir.** Chaque stratégie est jugée en
hors-échantillon, avec les vrais coûts, un test de robustesse et un **contrôle aléatoire**. Savoir
*quand ne pas trader* est la compétence centrale d'un vrai quant.

## Architecture technique
- **Collecte read-only** : API Indexer REST + **firehose WebSocket** multiplexé, avec reconnect,
  gap-recovery, pagination, déduplication.
- **Stockage SQLite** sans doublons ; recording « replay » incassable (fichiers par-process, atomique).
- **Reconstruction des positions** par wallet/subaccount/marché/sens (OPEN/ADD/REDUCE/CLOSE).
- **Moteur de replay** : espace à 15 dimensions, base jusqu'à **150 M** scénarios, recherche streaming.
- **Simulation d'exécution réaliste** : frais, spread, slippage, latence, dégradation de copie, +
  modèles maker (sélection adverse) et market-making en grille.
- **ML from scratch** : régression logistique par descente de gradient, standardisation train-only.
- **Garde-fous** : *paper-only / testnet-locked*, vérifiés par tests — aucun ordre réel possible.

## Méthodologie scientifique
Validation **hors-échantillon** (train/test temporel) · **anti-surapprentissage** (gate + plateau) ·
**Monte-Carlo** (bootstrap) · **contrôle aléatoire** (le meilleur doit battre le hasard) · **coûts
réels** partout · **stress-testing** sur régimes adverses.

## Études de recherche menées (toutes en hors-échantillon, coûts réels)

| Étude | Question | Verdict honnête |
|---|---|---|
| Copy-trading | Copier les baleines paie-t-il ? | Non — dégradation de copie ~13 bps ; edge médian négatif |
| Calibrage (1,4 M scénarios) | Le bon SL/TP existe-t-il ? | Non — `robust=0`, aucun ne tient en OOS |
| Entrée maker | Économiser le spread aide-t-il ? | Non — 16 % de fill, sélection adverse |
| Grid / market-making | Le « grinder » marche-t-il ? | Non — breakeven en calme, catastrophe en tendance |
| Réversion à la moyenne | Un mécanisme statistique différent ? | Non — edge brut ~0,6 bps, 20× trop petit vs coûts |
| Scan de mécanismes + **hasard** | Quel est le meilleur ? | Tous perdent ; 0/50 aléatoires positifs (méta-preuve) |
| Oracle-exit | Est-ce le SL/TP ? | Plafond parfait +$50k *irréalisable* ; problème de prédiction, pas de calibrage |
| Modèle prédictif (ML) | Peut-on prédire les gagnants ? | Souffle de signal, mais 15× trop faible + changement de régime |

**Conclusion transversale, chiffrée et méta-prouvée** : sur ce marché, en retail, la **friction dépasse
les petits edges**. Le meilleur choix mesuré est *ne pas trader*.

## Sécurité & éthique
Conçu pour être **impossible à transformer en perte réelle** : lecture seule, simulation locale, aucune
clé, aucune signature, aucun dépôt. Une démarche responsable.

## Compétences démontrées
Python · architecture modulaire · ingénierie de données (REST/WebSocket, SQLite) · programmation
concurrente · méthodes quantitatives (backtesting, OOS, Monte-Carlo, modélisation de coûts) · **ML
from scratch** · rigueur scientifique & honnêteté intellectuelle · tests automatisés · documentation.

## Ce que j'ai appris
Qu'un marché liquide est difficile à battre, et *pourquoi* : les edges publics disparaissent, la latence
coûte, les coûts mangent les petits avantages, et les régimes changent. Et surtout — que **la valeur
d'un système de recherche se mesure à son honnêteté**, pas à un chiffre de PnL flatteur.
