# Plan de collecte de données — pour les étapes 2/3/4/7 (2026-07-10)

> Les seules avenues honnêtes qui restent exigent de **nouvelles données** (pas plus d'analyse des 6 h
> actuelles). Ce document dit **quoi** collecter, **comment**, et **à quoi** ça sert. Read-only,
> paper-only : la collecte n'exécute jamais d'ordre.

## Ce qu'il faut collecter

| # | Donnée | Cadence | Format (jsonl) | Sert à |
|---|---|---|---|---|
| ② | **Latence bout-en-bout** : `t_fill_leader`, `t_observé`, `t_décision` par signal | par signal | `latency.jsonl` | mesurer la dégradation de copie au ms → seule vraie piste d'edge |
| ③ | **Taux de funding** par marché (+ horodatage) | à chaque heure de funding | `funding.jsonl` | backtester `funding_arb_paper` (delta-neutral) |
| ④ | **Carnet L2** (bid/ask, profondeur top-N) | toutes 1-5 s sur coins liquides | `l2book.jsonl` | tests maker/MM *réalistes* (fin du « mid-touch = fill ») |
| ⑦ | **Historique de prix étendu** (marks) | continu, **semaines** | `marks.jsonl` (déjà en place) | voir les vrais régimes (tendances/crashes), pas 6 h de calme |

## Comment (sans risque)

1. **Un run propre et long** (jours → semaines), read-only, avec les 4 enregistreurs actifs.
2. Chaque flux écrit dans son propre fichier jsonl **par-process** (comme le recording replay actuel),
   avec cap atomique anti-saturation — le module `research_recorder.py` fournit cette brique (testée).
3. Aucune donnée fabriquée : si une source manque/rate, on écrit un état vide honnête, jamais un faux.

## À quoi ça débloque

- **Latence (②)** : si on identifie où partent les ms, on peut viser à réduire la dégradation < ~13 bps
  — le seul levier qui, mathématiquement, pourrait rendre un edge net positif.
- **Funding (③)** : évaluer honnêtement le carry delta-neutral (structurellement différent du copy).
- **L2 (④)** : mesurer le *vrai* taux de fill maker et la profondeur → tests MM/exécution crédibles.
- **Historique long (⑦)** : conclure sur grid/réversion/momentum sur plusieurs régimes (pas
  survivorship de 6 h calmes).

## Discipline (rappel)
Toute donnée collectée passera par la **même** méthodologie : hors-échantillon + coûts réels + contrôle
aléatoire + critère d'arrêt écrit à l'avance (étape 10). On ne relâche jamais la rigueur, même — surtout
— si un résultat a l'air prometteur.

## Sécurité
✅ 0 ordre réel · 0 argent · 0 clé · 0 signature. La collecte est strictement en lecture seule.
