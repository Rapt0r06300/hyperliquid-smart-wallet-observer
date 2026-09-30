# FRAÎCHEUR DES DONNÉES ET LATENCE DE SIGNAL (2026-07-21)

> Données : `data/reports/source_freshness_metrics.json`.
> **Principe directeur** : on ne cherche pas la latence minimale partout. La loi `latence`
> dit que sur le copy, la courbe edge/horizon est **plate** — accélérer un signal qui ne
> prédit rien fait perdre plus vite. La fraîcheur ne se paie que là où elle a une **valeur
> économique démontrable**.

## 1. Mesures par source (intervalles entre observations consécutives)

| source | lignes | étendue | p50 | p95 | p99 | max | trous > 5× médiane | doublons |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| cross-venue (dispersion) | 9 456 | 49,2 h | **253,8 s** | 304,2 s | 304,6 s | 15 746 s | 1 | 0 |
| carry (journal de scans) | 240 | 0,8 h | 263,2 s | 264,7 s | 264,7 s | 264,7 s | 0 | 0 |
| carry (ledger) | 97 | 73,7 h | 931,9 s | 14 875 s | 46 230 s | 46 230 s | 12 | — |
| fills de leaders | 4 133 | **7,4 h** * | **0,31 s** | 43,1 s | 146,1 s | — | 886 * | 0 |

\* après correction du défaut d'intégrité décrit au §3.

## 2. Lecture

- **cross-venue à 253 s de médiane** : la cadence ×5 (300 s → 60 s) est écrite dans les
  launchers mais **ne prendra effet qu'au prochain redémarrage**. C'est la source où la
  fraîcheur a la plus forte valeur économique (une dislocation de 20 bps qui dure 3 min est
  aujourd'hui invisible), et c'est celle qui attend.
- **carry : 263 s, aucun trou** — la cadence est stable et suffisante. Le carry se décide sur
  du funding horaire : gagner des secondes n'y a **aucune valeur économique**. Ne pas y toucher.
- **ledger carry : 12 trous** — normal, ce sont des **événements** (ouvertures/fermetures),
  pas un échantillonnage. Un intervalle de 12 h y signifie « rien ne s'est passé », pas une panne.
- **fills de leaders : p50 = 0,31 s** — la source la plus fraîche du système, de loin. Elle
  alimente un module **verrouillé**. C'est cohérent : on collecte pour prouver, pas pour agir.

## 3. 🔴 Défaut d'intégrité trouvé par cette mesure

L'audit annonçait **495 734 h d'étendue** (56 ans) sur les fills de leaders. Cause : **3
lignes de fixtures de test dans la donnée live** (`ts_ms = 0`, adresses `0x1111…`, `0x2222…`,
`0x3333…`). Étendue réelle : **7,4 h**.

Le risque n'était pas cosmétique : un leader **fabriqué** accumulant assez de fills pouvait
entrer dans la whitelist et **déverrouiller le copy sur de la donnée inventée**.

Corrigé dans `tools/ecrire_copy_whitelist.py` (horodatage plausible + adresse non
synthétique, fills écartés **et comptés**), avec test dédié. Les 886 « trous » de la ligne
correspondante s'expliquent aussi par ces valeurs aberrantes.

## 4. Ce qui n'est PAS vérifié (honnêtement)

La mission demande de vérifier le traitement WebSocket : `isSnapshot=true` distingué de
`false`, snapshot non rejoué comme événements, déduplication des fills, reconnexions,
récupération des données manquées, invalidation des signaux périmés, WebSocket non bloqué
par des écritures lourdes.

**Aucun de ces points n'a été audité dans cette passe.** Les métriques ci-dessus mesurent les
**fichiers produits**, pas le comportement du transport. C'est la tâche **P8-1**, ouverte.

Ce qui est prouvé côté fichiers : **0 doublon** sur les trois sources où une clé d'unicité
existe (`ts+coin`, `ts_ms+coin`, `ts_ms+adresse+coin`). C'est un indice favorable sur la
déduplication, pas une preuve du traitement du snapshot.

## 5. Priorisation (par valeur économique, pas par élégance technique)

| priorité | source | pourquoi |
|---|---|---|
| **1** | cross-venue | l'edge d'arbitrage vit dans des dislocations courtes — redémarrage requis |
| **2** | fills de leaders | déjà à 0,31 s ; ne rien changer tant que le copy est verrouillé |
| **3** | carry | funding horaire : la fraîcheur n'a aucune valeur ici |
| — | copy « plus vite » | **interdit par la loi `latence`** sans une courbe edge/horizon en pente |

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
